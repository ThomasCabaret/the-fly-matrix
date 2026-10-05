from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
import torch
import yaml

from .central_graph import classify_population_scope
from .ledger import ROOT
from .lif_gate import _expand_torch_events, build_outgoing_graph
from .lif_source_fidelity import (
    SourceAlignedProfile,
    _linear_factors,
    audit_pinned_source,
    scaled_torch_weights,
)
from .signed_dynamics import (
    compile_signed_matrix,
    generate_pilot_candidate,
    load_neuron_classes,
    load_signed_runtime_assets,
)


PROTOCOL_PATH = ROOT / "calibration" / "evidence" / "antennal-abn1-model-class-reference-v2.yaml"
CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "neural-model-class-abn1-v2.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "neural-model-class-abn1-v2.yaml"
RUN_ROOT = ROOT / "runs" / "calibration" / "neural-model-class-abn1-v2"
ANNOTATION_PATH = (
    ROOT
    / "data"
    / "raw"
    / "malecns"
    / "v1.0"
    / "body-annotations-male-cns-v1.0-minconf-0.5.feather"
)
RATE_ENSEMBLE_PATH = (
    ROOT / "calibration" / "parameter_sets" / "central-timestep-convergent-ensemble-v1.yaml"
)


class Abn1ModelClassError(RuntimeError):
    """Raised when the locked aBN1 comparison loses a declared boundary."""


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, encoding="utf-8"
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def load_protocol() -> tuple[dict[str, Any], dict[str, Any]]:
    protocol = yaml.safe_load(PROTOCOL_PATH.read_text(encoding="utf-8"))
    campaign = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="utf-8"))
    if protocol.get("status") not in {
        "protocol_locked_execution_pending",
        "protocol_locked_pilot_complete_full_pending_review",
    }:
        raise Abn1ModelClassError("The v2 protocol is not locked before execution")
    if campaign.get("optimization", {}).get("enabled") is not False:
        raise Abn1ModelClassError("The aBN1 reference must not optimize parameters")
    if campaign.get("behavior_targets"):
        raise Abn1ModelClassError("The aBN1 campaign cannot consume behavior targets")
    metrics = protocol.get("native_metrics_locked_before_candidate_execution", {})
    if metrics.get("forbidden_metric") != "cross_model_native_amplitude_difference":
        raise Abn1ModelClassError("The representation-neutral metric boundary drifted")
    return protocol, campaign


def resolve_groups(protocol: Mapping[str, Any], body_ids: np.ndarray) -> dict[str, np.ndarray]:
    annotations = classify_population_scope(pd.read_feather(ANNOTATION_PATH))
    canonical = annotations.loc[annotations["is_canonical_neuron"]].copy()
    types = canonical["type"].fillna("").astype(str)
    body_groups: dict[str, np.ndarray] = {}
    for group_id in ("JO_CE", "JO_F"):
        spec = protocol["scope"]["source_groups"][group_id]
        prefixes = tuple(str(item) for item in spec["malecns_type_prefixes"])
        selected = np.sort(
            canonical.loc[types.str.startswith(prefixes), "bodyId"].to_numpy(dtype=np.int64)
        )
        if len(selected) != int(spec["expected_malecns_count"]):
            raise Abn1ModelClassError(
                f"{group_id} count drift: expected {spec['expected_malecns_count']}, got {len(selected)}"
            )
        body_groups[group_id] = selected
    target = np.asarray(protocol["scope"]["target_group"]["body_ids"], dtype=np.int64)
    target_type = str(protocol["scope"]["target_group"]["systematic_type"])
    observed_target = np.sort(
        canonical.loc[types.eq(target_type), "bodyId"].to_numpy(dtype=np.int64)
    )
    if not np.array_equal(np.sort(target), observed_target):
        raise Abn1ModelClassError("aBN1 identity drift")
    body_groups["aBN1"] = np.sort(target)
    index_groups: dict[str, np.ndarray] = {}
    for key, values in body_groups.items():
        indices = np.searchsorted(body_ids, values)
        if np.any(indices >= len(body_ids)) or not np.array_equal(body_ids[indices], values):
            raise Abn1ModelClassError(f"{key} is not fully represented in the runtime graph")
        index_groups[key] = indices.astype(np.int64, copy=False)
    return index_groups


def poisson_source_schedule(
    source_count: int,
    frequency_hz: float,
    trial_index: int,
    *,
    steps: int = 10_000,
    dt_ms: float = 0.1,
) -> np.ndarray:
    """Return a locked source x timestep event mask shared by both representations."""
    if source_count <= 0 or steps <= 0 or dt_ms <= 0 or frequency_hz < 0:
        raise ValueError("Invalid Poisson schedule arguments")
    probability = 1.0 - math.exp(-frequency_hz * dt_ms / 1000.0)
    rng = np.random.default_rng(51_000 + int(trial_index))
    return rng.random((steps, source_count)) < probability


def aggregate_rate_input(
    events: np.ndarray,
    *,
    rate_dt_ms: float = 5.0,
    master_dt_ms: float = 0.1,
    normalization_hz: float = 220.0,
) -> np.ndarray:
    bin_steps = int(round(rate_dt_ms / master_dt_ms))
    if not math.isclose(bin_steps * master_dt_ms, rate_dt_ms, abs_tol=1e-12):
        raise ValueError("Rate timestep must contain an integer number of master steps")
    if len(events) % bin_steps:
        raise ValueError("Event schedule does not fill complete rate bins")
    counts = events.reshape(len(events) // bin_steps, bin_steps, events.shape[1]).sum(axis=1)
    return counts.astype(np.float32) / float(normalization_hz * rate_dt_ms / 1000.0)


def _event_trial(
    outgoing: Any,
    neuron_signs: np.ndarray,
    source_indices: np.ndarray,
    target_indices: np.ndarray,
    events: np.ndarray,
    device: str,
    profile: SourceAlignedProfile,
) -> dict[str, Any]:
    c = profile.constants
    steps = len(events)
    delay_steps = int(round(c.fixed_delay_ms / profile.dt_ms))
    refractory_steps = int(round(c.refractory_ms / profile.dt_ms))
    node_count = outgoing.shape[0]
    indptr = torch.from_numpy(outgoing.indptr.astype(np.int64, copy=False)).to(device)
    indices = torch.from_numpy(outgoing.indices.astype(np.int64, copy=False)).to(device)
    unitary_weight_mV = float(
        profile.model["reference_constants"]["unitary_synaptic_weight_mV"]["value"]
    )
    weights = scaled_torch_weights(outgoing.data, unitary_weight_mV, device)
    signs = torch.from_numpy(neuron_signs.astype(np.float32, copy=False)).to(device)
    source_tensor = torch.from_numpy(source_indices).to(device)
    target_tensor = torch.from_numpy(target_indices).to(device)
    v = torch.full((node_count,), c.v_rest_mV, dtype=torch.float32, device=device)
    g = torch.zeros(node_count, dtype=torch.float32, device=device)
    refractory = torch.zeros(node_count, dtype=torch.int32, device=device)
    queue = [torch.empty(0, dtype=torch.int64, device=device) for _ in range(delay_steps + 1)]
    membrane_decay, synaptic_decay, coupling = _linear_factors(c, profile.dt_ms)
    target_spikes = delivered = forced_spikes = endogenous_spikes = 0
    source_endogenous_spikes = 0
    target_v_peak = -math.inf
    target_g_peak = -math.inf
    started = time.perf_counter()
    with torch.inference_mode():
        for step in range(steps):
            slot = step % len(queue)
            arriving, count = _expand_torch_events(
                indptr, indices, weights, queue[slot], node_count, signs
            )
            queue[slot] = torch.empty(0, dtype=torch.int64, device=device)
            delivered += count
            refractory[refractory > 0] -= 1
            active = refractory == 0
            v_active = v[active]
            g_active = g[active]
            v[active] = c.v_rest_mV + (
                (v_active - c.v_rest_mV) * membrane_decay + g_active * coupling
            )
            g[active] = g_active * synaptic_decay
            generated = torch.nonzero(active & (v > c.threshold_mV)).flatten()
            target_v_peak = max(target_v_peak, float(torch.max(v[target_tensor]).item()))
            g += arriving
            target_g_peak = max(target_g_peak, float(torch.max(g[target_tensor]).item()))
            if generated.numel():
                source_generated = torch.isin(generated, source_tensor)
                source_endogenous_spikes += int(source_generated.sum().item())
                v[generated] = c.reset_mV
                g[generated] = 0.0
                refractory[generated] = refractory_steps
            # In the pinned source every Poisson-target neuron has rfc=0, also
            # when recurrent input rather than the external impulse made it fire.
            refractory[source_tensor] = 0
            # The published PoissonInput impulse is delivered after thresholding;
            # therefore it can cause a source spike no earlier than the next step.
            forced = torch.empty(0, dtype=torch.int64, device=device)
            if step > 0:
                local = np.flatnonzero(events[step - 1]).astype(np.int64, copy=False)
                if len(local):
                    forced = source_tensor[torch.from_numpy(local).to(device)]
                    if generated.numel():
                        generated = generated[~torch.isin(generated, forced)]
                    v[forced] = c.reset_mV
                    g[forced] = 0.0
                    refractory[forced] = 0
            emitted = torch.cat((forced, generated))
            queue[(step + delay_steps) % len(queue)] = emitted
            target_spikes += int(torch.isin(emitted, target_tensor).sum().item())
            forced_spikes += int(forced.numel())
            endogenous_spikes += int(generated.numel())
    if device.startswith("cuda"):
        torch.cuda.synchronize(device)
    elapsed = time.perf_counter() - started
    finite = bool(torch.isfinite(v).all().item() and torch.isfinite(g).all().item())
    return {
        "response": target_spikes / (steps * profile.dt_ms / 1000.0) / len(target_indices),
        "response_unit": "aBN1_spikes_per_second_per_neuron",
        "target_spikes": target_spikes,
        "target_v_peak_mV": target_v_peak,
        "target_g_peak_mV": target_g_peak,
        "forced_source_spikes": forced_spikes,
        "endogenous_spikes": endogenous_spikes,
        "source_endogenous_spikes": source_endogenous_spikes,
        "delivered_edge_events": delivered,
        "unitary_synaptic_weight_mV": unitary_weight_mV,
        "wall_seconds": elapsed,
        "finite_state": finite,
    }


def _torch_rate_matrix(candidate: Mapping[str, float], device: str) -> tuple[Any, Any]:
    assets = load_signed_runtime_assets()
    efficacies = {key: float(candidate[key]) for key in assets.contract.class_ids}
    signed = compile_signed_matrix(
        assets.graph.matrix, assets.neuron_class_indices, assets.contract, efficacies
    )
    crow = torch.from_numpy(signed.indptr.astype(np.int64, copy=False)).to(device)
    col = torch.from_numpy(signed.indices.astype(np.int64, copy=False)).to(device)
    data = torch.from_numpy(signed.data.astype(np.float32, copy=False)).to(device)
    matrix = torch.sparse_csr_tensor(
        crow, col, data, size=signed.shape, device=device, check_invariants=False
    )
    inverse = torch.from_numpy(assets.graph.incoming_inverse).to(device)
    return matrix, inverse


def _rate_trial(
    matrix: Any,
    incoming_inverse: Any,
    source_indices: np.ndarray,
    target_indices: np.ndarray,
    rate_input: np.ndarray,
    bridge_scale: float,
    candidate: Mapping[str, float],
    device: str,
) -> dict[str, Any]:
    node_count = matrix.shape[0]
    source_tensor = torch.from_numpy(source_indices).to(device)
    target_tensor = torch.from_numpy(target_indices).to(device)
    state = torch.zeros(node_count, dtype=torch.float32, device=device)
    stimulus = torch.zeros_like(state)
    alpha = 1.0 - math.exp(-5.0 / float(candidate["time_constant_ms"]))
    samples: list[float] = []
    started = time.perf_counter()
    with torch.inference_mode():
        for step in range(len(rate_input)):
            stimulus.zero_()
            stimulus[source_tensor] = (
                torch.from_numpy(rate_input[step]).to(device) * float(bridge_scale)
            )
            drive = torch.sparse.mm(matrix, state[:, None]).flatten() * incoming_inverse
            proposal = torch.tanh(
                drive + float(candidate["input_gain"]) * stimulus + float(candidate["bias"])
            )
            state = (1.0 - alpha) * state + alpha * proposal
            if step >= len(rate_input) // 2:
                samples.append(float(torch.mean(state[target_tensor]).item()))
    if device.startswith("cuda"):
        torch.cuda.synchronize(device)
    elapsed = time.perf_counter() - started
    return {
        "response": float(np.mean(samples)),
        "response_unit": "mean_aBN1_model_activity",
        "wall_seconds": elapsed,
        "finite_state": bool(torch.isfinite(state).all().item()),
    }


def _write_jsonl(path: Path, row: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(dict(row), sort_keys=True, allow_nan=False) + "\n")


def summarize_directional_pilot(
    rows: list[dict[str, Any]], frequencies: Iterable[int]
) -> dict[str, Any]:
    grouped: dict[tuple[str, str, float | None], dict[tuple[str, int], float]] = {}
    for row in rows:
        key = (str(row["model"]), str(row["parameter_member"]), row["bridge_scale"])
        grouped.setdefault(key, {})[(str(row["condition"]), int(row["frequency_hz"]))] = float(
            row["response"]
        )
    series: list[dict[str, Any]] = []
    for (model, member, scale), values in sorted(
        grouped.items(), key=lambda item: (item[0][0], item[0][1], str(item[0][2]))
    ):
        contrasts = [
            values[("JO_CE", int(frequency))] - values[("JO_F", int(frequency))]
            for frequency in frequencies
        ]
        series.append(
            {
                "model": model,
                "parameter_member": member,
                "bridge_scale": scale,
                "JO_CE_minus_JO_F": contrasts,
                "positive_frequency_fraction": float(np.mean(np.asarray(contrasts) > 0)),
            }
        )
    return {
        "scope": "pilot_descriptive_only_not_a_decision",
        "frequencies_hz": [int(item) for item in frequencies],
        "series": series,
        "all_series_positive_at_all_pilot_frequencies": bool(
            series and all(item["positive_frequency_fraction"] == 1.0 for item in series)
        ),
    }


def run_pilot(backend: str = "auto") -> dict[str, Any]:
    protocol, campaign = load_protocol()
    if backend == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = backend
    if device == "cuda" and not torch.cuda.is_available():
        raise Abn1ModelClassError("CUDA requested but unavailable")
    print("[1/6] Audit de la source publiée et du protocole verrouillé...", flush=True)
    source_profile = SourceAlignedProfile.load()
    source_audit = audit_pinned_source(source_profile)
    print("[2/6] Chargement du graphe canonique et résolution JO-CE/JO-F/aBN1...", flush=True)
    outgoing, body_ids = build_outgoing_graph()
    groups = resolve_groups(protocol, body_ids)
    contract = load_signed_runtime_assets().contract
    class_indices, _ = load_neuron_classes(body_ids, contract)
    class_values = np.asarray(
        [contract.probe_efficacies[key] for key in contract.class_ids],
        dtype=np.float32,
    )
    neuron_signs = np.sign(class_values[class_indices])
    ensemble = yaml.safe_load(RATE_ENSEMBLE_PATH.read_text(encoding="utf-8"))
    admissible = [int(str(item).split("-")[-1]) for item in ensemble["solution_set"]["admissible_member_ids"]]
    expected = list(protocol["pilot_policy"]["rate_candidate_indices"])
    if any(item not in admissible for item in expected):
        raise Abn1ModelClassError("Pilot candidate is outside the retained rate ensemble")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "--abn1-model-class-v2-pilot"
    run_dir = RUN_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    row_path = run_dir / "results.jsonl"
    frequencies = [0, *protocol["pilot_policy"]["frequencies_hz"]]
    trial = int(protocol["pilot_policy"]["trial_indices"][0])
    print("[3/6] Exécution événementielle source-alignée (sham + 6 conditions)...", flush=True)
    event_rows: list[dict[str, Any]] = []
    event_sham = 0.0
    for condition in ("SHAM", "JO_CE", "JO_F"):
        condition_frequencies = [0] if condition == "SHAM" else frequencies[1:]
        source_group = groups["JO_CE"] if condition == "SHAM" else groups[condition]
        for frequency in condition_frequencies:
            events = poisson_source_schedule(len(source_group), float(frequency), trial)
            result = _event_trial(
                outgoing, neuron_signs, source_group, groups["aBN1"], events, device, source_profile
            )
            native_response = float(result.pop("response"))
            if condition == "SHAM":
                event_sham = native_response
            row = {
                "model": "event_lif_source_aligned_v1",
                "parameter_member": "published_point_comparator",
                "bridge_scale": None,
                "condition": condition,
                "frequency_hz": frequency,
                "trial_index": trial,
                "native_response": native_response,
                "paired_sham_response": event_sham,
                "response": native_response - event_sham,
                "response_unit": "delta_aBN1_spikes_per_second_per_neuron_from_sham",
                **{key: value for key, value in result.items() if key != "response_unit"},
            }
            _write_jsonl(row_path, row)
            event_rows.append(row)
            print(
                f"      event {condition:5} {frequency:3} Hz: {native_response:.3g} spike/s, {result['wall_seconds']:.1f} s",
                flush=True,
            )
    print("[4/6] Exécution rate des 3 sentinelles et des 3 ponts d'unité...", flush=True)
    rate_rows: list[dict[str, Any]] = []
    for candidate_index in expected:
        candidate = generate_pilot_candidate(candidate_index)
        matrix, inverse = _torch_rate_matrix(candidate, device)
        for bridge_scale in protocol["stimulus_contract"]["rate_bridge_scale_sensitivity"]:
            rate_sham = 0.0
            for condition in ("SHAM", "JO_CE", "JO_F"):
                condition_frequencies = [0] if condition == "SHAM" else frequencies[1:]
                source_group = groups["JO_CE"] if condition == "SHAM" else groups[condition]
                for frequency in condition_frequencies:
                    events = poisson_source_schedule(len(source_group), float(frequency), trial)
                    rate_input = aggregate_rate_input(events)
                    result = _rate_trial(
                        matrix,
                        inverse,
                        source_group,
                        groups["aBN1"],
                        rate_input,
                        float(bridge_scale),
                        candidate,
                        device,
                    )
                    native_response = float(result.pop("response"))
                    if condition == "SHAM":
                        rate_sham = native_response
                    row = {
                        "model": "typed_signed_rate_v0",
                        "parameter_member": f"candidate-{candidate_index:02d}",
                        "bridge_scale": float(bridge_scale),
                        "condition": condition,
                        "frequency_hz": frequency,
                        "trial_index": trial,
                        "native_response": native_response,
                        "paired_sham_response": rate_sham,
                        "response": native_response - rate_sham,
                        "response_unit": "delta_mean_aBN1_model_activity_from_sham",
                        **{key: value for key, value in result.items() if key != "response_unit"},
                    }
                    _write_jsonl(row_path, row)
                    rate_rows.append(row)
            print(f"      rate candidate-{candidate_index:02d}, pont {bridge_scale:g}: terminé", flush=True)
        del matrix, inverse
        if device.startswith("cuda"):
            torch.cuda.empty_cache()
    print("[5/6] Vérification des artefacts et estimation du coût complet...", flush=True)
    rows = event_rows + rate_rows
    if not rows or not all(row["finite_state"] for row in rows):
        raise Abn1ModelClassError("Pilot produced absent or non-finite rows")
    event_seconds = sum(float(row["wall_seconds"]) for row in event_rows)
    rate_seconds = sum(float(row["wall_seconds"]) for row in rate_rows)
    event_full_units = 30 * (1 + 2 * len(protocol["source_protocol_lock"]["frequencies_hz"]))
    rate_full_units = len(admissible) * 3 * event_full_units
    estimate = {
        "method": "linear_from_pilot_unit_means_no_batching_assumed",
        "event_full_units": event_full_units,
        "rate_full_units": rate_full_units,
        "event_full_wall_hours": event_full_units * (event_seconds / len(event_rows)) / 3600.0,
        "rate_full_wall_hours": rate_full_units * (rate_seconds / len(rate_rows)) / 3600.0,
        "warning": "cost estimate is diagnostic; full campaign requires batching or a reviewed reduction rule",
    }
    directional = summarize_directional_pilot(
        rows, protocol["pilot_policy"]["frequencies_hz"]
    )
    semantic = {
        "protocol_id": protocol["id"],
        "campaign_id": campaign["id"],
        "protocol_sha256": hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest(),
        "campaign_sha256": hashlib.sha256(CAMPAIGN_PATH.read_bytes()).hexdigest(),
        "groups": {key: len(value) for key, value in groups.items()},
        "rows": rows,
        "cost_estimate": estimate,
        "directional_description": directional,
    }
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "status": "pilot_complete_non_decisional_full_campaign_cost_gate_open",
        "claim_label": protocol["claim_label"],
        "backend": device,
        "source_audit": source_audit,
        "pilot_scope": protocol["pilot_policy"],
        "completed_rows": len(rows),
        "event_rows": len(event_rows),
        "rate_rows": len(rate_rows),
        "all_states_finite": True,
        "cost_estimate": estimate,
        "directional_description": directional,
        "semantic_result_sha256": _canonical_hash(semantic),
        "reproducibility": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "torch": torch.__version__,
            "project_git_commit": _git_value("rev-parse", "HEAD"),
        },
        "scientific_model_class_decision": "forbidden_from_pilot",
        "accepted_claims": [
            "Both candidate representations consumed schedules derived from the same locked generator.",
            "The pilot exercised the full canonical graph, native metrics, artifact path and cost accounting.",
        ],
        "forbidden_claims": protocol["forbidden_claims"],
        "next_action": "Review measured cost and implement a verified batched/resumable full executor before model-class interpretation.",
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    compact = {
        "schema_version": 1,
        "id": "runner_result.neural_model_class_abn1.v2",
        "status": summary["status"],
        "claim_label": summary["claim_label"],
        "run_id": run_id,
        "run_summary_ref": str((run_dir / "summary.json").relative_to(ROOT)).replace("\\", "/"),
        "completed_rows": len(rows),
        "all_states_finite": True,
        "cost_estimate": estimate,
        "directional_description": directional,
        "semantic_result_sha256": summary["semantic_result_sha256"],
        "scientific_model_class_decision": "forbidden_from_pilot",
        "next_action": summary["next_action"],
    }
    RESULT_PATH.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")
    print("[6/6] Pilote terminé; aucune décision scientifique n'est autorisée.", flush=True)
    print(f"      {run_dir / 'summary.json'}", flush=True)
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the non-decisional aBN1 model-class pilot")
    parser.add_argument("--backend", choices=("auto", "cpu", "cuda"), default="auto")
    args = parser.parse_args(list(argv) if argv is not None else None)
    run_pilot(args.backend)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

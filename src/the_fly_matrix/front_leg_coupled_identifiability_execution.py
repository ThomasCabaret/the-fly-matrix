from __future__ import annotations

import argparse
import gc
import hashlib
import itertools
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml
from scipy import sparse

from .basal_source_bridges import event_probability, hz_to_graded
from .front_leg_coupled_identifiability import (
    _assignment_for_member,
    _functional_class_map,
    build_owner_orthogonal_array,
)
from .ledger import ROOT
from .typed_hybrid_runtime import (
    EVENT,
    GRADED,
    DiagnosticConstants,
    LifConstants,
    TorchTypedHybridRuntime,
    boundary_edge_counts,
)


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "front-leg-coupled-identifiability-execution-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "front-leg-coupled-identifiability-execution-v0.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "front-leg-coupled-identifiability-execution-v0.yaml"
PARAMETER_SET_PATH = ROOT / "calibration" / "parameter_sets" / "front-leg-coupled-technical-ensemble-v0.yaml"
OUTPUT_ROOT = ROOT / "data" / "derived" / "calibration" / "front-leg-coupled-identifiability-execution-v0"


class CoupledExecutionError(RuntimeError):
    """Raised when the preregistered FH-05 execution loses an invariant."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CoupledExecutionError(f"{path} must contain a YAML mapping")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _semantic_float_quantization(value: Any, significant_digits: int = 6) -> Any:
    if isinstance(value, dict):
        return {
            key: _semantic_float_quantization(item, significant_digits)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_semantic_float_quantization(item, significant_digits) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CoupledExecutionError("semantic metrics must be finite")
        return float(f"{value:.{significant_digits}g}")
    return value


def _verify_campaign(campaign: Mapping[str, Any]) -> dict[str, Path]:
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise CoupledExecutionError("FH-05 execution must remain diagnostic_only")
    if campaign.get("behavior_targets"):
        raise CoupledExecutionError("FH-05 execution cannot expose a named behavior")
    if campaign.get("topology_changes_allowed") is not False:
        raise CoupledExecutionError("FH-05 execution cannot change topology")
    if int(campaign.get("parameter_values_promoted", -1)) != 0:
        raise CoupledExecutionError("FH-05 execution cannot promote parameter values")
    paths: dict[str, Path] = {}
    for key, record in campaign["frozen_inputs"].items():
        path = ROOT / str(record["path"])
        if not path.is_file():
            raise CoupledExecutionError(f"missing frozen input {key}: {path}")
        observed = _sha256(path)
        if observed != str(record["sha256"]):
            raise CoupledExecutionError(
                f"frozen input drift for {key}: {observed} != {record['sha256']}"
            )
        paths[key] = path
    return paths


def deterministic_event_presence(
    rates_hz: np.ndarray,
    dt_ms: float,
    steps: int,
    phases: np.ndarray,
) -> np.ndarray:
    """Return phase-balanced regular event trains without hidden RNG choices."""

    probabilities = event_probability(np.asarray(rates_hz, dtype=np.float64), dt_ms)
    phase = np.asarray(phases, dtype=np.float64)
    if phase.shape != probabilities.shape or np.any((phase < 0.0) | (phase >= 1.0)):
        raise CoupledExecutionError("event phases must match rates and lie in [0, 1)")
    time = np.arange(steps, dtype=np.float64)[:, None]
    epsilon = 1e-12
    before = np.floor(time * probabilities[None, :] + phase[None, :] + epsilon)
    after = np.floor((time + 1.0) * probabilities[None, :] + phase[None, :] + epsilon)
    return after > before


def build_boundary_graph(
    incoming_full: sparse.csr_matrix,
    source_positions: np.ndarray,
    cone_positions: np.ndarray,
) -> tuple[sparse.csr_matrix, dict[str, int]]:
    """Build source ports -> cone plus recurrent cone, excluding outside recurrence."""

    source_positions = np.asarray(source_positions, dtype=np.int64)
    cone_positions = np.asarray(cone_positions, dtype=np.int64)
    if len(np.intersect1d(source_positions, cone_positions)):
        raise CoupledExecutionError("basal source ports overlap the 196-neuron cone")
    source_to_cone = incoming_full[cone_positions][:, source_positions].tocsr()
    cone_to_cone = incoming_full[cone_positions][:, cone_positions].tocsr()
    zeros_ss = sparse.csr_matrix((len(source_positions), len(source_positions)), dtype=np.float32)
    zeros_sc = sparse.csr_matrix((len(source_positions), len(cone_positions)), dtype=np.float32)
    graph = sparse.bmat(
        [[zeros_ss, zeros_sc], [source_to_cone, cone_to_cone]],
        format="csr",
        dtype=np.float32,
    )
    return graph, {
        "source_ports": int(len(source_positions)),
        "cone_neurons": int(len(cone_positions)),
        "direct_source_to_cone_edges": int(source_to_cone.nnz),
        "direct_source_targets": int(np.unique(source_to_cone.nonzero()[0]).size),
        "direct_sources_with_edges": int(np.unique(source_to_cone.nonzero()[1]).size),
        "cone_recurrent_edges": int(cone_to_cone.nnz),
        "total_edges": int(graph.nnz),
    }


def _factor_ratio(label: str) -> float:
    values = {
        "ratio_0p5": 0.5,
        "ratio_0p75": 0.75,
        "ratio_1p0": 1.0,
        "ratio_1p25": 1.25,
        "ratio_2p0": 2.0,
    }
    try:
        return values[label]
    except KeyError as exc:
        raise CoupledExecutionError(f"unknown engineering coordinate {label!r}") from exc


def _constants_for_owner(
    fixture: Mapping[str, Any], owner: Mapping[str, Any]
) -> DiagnosticConstants:
    event = fixture["event_comparator"]
    boundary = fixture["boundary_scales"]
    same = _factor_ratio(str(owner["same_native_efficacy"]))
    cross = _factor_ratio(str(owner["cross_native_conversion"]))
    threshold = _factor_ratio(str(owner["threshold_distance"]))
    rest = float(event["v_rest_mV"])
    base_distance = float(event["threshold_mV"]) - rest
    return DiagnosticConstants(
        dt_ms=float(fixture["dt_ms"]),
        lif=LifConstants(
            v_rest_mV=rest,
            reset_mV=float(event["reset_mV"]),
            threshold_mV=rest + base_distance * threshold,
            tau_membrane_ms=float(event["tau_membrane_ms"]),
            tau_syn_ms=float(event["tau_syn_ms"]),
            refractory_ms=float(event["refractory_ms"]),
            fixed_delay_ms=float(event["fixed_delay_ms"]),
        ),
        event_to_event_mV=float(boundary["event_to_event_mV"]) * same,
        event_to_graded=float(boundary["event_to_graded"]) * cross,
        graded_to_event_mV=float(boundary["graded_to_event_mV"]) * cross,
        graded_to_graded=float(boundary["graded_to_graded"]) * same,
        graded_tau_ms=float(fixture["graded_tau_ms"]),
        external_graded_probe=float(fixture["feco_graded_drive"]),
    )


def _compile_schedules(
    *,
    assignment: np.ndarray,
    source_count: int,
    feco_indices: np.ndarray,
    families: np.ndarray,
    owner: Mapping[str, Any],
    source_profile: str,
    fixture: Mapping[str, Any],
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    steps = int(fixture["steps"])
    dt_ms = float(fixture["dt_ms"])
    start = int(fixture["stimulus_start_step"])
    stop = int(fixture["stimulus_stop_step"])
    basal_ratio = _factor_ratio(str(owner["basal_source_intensity"]))
    feco_ratio = _factor_ratio(str(owner["feco_native_amplitude"]))
    unknown_policy = str(owner["unknown_afferent_policy"])
    unknown_family = str(fixture["unknown_family_id"])
    unknown = families == unknown_family
    rates = np.full(source_count, float(fixture["basal_rate_hz"]) * basal_ratio)
    if unknown_policy == "zero":
        rates[unknown] = 0.0
    phases = ((np.arange(source_count, dtype=np.float64) * 0.6180339887498949) % 1.0)
    event_schedule = np.zeros((steps, len(assignment)), dtype=bool)
    graded_schedule = np.zeros((steps, len(assignment)), dtype=np.float32)
    rng = np.random.default_rng(seed)
    if source_profile == "all_event_candidate":
        regular = deterministic_event_presence(rates, dt_ms, steps, phases)
        event_schedule[:, :source_count] = regular
        if unknown_policy == "matched_stochastic_fixture":
            probabilities = event_probability(rates[unknown], dt_ms)
            event_schedule[:, np.flatnonzero(unknown)] = (
                rng.random((steps, int(np.count_nonzero(unknown))))
                < probabilities[None, :]
            )
    elif source_profile == "all_graded_candidate":
        drive = hz_to_graded(rates, float(fixture["graded_half_saturation_hz"]))
        graded_schedule[:, :source_count] = drive[None, :]
        if unknown_policy == "matched_stochastic_fixture":
            toggles = rng.integers(0, 2, size=(steps, int(np.count_nonzero(unknown))))
            graded_schedule[:, np.flatnonzero(unknown)] = (
                2.0 * drive[unknown][None, :] * toggles
            )
    else:
        raise CoupledExecutionError(f"unknown source profile {source_profile!r}")

    feco_event = feco_indices[assignment[feco_indices] == EVENT]
    feco_graded = feco_indices[assignment[feco_indices] == GRADED]
    if len(feco_event):
        local_rates = np.full(len(feco_event), float(fixture["feco_event_rate_hz"]) * feco_ratio)
        local_phases = ((np.arange(len(feco_event), dtype=np.float64) * 0.4142135623730951) % 1.0)
        feco_events = deterministic_event_presence(local_rates, dt_ms, stop - start, local_phases)
        event_schedule[start:stop, feco_event] |= feco_events
    if len(feco_graded):
        graded_schedule[start:stop, feco_graded] += (
            float(fixture["feco_graded_drive"]) * feco_ratio
        )
    sham_event = event_schedule.copy()
    sham_graded = graded_schedule.copy()
    sham_event[start:stop, feco_indices] = False
    sham_graded[start:stop, feco_indices] = 0.0
    accounting = {
        "source_profile": source_profile,
        "basal_rate_hz": float(fixture["basal_rate_hz"]) * basal_ratio,
        "feco_event_rate_hz": float(fixture["feco_event_rate_hz"]) * feco_ratio,
        "feco_graded_drive": float(fixture["feco_graded_drive"]) * feco_ratio,
        "unknown_policy": unknown_policy,
        "unknown_source_count": int(np.count_nonzero(unknown)),
        "stimulus_event_count": int(
            np.count_nonzero(event_schedule[:, feco_indices])
            - np.count_nonzero(sham_event[:, feco_indices])
        ),
        "stimulus_graded_integral": float(
            np.sum(graded_schedule[:, feco_indices] - sham_graded[:, feco_indices])
        ),
        "basal_event_count": int(np.count_nonzero(sham_event[:, :source_count])),
        "basal_graded_integral": float(np.sum(sham_graded[:, :source_count])),
    }
    return event_schedule, graded_schedule, sham_event, sham_graded, accounting


def _execute_pair(
    graph: sparse.csr_matrix,
    assignment: np.ndarray,
    constants: DiagnosticConstants,
    event_schedule: np.ndarray,
    graded_schedule: np.ndarray,
    sham_event: np.ndarray,
    sham_graded: np.ndarray,
    probe_groups: Mapping[str, np.ndarray],
    device: str,
) -> dict[str, Any]:
    import torch

    stimulus = TorchTypedHybridRuntime(graph, assignment, constants, device)
    sham = TorchTypedHybridRuntime(graph, assignment, constants, device)
    probes = {
        name: torch.as_tensor(indices, dtype=torch.int64, device=device)
        for name, indices in probe_groups.items()
    }
    metrics = {
        name: {"delta_peak_l1": 0.0, "delta_max_abs": 0.0, "delta_integral_l1": 0.0}
        for name in probes
    }
    generated = {"stimulus": 0, "sham": 0}
    with torch.inference_mode():
        for step in range(event_schedule.shape[0]):
            stim_row = stimulus.step(
                forced_event_indices=np.flatnonzero(event_schedule[step]),
                external_graded=graded_schedule[step],
            )
            sham_row = sham.step(
                forced_event_indices=np.flatnonzero(sham_event[step]),
                external_graded=sham_graded[step],
            )
            generated["stimulus"] += int(stim_row["generated_events"])
            generated["sham"] += int(sham_row["generated_events"])
            for name, indices in probes.items():
                event_delta = stimulus.g[indices] - sham.g[indices]
                graded_delta = stimulus.graded[indices] - sham.graded[indices]
                combined = torch.abs(event_delta) + torch.abs(graded_delta)
                l1 = float(torch.sum(combined).item())
                maximum = float(torch.max(combined).item()) if len(indices) else 0.0
                metrics[name]["delta_peak_l1"] = max(metrics[name]["delta_peak_l1"], l1)
                metrics[name]["delta_max_abs"] = max(metrics[name]["delta_max_abs"], maximum)
                metrics[name]["delta_integral_l1"] += l1 * constants.dt_ms
    stimulus_state = stimulus.state_arrays()
    sham_state = sham.state_arrays()
    finite = all(
        np.isfinite(value).all()
        for state in (stimulus_state, sham_state)
        for value in state.values()
    )
    result = {
        "finite": bool(finite),
        "generated_events": generated,
        "probe_delta": metrics,
        "stimulus_state_sha256": _canonical_hash(
            {key: hashlib.sha256(value.tobytes()).hexdigest() for key, value in stimulus_state.items()}
        ),
        "sham_state_sha256": _canonical_hash(
            {key: hashlib.sha256(value.tobytes()).hexdigest() for key, value in sham_state.items()}
        ),
    }
    del stimulus, sham
    gc.collect()
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    return result


def summarize_factor_observability(
    rows: Sequence[Mapping[str, Any]], factor_names: Sequence[str]
) -> dict[str, Any]:
    """Describe main-effect signatures; never rank or reject an owner level."""

    metric_names = (
        "sensory_delta_peak_l1",
        "intermediate_delta_peak_l1",
        "motor_delta_peak_l1",
        "motor_delta_integral_l1",
        "generated_event_delta",
    )
    signatures: dict[str, np.ndarray] = {}
    factors: dict[str, Any] = {}
    for factor in factor_names:
        levels = sorted({str(row[factor]) for row in rows})
        means: dict[str, list[float]] = {}
        for level in levels:
            selected = [row for row in rows if str(row[factor]) == level]
            means[level] = [
                float(np.mean([math.log1p(max(0.0, float(row[name]))) for row in selected]))
                for name in metric_names
            ]
        matrix = np.asarray([means[level] for level in levels], dtype=np.float64)
        centered = matrix - matrix.mean(axis=0, keepdims=True)
        signature = centered.flatten()
        signatures[factor] = signature
        factors[factor] = {
            "levels": levels,
            "replicates_per_level": {
                level: sum(str(row[factor]) == level for row in rows) for level in levels
            },
            "log1p_metric_means": dict(zip(levels, matrix.tolist(), strict=True)),
            "signature_l2": float(np.linalg.norm(signature)),
            "dynamically_observable_in_declared_metrics": bool(np.linalg.norm(signature) > 0.0),
        }
    similarities: dict[str, Any] = {}
    for left, right in itertools.combinations(factor_names, 2):
        a, b = signatures[left], signatures[right]
        denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
        cosine = float(np.dot(a, b) / denominator) if denominator else None
        similarities[f"{left}__x__{right}"] = {
            "absolute_cosine": abs(cosine) if cosine is not None else None,
            "high_signature_similarity_over_0p95": bool(
                cosine is not None and abs(cosine) > 0.95
            ),
        }
    return {
        "metrics": list(metric_names),
        "factors": factors,
        "pairwise_signature_similarity": similarities,
        "interpretation": (
            "Main-effect signatures are descriptive under a strength-two design. "
            "They expose non-observability or possible compensation but do not identify "
            "a physiological value or exclude unsampled higher-order interactions."
        ),
    }


def run_execution(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    parameter_set_path: Path = PARAMETER_SET_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    import torch

    campaign = _load_yaml(campaign_path)
    print("[1/10] Verifying the FH-05 execution contract and frozen inputs", flush=True)
    paths = _verify_campaign(campaign)
    fixture = campaign["execution_fixture"]

    print("[2/10] Reconstructing the 196-neuron cone and 6,041 explicit basal ports", flush=True)
    members = pd.read_csv(paths["population_members"])
    feco = members.loc[members["population_id"].eq("population.front_leg_feco.v0")].copy()
    motor = members.loc[members["population_id"].eq("population.front_leg_tibia_flexor_motor.v0")].copy()
    classified = pd.read_csv(paths["classified_intermediates"])
    cone_ids = sorted(set(feco.body_id.astype(int)) | set(motor.body_id.astype(int)) | set(classified.body_id.astype(int)))
    nodes = pd.read_parquet(paths["central_nodes"]).sort_values("runtime_node_index")
    nodes = nodes.loc[nodes["included_in_neural_runtime"].astype(bool)].reset_index(drop=True)
    canonical_ids = nodes.body_id.to_numpy(np.int64)
    cone_positions = np.searchsorted(canonical_ids, np.asarray(cone_ids, dtype=np.int64))
    if len(cone_positions) != 196 or not np.array_equal(canonical_ids[cone_positions], cone_ids):
        raise CoupledExecutionError("canonical cone mapping drift")
    cone_body_ids = canonical_ids[cone_positions]
    index_by_body = {int(body_id): index for index, body_id in enumerate(cone_body_ids)}
    source_rows = pd.read_csv(paths["source_terminals"]).sort_values("body_id").reset_index(drop=True)
    source_ids = source_rows.body_id.to_numpy(np.int64)
    source_positions = np.searchsorted(canonical_ids, source_ids)
    if len(source_rows) != 6041 or not np.array_equal(canonical_ids[source_positions], source_ids):
        raise CoupledExecutionError("basal source accounting or mapping drift")
    incoming_full = sparse.load_npz(paths["incoming_graph"]).tocsr()
    graph, graph_summary = build_boundary_graph(incoming_full, source_positions, cone_positions)

    print("[3/10] Reconstructing 81 preregistered structural x owner sentinels", flush=True)
    sensory = _load_yaml(paths["feco_parameter_set"])
    routing_by_id = {str(row["profile_id"]): row for row in sensory["routing"]["profiles"]}
    native_by_id = {str(row["profile_id"]): row for row in sensory["native_boundary_capacity"]["profiles"]}
    crosswalk = _load_yaml(paths["feco_crosswalk"])
    panel = pd.read_csv(paths["intermediate_panel"])
    panel_lookup = {(str(row.profile_id), int(row.body_id)): str(row.assignment) for row in panel.itertuples(index=False)}
    owner, owner_summary = build_owner_orthogonal_array(campaign["owner_design_levels"])
    schedule = [
        {
            "execution_id": f"{anchor['anchor_id']}__{row['owner_design_id']}",
            **anchor,
            **row,
        }
        for anchor in campaign["execution_anchors"]
        for row in owner.to_dict(orient="records")
    ]
    if len(schedule) != int(campaign["acceptance"]["expected_sentinels"]):
        raise CoupledExecutionError("execution schedule cardinality drift")

    source_count = len(source_rows)
    feco_local = np.asarray([index_by_body[int(value)] for value in feco.body_id], dtype=np.int64) + source_count
    intermediate_local = np.asarray([index_by_body[int(value)] for value in classified.body_id], dtype=np.int64) + source_count
    motor_local = np.asarray([index_by_body[int(value)] for value in motor.body_id], dtype=np.int64) + source_count
    probes = {"sensory_36": feco_local, "intermediate_150": intermediate_local, "motor_10": motor_local}
    families = source_rows.family_id.astype(str).to_numpy()
    device = "cuda" if torch.cuda.is_available() else "cpu"

    print(f"[4/10] Executing {len(schedule)} paired sentinels x 2 basal-native mirrors on {device}", flush=True)
    raw_rows: list[dict[str, Any]] = []
    for index, row in enumerate(schedule, start=1):
        if index == 1 or index % 5 == 0 or index == len(schedule):
            print(f"[4/10] sentinel {index}/{len(schedule)}: {row['execution_id']}", flush=True)
        cone_assignment = _assignment_for_member(
            feco=feco,
            motor=motor,
            classified=classified,
            panel_lookup=panel_lookup,
            routing=routing_by_id[str(row["routing_profile_id"])],
            native=native_by_id[str(row["native_profile_id"])],
            crosswalk=crosswalk,
            body_ids=cone_body_ids,
            index_by_body=index_by_body,
            intermediate_profile_id=str(row["intermediate_profile_id"]),
        )
        constants = _constants_for_owner(fixture, row)
        for source_profile in campaign["source_port_profiles"]:
            source_assignment = np.full(source_count, EVENT if source_profile == "all_event_candidate" else GRADED, dtype=np.int8)
            assignment = np.concatenate((source_assignment, cone_assignment)).astype(np.int8)
            seed = int(fixture["seed"]) + index * 97 + (1 if source_profile == "all_event_candidate" else 0)
            event_schedule, graded_schedule, sham_event, sham_graded, input_accounting = _compile_schedules(
                assignment=assignment,
                source_count=source_count,
                feco_indices=feco_local,
                families=families,
                owner=row,
                source_profile=str(source_profile),
                fixture=fixture,
                seed=seed,
            )
            execution = _execute_pair(
                graph, assignment, constants, event_schedule, graded_schedule,
                sham_event, sham_graded, probes, device,
            )
            raw_rows.append({
                **row,
                "source_profile": source_profile,
                "seed": seed,
                "event_nodes": int(np.count_nonzero(assignment == EVENT)),
                "graded_nodes": int(np.count_nonzero(assignment == GRADED)),
                "boundary_counts": boundary_edge_counts(graph, assignment),
                "constants": {
                    "threshold_mV": constants.lif.threshold_mV,
                    "event_to_event_mV": constants.event_to_event_mV,
                    "event_to_graded": constants.event_to_graded,
                    "graded_to_event_mV": constants.graded_to_event_mV,
                    "graded_to_graded": constants.graded_to_graded,
                },
                "input_accounting": input_accounting,
                **execution,
            })

    print("[5/10] Quantifying owner observability and possible compensation without ranking", flush=True)
    analysis_rows: list[dict[str, Any]] = []
    for row in raw_rows:
        analysis_rows.append({
            **{name: row[name] for name in campaign["owner_design_levels"]},
            "sensory_delta_peak_l1": row["probe_delta"]["sensory_36"]["delta_peak_l1"],
            "intermediate_delta_peak_l1": row["probe_delta"]["intermediate_150"]["delta_peak_l1"],
            "motor_delta_peak_l1": row["probe_delta"]["motor_10"]["delta_peak_l1"],
            "motor_delta_integral_l1": row["probe_delta"]["motor_10"]["delta_integral_l1"],
            "generated_event_delta": max(0, row["generated_events"]["stimulus"] - row["generated_events"]["sham"]),
        })
    observability = summarize_factor_observability(analysis_rows, list(campaign["owner_design_levels"]))

    print("[6/10] Applying mechanical, accounting, and anti-selection gates", flush=True)
    expected_runs = int(campaign["acceptance"]["expected_runtime_branches"])
    checks = {
        "cone_and_source_accounting_exact": graph_summary["cone_neurons"] == 196 and graph_summary["source_ports"] == 6041,
        "real_direct_boundary_edges_present": graph_summary["direct_source_to_cone_edges"] == int(campaign["acceptance"]["expected_direct_source_edges"]),
        "outside_recurrence_excluded": graph_summary["total_edges"] == graph_summary["direct_source_to_cone_edges"] + graph_summary["cone_recurrent_edges"],
        "owner_pairwise_design_preserved": bool(owner_summary["all_pair_combinations_repeated_three_times"]),
        "all_sentinels_and_native_mirrors_executed": len(raw_rows) == expected_runs,
        "all_runs_finite": all(row["finite"] for row in raw_rows),
        "every_stimulus_differs_from_sham_at_declared_input": all(
            row["input_accounting"]["stimulus_event_count"] > 0
            or row["input_accounting"]["stimulus_graded_integral"] > 0
            for row in raw_rows
        ),
        "every_stimulus_reaches_all_three_local_probe_groups": all(
            values["delta_peak_l1"] > 0.0
            for row in raw_rows
            for values in row["probe_delta"].values()
        ),
        "all_six_owner_axes_change_runtime_inputs": all(
            len({str(row[name]) for row in raw_rows}) == 3
            for name in campaign["owner_design_levels"]
        ),
        "parameter_values_promoted": False,
        "population_assignments_promoted": False,
        "members_ranked_or_selected": False,
        "named_behavior_exposed": False,
    }
    forbidden = ("parameter_values_promoted", "population_assignments_promoted", "members_ranked_or_selected", "named_behavior_exposed")
    if not all(value for key, value in checks.items() if key not in forbidden) or any(checks[key] for key in forbidden):
        raise CoupledExecutionError(f"FH-05 execution gate failed: {checks}")

    print("[7/10] Retaining the complete finite technical ensemble without selection", flush=True)
    member_ids = [str(row["execution_id"]) for row in schedule]
    compact_rows = [
        {
            "execution_id": row["execution_id"],
            "source_profile": row["source_profile"],
            "finite": row["finite"],
            "stimulus_reaches_groups": {
                name: bool(values["delta_peak_l1"] > 0.0)
                for name, values in row["probe_delta"].items()
            },
            "semantic_sha256": _canonical_hash({
                "execution_id": row["execution_id"],
                "source_profile": row["source_profile"],
                "owner_levels": {name: row[name] for name in campaign["owner_design_levels"]},
                "anchor_id": row["anchor_id"],
                "input_accounting": row["input_accounting"],
                "boundary_counts": row["boundary_counts"],
                "finite": row["finite"],
            }),
        }
        for row in raw_rows
    ]
    semantic = _semantic_float_quantization({
        "campaign_id": campaign["id"],
        "frozen_inputs": {key: value["sha256"] for key, value in campaign["frozen_inputs"].items()},
        "graph": graph_summary,
        "sentinel_members": member_ids,
        "runtime_branches": compact_rows,
        "owner_observability": observability,
        "checks": checks,
        "scientific_boundary": {
            "technical_execution_admissible_members": len(member_ids),
            "runtime_branches": len(raw_rows),
            "physiological_values_promoted": 0,
            "population_assignments_promoted": 0,
            "members_ranked_or_selected": False,
            "higher_order_assignment_coverage_claimed": False,
            "outside_cone_recurrence_claimed": False,
            "behavior_outcomes_consumed": 0,
        },
    })
    semantic_hash = _canonical_hash(semantic)
    result = {
        "schema_version": 1,
        "id": "runner_result.front_leg_coupled_identifiability_execution.v0",
        "campaign_id": campaign["id"],
        "status": "accepted_finite_technical_execution_ensemble_FH05_complete_zero_scientific_selection",
        "completed_at": datetime.now(UTC).isoformat(),
        "command": "front_leg_coupled_identifiability_execution.bat",
        "backend": device,
        "graph_boundary": graph_summary,
        "accounting": {
            "sentinel_members": len(member_ids),
            "source_native_mirrors_per_member": len(campaign["source_port_profiles"]),
            "paired_stimulus_sham_runtime_branches": len(raw_rows),
            "individual_runtime_instances": len(raw_rows) * 2,
        },
        "owner_observability": observability,
        "runtime_branches": compact_rows,
        "checks": checks,
        "scientific_boundary": semantic["scientific_boundary"],
        "semantic_result_sha256": semantic_hash,
        "next_action": campaign["next_action"],
    }
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.front_leg_coupled_identifiability_execution.v0",
        "campaign_id": campaign["id"],
        "status": "accepted_FH05_complete_finite_unranked_technical_ensemble",
        "conclusion": (
            "All 81 preregistered owner-separated sentinels execute as paired stimulus/sham runs "
            "under both explicit basal source-native mirrors. The retained set is finite and "
            "mechanically admissible without threshold-only selection. It is not a physiological "
            "parameter set: no value, population assignment, route, member, or behavior is selected."
        ),
        "graph_boundary": graph_summary,
        "accounting": result["accounting"],
        "owner_observability": observability,
        "checks": checks,
        "scientific_boundary": semantic["scientific_boundary"],
        "runner_semantic_sha256": semantic_hash,
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    parameter_set = {
        "schema_version": 1,
        "id": "parameters.front_leg_coupled_technical_ensemble.v0",
        "title": "FH-05 finite owner-separated technical execution ensemble",
        "status": "accepted_for_member_conditioned_execution_not_physiological_promotion",
        "primary_class": "technical",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": semantic_hash,
        "member_count": len(member_ids),
        "member_ids": member_ids,
        "source_port_profiles": list(campaign["source_port_profiles"]),
        "members_ranked": False,
        "selected_reference_member_id": None,
        "values_are_physiological_bounds": False,
        "parameter_ownership": campaign["parameter_ownership"],
        "propagation_contract": "all_members_and_both_source_native_mirrors_remain_conditioned_and_unranked",
        "reopening_policy": "new_campaign_required_no_silent_selection_or_promotion",
        "next_action": campaign["next_action"],
    }

    print("[8/10] Writing compact registries and ignored raw diagnostics", flush=True)
    for path, payload in ((result_path, result), (evaluation_path, evaluation), (parameter_set_path, parameter_set)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "raw-diagnostics.json").write_text(
        json.dumps({"campaign_id": campaign["id"], "rows": raw_rows}, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (output_root / "semantic-summary.json").write_text(
        json.dumps(semantic, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print("[9/10] Re-reading the semantic result hash", flush=True)
    if _load_yaml(result_path)["semantic_result_sha256"] != semantic_hash:
        raise CoupledExecutionError("written result semantic hash drift")
    print(
        f"[10/10] PASS: {len(member_ids)} members, {len(raw_rows)} paired branches, "
        f"{graph_summary['direct_source_to_cone_edges']} direct basal edges, zero selection; {semantic_hash}",
        flush=True,
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--result", type=Path, default=RESULT_PATH)
    parser.add_argument("--evaluation", type=Path, default=EVALUATION_PATH)
    parser.add_argument("--parameter-set", type=Path, default=PARAMETER_SET_PATH)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    try:
        run_execution(args.campaign, args.result, args.evaluation, args.parameter_set, args.output_root)
    except CoupledExecutionError as exc:
        print(f"[FAIL] {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

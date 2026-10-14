from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml
from scipy import sparse

from .basal_source_bridges import event_probability
from .basal_source_envelope import _locate, _probe_ids
from .ledger import ROOT
from .typed_hybrid_runtime import EVENT, GRADED, DiagnosticConstants, TorchTypedHybridRuntime, _load_assignments


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "basal-event-scale-compatibility-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "basal-event-scale-compatibility-v0.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "basal-event-scale-compatibility-v0.yaml"
PARAMETER_SET_PATH = ROOT / "calibration" / "parameter_sets" / "basal-event-scale-technical-grid-v0.yaml"
OUTPUT_ROOT = ROOT / "data" / "derived" / "calibration" / "basal-event-scale-compatibility-v0"


class BasalEventScaleGateError(RuntimeError):
    """Raised when the preregistered technical compatibility scan drifts."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BasalEventScaleGateError(f"{path} must contain a YAML mapping")
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


def _verify_frozen_inputs(campaign: Mapping[str, Any]) -> dict[str, Path]:
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise BasalEventScaleGateError("the scan cannot optimize parameters")
    if campaign.get("behavior_targets"):
        raise BasalEventScaleGateError("the scan cannot expose named behavior")
    if campaign.get("topology_changes_allowed") is not False:
        raise BasalEventScaleGateError("the scan cannot change topology")
    if int(campaign.get("parameter_values_promoted", -1)) != 0:
        raise BasalEventScaleGateError("technical grid values cannot be promoted")
    paths: dict[str, Path] = {}
    for key, record in campaign["frozen_inputs"].items():
        path = ROOT / str(record["path"])
        if not path.is_file():
            raise BasalEventScaleGateError(f"missing frozen input {key}: {path}")
        observed = _sha256(path)
        if observed != str(record["sha256"]):
            raise BasalEventScaleGateError(
                f"frozen input drift for {key}: {observed} != {record['sha256']}"
            )
        paths[key] = path
    return paths


def compile_members(campaign: Mapping[str, Any]) -> list[dict[str, Any]]:
    grid = campaign["technical_grid"]
    steps = int(grid["steps"])
    members: list[dict[str, Any]] = [
        {
            "member_id": "silence_control",
            "uniform_rate_hz": 0.0,
            "event_to_event_mV": float(grid["event_to_event_mV"][0]),
            "steps": steps,
            "seed": int(grid["seed"]),
        }
    ]
    for rate_index, rate_hz in enumerate(grid["uniform_rate_hz"]):
        # The seed depends on rate, not scale: each scale sees identical source events.
        rate_seed = int(grid["seed"]) + rate_index + 1
        for scale_mV in grid["event_to_event_mV"]:
            members.append(
                {
                    "member_id": f"rate_{float(rate_hz):g}hz__scale_{float(scale_mV):g}mv",
                    "uniform_rate_hz": float(rate_hz),
                    "event_to_event_mV": float(scale_mV),
                    "steps": steps,
                    "seed": rate_seed,
                }
            )
    if len({row["member_id"] for row in members}) != len(members):
        raise BasalEventScaleGateError("grid member ids are not unique")
    return members


def _execute_member(
    incoming: sparse.csr_matrix,
    assignment: np.ndarray,
    constants: DiagnosticConstants,
    source_positions: np.ndarray,
    probe_groups: Mapping[str, np.ndarray],
    *,
    device: str,
    rate_hz: float,
    steps: int,
    seed: int,
) -> dict[str, Any]:
    import torch

    if np.any(assignment[source_positions] != EVENT):
        raise BasalEventScaleGateError("all source terminals must use event ports in this scan")
    probability = float(event_probability(np.asarray([rate_hz]), constants.dt_ms)[0])
    rng = np.random.default_rng(seed)
    runtime = TorchTypedHybridRuntime(incoming, assignment, constants, device)
    torch_probes = {
        key: torch.as_tensor(value, dtype=torch.int64, device=device)
        for key, value in probe_groups.items()
    }
    maxima = {
        key: {"event_g_l1": 0.0, "state_max_abs": 0.0}
        for key in probe_groups
    }
    forced_events = 0
    generated_events = 0
    first_generated_step: int | None = None
    for step in range(steps):
        selected = rng.random(len(source_positions)) < probability
        forced = source_positions[np.flatnonzero(selected)]
        row = runtime.step(forced_event_indices=forced)
        forced_events += int(len(forced))
        generated = int(row["generated_events"])
        generated_events += generated
        if generated and first_generated_step is None:
            first_generated_step = step
        for key, indices in torch_probes.items():
            event_l1 = float(torch.sum(torch.abs(runtime.g[indices])).item())
            state_max = float(torch.max(torch.abs(runtime.g[indices])).item())
            maxima[key]["event_g_l1"] = max(maxima[key]["event_g_l1"], event_l1)
            maxima[key]["state_max_abs"] = max(maxima[key]["state_max_abs"], state_max)
    states = runtime.state_arrays()
    result = {
        "event_presence_probability_per_step": probability,
        "forced_source_events": forced_events,
        "generated_internal_events": generated_events,
        "first_generated_step": first_generated_step,
        "first_generated_time_ms": (
            None
            if first_generated_step is None
            else round(first_generated_step * constants.dt_ms, 9)
        ),
        "probe_maxima": maxima,
        "finite_state": bool(all(np.isfinite(value).all() for value in states.values())),
    }
    del runtime
    gc.collect()
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    return result


def run_gate(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    parameter_set_path: Path = PARAMETER_SET_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    import torch

    campaign = _load_yaml(campaign_path)
    paths = _verify_frozen_inputs(campaign)
    runtime_campaign = _load_yaml(paths["runtime_campaign"])
    base_constants = DiagnosticConstants.from_campaign(runtime_campaign)

    print("[1/8] Verifying frozen graph, all-event assignment and 6,041 sources", flush=True)
    incoming = sparse.load_npz(paths["incoming_graph"]).tocsr()
    mixed_assignment, body_ids = _load_assignments(paths, runtime_campaign)
    assignment = np.where(mixed_assignment == GRADED, EVENT, mixed_assignment).astype(np.int8)
    sources = pd.read_csv(paths["source_terminals"]).sort_values(
        ["family_id", "channel_id", "body_id"]
    ).reset_index(drop=True)
    source_positions = _locate(
        body_ids, sources["body_id"].to_numpy(np.int64), "basal source table"
    )
    if len(sources) != int(campaign["acceptance"]["expected_terminals"]):
        raise BasalEventScaleGateError("basal source count drift")
    sensory, intermediate, motor = _probe_ids(paths)
    probe_groups = {
        "sensory_36": _locate(body_ids, sensory, "local sensory probe"),
        "intermediate_150": _locate(body_ids, intermediate, "local intermediate probe"),
        "motor_10": _locate(body_ids, motor, "local motor probe"),
    }

    print("[2/8] Compiling the immutable silence + 3 x 4 technical grid", flush=True)
    members = compile_members(campaign)
    if len(members) != int(campaign["acceptance"]["expected_members"]):
        raise BasalEventScaleGateError("technical grid size drift")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    alias_limit = float(campaign["acceptance"]["max_event_presence_probability_per_step"])

    print(f"[3/8] Executing {len(members)} full-graph members on {device}", flush=True)
    rows: list[dict[str, Any]] = []
    for index, member in enumerate(members, start=1):
        print(f"[3/8] member {index}/{len(members)}: {member['member_id']}", flush=True)
        constants = replace(base_constants, event_to_event_mV=member["event_to_event_mV"])
        constants.validate()
        execution = _execute_member(
            incoming,
            assignment,
            constants,
            source_positions,
            probe_groups,
            device=device,
            rate_hz=member["uniform_rate_hz"],
            steps=member["steps"],
            seed=member["seed"],
        )
        if execution["event_presence_probability_per_step"] > alias_limit:
            raise BasalEventScaleGateError(f"event alias bound exceeded by {member['member_id']}")
        rows.append({**member, **execution})

    print("[4/8] Mapping threshold-crossing regimes without ranking members", flush=True)
    non_silence = [row for row in rows if row["uniform_rate_hz"] > 0]
    active = [row for row in non_silence if row["generated_internal_events"] > 0]
    inactive = [row for row in non_silence if row["generated_internal_events"] == 0]
    straddles = bool(active and inactive)
    onset_by_rate = {}
    for rate_hz in campaign["technical_grid"]["uniform_rate_hz"]:
        rate_rows = [row for row in non_silence if math.isclose(row["uniform_rate_hz"], float(rate_hz))]
        active_scales = [row["event_to_event_mV"] for row in rate_rows if row["generated_internal_events"] > 0]
        onset_by_rate[f"{float(rate_hz):g}_hz"] = min(active_scales) if active_scales else None

    print("[5/8] Applying accounting, finiteness and anti-promotion gates", flush=True)
    silence = rows[0]
    checks = {
        "all_6041_sources_accounted_once": len(sources) == 6041 and not sources["body_id"].duplicated().any(),
        "all_sources_are_event_ports": bool(np.all(assignment[source_positions] == EVENT)),
        "complete_grid_executed": len(rows) == 13,
        "identical_event_draw_seed_across_scales_at_fixed_rate": all(
            len({row["seed"] for row in non_silence if math.isclose(row["uniform_rate_hz"], float(rate))}) == 1
            for rate in campaign["technical_grid"]["uniform_rate_hz"]
        ),
        "event_alias_bound_pass": all(row["event_presence_probability_per_step"] <= alias_limit for row in rows),
        "all_runs_finite": all(row["finite_state"] for row in rows),
        "silence_generates_no_events": silence["forced_source_events"] == 0 and silence["generated_internal_events"] == 0,
        "grid_contains_subthreshold_member": bool(inactive),
        "grid_contains_threshold_crossing_member": bool(active),
        "grid_straddles_threshold_compatibility": straddles,
        "parameter_values_promoted": False,
        "members_ranked_or_selected": False,
        "named_behavior_exposed": False,
    }
    required = (
        "all_6041_sources_accounted_once",
        "all_sources_are_event_ports",
        "complete_grid_executed",
        "identical_event_draw_seed_across_scales_at_fixed_rate",
        "event_alias_bound_pass",
        "all_runs_finite",
        "silence_generates_no_events",
    )
    if not all(checks[key] for key in required):
        failed = [key for key in required if not checks[key]]
        raise BasalEventScaleGateError(f"required gates failed: {failed}")

    print("[6/8] Building semantic and raw results", flush=True)
    semantic_members = [
        {
            "member_id": row["member_id"],
            "uniform_rate_hz": row["uniform_rate_hz"],
            "event_to_event_mV": row["event_to_event_mV"],
            "steps": row["steps"],
            "seed": row["seed"],
            "forced_source_events": row["forced_source_events"],
            "generated_internal_events": row["generated_internal_events"],
            "first_generated_step": row["first_generated_step"],
            "finite_state": row["finite_state"],
            "reached_probe_groups": [
                key for key, value in row["probe_maxima"].items() if value["state_max_abs"] > 0
            ],
        }
        for row in rows
    ]
    semantic = {
        "campaign_id": campaign["id"],
        "members": semantic_members,
        "threshold_crossing_members": len(active),
        "subthreshold_members": len(inactive),
        "onset_scale_mV_by_rate": onset_by_rate,
        "checks": checks,
    }
    semantic_hash = _canonical_hash(semantic)
    compact_members = [
        {
            **member,
            "first_generated_time_ms": row["first_generated_time_ms"],
            "semantic_sha256": _canonical_hash(member),
        }
        for member, row in zip(semantic_members, rows, strict=True)
    ]
    conclusion = (
        "The fixed technical grid straddles internally silent and threshold-crossing regimes, "
        "so source intensity and event-to-event scale are a coupled compatibility gate."
        if straddles
        else "The fixed technical grid does not straddle threshold compatibility; the gate remains unresolved."
    )
    status = (
        "accepted_technical_compatibility_map_no_value_promoted"
        if straddles
        else "completed_negative_technical_map_compatibility_unresolved"
    )
    result = {
        "schema_version": 1,
        "id": "runner_result.basal_event_scale_compatibility.v0",
        "campaign_id": campaign["id"],
        "status": status,
        "backend": device,
        "graph": {"nodes": int(incoming.shape[0]), "edges": int(incoming.nnz)},
        "source_terminals": len(sources),
        "local_probe_populations": {"sensory": 36, "intermediate": 150, "motor": 10},
        "members": compact_members,
        "diagnostic_findings": {
            "threshold_crossing_members": len(active),
            "subthreshold_members": len(inactive),
            "onset_scale_mV_by_rate": onset_by_rate,
            "interpretation": conclusion + " These coordinates are engineering probes, not physiological bounds.",
        },
        "checks": checks,
        "scientific_boundary": {
            "physiological_values_promoted": 0,
            "selected_reference_member_id": None,
            "members_ranked_or_selected": False,
            "named_behavior_exposed": False,
        },
        "semantic_result_sha256": semantic_hash,
        "next_action": campaign["next_action"],
    }
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.basal_event_scale_compatibility.v0",
        "campaign_id": campaign["id"],
        "status": status,
        "conclusion": conclusion,
        "diagnostic_findings": result["diagnostic_findings"],
        "checks": checks,
        "runner_semantic_sha256": semantic_hash,
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    parameter_set = {
        "schema_version": 1,
        "id": "parameters.basal_event_scale_technical_grid.v0",
        "title": "Unselected basal event intensity and synaptic-scale compatibility grid",
        "status": "technical_sensitivity_set_unpromotable_as_physiology",
        "campaign_id": campaign["id"],
        "runner_semantic_sha256": semantic_hash,
        "member_count": len(rows),
        "member_ids": [row["member_id"] for row in rows],
        "members_ranked": False,
        "selected_reference_member_id": None,
        "values_are_physiological_bounds": False,
        "reopening_policy": "new_campaign_required_no_post_hoc_grid_extension",
        "next_action": campaign["next_action"],
    }

    print("[7/8] Writing compact records and ignored raw diagnostics", flush=True)
    for path, payload in (
        (result_path, result),
        (evaluation_path, evaluation),
        (parameter_set_path, parameter_set),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "raw-diagnostics.json").write_text(
        json.dumps({"campaign_id": campaign["id"], "members": rows}, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (output_root / "semantic-summary.json").write_text(
        json.dumps(semantic, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    if _load_yaml(result_path)["semantic_result_sha256"] != semantic_hash:
        raise BasalEventScaleGateError("written semantic hash drift")
    print(
        f"[8/8] PASS: {len(rows)} members, {len(inactive)} subthreshold, "
        f"{len(active)} threshold-crossing, semantic {semantic_hash}",
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
        run_gate(args.campaign, args.result, args.evaluation, args.parameter_set, args.output_root)
    except BasalEventScaleGateError as exc:
        print(f"[FAIL] {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

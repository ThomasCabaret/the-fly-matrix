from __future__ import annotations

import argparse
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import yaml

from .embodied_measurement_contract import _episode_metrics, paired_recovery_metrics
from .ledger import ROOT
from .neutral_embodied_declared_closed_loop_sentinel import (
    DeclaredClosedLoopSentinelError,
    _canonical_hash,
    _compact_episode,
    _incoming_l1_matrices,
    _load_yaml,
    _profiles,
    _run_episode,
    _verified_context,
    geometry_oracle,
)
from .neutral_embodied_full_chain_sentinel import _sha256
from .runtime import FlyBodyPhysicsLoop


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "neutral-embodied-declared-closed-loop-panel-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "neutral-embodied-declared-closed-loop-panel-v0.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "neutral-embodied-declared-closed-loop-panel-v0.yaml"
RUN_ROOT = ROOT / "runs" / "calibration" / "neutral-embodied-declared-closed-loop-panel-v0"


class DeclaredClosedLoopPanelError(RuntimeError):
    """Raised when exhaustive causal physical accounting violates its contract."""


def _load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = _load_yaml(path)
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise DeclaredClosedLoopPanelError("panel must remain diagnostic_only")
    if campaign.get("behavior_targets"):
        raise DeclaredClosedLoopPanelError("panel cannot expose behavior targets")
    if campaign.get("topology_changes_allowed") is not False:
        raise DeclaredClosedLoopPanelError("panel cannot change topology")
    boundary = campaign["scientific_boundary"]
    for key in ("optimized_parameters", "promoted_parameter_values", "selected_candidates", "named_behavior_exposure"):
        if int(boundary.get(key, -1)) != 0:
            raise DeclaredClosedLoopPanelError(f"panel requires zero {key}")
    acceptance = campaign["acceptance"]
    for key in ("allow_neural_magnitude_to_select_candidate", "allow_physical_magnitude_to_select_candidate"):
        if acceptance.get(key) is not False:
            raise DeclaredClosedLoopPanelError(f"panel must forbid {key}")
    if acceptance.get("stability_acceptance_possible") is not False:
        raise DeclaredClosedLoopPanelError("panel cannot accept stability")
    return campaign


def _verified_panel_context(campaign: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    frozen = campaign["frozen_inputs"]
    hash_pairs = {
        "causal_sentinel_campaign": "causal_sentinel_campaign_sha256",
        "causal_sentinel_result": "causal_sentinel_result_sha256",
        "causal_sentinel_evaluation": "causal_sentinel_evaluation_sha256",
        "declared_schedule": "declared_schedule_sha256",
        "declared_parameter_set": "declared_parameter_set_sha256",
    }
    observed: dict[str, str] = {}
    for key, expected_key in hash_pairs.items():
        path = ROOT / str(frozen[key])
        observed[key] = _sha256(path)
        if observed[key] != str(frozen[expected_key]):
            raise DeclaredClosedLoopPanelError(f"frozen input drift for {key}")

    sentinel_campaign = _load_yaml(ROOT / str(frozen["causal_sentinel_campaign"]))
    sentinel_result = _load_yaml(ROOT / str(frozen["causal_sentinel_result"]))
    sentinel_evaluation = _load_yaml(ROOT / str(frozen["causal_sentinel_evaluation"]))
    if sentinel_result.get("semantic_result_sha256") != frozen["causal_sentinel_result_semantic_sha256"]:
        raise DeclaredClosedLoopPanelError("causal sentinel semantic result drift")
    if sentinel_result.get("status") != "pass_causal_closed_loop_execution_no_fit_no_selection":
        raise DeclaredClosedLoopPanelError("causal sentinel is not passed")
    if sentinel_evaluation.get("status") != "pass":
        raise DeclaredClosedLoopPanelError("causal sentinel evaluation is not passed")
    context = _verified_context(sentinel_campaign)
    if len(context["rows"]) != int(campaign["coverage_contract"]["schedule_tuples"]):
        raise DeclaredClosedLoopPanelError("exact schedule tuple count drift")
    return context, sentinel_result, observed


def _coverage(rows: Sequence[Mapping[str, str]]) -> dict[str, int]:
    specs = {
        "schedule_tuples": "tuple_id",
        "feco_routing_profiles": "feco_routing_profile_id",
        "unknown_sign_profiles": "unknown_sign_profile_id",
        "numeric_profiles": "numeric_profile_id",
        "intermediate_profiles": "intermediate_profile_id",
        "feco_alternatives": "feco_alternative_id",
        "motor_assignments": "motor_assignment_signature",
        "bridge_gains": "bridge_gain_index",
    }
    observed = {name: len({str(row[column]) for row in rows}) for name, column in specs.items()}
    observed["route_basis_edges"] = len({
        (str(row["route_body_id"]), str(row["route_target_actuator_id"]))
        for row in rows
    })
    return observed


def _distribution(values: Sequence[float | int]) -> dict[str, float | int | None]:
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0:
        return {"count": 0, "min": None, "q25": None, "median": None, "q75": None, "max": None, "mean": None}
    return {
        "count": int(array.size),
        "min": float(array.min()),
        "q25": float(np.quantile(array, 0.25)),
        "median": float(np.median(array)),
        "q75": float(np.quantile(array, 0.75)),
        "max": float(array.max()),
        "mean": float(array.mean()),
    }


def _descriptive_summary(completed: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    branches = [(item, branch) for item in completed for branch in ("baseline", "perturbed")]
    chain_branches = [(item, f"{branch}_chain") for item in completed for branch in ("baseline", "perturbed")]
    silent_ids = [
        str(item["tuple_id"])
        for item in completed
        if int(item["baseline_chain"]["route_motor_event_count"]) == 0
        and int(item["perturbed_chain"]["route_motor_event_count"]) == 0
    ]
    command_ids = [
        str(item["tuple_id"])
        for item in completed
        if float(item["baseline_chain"]["peak_abs_command"]) > 0.0
        or float(item["perturbed_chain"]["peak_abs_command"]) > 0.0
    ]
    return {
        "tuples_with_silent_scheduled_route": len(silent_ids),
        "silent_tuple_ids": silent_ids,
        "tuples_with_nonzero_routed_command": len(command_ids),
        "nonzero_command_tuple_ids": command_ids,
        "unique_chain_trace_hashes": len({str(item[key]["trace_sha256"]) for item, key in chain_branches}),
        "source_nonzero_steps": _distribution([item[key]["source_nonzero_steps"] for item, key in chain_branches]),
        "source_event_count": _distribution([item[key]["source_event_count"] for item, key in chain_branches]),
        "intermediate_spike_count": _distribution([item[key]["intermediate_spike_count"] for item, key in chain_branches]),
        "motor_spike_count": _distribution([item[key]["motor_spike_count"] for item, key in chain_branches]),
        "route_motor_event_count": _distribution([item[key]["route_motor_event_count"] for item, key in chain_branches]),
        "peak_abs_command": _distribution([item[key]["peak_abs_command"] for item, key in chain_branches]),
        "joint_limit_violation_frames": _distribution([item[key]["joint_limit_violation_frames"] for item, key in branches]),
        "gross_fall_proxy_frames": _distribution([item[key]["gross_fall_proxy_frames"] for item, key in branches]),
        "numerical_failure_frames": _distribution([item[key]["numerical_failure_frames"] for item, key in branches]),
        "paired_center_of_mass_final_over_peak": _distribution([
            item["paired_recovery"]["center_of_mass"]["final_over_peak"] for item in completed
        ]),
        "paired_qpos_final_over_peak": _distribution([
            item["paired_recovery"]["qpos"]["final_over_peak"] for item in completed
        ]),
        "paired_qvel_final_over_peak": _distribution([
            item["paired_recovery"]["qvel"]["final_over_peak"] for item in completed
        ]),
        "interpretation": "Descriptive accounting only; no observed magnitude is a selection rule or a stability threshold.",
    }


def run_panel(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    run_root: Path = RUN_ROOT,
) -> dict[str, Any]:
    started = time.perf_counter()
    print("[1/8] Verifying preregistration, exact schedule and frozen sentinel", flush=True)
    campaign = _load_campaign(campaign_path)
    context, sentinel_result, frozen_hashes = _verified_panel_context(campaign)
    rows = list(context["rows"])
    expected_ids = [str(row["tuple_id"]) for row in rows]
    observed_coverage = _coverage(rows)
    expected_coverage = {
        key: int(value)
        for key, value in campaign["coverage_contract"].items()
        if key in observed_coverage
    }
    if observed_coverage != expected_coverage:
        raise DeclaredClosedLoopPanelError(f"schedule coverage drift: {observed_coverage} != {expected_coverage}")

    print("[2/8] Revalidating geometry and structural coupling oracles", flush=True)
    geometry = geometry_oracle()
    profiles = _profiles(context)
    first, second, direct, coupling_audit = _incoming_l1_matrices(context["inputs"])
    matrices = (first, second, direct)
    if not geometry["all_strictly_increasing"] or geometry["minimum_covered_span_deg"] < 120.0:
        raise DeclaredClosedLoopPanelError("geometric registration oracle failed")
    if not coupling_audit["all_nonzero_columns_exact"]:
        raise DeclaredClosedLoopPanelError("incoming-L1 structural oracle failed")

    sentinel_outcomes = {str(item["tuple_id"]): item for item in sentinel_result["outcomes"]}
    sentinel_campaign = _load_yaml(ROOT / str(campaign["frozen_inputs"]["causal_sentinel_campaign"]))
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    artifact_root = run_root / run_id
    artifact_root.mkdir(parents=True, exist_ok=False)
    perturbation = sentinel_campaign["physical_protocol"]["perturbation"]
    outcomes: list[dict[str, Any]] = []

    print("[3/8] Building one reusable FlyBody/MuJoCo model", flush=True)
    with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=False) as loop:
        print("[4/8] Executing 240 tuples / 480 reset-isolated physical episodes", flush=True)
        for index, row in enumerate(rows, start=1):
            print(f"[TUPLE {index:03d}/{len(rows)}] {row['tuple_id']}", flush=True)
            outcome: dict[str, Any] = {"tuple_id": str(row["tuple_id"]), "status": "error"}
            try:
                baseline, baseline_metadata, baseline_diag = _run_episode(
                    sentinel_campaign,
                    row,
                    context,
                    profiles,
                    matrices,
                    perturbation=None,
                    reusable_loop=loop,
                )
                perturbed, perturbed_metadata, perturbed_diag = _run_episode(
                    sentinel_campaign,
                    row,
                    context,
                    profiles,
                    matrices,
                    perturbation=perturbation,
                    reusable_loop=loop,
                )
                if baseline_metadata["model_contract"] != perturbed_metadata["model_contract"]:
                    raise DeclaredClosedLoopPanelError("paired model contracts differ")
                baseline_metrics = _episode_metrics(baseline, baseline_metadata)
                perturbed_metrics = _episode_metrics(perturbed, perturbed_metadata)
                recovery = paired_recovery_metrics(
                    baseline,
                    perturbed,
                    int(sentinel_campaign["physical_protocol"]["perturbation_step"]),
                )
                finite = baseline_metrics["finite_fraction"] == 1.0 and perturbed_metrics["finite_fraction"] == 1.0
                tuple_dir = artifact_root / str(row["tuple_id"])
                tuple_dir.mkdir(parents=True, exist_ok=False)
                baseline_path = tuple_dir / "baseline.npz"
                perturbed_path = tuple_dir / "perturbed.npz"
                np.savez_compressed(baseline_path, **baseline)
                np.savez_compressed(perturbed_path, **perturbed)
                outcome.update({
                    "status": "completed_contract" if finite else "failed_nonfinite",
                    "baseline": _compact_episode(baseline_metrics),
                    "perturbed": _compact_episode(perturbed_metrics),
                    "baseline_chain": baseline_diag,
                    "perturbed_chain": perturbed_diag,
                    "paired_recovery": recovery,
                    "artifacts": {
                        "baseline": str(baseline_path.relative_to(ROOT)).replace("\\", "/"),
                        "perturbed": str(perturbed_path.relative_to(ROOT)).replace("\\", "/"),
                    },
                })
            except Exception as exc:
                outcome["error"] = f"{type(exc).__name__}: {exc}"
            outcomes.append(outcome)

    print("[5/8] Accounting every result without candidate ranking", flush=True)
    counts = Counter(item["status"] for item in outcomes)
    completed = [item for item in outcomes if item["status"] == "completed_contract"]
    source_active = all(
        int(item[key]["source_nonzero_steps"]) > 0
        for item in completed for key in ("baseline_chain", "perturbed_chain")
    )
    isolated = all(
        item[key]["active_actuator_ids"] in ([], [item[key]["target_actuator_id"]])
        for item in completed for key in ("baseline_chain", "perturbed_chain")
    )
    causal_actuation = any(
        float(item[key]["peak_abs_command"]) > 0.0
        for item in completed for key in ("baseline_chain", "perturbed_chain")
    )
    perturbation_detected = all(
        float(item["paired_recovery"]["qvel"]["peak_l2"]) > 0.0 for item in completed
    )
    overlap_checks: dict[str, bool] = {}
    by_id = {str(item["tuple_id"]): item for item in completed}
    for tuple_id, sentinel_item in sentinel_outcomes.items():
        panel_item = by_id.get(tuple_id)
        overlap_checks[tuple_id] = bool(
            panel_item
            and panel_item["baseline_chain"]["trace_sha256"] == sentinel_item["baseline_chain"]["trace_sha256"]
            and panel_item["perturbed_chain"]["trace_sha256"] == sentinel_item["perturbed_chain"]["trace_sha256"]
        )

    elapsed = time.perf_counter() - started
    checks = {
        "every_schedule_tuple_accounted_exactly_once": [str(item["tuple_id"]) for item in outcomes] == expected_ids,
        "all_480_paired_episodes_finite": len(completed) == len(rows),
        "exact_schedule_axis_coverage": observed_coverage == expected_coverage,
        "bilateral_geometric_registration_passed": bool(geometry["all_strictly_increasing"]),
        "causal_source_path_active_in_every_episode": source_active and len(completed) == len(rows),
        "non_scoped_actuator_outputs_zero": isolated and len(completed) == len(rows),
        "generic_perturbation_detected_in_every_pair": perturbation_detected and len(completed) == len(rows),
        "at_least_one_causal_nonzero_actuator_command": causal_actuation,
        "incoming_L1_columns_exact": bool(coupling_audit["all_nonzero_columns_exact"]),
        "all_16_frozen_sentinel_traces_reproduced_after_model_reuse": len(overlap_checks) == 16 and all(overlap_checks.values()),
        "within_preregistered_wall_clock_budget": elapsed <= float(campaign["compute_budget"]["maximum_wall_clock_minutes"]) * 60.0,
        "zero_fit_zero_selection_zero_behavior": True,
    }
    passed = all(checks.values())
    descriptive = _descriptive_summary(completed)

    print("[6/8] Writing heavy ignored traces and compact versioned accounting", flush=True)
    result = {
        "schema_version": 1,
        "id": "runner_result.neutral_embodied_declared_closed_loop_panel.v0",
        "campaign_id": campaign["id"],
        "status": "pass_exhaustive_causal_physical_accounting_no_fit_no_selection" if passed else "failed_exhaustive_causal_physical_accounting",
        "completed_at": datetime.now(UTC).isoformat(),
        "claim_label": campaign["claim_label"],
        "command": "neutral_embodied_declared_closed_loop_panel.bat",
        "frozen_input_sha256": frozen_hashes,
        "geometry_registration": geometry,
        "structural_coupling_audit": coupling_audit,
        "coverage": observed_coverage,
        "accounting": {
            "schedule_tuples": len(rows),
            "paired_physical_episodes": len(rows) * 2,
            "outcome_counts": dict(sorted(counts.items())),
            "optimized_parameters": 0,
            "promoted_parameter_values": 0,
            "selected_candidates": 0,
            "named_behavior_exposure": 0,
        },
        "checks": checks,
        "sentinel_overlap_trace_reproduction": overlap_checks,
        "descriptive_only": descriptive,
        "outcomes": outcomes,
        "scientific_boundary": campaign["scientific_boundary"],
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "wall_seconds": elapsed,
        "next_action": campaign["next_action"],
    }
    semantic_outcomes = [{key: value for key, value in item.items() if key != "artifacts"} for item in outcomes]
    result["semantic_result_sha256"] = _canonical_hash({
        **{key: value for key, value in result.items() if key not in {"completed_at", "wall_seconds", "outcomes"}},
        "outcomes": semantic_outcomes,
    })
    result_path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.neutral_embodied_declared_closed_loop_panel.v0",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": result["semantic_result_sha256"],
        "status": "pass" if passed else "fail",
        "checks": checks,
        "descriptive_only_summary": descriptive,
        "stability_accepted": False,
        "population_assignment_accepted": False,
        "candidate_selected": False,
        "behavior_claimed": False,
        "interpretation": "A pass closes exhaustive causal physical accounting for the declared local envelope only; it calibrates and selects nothing.",
        "next_action": campaign["next_action"],
    }
    evaluation_path.write_text(yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8")

    print("[7/8] Verifying locked scientific boundaries", flush=True)
    if not passed:
        failed = [key for key, value in checks.items() if not value]
        raise DeclaredClosedLoopPanelError(f"declared causal panel failed: {failed}")
    print("[8/8] PASS", flush=True)
    print(f"[ACCOUNTING] {len(rows)}/240 tuples, {len(rows) * 2}/480 paired episodes", flush=True)
    print(f"[SILENT RETAINED] {descriptive['tuples_with_silent_scheduled_route']} tuples", flush=True)
    print(f"[NONZERO COMMAND] {descriptive['tuples_with_nonzero_routed_command']} tuples", flush=True)
    print("[BOUNDARY] 0 fit, 0 selection, 0 promotion, 0 behavior, 0 stability acceptance", flush=True)
    print(f"[WALL] {elapsed:.2f} s", flush=True)
    print(f"[HASH] {result['semantic_result_sha256']}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run exhaustive declared causal physical accounting")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    run_panel(campaign_path=args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml

from .actuator_attribution import _deviation_metrics
from .ledger import ROOT
from .neutral_embodied_declared_closed_loop_sentinel import (
    _canonical_hash,
    _incoming_l1_matrices,
    _load_yaml,
    _profiles,
    _run_episode,
    _sha256,
    _verified_context,
)
from .neutral_embodied_feedback_identifiability import (
    _compact_metrics,
    _max_abs_delta,
    _run_frozen_command_episode,
)
from .runtime import FlyBodyPhysicsLoop


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "neutral-embodied-feedback-nonamplification-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "neutral-embodied-feedback-nonamplification-v0.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "neutral-embodied-feedback-nonamplification-v0.yaml"
PARAMETER_SET_PATH = ROOT / "calibration" / "parameter_sets" / "front-leg-local-feedback-nonamplifying-ensemble-v0.yaml"
RUN_ROOT = ROOT / "runs" / "calibration" / "neutral-embodied-feedback-nonamplification-v0"


class FeedbackNonamplificationError(RuntimeError):
    """Raised when the locked local non-amplification experiment cannot be completed."""


def _load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = _load_yaml(path)
    if campaign.get("primary_class") != "technical":
        raise FeedbackNonamplificationError("non-amplification campaign must remain technical")
    if campaign.get("optimization_exposure") != "allowed":
        raise FeedbackNonamplificationError("technical pass/fail selection must remain explicitly exposed")
    if campaign.get("behavior_targets"):
        raise FeedbackNonamplificationError("non-amplification campaign cannot expose behavior targets")
    if campaign.get("topology_changes_allowed") is not False:
        raise FeedbackNonamplificationError("non-amplification campaign cannot change topology")
    if campaign["campaign_acceptance"].get("stability_acceptance_possible") is not False:
        raise FeedbackNonamplificationError("bounded local experiment cannot accept whole-body stability")
    if campaign["per_row_acceptance"].get("allow_ranking_within_accepted_set") is not False:
        raise FeedbackNonamplificationError("accepted exact composites cannot be ranked")
    return campaign


def _verified_inputs(campaign: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    frozen = campaign["frozen_inputs"]
    keys = ("feedback_campaign", "feedback_result", "feedback_evaluation", "causal_execution_campaign")
    hashes: dict[str, str] = {}
    for key in keys:
        observed = _sha256(ROOT / str(frozen[key]))
        expected = str(frozen[f"{key}_sha256"])
        if observed != expected:
            raise FeedbackNonamplificationError(f"frozen input drift for {key}: {observed} != {expected}")
        hashes[key] = observed
    feedback_result = _load_yaml(ROOT / str(frozen["feedback_result"]))
    if feedback_result.get("semantic_result_sha256") != frozen["feedback_result_semantic_sha256"]:
        raise FeedbackNonamplificationError("feedback result semantic hash drift")
    if feedback_result.get("status") != "pass_feedback_identifiability_no_selection":
        raise FeedbackNonamplificationError("feedback-identifiability parent did not pass")
    sentinel_campaign = _load_yaml(ROOT / str(frozen["causal_execution_campaign"]))
    return {"feedback_result": feedback_result, "sentinel_campaign": sentinel_campaign}, hashes


def _active_ids(campaign: Mapping[str, Any], feedback_result: Mapping[str, Any]) -> list[str]:
    outcomes = feedback_result["outcomes"]
    active = [str(item["tuple_id"]) for item in outcomes if item.get("status") == "completed"]
    expected = campaign["workload_rule"]
    if len(outcomes) != int(expected["active_exact_rows"]) or len(active) != int(expected["active_exact_rows"]):
        raise FeedbackNonamplificationError("parent active-row accounting drift")
    classes = Counter(str(item["classification"]) for item in outcomes)
    if classes["feedback_physically_identifiable"] != int(expected["previously_physically_identifiable"]):
        raise FeedbackNonamplificationError("parent identifiable count drift")
    if classes["feedback_not_identifiable"] != int(expected["previously_not_identifiable"]):
        raise FeedbackNonamplificationError("parent non-identifiable count drift")
    previous_unidentified = [
        str(item["tuple_id"])
        for item in outcomes
        if item["classification"] == "feedback_not_identifiable"
    ]
    if previous_unidentified != list(map(str, expected["previously_not_identifiable_tuple_ids"])):
        raise FeedbackNonamplificationError("parent non-identifiable tuple drift")
    return active


def _within_paired_limit(closed: float, opened: float, tolerances: Mapping[str, Any]) -> bool:
    allowance = float(tolerances["paired_comparison_absolute_tolerance"]) + float(
        tolerances["paired_comparison_relative_tolerance"]
    ) * abs(float(opened))
    return float(closed) <= float(opened) + allowance


def _failure_nonworsening(
    closed_metrics: Mapping[str, Any],
    open_metrics: Mapping[str, Any],
    required: list[str],
) -> tuple[bool, dict[str, Any]]:
    comparisons = {
        key: {
            "closed": int(closed_metrics[key]),
            "open": int(open_metrics[key]),
            "pass": int(closed_metrics[key]) <= int(open_metrics[key]),
        }
        for key in required
    }
    return all(item["pass"] for item in comparisons.values()), comparisons


def _probe_perturbation(
    campaign: Mapping[str, Any],
    sentinel_campaign: Mapping[str, Any],
    row: Mapping[str, str],
    context: Mapping[str, Any],
    profiles: Mapping[str, Any],
    matrices: tuple[np.ndarray, np.ndarray, np.ndarray],
    loop: FlyBodyPhysicsLoop,
    baseline: Mapping[str, np.ndarray],
    baseline_commands: np.ndarray,
    perturbation: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    open_episode, open_metadata = _run_frozen_command_episode(
        sentinel_campaign,
        row,
        baseline_commands,
        perturbation=perturbation,
        loop=loop,
    )
    closed_capture: list[np.ndarray] = []
    closed_episode, closed_metadata, closed_diagnostic = _run_episode(
        sentinel_campaign,
        row,
        context,
        profiles,
        matrices,
        perturbation=perturbation,
        reusable_loop=loop,
        native_command_trace_out=closed_capture,
    )
    if open_metadata["model_contract"] != closed_metadata["model_contract"]:
        raise FeedbackNonamplificationError("open and closed perturbation model contracts differ")

    protocol = campaign["physical_protocol"]
    perturb_native = int(protocol["perturbation_step"]) * int(protocol["physics_substeps_per_frame"])
    command_delta = np.abs(closed_capture[0] - baseline_commands)[perturb_native:]
    command_peak = float(np.max(command_delta, initial=0.0))
    frame = int(protocol["perturbation_step"])
    state_gap = _deviation_metrics(closed_episode, open_episode, frame)
    open_deviation = _deviation_metrics(open_episode, baseline, frame)
    closed_deviation = _deviation_metrics(closed_episode, baseline, frame)
    tolerances = campaign["locked_numeric_tolerances"]
    command_identifiable = command_peak >= float(tolerances["feedback_command_adaptation_l2_min"])
    physical_identifiable = float(state_gap["qpos_l2_peak"]) >= float(tolerances["closed_open_state_gap_l2_min"])
    qpos_nonamplifying = _within_paired_limit(
        closed_deviation["qpos_l2_final"], open_deviation["qpos_l2_final"], tolerances
    )
    qvel_nonamplifying = _within_paired_limit(
        closed_deviation["qvel_l2_final"], open_deviation["qvel_l2_final"], tolerances
    )
    open_compact = _compact_metrics(open_episode, open_metadata)
    closed_compact = _compact_metrics(closed_episode, closed_metadata)
    failure_pass, failure_comparisons = _failure_nonworsening(
        closed_compact,
        open_compact,
        list(campaign["per_perturbation_acceptance"]["require_closed_failure_masks_not_above_open"]),
    )
    passed = command_identifiable and physical_identifiable and qpos_nonamplifying and qvel_nonamplifying and failure_pass
    result = {
        "perturbation": dict(perturbation),
        "status": "pass_nonamplifying" if passed else "fail_nonamplifying",
        "checks": {
            "feedback_command_adaptation": command_identifiable,
            "physical_closed_open_state_gap": physical_identifiable,
            "closed_final_qpos_not_above_open": qpos_nonamplifying,
            "closed_final_qvel_not_above_open": qvel_nonamplifying,
            "closed_failure_masks_not_above_open": failure_pass,
        },
        "feedback_command_adaptation": {
            "l2_peak": command_peak,
            "nonzero_native_steps": int(
                np.count_nonzero(command_delta > float(tolerances["feedback_command_adaptation_l2_min"]))
            ),
        },
        "closed_open_state_gap": state_gap,
        "open_perturbed_vs_baseline": open_deviation,
        "closed_perturbed_vs_baseline": closed_deviation,
        "failure_mask_comparisons": failure_comparisons,
        "branch_metrics": {"open_perturbed": open_compact, "closed_perturbed": closed_compact},
        "closed_chain": closed_diagnostic,
    }
    arrays = {
        "open_qpos": open_episode["qpos"],
        "open_qvel": open_episode["qvel"],
        "closed_qpos": closed_episode["qpos"],
        "closed_qvel": closed_episode["qvel"],
        "closed_native_command": closed_capture[0],
    }
    return result, arrays


def _run_row(
    campaign: Mapping[str, Any],
    sentinel_campaign: Mapping[str, Any],
    row: Mapping[str, str],
    context: Mapping[str, Any],
    profiles: Mapping[str, Any],
    matrices: tuple[np.ndarray, np.ndarray, np.ndarray],
    loop: FlyBodyPhysicsLoop,
    artifact_root: Path,
) -> dict[str, Any]:
    baseline_capture: list[np.ndarray] = []
    baseline, baseline_metadata, baseline_diagnostic = _run_episode(
        sentinel_campaign,
        row,
        context,
        profiles,
        matrices,
        perturbation=None,
        reusable_loop=loop,
        native_command_trace_out=baseline_capture,
    )
    baseline_replay, replay_metadata = _run_frozen_command_episode(
        sentinel_campaign,
        row,
        baseline_capture[0],
        perturbation=None,
        loop=loop,
    )
    if baseline_metadata["model_contract"] != replay_metadata["model_contract"]:
        raise FeedbackNonamplificationError("baseline replay model contract drift")
    replay_state_error = _max_abs_delta(baseline, baseline_replay, ("qpos", "qvel"))
    replay_command_error = _max_abs_delta(baseline, baseline_replay, ("applied_commands",))

    perturbation_results: list[dict[str, Any]] = []
    artifact_arrays: dict[str, np.ndarray] = {
        "baseline_qpos": baseline["qpos"],
        "baseline_qvel": baseline["qvel"],
        "baseline_native_command": baseline_capture[0],
        "baseline_replay_qpos": baseline_replay["qpos"],
        "baseline_replay_qvel": baseline_replay["qvel"],
    }
    for perturbation in campaign["physical_protocol"]["perturbations"]:
        result, arrays = _probe_perturbation(
            campaign,
            sentinel_campaign,
            row,
            context,
            profiles,
            matrices,
            loop,
            baseline,
            baseline_capture[0],
            perturbation,
        )
        perturbation_results.append(result)
        prefix = str(perturbation["id"])
        for key, value in arrays.items():
            artifact_arrays[f"{prefix}__{key}"] = value

    passed_count = sum(item["status"] == "pass_nonamplifying" for item in perturbation_results)
    identifiable_count = sum(
        item["checks"]["feedback_command_adaptation"] and item["checks"]["physical_closed_open_state_gap"]
        for item in perturbation_results
    )
    if passed_count == len(perturbation_results):
        classification = "accepted_local_nonamplifying"
    elif identifiable_count == 0:
        classification = "not_identifiable_on_validation_perturbations"
    else:
        classification = "mixed_or_amplifying"

    tuple_dir = artifact_root / str(row["tuple_id"])
    tuple_dir.mkdir(parents=True, exist_ok=False)
    artifact_path = tuple_dir / "branches.npz"
    np.savez_compressed(artifact_path, **artifact_arrays)
    return {
        "tuple_id": str(row["tuple_id"]),
        "status": "completed",
        "classification": classification,
        "perturbations_passed": passed_count,
        "perturbations_identifiable": identifiable_count,
        "unperturbed_replay": {
            "state_max_abs_error": replay_state_error,
            "command_max_abs_error": replay_command_error,
        },
        "baseline_chain": baseline_diagnostic,
        "baseline_metrics": _compact_metrics(baseline, baseline_metadata),
        "perturbations": perturbation_results,
        "artifact": str(artifact_path.relative_to(ROOT)).replace("\\", "/"),
    }


def _write_parameter_set(
    campaign: Mapping[str, Any],
    result: Mapping[str, Any],
    accepted_ids: list[str],
    path: Path,
) -> dict[str, Any]:
    parameter_set = {
        "schema_version": 1,
        "id": "parameters.front_leg_local_feedback_nonamplifying_ensemble.v0",
        "title": "Exact-composite ensemble passing mirrored local feedback non-amplification",
        "status": "accepted_local_technical_ensemble" if accepted_ids else "completed_empty_technical_ensemble",
        "scope_ids": campaign["scope_ids"],
        "primary_class": "technical",
        "claim_label": campaign["claim_label"],
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": result["semantic_result_sha256"],
        "selection_exposure": {
            "technical_body_trajectory_used": True,
            "named_behavior_used": False,
            "ranking_used": False,
            "held_out_protocol_used": False,
        },
        "ensemble": {
            "representation": "finite_exact_composite_ids",
            "member_count": len(accepted_ids),
            "member_tuple_ids": accepted_ids,
            "members_ranked": False,
            "individual_parameter_values_promoted": 0,
        },
        "applicability": {
            "local_front_leg_chain_only": True,
            "short_horizon_seconds": float(campaign["physical_protocol"]["duration_s_per_episode"]),
            "perturbation_ids": [str(item["id"]) for item in campaign["physical_protocol"]["perturbations"]],
            "whole_body_stability": False,
            "complete_recurrent_MaleCNS": False,
            "biological_behavior": False,
        },
        "frozen_lineage": campaign["frozen_inputs"],
        "reopening_policy": "new_campaign_required_no_silent_threshold_or_topology_change",
        "next_action": campaign["next_action"],
    }
    path.write_text(yaml.safe_dump(parameter_set, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return parameter_set


def run_feedback_nonamplification(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    parameter_set_path: Path = PARAMETER_SET_PATH,
    run_root: Path = RUN_ROOT,
) -> dict[str, Any]:
    started = time.perf_counter()
    print("[1/8] Verifying the frozen feedback gate and causal execution contract", flush=True)
    campaign = _load_campaign(campaign_path)
    inputs, frozen_hashes = _verified_inputs(campaign)
    active_ids = _active_ids(campaign, inputs["feedback_result"])
    sentinel_campaign = inputs["sentinel_campaign"]
    context = _verified_context(sentinel_campaign)
    profiles = _profiles(context)
    first, second, direct, coupling_audit = _incoming_l1_matrices(context["inputs"])
    matrices = (first, second, direct)
    by_id = {str(row["tuple_id"]): row for row in context["rows"]}

    print("[2/8] Locking four new mirrored perturbations and paired dominance criteria", flush=True)
    perturbations = campaign["physical_protocol"]["perturbations"]
    if len(perturbations) != 4 or len({str(item["id"]) for item in perturbations}) != 4:
        raise FeedbackNonamplificationError("expected four unique perturbations")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    artifact_root = run_root / run_id
    artifact_root.mkdir(parents=True, exist_ok=False)
    outcomes: list[dict[str, Any]] = []

    print("[3/8] Executing 65 rows x (baseline, replay, 4 open, 4 closed)", flush=True)
    with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=False) as loop:
        for index, tuple_id in enumerate(active_ids, start=1):
            print(f"[ROW {index:02d}/{len(active_ids)}] {tuple_id}", flush=True)
            try:
                outcome = _run_row(
                    campaign,
                    sentinel_campaign,
                    by_id[tuple_id],
                    context,
                    profiles,
                    matrices,
                    loop,
                    artifact_root,
                )
            except Exception as exc:
                outcome = {"tuple_id": tuple_id, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
            outcomes.append(outcome)

    print("[4/8] Applying locked pass/fail rules without ranking members", flush=True)
    completed = [item for item in outcomes if item["status"] == "completed"]
    classes = Counter(str(item["classification"]) for item in completed)
    accepted_ids = [
        str(item["tuple_id"])
        for item in completed
        if item["classification"] == "accepted_local_nonamplifying"
    ]
    tolerances = campaign["locked_numeric_tolerances"]
    replay_ok = all(
        item["unperturbed_replay"]["state_max_abs_error"] <= float(tolerances["unperturbed_replay_state_max_abs_error"])
        and item["unperturbed_replay"]["command_max_abs_error"] <= float(tolerances["unperturbed_replay_command_max_abs_error"])
        for item in completed
    )
    all_finite = all(
        branch["finite_fraction"] == 1.0
        for item in completed
        for perturbation in item["perturbations"]
        for branch in perturbation["branch_metrics"].values()
    )
    checks = {
        "all_65_active_rows_accounted": len(outcomes) == 65,
        "all_65_rows_completed": len(completed) == 65,
        "all_650_episodes_complete": len(completed) * 10 == 650,
        "all_recorded_branch_arrays_finite": all_finite and len(completed) == 65,
        "all_unperturbed_replays_within_tolerance": replay_ok and len(completed) == 65,
        "four_unique_new_mirrored_perturbations": len(perturbations) == 4,
        "incoming_L1_columns_exact": bool(coupling_audit["all_nonzero_columns_exact"]),
        "zero_numeric_optimization_zero_ranking_zero_behavior": True,
    }
    experiment_passed = all(checks.values())

    print("[5/8] Writing compact result and ignored heavy traces", flush=True)
    elapsed = time.perf_counter() - started
    result: dict[str, Any] = {
        "schema_version": 1,
        "id": "runner_result.neutral_embodied_feedback_nonamplification.v0",
        "campaign_id": campaign["id"],
        "status": "completed_locked_validation" if experiment_passed else "failed_execution_contract",
        "completed_at": datetime.now(UTC).isoformat(),
        "claim_label": campaign["claim_label"],
        "command": "neutral_embodied_feedback_nonamplification.bat",
        "frozen_input_sha256": frozen_hashes,
        "locked_numeric_tolerances": tolerances,
        "accounting": {
            "active_rows": 65,
            "perturbations_per_row": 4,
            "physical_episodes": 650,
            "outcome_counts": dict(sorted(Counter(item["status"] for item in outcomes).items())),
            "classification_counts": dict(sorted(classes.items())),
            "technical_ensemble_members": len(accepted_ids),
            "optimized_numeric_values": 0,
            "individual_parameter_values_promoted": 0,
            "named_behavior_exposure": 0,
        },
        "accepted_tuple_ids": accepted_ids,
        "checks": checks,
        "outcomes": outcomes,
        "scientific_boundary": campaign["scientific_boundary"],
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "whole_body_stability_accepted": False,
        "wall_seconds": elapsed,
        "next_action": campaign["next_action"],
    }
    semantic_outcomes = [{key: value for key, value in item.items() if key != "artifact"} for item in outcomes]
    result["semantic_result_sha256"] = _canonical_hash({
        **{key: value for key, value in result.items() if key not in {"completed_at", "wall_seconds", "outcomes"}},
        "outcomes": semantic_outcomes,
    })
    result_path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")

    print("[6/8] Writing immutable finite-ensemble parameter-set record", flush=True)
    parameter_set = _write_parameter_set(campaign, result, accepted_ids, parameter_set_path)
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.neutral_embodied_feedback_nonamplification.v0",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": result["semantic_result_sha256"],
        "parameter_set_id": parameter_set["id"],
        "status": "completed" if experiment_passed else "failed",
        "checks": checks,
        "classification_counts": dict(sorted(classes.items())),
        "accepted_tuple_ids": accepted_ids,
        "local_feedback_nonamplification_accepted": bool(accepted_ids),
        "whole_body_stability_accepted": False,
        "population_assignment_accepted": False,
        "named_behavior_exposed": False,
        "candidate_ranking_used": False,
        "interpretation": (
            "A nonempty set is a bounded exact-composite technical ensemble for the local front-leg chain only. "
            "It is neither a whole-body stability result nor a biological parameter promotion."
        ),
        "next_action": campaign["next_action"],
    }
    evaluation_path.write_text(yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8")

    print("[7/8] Verifying compute budget and scientific boundaries", flush=True)
    if elapsed > float(campaign["compute_budget"]["maximum_wall_clock_minutes"]) * 60.0:
        raise FeedbackNonamplificationError("wall-clock budget exceeded; result retained")
    if not experiment_passed:
        failed = [key for key, value in checks.items() if not value]
        raise FeedbackNonamplificationError(f"execution contract failed: {failed}")
    print("[8/8] COMPLETE", flush=True)
    print(f"[CLASSES] {dict(sorted(classes.items()))}", flush=True)
    print(f"[ENSEMBLE] {len(accepted_ids)} exact composites; unranked", flush=True)
    print("[BOUNDARY] local technical non-amplification only; whole-body stability NOT accepted", flush=True)
    print(f"[HASH] {result['semantic_result_sha256']}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run mirrored local feedback non-amplification validation")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    run_feedback_nonamplification(campaign_path=args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

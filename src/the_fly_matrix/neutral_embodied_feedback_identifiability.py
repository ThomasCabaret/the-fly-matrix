from __future__ import annotations

import argparse
import csv
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml

from .actuator_attribution import _deviation_metrics
from .embodied_measurement_contract import (
    _center_of_mass,
    _episode_metrics,
    _model_measurement_metadata,
    _root_up_z,
)
from .ledger import ROOT
from .neutral_embodied_declared_closed_loop_sentinel import (
    DeclaredClosedLoopSentinelError,
    _canonical_hash,
    _incoming_l1_matrices,
    _load_yaml,
    _profiles,
    _run_episode,
    _sha256,
    _verified_context,
)
from .runtime import FlyBodyPhysicsLoop


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "neutral-embodied-feedback-identifiability-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "neutral-embodied-feedback-identifiability-v0.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "neutral-embodied-feedback-identifiability-v0.yaml"
RUN_ROOT = ROOT / "runs" / "calibration" / "neutral-embodied-feedback-identifiability-v0"


class FeedbackIdentifiabilityError(RuntimeError):
    """Raised when the preregistered causal-identifiability contract is violated."""


def _load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = _load_yaml(path)
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise FeedbackIdentifiabilityError("feedback gate must remain diagnostic_only")
    if campaign.get("behavior_targets"):
        raise FeedbackIdentifiabilityError("feedback gate cannot expose a behavior target")
    if campaign.get("topology_changes_allowed") is not False:
        raise FeedbackIdentifiabilityError("feedback gate cannot change topology")
    boundary = campaign["scientific_boundary"]
    for key in ("optimized_parameters", "promoted_parameter_values", "selected_candidates", "named_behavior_exposure"):
        if int(boundary.get(key, -1)) != 0:
            raise FeedbackIdentifiabilityError(f"feedback gate requires zero {key}")
    acceptance = campaign["acceptance"]
    if acceptance.get("allow_activity_or_motion_magnitude_to_rank_candidate") is not False:
        raise FeedbackIdentifiabilityError("feedback magnitude cannot rank candidates")
    if acceptance.get("allow_silent_row_rejection") is not False:
        raise FeedbackIdentifiabilityError("silent rows must remain unresolved, not rejected")
    return campaign


def _verified_inputs(campaign: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    frozen = campaign["frozen_inputs"]
    path_keys = (
        "command_policy_campaign",
        "command_policy_result",
        "command_policy_evaluation",
        "command_policy_schedule",
        "exhaustive_panel_campaign",
        "exhaustive_panel_result",
        "exhaustive_panel_evaluation",
        "causal_execution_campaign",
    )
    hashes: dict[str, str] = {}
    for key in path_keys:
        path = ROOT / str(frozen[key])
        observed = _sha256(path)
        expected = str(frozen[f"{key}_sha256"])
        if observed != expected:
            raise FeedbackIdentifiabilityError(f"frozen input drift for {key}: {observed} != {expected}")
        hashes[key] = observed

    policy_result = _load_yaml(ROOT / str(frozen["command_policy_result"]))
    if policy_result.get("semantic_result_sha256") != frozen["command_policy_result_semantic_sha256"]:
        raise FeedbackIdentifiabilityError("command policy semantic hash drift")
    panel_result = _load_yaml(ROOT / str(frozen["exhaustive_panel_result"]))
    if panel_result.get("semantic_result_sha256") != frozen["exhaustive_panel_result_semantic_sha256"]:
        raise FeedbackIdentifiabilityError("exhaustive panel semantic hash drift")
    sentinel_campaign = _load_yaml(ROOT / str(frozen["causal_execution_campaign"]))
    return {
        "policy_result": policy_result,
        "panel_result": panel_result,
        "sentinel_campaign": sentinel_campaign,
    }, hashes


def _accounting_sets(
    campaign: Mapping[str, Any],
    inputs: Mapping[str, Any],
) -> tuple[list[str], list[str], list[str]]:
    policy_path = ROOT / str(campaign["frozen_inputs"]["command_policy_schedule"])
    with policy_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    admitted = [
        str(row["tuple_id"])
        for row in rows
        if row["disposition"] == "observed_within_direct_motor_contract_not_promoted"
    ]
    blocked = [str(row["tuple_id"]) for row in rows if row["disposition"].startswith("blocked_")]
    descriptive = inputs["panel_result"]["descriptive_only"]
    active = list(map(str, descriptive["nonzero_command_tuple_ids"]))
    silent = list(map(str, descriptive["silent_tuple_ids"]))

    expected = campaign["workload_rule"]
    if len(rows) != 240 or len(admitted) != int(expected["admitted_rows"]):
        raise FeedbackIdentifiabilityError("command policy row accounting drift")
    if blocked != list(map(str, expected["blocked_tuple_ids"])):
        raise FeedbackIdentifiabilityError("blocked tuple identity drift")
    if len(active) != int(expected["active_rows_to_probe"]) or len(silent) != int(expected["silent_rows_accounted_without_reexecution"]):
        raise FeedbackIdentifiabilityError("frozen active/silent workload count drift")
    if set(active) & set(silent) or set(active) | set(silent) != set(admitted):
        raise FeedbackIdentifiabilityError("active and silent strata do not partition admitted rows")
    return active, silent, blocked


def _record_physical_frame(loop: FlyBodyPhysicsLoop, metadata: Mapping[str, Any]) -> dict[str, Any]:
    joint_state = loop.read_joint_state()
    contact_found, forces, _torques, _positions, _normals, _tangents = loop.simulation.get_ground_contact_info("flybody")
    return {
        "timestamps_s": float(loop.simulation.mj_data.time),
        "qpos": loop.simulation.mj_data.qpos.copy(),
        "qvel": loop.simulation.mj_data.qvel.copy(),
        "joint_positions": joint_state.positions.copy(),
        "joint_velocities": joint_state.velocities.copy(),
        "actuator_forces": np.asarray(loop.simulation.get_actuator_forces("flybody", loop.actuator_type), dtype=np.float64).copy(),
        "applied_commands": loop.simulation.mj_data.ctrl.copy(),
        "center_of_mass": _center_of_mass(loop, metadata),
        "root_up_z": _root_up_z(loop.simulation.mj_data.qpos),
        "ground_contact_found": np.asarray(contact_found, dtype=np.float64).copy(),
        "ground_contact_force_norm": np.linalg.norm(np.asarray(forces, dtype=np.float64), axis=1),
    }


def _run_frozen_command_episode(
    sentinel_campaign: Mapping[str, Any],
    row: Mapping[str, str],
    native_commands: np.ndarray,
    *,
    perturbation: Mapping[str, Any] | None,
    loop: FlyBodyPhysicsLoop,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    import mujoco

    protocol = sentinel_campaign["physical_protocol"]
    substeps = int(protocol["physics_substeps_per_frame"])
    total_steps = int(protocol["frames"]) * substeps
    commands = np.asarray(native_commands, dtype=np.float64)
    if commands.shape != (total_steps,):
        raise FeedbackIdentifiabilityError(f"native command trace shape drift: {commands.shape}")
    if not np.isfinite(commands).all() or float(np.max(np.abs(commands), initial=0.0)) > 0.01:
        raise FeedbackIdentifiabilityError("frozen command trace violates direct-MOTOR envelope")

    target_id = int(row["route_target_actuator_id"])
    if loop.actuator_names[target_id] != str(row["route_target_actuator_name"]):
        raise FeedbackIdentifiabilityError("scheduled actuator address drift")
    loop.reset()
    metadata = _model_measurement_metadata(loop)
    native_dt = float(loop.simulation.mj_model.opt.timestep)
    expected_dt = float(sentinel_campaign["runtime_contract"]["timestep_s"])
    if not np.isclose(native_dt, expected_dt, atol=0.0, rtol=1e-12):
        raise FeedbackIdentifiabilityError("physics timestep differs from frozen causal execution")
    mujoco.mj_forward(loop.simulation.mj_model, loop.simulation.mj_data)
    perturbation_native_step = int(protocol["perturbation_step"]) * substeps
    records: dict[str, list[Any]] = {}
    for step_index, scalar in enumerate(commands):
        if perturbation is not None and step_index == perturbation_native_step:
            loop.simulation.mj_data.qvel[int(perturbation["qvel_address"])] += float(perturbation["delta"])
            mujoco.mj_forward(loop.simulation.mj_model, loop.simulation.mj_data)
        command = np.zeros(102, dtype=np.float64)
        command[target_id] = scalar
        addressed = loop.actuator_interface.step(command)
        loop.simulation.set_actuator_inputs("flybody", loop.actuator_type, addressed.values)
        loop.simulation.step()
        if (step_index + 1) % substeps == 0:
            for key, value in _record_physical_frame(loop, metadata).items():
                records.setdefault(key, []).append(value)
    episode = {key: np.asarray(values) for key, values in records.items()}
    if not all(np.isfinite(value).all() for value in episode.values()):
        raise FeedbackIdentifiabilityError("frozen-command episode contains non-finite state")
    return episode, metadata


def _max_abs_delta(first: Mapping[str, np.ndarray], second: Mapping[str, np.ndarray], keys: tuple[str, ...]) -> float:
    return max(float(np.max(np.abs(np.asarray(first[key]) - np.asarray(second[key])), initial=0.0)) for key in keys)


def _compact_metrics(episode: Mapping[str, np.ndarray], metadata: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _episode_metrics(episode, metadata)
    return {
        "finite_fraction": float(metrics["finite_fraction"]),
        "joint_limit_violation_frames": int(metrics["failure_masks"]["joint_limit_violation_frames"]),
        "gross_fall_proxy_frames": int(metrics["failure_masks"]["gross_fall_proxy_frames"]),
        "numerical_failure_frames": int(metrics["failure_masks"]["numerical_failure_frames"]),
        "com_translation_peak_l2": float(metrics["center_of_mass"]["translation_from_initial_peak_l2"]),
        "com_jerk_peak": float(metrics["physical_com_kinematics"]["jerk_l2_peak"]),
        "direct_motor_work_proxy": float(metrics["declared_direct_motor_work_proxy"]["absolute_force_velocity_integral"]),
    }


def _run_active_probe(
    campaign: Mapping[str, Any],
    sentinel_campaign: Mapping[str, Any],
    row: Mapping[str, str],
    context: Mapping[str, Any],
    profiles: Mapping[str, Any],
    matrices: tuple[np.ndarray, np.ndarray, np.ndarray],
    loop: FlyBodyPhysicsLoop,
    artifact_root: Path,
) -> dict[str, Any]:
    perturbation = campaign["physical_protocol"]["perturbation"]
    captured: list[np.ndarray] = []
    baseline, baseline_metadata, baseline_diag = _run_episode(
        sentinel_campaign,
        row,
        context,
        profiles,
        matrices,
        perturbation=None,
        reusable_loop=loop,
        native_command_trace_out=captured,
    )
    baseline_replay, replay_metadata = _run_frozen_command_episode(
        sentinel_campaign, row, captured[0], perturbation=None, loop=loop
    )
    open_perturbed, open_metadata = _run_frozen_command_episode(
        sentinel_campaign, row, captured[0], perturbation=perturbation, loop=loop
    )
    perturbed_capture: list[np.ndarray] = []
    closed_perturbed, closed_metadata, closed_diag = _run_episode(
        sentinel_campaign,
        row,
        context,
        profiles,
        matrices,
        perturbation=perturbation,
        reusable_loop=loop,
        native_command_trace_out=perturbed_capture,
    )
    if not (
        baseline_metadata["model_contract"]
        == replay_metadata["model_contract"]
        == open_metadata["model_contract"]
        == closed_metadata["model_contract"]
    ):
        raise FeedbackIdentifiabilityError("branch model contracts differ")

    thresholds = campaign["identifiability_thresholds"]
    replay_state_error = _max_abs_delta(baseline, baseline_replay, ("qpos", "qvel"))
    replay_command_error = _max_abs_delta(baseline, baseline_replay, ("applied_commands",))
    native_perturbation_step = int(campaign["physical_protocol"]["perturbation_step"]) * int(
        campaign["physical_protocol"]["physics_substeps_per_frame"]
    )
    command_delta = np.abs(perturbed_capture[0] - captured[0])[native_perturbation_step:]
    command_peak = float(np.max(command_delta, initial=0.0))
    frame = int(campaign["physical_protocol"]["perturbation_step"])
    state_gap = _deviation_metrics(closed_perturbed, open_perturbed, frame)
    state_peak = float(state_gap["qpos_l2_peak"])
    command_identifiable = command_peak >= float(thresholds["closed_feedback_command_adaptation_l2_min"])
    state_identifiable = state_peak >= float(thresholds["closed_open_state_gap_l2_min"])
    if command_identifiable and state_identifiable:
        classification = "feedback_physically_identifiable"
    elif command_identifiable:
        classification = "feedback_command_only"
    else:
        classification = "feedback_not_identifiable"

    tuple_dir = artifact_root / str(row["tuple_id"])
    tuple_dir.mkdir(parents=True, exist_ok=False)
    artifact_path = tuple_dir / "branches.npz"
    np.savez_compressed(
        artifact_path,
        baseline_qpos=baseline["qpos"],
        baseline_qvel=baseline["qvel"],
        baseline_commands=baseline["applied_commands"],
        baseline_native_command=captured[0],
        baseline_replay_qpos=baseline_replay["qpos"],
        baseline_replay_qvel=baseline_replay["qvel"],
        open_perturbed_qpos=open_perturbed["qpos"],
        open_perturbed_qvel=open_perturbed["qvel"],
        closed_perturbed_qpos=closed_perturbed["qpos"],
        closed_perturbed_qvel=closed_perturbed["qvel"],
        closed_perturbed_native_command=perturbed_capture[0],
    )
    return {
        "tuple_id": str(row["tuple_id"]),
        "status": "completed",
        "classification": classification,
        "route_body_id": int(row["route_body_id"]),
        "route_target_actuator_id": int(row["route_target_actuator_id"]),
        "route_target_actuator_name": str(row["route_target_actuator_name"]),
        "baseline_chain": baseline_diag,
        "closed_perturbed_chain": closed_diag,
        "unperturbed_replay": {
            "state_max_abs_error": replay_state_error,
            "command_max_abs_error": replay_command_error,
        },
        "feedback_command_adaptation": {
            "l2_peak": command_peak,
            "nonzero_native_steps": int(np.count_nonzero(command_delta > float(thresholds["closed_feedback_command_adaptation_l2_min"]))),
        },
        "closed_open_state_gap": state_gap,
        "open_perturbed_vs_baseline": _deviation_metrics(open_perturbed, baseline, frame),
        "closed_perturbed_vs_baseline": _deviation_metrics(closed_perturbed, baseline, frame),
        "branch_metrics": {
            "baseline_live": _compact_metrics(baseline, baseline_metadata),
            "baseline_replay": _compact_metrics(baseline_replay, replay_metadata),
            "open_perturbed": _compact_metrics(open_perturbed, open_metadata),
            "closed_perturbed": _compact_metrics(closed_perturbed, closed_metadata),
        },
        "artifact": str(artifact_path.relative_to(ROOT)).replace("\\", "/"),
    }


def run_feedback_identifiability(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    run_root: Path = RUN_ROOT,
) -> dict[str, Any]:
    started = time.perf_counter()
    print("[1/7] Verifying frozen policy, panel and causal execution contracts", flush=True)
    campaign = _load_campaign(campaign_path)
    inputs, frozen_hashes = _verified_inputs(campaign)
    active_ids, silent_ids, blocked_ids = _accounting_sets(campaign, inputs)

    sentinel_campaign = inputs["sentinel_campaign"]
    context = _verified_context(sentinel_campaign)
    profiles = _profiles(context)
    first, second, direct, coupling_audit = _incoming_l1_matrices(context["inputs"])
    matrices = (first, second, direct)
    by_id = {str(row["tuple_id"]): row for row in context["rows"]}
    if set(active_ids) - set(by_id):
        raise FeedbackIdentifiabilityError("active tuple missing from frozen declared schedule")

    print("[2/7] Accounting 237 admitted rows: 65 active probes and 172 silent non-informative rows", flush=True)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    artifact_root = run_root / run_id
    artifact_root.mkdir(parents=True, exist_ok=False)
    outcomes: list[dict[str, Any]] = []

    print("[3/7] Executing four causal branches for every active row", flush=True)
    with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=False) as loop:
        for index, tuple_id in enumerate(active_ids, start=1):
            print(f"[PROBE {index:02d}/{len(active_ids)}] {tuple_id}", flush=True)
            try:
                outcome = _run_active_probe(
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

    print("[4/7] Classifying causal identifiability without ranking or promotion", flush=True)
    completed = [item for item in outcomes if item["status"] == "completed"]
    classifications = Counter(item["classification"] for item in completed)
    thresholds = campaign["identifiability_thresholds"]
    replay_ok = all(
        item["unperturbed_replay"]["state_max_abs_error"] <= float(thresholds["unperturbed_replay_state_max_abs_error"])
        and item["unperturbed_replay"]["command_max_abs_error"] <= float(thresholds["unperturbed_replay_command_max_abs_error"])
        for item in completed
    )
    all_finite = all(
        branch["finite_fraction"] == 1.0
        for item in completed
        for branch in item["branch_metrics"].values()
    )
    checks = {
        "all_240_rows_accounted_exactly_once": len(active_ids) + len(silent_ids) + len(blocked_ids) == 240
        and not (set(active_ids) & set(silent_ids) or set(active_ids) & set(blocked_ids) or set(silent_ids) & set(blocked_ids)),
        "exact_237_admitted_3_blocked": len(active_ids) + len(silent_ids) == 237 and len(blocked_ids) == 3,
        "exact_65_active_172_silent": len(active_ids) == 65 and len(silent_ids) == 172,
        "all_65_active_probes_complete": len(completed) == 65,
        "all_active_probe_arrays_finite": all_finite and len(completed) == 65,
        "unperturbed_native_command_replay_within_tolerance": replay_ok and len(completed) == 65,
        "at_least_one_feedback_command_adaptation": sum(classifications.values()) - classifications["feedback_not_identifiable"] > 0,
        "at_least_one_feedback_physical_state_gap": classifications["feedback_physically_identifiable"] > 0,
        "incoming_L1_columns_exact": bool(coupling_audit["all_nonzero_columns_exact"]),
        "zero_fit_zero_ranking_zero_promotion_zero_behavior": True,
    }
    passed = all(checks.values())

    print("[5/7] Writing hash-linked compact result and ignored heavy traces", flush=True)
    elapsed = time.perf_counter() - started
    result: dict[str, Any] = {
        "schema_version": 1,
        "id": "runner_result.neutral_embodied_feedback_identifiability.v0",
        "campaign_id": campaign["id"],
        "status": "pass_feedback_identifiability_no_selection" if passed else "failed_feedback_identifiability_gate",
        "completed_at": datetime.now(UTC).isoformat(),
        "claim_label": campaign["claim_label"],
        "command": "neutral_embodied_feedback_identifiability.bat",
        "frozen_input_sha256": frozen_hashes,
        "workload_rule": campaign["workload_rule"],
        "thresholds": thresholds,
        "accounting": {
            "schedule_rows": 240,
            "admitted_rows": 237,
            "active_rows_probed": len(active_ids),
            "silent_noninformative_rows": len(silent_ids),
            "blocked_command_contract_rows": len(blocked_ids),
            "physical_episodes": len(active_ids) * 4,
            "optimized_parameters": 0,
            "promoted_parameter_values": 0,
            "selected_candidates": 0,
            "named_behavior_exposure": 0,
        },
        "strata": {
            "silent_noninformative_tuple_ids": silent_ids,
            "blocked_command_contract_tuple_ids": blocked_ids,
            "active_probe_classification_counts": dict(sorted(classifications.items())),
        },
        "checks": checks,
        "outcomes": outcomes,
        "scientific_boundary": campaign["scientific_boundary"],
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "wall_seconds": elapsed,
        "next_action": campaign["next_action"],
    }
    semantic_outcomes = [{key: value for key, value in item.items() if key != "artifact"} for item in outcomes]
    result["semantic_result_sha256"] = _canonical_hash({
        **{key: value for key, value in result.items() if key not in {"completed_at", "wall_seconds", "outcomes"}},
        "outcomes": semantic_outcomes,
    })
    result_path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.neutral_embodied_feedback_identifiability.v0",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": result["semantic_result_sha256"],
        "status": "pass" if passed else "fail",
        "checks": checks,
        "classification_counts": dict(sorted(classifications.items())),
        "silent_rows_remain_unresolved": True,
        "stability_accepted": False,
        "population_assignment_accepted": False,
        "candidate_selected": False,
        "behavior_claimed": False,
        "interpretation": (
            "A pass validates causal feedback identifiability and replay controls only; "
            "it does not accept stability or any parameter member."
        ),
        "next_action": campaign["next_action"],
    }
    evaluation_path.write_text(yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8")

    print("[6/7] Verifying scientific boundary and compute budget", flush=True)
    if elapsed > float(campaign["compute_budget"]["maximum_wall_clock_minutes"]) * 60.0:
        raise FeedbackIdentifiabilityError("wall-clock budget exceeded; result retained")
    if not passed:
        failed = [key for key, value in checks.items() if not value]
        raise FeedbackIdentifiabilityError(f"feedback identifiability gate failed: {failed}")
    print("[7/7] PASS", flush=True)
    print(f"[ACCOUNTING] 65 active / 172 silent / 3 blocked / 260 episodes", flush=True)
    print(f"[CLASSES] {dict(sorted(classifications.items()))}", flush=True)
    print("[BOUNDARY] 0 fit, 0 ranking, 0 promotion, 0 behavior, stability NOT accepted", flush=True)
    print(f"[HASH] {result['semantic_result_sha256']}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the neutral embodied feedback-identifiability gate")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    run_feedback_identifiability(campaign_path=args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

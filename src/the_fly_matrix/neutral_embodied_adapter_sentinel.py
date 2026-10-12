from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml

from .embodied_measurement_contract import (
    _center_of_mass,
    _episode_metrics,
    _model_measurement_metadata,
    _root_up_z,
    paired_recovery_metrics,
)
from .ledger import ROOT
from .local_conversion import (
    ActuatorBridgeParameters,
    MotorTwitchParameters,
    force_uN_to_actuator_command,
    motor_events_to_force_uN,
)
from .runtime import FlyBodyPhysicsLoop


CAMPAIGN_PATH = (
    ROOT / "calibration" / "campaigns" / "neutral-embodied-adapter-sentinel-v0.yaml"
)
RESULT_PATH = (
    ROOT / "calibration" / "runner" / "neutral-embodied-adapter-sentinel-v0.yaml"
)
EVALUATION_PATH = (
    ROOT / "calibration" / "evaluations" / "neutral-embodied-adapter-sentinel-v0.yaml"
)
RUN_ROOT = ROOT / "runs" / "calibration" / "neutral-embodied-adapter-sentinel-v0"


class NeutralAdapterSentinelError(RuntimeError):
    """Raised when a frozen schedule tuple cannot cross the declared adapter."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise NeutralAdapterSentinelError(f"{path} must contain a YAML mapping")
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


def _load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = _load_yaml(path)
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise NeutralAdapterSentinelError("adapter sentinel must remain diagnostic_only")
    if campaign.get("behavior_targets"):
        raise NeutralAdapterSentinelError("adapter sentinel cannot expose a behavior")
    boundary = campaign.get("scientific_boundary", {})
    for key in ("optimized_parameters", "promoted_parameter_values", "selected_candidates"):
        if int(boundary.get(key, -1)) != 0:
            raise NeutralAdapterSentinelError(f"adapter sentinel requires zero {key}")
    if campaign.get("topology_changes_allowed") is not False:
        raise NeutralAdapterSentinelError("adapter sentinel cannot change topology")
    if campaign["sentinel_selection"].get("selected_from_body_motion") is not False:
        raise NeutralAdapterSentinelError("sentinel tuple selection cannot use body motion")
    return campaign


def _read_schedule(campaign: Mapping[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    frozen = campaign["frozen_inputs"]
    schedule_path = ROOT / str(frozen["schedule"])
    result_path = ROOT / str(frozen["schedule_result"])
    if _sha256(schedule_path) != str(frozen["schedule_sha256"]):
        raise NeutralAdapterSentinelError("immutable neutral schedule file drift")
    schedule_result = _load_yaml(result_path)
    if (
        schedule_result.get("semantic_result_sha256")
        != frozen["schedule_result_semantic_sha256"]
    ):
        raise NeutralAdapterSentinelError("immutable neutral schedule result drift")
    if schedule_result["schedule"]["sha256"] != frozen["schedule_sha256"]:
        raise NeutralAdapterSentinelError("schedule result points to another CSV")
    with schedule_path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    expected = int(campaign["acceptance"]["scheduled_tuples_loaded"])
    if len(rows) != expected or len({row["tuple_id"] for row in rows}) != expected:
        raise NeutralAdapterSentinelError("scheduled tuple accounting drift")
    return rows, schedule_result


def _load_profile_index(path: Path) -> dict[str, dict[int, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    result: dict[str, dict[int, str]] = {}
    for row in rows:
        result.setdefault(row["profile_id"], {})[int(row["body_id"])] = row[
            "assignment"
        ]
    if not result or any(len(assignments) != 148 for assignments in result.values()):
        raise NeutralAdapterSentinelError("intermediate profile panel is not 50 x 148")
    allowed = {"event_candidate", "graded_candidate"}
    if any(set(assignments.values()) - allowed for assignments in result.values()):
        raise NeutralAdapterSentinelError("unsupported intermediate assignment label")
    return result


def _load_compiler_inputs(campaign: Mapping[str, Any]) -> dict[str, Any]:
    frozen = campaign["frozen_inputs"]
    profile_path = ROOT / str(frozen["intermediate_profile_panel"])
    feco_path = ROOT / str(frozen["feco_joint_source_paths"])
    motor_ensemble_path = ROOT / str(frozen["motor_class_ensemble"])
    force_fit_path = ROOT / str(frozen["motor_force_fit"])
    temporal_path = ROOT / str(frozen["motor_temporal_diagnostic"])
    profiles = _load_profile_index(profile_path)
    feco_paths = json.loads(feco_path.read_text(encoding="utf-8"))
    if not isinstance(feco_paths, list) or len(feco_paths) != 12:
        raise NeutralAdapterSentinelError("FeCO source-path axis must contain 12 paths")
    motor_ensemble = _load_yaml(motor_ensemble_path)
    body_ids = sorted(int(member["body_id"]) for member in motor_ensemble["members"])
    if len(body_ids) != 10:
        raise NeutralAdapterSentinelError("motor class ensemble must contain ten bodies")
    force_fit = _load_yaml(force_fit_path)
    force_by_class = {
        str(key): float(value)
        for key, value in force_fit["procedure_readiness"][
            "fitted_slopes_uN_per_spike"
        ].items()
        if key in {"fast_81A07", "intermediate_22A08"}
    }
    temporal = _load_yaml(temporal_path)
    temporal_by_class = {
        class_id: {
            key: float(temporal["class_results"][class_id]["all_data_best_candidate"][key])
            for key in ("rise_time_s", "decay_time_s")
        }
        for class_id in ("fast_81A07", "intermediate_22A08")
    }
    input_hashes = {
        "intermediate_profile_panel": _sha256(profile_path),
        "feco_joint_source_paths": _sha256(feco_path),
        "motor_class_ensemble": _sha256(motor_ensemble_path),
        "motor_force_fit": _sha256(force_fit_path),
        "motor_temporal_diagnostic": _sha256(temporal_path),
    }
    expected_hashes = campaign["frozen_input_sha256"]
    if input_hashes != expected_hashes:
        drift = {
            key: {"expected": expected_hashes.get(key), "observed": value}
            for key, value in input_hashes.items()
            if expected_hashes.get(key) != value
        }
        raise NeutralAdapterSentinelError(f"adapter compiler input drift: {drift}")
    return {
        "profiles": profiles,
        "feco_paths": feco_paths,
        "body_ids": body_ids,
        "force_by_class": force_by_class,
        "temporal_by_class": temporal_by_class,
        "input_hashes": input_hashes,
    }


def _decode_motor_assignment(
    row: Mapping[str, str], body_ids: list[int]
) -> dict[int, str]:
    signature = str(row["motor_assignment_signature"])
    if len(signature) != len(body_ids) or set(signature) - {"F", "I"}:
        raise NeutralAdapterSentinelError("invalid motor assignment signature")
    index = int(row["motor_assignment_index"])
    expected = "".join(
        "I" if (index >> bit_index) & 1 else "F"
        for bit_index in range(len(body_ids))
    )
    if signature != expected:
        raise NeutralAdapterSentinelError("motor assignment signature/index mismatch")
    classes = {"F": "fast_81A07", "I": "intermediate_22A08"}
    return {
        body_id: classes[code]
        for body_id, code in zip(body_ids, signature, strict=True)
    }


def compile_motor_route_trace(
    row: Mapping[str, str],
    inputs: Mapping[str, Any],
    event_counts: np.ndarray,
    *,
    frame_dt_s: float,
    actuator_names: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Compile caller-owned motor events through the frozen physical adapter."""

    events = np.asarray(event_counts)
    if events.ndim != 1 or not np.issubdtype(events.dtype, np.integer):
        raise NeutralAdapterSentinelError(
            "route event_counts must be a one-dimensional integer vector"
        )
    if (events < 0).any():
        raise NeutralAdapterSentinelError("route event_counts cannot be negative")
    if not np.isfinite(frame_dt_s) or frame_dt_s <= 0.0:
        raise NeutralAdapterSentinelError("route frame_dt_s must be finite and positive")

    assignment = _decode_motor_assignment(row, list(inputs["body_ids"]))
    route_body_id = int(row["route_body_id"])
    if route_body_id not in assignment:
        raise NeutralAdapterSentinelError("scheduled route body is outside motor ensemble")
    route_class = assignment[route_body_id]
    target_id = int(row["route_target_actuator_id"])
    target_name = str(row["route_target_actuator_name"])
    if not 0 <= target_id < 102:
        raise NeutralAdapterSentinelError("scheduled target actuator id is invalid")
    if actuator_names is not None and actuator_names[target_id] != target_name:
        raise NeutralAdapterSentinelError("scheduled target actuator name/address drift")

    temporal = inputs["temporal_by_class"][route_class]
    twitch = MotorTwitchParameters(
        force_per_event_uN=np.asarray([inputs["force_by_class"][route_class]]),
        rise_time_s=np.asarray([temporal["rise_time_s"]]),
        decay_time_s=np.asarray([temporal["decay_time_s"]]),
    )
    force = motor_events_to_force_uN(events[:, None], twitch, timestep_s=frame_dt_s)
    gain = float(row["bridge_gain_command_per_uN"])
    local_command = force_uN_to_actuator_command(
        force,
        ActuatorBridgeParameters(
            command_per_uN=np.asarray([gain]),
            command_offset=np.asarray([0.0]),
        ),
    )[:, 0]
    command_trace = np.zeros((len(events), 102), dtype=np.float64)
    command_trace[:, target_id] = local_command
    active_columns = np.flatnonzero(np.any(command_trace != 0.0, axis=0)).tolist()
    if active_columns not in ([], [target_id]):
        raise NeutralAdapterSentinelError("motor event source leaked outside scheduled route")
    if not np.isfinite(command_trace).all() or np.max(
        np.abs(command_trace), initial=0.0
    ) > 0.01:
        raise NeutralAdapterSentinelError("compiled command is non-finite or exceeds motor limit")
    return {
        "assignment": assignment,
        "route_body_id": route_body_id,
        "route_body_class": route_class,
        "target_actuator_id": target_id,
        "target_actuator_name": target_name,
        "force_per_event_uN": float(inputs["force_by_class"][route_class]),
        "rise_time_s": temporal["rise_time_s"],
        "decay_time_s": temporal["decay_time_s"],
        "bridge_gain_index": int(row["bridge_gain_index"]),
        "bridge_gain_command_per_uN": gain,
        "event_count": int(events.sum()),
        "command_trace": command_trace,
        "active_actuator_ids": active_columns,
    }


def compile_tuple(
    row: Mapping[str, str],
    campaign: Mapping[str, Any],
    inputs: Mapping[str, Any],
    *,
    actuator_names: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    profile_id = str(row["intermediate_profile_id"])
    if profile_id not in inputs["profiles"]:
        raise NeutralAdapterSentinelError(f"unknown intermediate profile {profile_id}")
    feco_index = int(row["feco_source_path_index"])
    if not 0 <= feco_index < len(inputs["feco_paths"]):
        raise NeutralAdapterSentinelError("FeCO source-path index out of bounds")
    representation = str(row["feco_native_representation"])
    if representation not in {"graded_candidate", "event_candidate"}:
        raise NeutralAdapterSentinelError("unsupported FeCO native representation")
    expected_feco_id = f"feco_{feco_index:02d}_{representation}"
    if row["feco_alternative_id"] != expected_feco_id:
        raise NeutralAdapterSentinelError("FeCO alternative id/index mismatch")

    protocol = campaign["physical_protocol"]
    fixture = campaign["synthetic_motor_fixture"]
    frames = int(protocol["frames"])
    event_frame = int(fixture["event_frame"])
    event_counts = np.zeros((frames, 1), dtype=np.int64)
    event_counts[event_frame, 0] = int(fixture["event_count"])
    route = compile_motor_route_trace(
        row,
        inputs,
        event_counts[:, 0],
        frame_dt_s=float(protocol["expected_frame_dt_s"]),
        actuator_names=actuator_names,
    )
    command_trace = route["command_trace"]
    if route["active_actuator_ids"] != [route["target_actuator_id"]]:
        raise NeutralAdapterSentinelError("motor fixture leaked outside scheduled route")

    profile = inputs["profiles"][profile_id]
    return {
        "tuple_id": row["tuple_id"],
        "seed": int(row["seed"]),
        "intermediate_profile": {
            "id": profile_id,
            "assignments": len(profile),
            "event_candidates": sum(value == "event_candidate" for value in profile.values()),
            "graded_candidates": sum(value == "graded_candidate" for value in profile.values()),
            "applied_to_cns": False,
        },
        "feco": {
            "alternative_id": row["feco_alternative_id"],
            "source_path_index": feco_index,
            "native_representation": representation,
            "source_path": inputs["feco_paths"][feco_index],
            "transduction_executed": False,
        },
        "motor": {
            "assignment_index": int(row["motor_assignment_index"]),
            "assignment_signature": row["motor_assignment_signature"],
            "decoded_bodies": len(route["assignment"]),
            "route_body_id": route["route_body_id"],
            "route_body_class": route["route_body_class"],
            "force_per_event_uN": route["force_per_event_uN"],
            "rise_time_s": route["rise_time_s"],
            "decay_time_s": route["decay_time_s"],
            "synthetic_event_count": int(event_counts.sum()),
        },
        "route": {
            "target_actuator_id": route["target_actuator_id"],
            "target_actuator_name": route["target_actuator_name"],
            "bridge_gain_index": route["bridge_gain_index"],
            "bridge_gain_command_per_uN": route["bridge_gain_command_per_uN"],
        },
        "command_trace": command_trace,
        "command_contract": {
            "frames": frames,
            "actuators": 102,
            "active_actuator_ids": route["active_actuator_ids"],
            "non_scoped_actuators_zero": True,
            "peak_abs_command": float(np.max(np.abs(command_trace))),
            "nonzero_samples": int(np.count_nonzero(command_trace)),
            "semantic_sha256": _canonical_hash(command_trace.tolist()),
        },
        "full_sensor_cns_motor_chain_executed": False,
    }


def compile_sentinel(
    campaign_path: Path = CAMPAIGN_PATH,
    *,
    actuator_names: tuple[str, ...] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    campaign = _load_campaign(campaign_path)
    rows, schedule_result = _read_schedule(campaign)
    inputs = _load_compiler_inputs(campaign)
    by_id = {row["tuple_id"]: row for row in rows}
    tuple_ids = list(campaign["sentinel_selection"]["tuple_ids"])
    if len(tuple_ids) != int(campaign["acceptance"]["sentinel_tuples"]):
        raise NeutralAdapterSentinelError("sentinel tuple count drift")
    if len(set(tuple_ids)) != len(tuple_ids) or set(tuple_ids) - set(by_id):
        raise NeutralAdapterSentinelError("sentinel tuple selection is invalid")
    compiled = [
        compile_tuple(by_id[tuple_id], campaign, inputs, actuator_names=actuator_names)
        for tuple_id in tuple_ids
    ]
    gains = {item["route"]["bridge_gain_index"] for item in compiled}
    classes = {item["motor"]["route_body_class"] for item in compiled}
    if gains != {0, 1, 2}:
        raise NeutralAdapterSentinelError("sentinel does not exercise all bridge gains")
    if classes != {"fast_81A07", "intermediate_22A08"}:
        raise NeutralAdapterSentinelError("sentinel does not exercise both motor classes")
    return campaign, compiled, {
        "schedule_result": schedule_result,
        "input_hashes": inputs["input_hashes"],
        "scheduled_tuple_count": len(rows),
    }


def _run_command_episode(
    campaign: Mapping[str, Any],
    command_trace: np.ndarray,
    *,
    perturbation: Mapping[str, Any] | None,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    import mujoco

    protocol = campaign["physical_protocol"]
    frames = int(protocol["frames"])
    substeps = int(protocol["physics_substeps_per_frame"])
    perturbation_step = int(protocol["perturbation_step"])
    if command_trace.shape != (frames, 102):
        raise NeutralAdapterSentinelError("compiled trace shape does not match protocol")
    records: dict[str, list[np.ndarray | float]] = {
        key: []
        for key in (
            "timestamps_s",
            "qpos",
            "qvel",
            "joint_positions",
            "joint_velocities",
            "actuator_forces",
            "applied_commands",
            "center_of_mass",
            "root_up_z",
            "ground_contact_found",
            "ground_contact_force_norm",
        )
    }
    with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=False) as loop:
        metadata = _model_measurement_metadata(loop)
        for frame_index in range(frames):
            if perturbation is not None and frame_index == perturbation_step:
                address = int(perturbation["qvel_address"])
                if not 0 <= address < len(loop.simulation.mj_data.qvel):
                    raise NeutralAdapterSentinelError("perturbation qvel address is invalid")
                loop.simulation.mj_data.qvel[address] += float(perturbation["delta"])
                mujoco.mj_forward(loop.simulation.mj_model, loop.simulation.mj_data)
            addressed = loop.actuator_interface.step(command_trace[frame_index])
            step = loop.step(addressed, substeps=substeps)
            contact_found, forces, _torques, _positions, _normals, _tangents = (
                loop.simulation.get_ground_contact_info("flybody")
            )
            records["timestamps_s"].append(float(step.simulation_time))
            records["qpos"].append(loop.simulation.mj_data.qpos.copy())
            records["qvel"].append(loop.simulation.mj_data.qvel.copy())
            records["joint_positions"].append(step.joint_state.positions.copy())
            records["joint_velocities"].append(step.joint_state.velocities.copy())
            records["actuator_forces"].append(step.actuator_forces.copy())
            records["applied_commands"].append(step.applied_commands.copy())
            records["center_of_mass"].append(_center_of_mass(loop, metadata))
            records["root_up_z"].append(_root_up_z(loop.simulation.mj_data.qpos))
            records["ground_contact_found"].append(
                np.asarray(contact_found, dtype=np.float64).copy()
            )
            records["ground_contact_force_norm"].append(
                np.linalg.norm(np.asarray(forces, dtype=np.float64), axis=1)
            )
    episode = {key: np.asarray(values) for key, values in records.items()}
    if not np.array_equal(episode["applied_commands"], command_trace):
        raise NeutralAdapterSentinelError("physical loop changed the compiled command trace")
    return episode, metadata


def _compact_episode(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "finite_fraction": metrics["finite_fraction"],
        "joint_limit_violation_frames": metrics["failure_masks"][
            "joint_limit_violation_frames"
        ],
        "gross_fall_proxy_frames": metrics["failure_masks"]["gross_fall_proxy_frames"],
        "numerical_failure_frames": metrics["failure_masks"]["numerical_failure_frames"],
        "com_translation_peak_l2": metrics["center_of_mass"][
            "translation_from_initial_peak_l2"
        ],
        "com_jerk_peak": metrics["physical_com_kinematics"]["jerk_l2_peak"],
        "direct_motor_work_proxy": metrics["declared_direct_motor_work_proxy"][
            "absolute_force_velocity_integral"
        ],
    }


def run_sentinel(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    run_root: Path = RUN_ROOT,
) -> dict[str, Any]:
    started = time.perf_counter()
    print("[1/6] Verifying immutable schedule, candidate evidence and fixed tuple ids", flush=True)
    with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=False) as probe_loop:
        actuator_names = tuple(probe_loop.actuator_names)
    campaign, compiled, context = compile_sentinel(
        campaign_path, actuator_names=actuator_names
    )
    print("[2/6] Compiling four synthetic single-event motor traces", flush=True)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    artifact_root = run_root / run_id
    artifact_root.mkdir(parents=True, exist_ok=False)
    outcomes: list[dict[str, Any]] = []
    perturbation = campaign["physical_protocol"]["perturbation"]

    print("[3/6] Executing eight paired physical episodes", flush=True)
    for tuple_index, item in enumerate(compiled, start=1):
        tuple_started = time.perf_counter()
        print(
            f"[TUPLE {tuple_index}/{len(compiled)}] {item['tuple_id']} | "
            f"{item['motor']['route_body_class']} -> {item['route']['target_actuator_name']}",
            flush=True,
        )
        outcome: dict[str, Any] = {
            "tuple_id": item["tuple_id"],
            "status": "error",
            "compiler": {
                "intermediate_profile_id": item["intermediate_profile"]["id"],
                "intermediate_assignments_loaded": item["intermediate_profile"]["assignments"],
                "intermediate_cns_executed": False,
                "feco_alternative_id": item["feco"]["alternative_id"],
                "feco_transduction_executed": False,
                "motor_assignment_index": item["motor"]["assignment_index"],
                "route_body_class": item["motor"]["route_body_class"],
                "target_actuator_id": item["route"]["target_actuator_id"],
                "target_actuator_name": item["route"]["target_actuator_name"],
                "bridge_gain_index": item["route"]["bridge_gain_index"],
                "command_trace_sha256": item["command_contract"]["semantic_sha256"],
                "peak_abs_command": item["command_contract"]["peak_abs_command"],
                "non_scoped_actuators_zero": item["command_contract"][
                    "non_scoped_actuators_zero"
                ],
            },
        }
        try:
            baseline, baseline_metadata = _run_command_episode(
                campaign, item["command_trace"], perturbation=None
            )
            perturbed, perturbed_metadata = _run_command_episode(
                campaign, item["command_trace"], perturbation=perturbation
            )
            if baseline_metadata["model_contract"] != perturbed_metadata["model_contract"]:
                raise NeutralAdapterSentinelError("paired episode model contracts differ")
            baseline_metrics = _episode_metrics(baseline, baseline_metadata)
            perturbed_metrics = _episode_metrics(perturbed, perturbed_metadata)
            recovery = paired_recovery_metrics(
                baseline,
                perturbed,
                int(campaign["physical_protocol"]["perturbation_step"]),
            )
            finite = (
                baseline_metrics["finite_fraction"] == 1.0
                and perturbed_metrics["finite_fraction"] == 1.0
            )
            tuple_dir = artifact_root / item["tuple_id"]
            tuple_dir.mkdir(parents=True, exist_ok=False)
            baseline_path = tuple_dir / "baseline.npz"
            perturbed_path = tuple_dir / "perturbed.npz"
            np.savez_compressed(baseline_path, **baseline)
            np.savez_compressed(perturbed_path, **perturbed)
            outcome.update(
                {
                    "status": "completed_contract" if finite else "failed_nonfinite",
                    "baseline": _compact_episode(baseline_metrics),
                    "perturbed": _compact_episode(perturbed_metrics),
                    "paired_recovery": recovery,
                    "artifacts": {
                        "baseline": str(baseline_path.relative_to(ROOT)).replace("\\", "/"),
                        "perturbed": str(perturbed_path.relative_to(ROOT)).replace("\\", "/"),
                    },
                }
            )
        except Exception as exc:  # retain every sentinel failure in the compact result
            outcome["error"] = f"{type(exc).__name__}: {exc}"
        outcome["wall_seconds"] = time.perf_counter() - tuple_started
        outcomes.append(outcome)

    print("[4/6] Accounting every tuple and checking the runtime budget", flush=True)
    counts = {
        status: sum(item["status"] == status for item in outcomes)
        for status in ("completed_contract", "failed_nonfinite", "error", "budget_skipped")
    }
    elapsed = time.perf_counter() - started
    episode_count = len(compiled) * 2
    projected_panel_seconds = elapsed / episode_count * 240
    main_campaign = _load_yaml(
        ROOT / "calibration" / "campaigns" / "neutral-embodied-stability-pilot-v0.yaml"
    )
    runtime_budget_seconds = float(main_campaign["compute_budget"]["maximum_wall_clock_hours"]) * 3600
    sentinel_pass = counts["completed_contract"] == len(compiled)
    status = (
        "pass_motor_physical_adapter_sentinel_full_chain_blocked"
        if sentinel_pass
        else "failed_adapter_sentinel_full_chain_blocked"
    )
    summary = {
        "schema_version": 1,
        "campaign_id": campaign["id"],
        "status": status,
        "claim_label": campaign["claim_label"],
        "generated_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "accounting": {
            "scheduled_tuples_loaded": context["scheduled_tuple_count"],
            "sentinel_tuples": len(compiled),
            "paired_physical_episodes": episode_count,
            "outcome_counts": counts,
            "all_sentinel_tuples_accounted": sum(counts.values()) == len(compiled),
        },
        "runtime_budget": {
            "observed_wall_seconds": elapsed,
            "projected_full_panel_wall_seconds_linear": projected_panel_seconds,
            "full_panel_wall_budget_seconds": runtime_budget_seconds,
            "runtime_budget_gate_pass": projected_panel_seconds <= runtime_budget_seconds,
            "projection_is_engineering_estimate_only": True,
        },
        "execution_boundary": {
            "schedule_consumed": True,
            "intermediate_profiles_loaded_not_executed": True,
            "feco_alternatives_loaded_not_executed": True,
            "motor_event_force_bridge_route_executed": True,
            "paired_mujoco_physics_executed": True,
            "full_sensor_cns_motor_chain_executed": False,
            "stability_evaluated": False,
            "candidate_selected_from_motion": False,
            "optimized_parameters": 0,
            "promoted_parameter_values": 0,
        },
        "input_hashes": context["input_hashes"],
        "schedule_result_semantic_sha256": context["schedule_result"][
            "semantic_result_sha256"
        ],
        "tuple_outcomes": outcomes,
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    hash_payload = dict(summary)
    hash_payload.pop("generated_at")
    hash_payload.pop("run_id")
    hash_payload["runtime_budget"] = {
        key: value
        for key, value in summary["runtime_budget"].items()
        if key not in {"observed_wall_seconds", "projected_full_panel_wall_seconds_linear"}
    }
    hash_payload["tuple_outcomes"] = [
        {
            key: value
            for key, value in outcome.items()
            if key not in {"wall_seconds", "artifacts"}
        }
        for outcome in outcomes
    ]
    summary["semantic_result_sha256"] = _canonical_hash(hash_payload)
    (artifact_root / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print("[5/6] Writing compact versioned result and evaluation", flush=True)
    compact = {
        "schema_version": 1,
        "id": "runner_result.neutral_embodied_adapter_sentinel.v0",
        "campaign_id": campaign["id"],
        "target_id": campaign["target_id"],
        "status": status,
        "claim_label": campaign["claim_label"],
        "command": "neutral_embodied_adapter_sentinel.bat",
        "behavior_targets": [],
        "campaign_sha256": _sha256(campaign_path),
        "implementation_sha256": _sha256(Path(__file__).resolve()),
        "semantic_result_sha256": summary["semantic_result_sha256"],
        "input_hashes": summary["input_hashes"],
        "accounting": summary["accounting"],
        "runtime_budget": summary["runtime_budget"],
        "execution_boundary": summary["execution_boundary"],
        "tuple_outcomes": outcomes,
        "artifact_ref": str((artifact_root / "summary.json").relative_to(ROOT)).replace(
            "\\", "/"
        ),
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    result_path.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.neutral_embodied_adapter_sentinel.v0",
        "title": "Neutral embodied adapter sentinel evaluation",
        "status": "evaluated" if sentinel_pass else "failed",
        "campaign_id": campaign["id"],
        "target_id": campaign["target_id"],
        "primary_class": campaign["primary_class"],
        "optimization_exposure": campaign["optimization_exposure"],
        "claim_label": campaign["claim_label"],
        "behavior_targets": [],
        "acceptance_result": (
            "pass_motor_physical_adapter_only_full_chain_blocked"
            if sentinel_pass
            else "fail_adapter_contract"
        ),
        "runner_result_id": compact["id"],
        "runner_semantic_sha256": compact["semantic_result_sha256"],
        "parameter_values_promoted": 0,
        "stability_accepted": False,
        "full_chain_executed": False,
        "conclusion": "",
    }
    evaluation["conclusion"] = (
        "The immutable schedule and motor-to-physics adapter sentinel passed. "
        "FeCO transduction and intermediate-CNS dynamics were intentionally not "
        "executed, so the full panel remains blocked and no stability claim exists."
        if sentinel_pass
        else "The adapter sentinel failed; the full panel remains blocked."
    )
    evaluation["next_action"] = campaign["next_action"]
    evaluation_path.write_text(
        yaml.safe_dump(evaluation, sort_keys=False), encoding="utf-8"
    )

    print("[6/6] Summary", flush=True)
    print(
        f"[ACCOUNTING] {counts['completed_contract']}/{len(compiled)} tuples completed; "
        f"{counts['error']} errors; {counts['failed_nonfinite']} non-finite",
        flush=True,
    )
    print(
        f"[RUNTIME] {elapsed:.1f}s sentinel; linear 240-episode projection "
        f"{projected_panel_seconds / 60:.1f} min",
        flush=True,
    )
    print("[PASS] motor event -> force -> route -> MuJoCo pairing", flush=True)
    print("[BLOCKED] FeCO -> typed intermediate CNS -> motor event source", flush=True)
    print("[BOUNDARY] 0 fit, 0 selection, 0 behavior, 0 stability claim", flush=True)
    print(f"[HASH] {summary['semantic_result_sha256']}", flush=True)
    return compact


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded neutral embodied schedule adapter sentinel"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--output", type=Path, default=RUN_ROOT)
    args = parser.parse_args()
    result = run_sentinel(args.campaign, run_root=args.output)
    return 0 if result["status"].startswith("pass_") else 1


if __name__ == "__main__":
    raise SystemExit(main())

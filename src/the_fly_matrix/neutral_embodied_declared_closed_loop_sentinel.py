from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from collections import Counter
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
from .feco_observation import CLAW_SOURCE_COEFFICIENTS
from .ledger import ROOT
from .neutral_embodied_adapter_sentinel import _decode_motor_assignment
from .neutral_embodied_declared_neural_sentinel import (
    _incoming_l1_matrices,
    _load_context,
    _profiles,
)
from .neutral_embodied_full_chain_sentinel import _sha256
from .runtime import FlyBodyPhysicsLoop


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "neutral-embodied-declared-closed-loop-sentinel-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "neutral-embodied-declared-closed-loop-sentinel-v0.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "neutral-embodied-declared-closed-loop-sentinel-v0.yaml"
RUN_ROOT = ROOT / "runs" / "calibration" / "neutral-embodied-declared-closed-loop-sentinel-v0"


class DeclaredClosedLoopSentinelError(RuntimeError):
    """Raised when the causal body-to-local-chain sentinel violates its contract."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DeclaredClosedLoopSentinelError(f"{path} must contain a YAML mapping")
    return value


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _array_hash(*arrays: np.ndarray) -> str:
    digest = hashlib.sha256()
    for array in arrays:
        value = np.ascontiguousarray(array)
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(str(value.shape).encode("ascii"))
        digest.update(value.tobytes())
    return digest.hexdigest()


def _load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = _load_yaml(path)
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise DeclaredClosedLoopSentinelError("closed-loop sentinel must remain diagnostic_only")
    if campaign.get("behavior_targets"):
        raise DeclaredClosedLoopSentinelError("closed-loop sentinel cannot expose behavior targets")
    if campaign.get("topology_changes_allowed") is not False:
        raise DeclaredClosedLoopSentinelError("closed-loop sentinel cannot change topology")
    boundary = campaign["scientific_boundary"]
    for key in ("optimized_parameters", "promoted_parameter_values", "selected_candidates", "named_behavior_exposure"):
        if int(boundary.get(key, -1)) != 0:
            raise DeclaredClosedLoopSentinelError(f"closed-loop sentinel requires zero {key}")
    selection = campaign["sentinel_selection"]
    if selection.get("selected_from_body_motion") is not False:
        raise DeclaredClosedLoopSentinelError("sentinel rows cannot be selected from body motion")
    if campaign["acceptance"].get("allow_physical_magnitude_to_select_candidate") is not False:
        raise DeclaredClosedLoopSentinelError("physical magnitude cannot select a candidate")
    return campaign


def _verified_context(campaign: Mapping[str, Any]) -> dict[str, Any]:
    frozen = campaign["frozen_inputs"]
    checks = {
        "declared_neural_campaign": "declared_neural_campaign_sha256",
        "declared_neural_result": "declared_neural_result_sha256",
        "declared_schedule": "declared_schedule_sha256",
        "declared_parameter_set": "declared_parameter_set_sha256",
        "actuator_attribution_result": "actuator_attribution_result_sha256",
        "measurement_contract_result": "measurement_contract_result_sha256",
    }
    observed: dict[str, str] = {}
    for key, hash_key in checks.items():
        path = ROOT / str(frozen[key])
        observed[key] = _sha256(path)
        if observed[key] != str(frozen[hash_key]):
            raise DeclaredClosedLoopSentinelError(f"frozen input drift for {key}")
    neural_campaign = _load_yaml(ROOT / str(frozen["declared_neural_campaign"]))
    neural_result = _load_yaml(ROOT / str(frozen["declared_neural_result"]))
    if neural_result.get("semantic_result_sha256") != frozen["declared_neural_result_semantic_sha256"]:
        raise DeclaredClosedLoopSentinelError("declared neural result semantic drift")
    context = _load_context(neural_campaign)
    context["campaign"] = neural_campaign
    context["frozen_hashes"] = observed
    return context


def _selected_rows(campaign: Mapping[str, Any], context: Mapping[str, Any]) -> list[dict[str, str]]:
    by_id = {str(row["tuple_id"]): row for row in context["rows"]}
    tuple_ids = list(map(str, campaign["sentinel_selection"]["tuple_ids"]))
    if len(tuple_ids) != int(campaign["acceptance"]["sentinel_tuples"]):
        raise DeclaredClosedLoopSentinelError("sentinel tuple count drift")
    if len(set(tuple_ids)) != len(tuple_ids) or set(tuple_ids) - set(by_id):
        raise DeclaredClosedLoopSentinelError("sentinel tuple selection is invalid")
    return [by_id[tuple_id] for tuple_id in tuple_ids]


class _DelayLine:
    def __init__(self, steps: int, width: int):
        if steps < 1:
            raise ValueError("delay must contain at least one step")
        self.values = np.zeros((steps, width), dtype=np.float64)
        self.index = 0

    def step(self, value: np.ndarray) -> np.ndarray:
        delayed = self.values[self.index].copy()
        self.values[self.index] = value
        self.index = (self.index + 1) % len(self.values)
        return delayed


class _TypedPopulation:
    def __init__(
        self,
        event_mask: np.ndarray,
        *,
        timestep_s: float,
        graded_tau_s: float,
        event_tau_s: float,
        synaptic_tau_s: float,
        refractory_s: float,
        threshold_excursion_mV: float,
        dimensionless_input_scale: float,
    ):
        self.event_mask = np.asarray(event_mask, dtype=bool)
        self.graded_mask = ~self.event_mask
        self.membrane = np.zeros(len(self.event_mask), dtype=np.float64)
        self.synaptic = np.zeros(len(self.event_mask), dtype=np.float64)
        self.refractory = np.zeros(len(self.event_mask), dtype=np.int64)
        self.refractory_steps = max(1, int(round(refractory_s / timestep_s)))
        self.alpha = timestep_s / np.where(self.event_mask, event_tau_s, graded_tau_s)
        self.synaptic_decay = float(np.exp(-timestep_s / synaptic_tau_s))
        self.threshold = float(threshold_excursion_mV)
        self.input_gain = self.threshold * float(dimensionless_input_scale)

    def step(self, drive: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        value = np.asarray(drive, dtype=np.float64)
        self.refractory = np.maximum(self.refractory - 1, 0)
        active = self.graded_mask | (self.event_mask & (self.refractory == 0))
        self.membrane[active] += self.alpha[active] * (
            -self.membrane[active] + self.input_gain * value[active]
        )
        fired = self.event_mask & (self.refractory == 0) & (self.membrane >= self.threshold)
        spikes = fired.astype(np.int64)
        self.membrane[fired] = 0.0
        self.refractory[fired] = self.refractory_steps
        self.synaptic = self.synaptic * self.synaptic_decay + spikes
        output = np.empty_like(self.membrane)
        output[self.event_mask] = self.synaptic[self.event_mask]
        output[self.graded_mask] = np.maximum(self.membrane[self.graded_mask], 0.0) / self.threshold
        if not np.isfinite(output).all():
            raise DeclaredClosedLoopSentinelError("typed population emitted non-finite state")
        return output, spikes


class _MotorTwitch:
    def __init__(self, force_per_event_uN: float, rise_s: float, decay_s: float, timestep_s: float, gain: float):
        if not 0.0 < rise_s < decay_s:
            raise DeclaredClosedLoopSentinelError("invalid motor twitch time constants")
        peak_time = rise_s * decay_s / (decay_s - rise_s) * np.log(decay_s / rise_s)
        self.peak = float(np.exp(-peak_time / decay_s) - np.exp(-peak_time / rise_s))
        self.decay_factor = float(np.exp(-timestep_s / decay_s))
        self.rise_factor = float(np.exp(-timestep_s / rise_s))
        self.force_per_event_uN = float(force_per_event_uN)
        self.gain = float(gain)
        self.decay_state = 0.0
        self.rise_state = 0.0

    def step(self, event_count: int) -> tuple[float, float]:
        self.decay_state = self.decay_state * self.decay_factor + int(event_count)
        self.rise_state = self.rise_state * self.rise_factor + int(event_count)
        force = (self.decay_state - self.rise_state) / self.peak * self.force_per_event_uN
        return float(force), float(force * self.gain)


def _joint_id(model: Any, name: str) -> int:
    import mujoco

    index = int(mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name))
    if index < 0:
        raise DeclaredClosedLoopSentinelError(f"FlyBody joint anchor is absent: {name}")
    return index


def _front_leg_anchor_ids(loop: FlyBodyPhysicsLoop) -> dict[str, tuple[int, int, int]]:
    model = loop.simulation.mj_model
    return {
        side: (
            _joint_id(model, f"flybody/{side}f_coxa-{side}f_trochanterfemur-pitch"),
            _joint_id(model, f"flybody/{side}f_trochanterfemur-{side}f_tibia-pitch"),
            _joint_id(model, f"flybody/{side}f_tibia-{side}f_tarsus1-pitch"),
        )
        for side in ("l", "r")
    }


def _internal_angle_deg(data: Any, joint_ids: tuple[int, int, int]) -> float:
    proximal, knee, distal = (np.asarray(data.xanchor[index], dtype=np.float64) for index in joint_ids)
    first = proximal - knee
    second = distal - knee
    denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
    if denominator <= 0.0:
        raise DeclaredClosedLoopSentinelError("degenerate femur-tibia anchor geometry")
    cosine = float(np.clip(np.dot(first, second) / denominator, -1.0, 1.0))
    angle = float(np.degrees(np.arccos(cosine)))
    if not np.isfinite(angle) or not 0.0 < angle < 180.0:
        raise DeclaredClosedLoopSentinelError("femur-tibia anatomical angle is invalid")
    return angle


def geometry_oracle() -> dict[str, Any]:
    """Verify that both signed FlyBody knee coordinates map monotonically to anatomy."""

    import mujoco

    raw_degrees = np.asarray([-70.0, -35.0, 0.0, 35.0, 70.0], dtype=np.float64)
    sides: dict[str, Any] = {}
    with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=False) as loop:
        anchor_ids = _front_leg_anchor_ids(loop)
        model = loop.simulation.mj_model
        data = loop.simulation.mj_data
        for side in ("l", "r"):
            knee_name = f"flybody/{side}f_trochanterfemur-{side}f_tibia-pitch"
            knee_id = _joint_id(model, knee_name)
            qpos_address = int(model.jnt_qposadr[knee_id])
            original = float(data.qpos[qpos_address])
            anatomical = []
            for raw in raw_degrees:
                data.qpos[qpos_address] = np.radians(raw)
                mujoco.mj_forward(model, data)
                anatomical.append(_internal_angle_deg(data, anchor_ids[side]))
            data.qpos[qpos_address] = original
            mujoco.mj_forward(model, data)
            anatomical_array = np.asarray(anatomical)
            increments = np.diff(anatomical_array)
            sides[side.upper()] = {
                "raw_joint_deg": raw_degrees.tolist(),
                "anatomical_internal_deg": anatomical_array.tolist(),
                "strictly_increasing": bool(np.all(increments > 0.0)),
                "minimum_increment_deg": float(np.min(increments)),
                "covered_span_deg": float(anatomical_array[-1] - anatomical_array[0]),
            }
    return {
        "method": "world_joint_anchor_internal_angle_arccos",
        "sides": sides,
        "all_strictly_increasing": all(item["strictly_increasing"] for item in sides.values()),
        "minimum_covered_span_deg": min(item["covered_span_deg"] for item in sides.values()),
    }


def _claw_bounds(center_deg: float) -> tuple[float, float]:
    anatomical_domain = np.linspace(0.0, 180.0, 1801)
    raw = np.polyval(CLAW_SOURCE_COEFFICIENTS, anatomical_domain - center_deg)
    return float(raw.min()), float(raw.max())


def _source_functions(angle_deg: float, velocity_deg_s: float, source_path: Mapping[str, str]) -> dict[str, float]:
    claw_id = str(source_path["claw_position"])
    club_id = str(source_path["club_vibration_and_speed"])
    hook_id = str(source_path["hook_flexion_direction"])
    center = 80.0 if "center_80" in claw_id else 90.0
    lower, upper = _claw_bounds(center)
    raw_claw = float(np.polyval(CLAW_SOURCE_COEFFICIENTS, angle_deg - center))
    claw = float(np.clip((raw_claw - lower) / (upper - lower), 0.0, 1.0))
    club_threshold = 5.0 if "threshold_5" in club_id else 50.0
    hook_threshold = -5.0 if "minus_5" in hook_id else -50.0
    return {
        "claw_position": claw,
        "club_vibration_and_speed": float(abs(velocity_deg_s) > club_threshold),
        "hook_flexion_direction": float(velocity_deg_s < hook_threshold),
    }


def _event_mask_and_signs(row: Mapping[str, str], context: Mapping[str, Any], profiles: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    inputs = context["inputs"]
    classified = inputs["classified"].set_index("body_id")
    intermediate_ids = list(map(int, inputs["intermediate_body_ids"]))
    assignment_profile = inputs["profiles"][str(row["intermediate_profile_id"])]
    event_mask = np.asarray([
        classified.loc[body_id, "assignment"] == "event_required" or assignment_profile.get(body_id) == "event_candidate"
        for body_id in intermediate_ids
    ], dtype=bool)
    sign_codes = classified.loc[intermediate_ids, "sign_code"].to_numpy(dtype=np.int8)
    signs = sign_codes.astype(np.float64)
    sign_profile = profiles["sign"][str(row["unknown_sign_profile_id"])]
    for index, body_id in enumerate(intermediate_ids):
        if sign_codes[index] == 0:
            signs[index] = -1.0 if int(sign_profile[str(body_id)]) == 0 else 1.0
    return event_mask, signs


def _compact_episode(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "finite_fraction": metrics["finite_fraction"],
        "joint_limit_violation_frames": metrics["failure_masks"]["joint_limit_violation_frames"],
        "gross_fall_proxy_frames": metrics["failure_masks"]["gross_fall_proxy_frames"],
        "numerical_failure_frames": metrics["failure_masks"]["numerical_failure_frames"],
        "com_translation_peak_l2": metrics["center_of_mass"]["translation_from_initial_peak_l2"],
        "com_jerk_peak": metrics["physical_com_kinematics"]["jerk_l2_peak"],
        "direct_motor_work_proxy": metrics["declared_direct_motor_work_proxy"]["absolute_force_velocity_integral"],
    }


def _run_episode(
    campaign: Mapping[str, Any],
    row: Mapping[str, str],
    context: Mapping[str, Any],
    profiles: Mapping[str, Any],
    matrices: tuple[np.ndarray, np.ndarray, np.ndarray],
    *,
    perturbation: Mapping[str, Any] | None,
) -> tuple[dict[str, np.ndarray], dict[str, Any], dict[str, Any]]:
    import mujoco

    inputs = context["inputs"]
    runtime = context["campaign"]["runtime_contract"]
    protocol = campaign["physical_protocol"]
    timestep_s = float(campaign["runtime_contract"]["timestep_s"])
    frames = int(protocol["frames"])
    substeps = int(protocol["physics_substeps_per_frame"])
    total_steps = frames * substeps
    delay_steps = int(round(float(runtime["fixed_delay_s"]) / timestep_s))
    numeric = profiles["numeric"][str(row["numeric_profile_id"])]
    event_mask, signs = _event_mask_and_signs(row, context, profiles)
    first, second, direct = matrices
    intermediate = _TypedPopulation(
        event_mask,
        timestep_s=timestep_s,
        graded_tau_s=float(numeric["graded_membrane_tau_s"]),
        event_tau_s=float(runtime["event_membrane_tau_s"]),
        synaptic_tau_s=float(runtime["event_synaptic_tau_s"]),
        refractory_s=float(runtime["event_refractory_s"]),
        threshold_excursion_mV=float(runtime["event_threshold_excursion_mV"]),
        dimensionless_input_scale=float(numeric["dimensionless_input_scale"]),
    )
    motor = _TypedPopulation(
        np.ones(10, dtype=bool),
        timestep_s=timestep_s,
        graded_tau_s=float(numeric["graded_membrane_tau_s"]),
        event_tau_s=float(runtime["event_membrane_tau_s"]),
        synaptic_tau_s=float(runtime["event_synaptic_tau_s"]),
        refractory_s=float(runtime["event_refractory_s"]),
        threshold_excursion_mV=float(runtime["event_threshold_excursion_mV"]),
        dimensionless_input_scale=float(numeric["dimensionless_input_scale"]),
    )
    first_delay = _DelayLine(delay_steps, 150)
    second_delay = _DelayLine(delay_steps, 10)
    direct_delay = _DelayLine(delay_steps, 10)
    source_state = np.zeros(36, dtype=np.float64)
    source_decay = float(np.exp(-timestep_s / float(runtime["event_synaptic_tau_s"])))
    rng = np.random.default_rng(int(row["seed"]))
    sensory_ids = list(map(int, inputs["sensory_body_ids"]))
    motor_ids = list(map(int, inputs["motor_body_ids"]))
    members = context["members"].set_index("body_id")
    sides = [str(members.loc[body_id, "side"]) for body_id in sensory_ids]
    feco_profile = profiles["feco"][str(row["feco_routing_profile_id"])]
    levels = list(profiles["functional_levels"])
    functions = [levels[int(feco_profile[profiles["body_to_group"][body_id]])] for body_id in sensory_ids]
    source_path = inputs["feco_paths"][int(row["feco_source_path_index"])]
    route_body_id = int(row["route_body_id"])
    route_index = motor_ids.index(route_body_id)
    assignment = _decode_motor_assignment(row, list(inputs["body_ids"]))
    route_class = assignment[route_body_id]
    temporal = inputs["temporal_by_class"][route_class]
    twitch = _MotorTwitch(
        inputs["force_by_class"][route_class],
        temporal["rise_time_s"],
        temporal["decay_time_s"],
        timestep_s,
        float(row["bridge_gain_command_per_uN"]),
    )
    target_id = int(row["route_target_actuator_id"])

    records: dict[str, list[Any]] = {key: [] for key in (
        "timestamps_s", "qpos", "qvel", "joint_positions", "joint_velocities",
        "actuator_forces", "applied_commands", "center_of_mass", "root_up_z",
        "ground_contact_found", "ground_contact_force_norm",
    )}
    angle_trace: list[list[float]] = []
    source_sum_trace: list[float] = []
    route_event_trace: list[int] = []
    command_scalar_trace: list[float] = []
    force_scalar_trace: list[float] = []
    intermediate_spikes = 0
    motor_spikes = 0
    source_events = 0
    perturbation_step = int(protocol["perturbation_step"]) * substeps

    with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=False) as loop:
        metadata = _model_measurement_metadata(loop)
        native_dt = float(loop.simulation.mj_model.opt.timestep)
        if not np.isclose(native_dt, timestep_s, atol=0.0, rtol=1e-12):
            raise DeclaredClosedLoopSentinelError(f"physics timestep {native_dt} differs from neural timestep {timestep_s}")
        if loop.actuator_names[target_id] != str(row["route_target_actuator_name"]):
            raise DeclaredClosedLoopSentinelError("scheduled actuator address drift")
        anchors = _front_leg_anchor_ids(loop)
        # FlyGym's freshly constructed mjData has not populated derived world
        # anchors yet.  Populate them before the first causal sensor read; this
        # does not advance simulation time or inject a state change.
        mujoco.mj_forward(loop.simulation.mj_model, loop.simulation.mj_data)
        previous_angles = {
            "L": _internal_angle_deg(loop.simulation.mj_data, anchors["l"]),
            "R": _internal_angle_deg(loop.simulation.mj_data, anchors["r"]),
        }
        for step_index in range(total_steps):
            if perturbation is not None and step_index == perturbation_step:
                address = int(perturbation["qvel_address"])
                loop.simulation.mj_data.qvel[address] += float(perturbation["delta"])
                mujoco.mj_forward(loop.simulation.mj_model, loop.simulation.mj_data)
            angles = {
                "L": _internal_angle_deg(loop.simulation.mj_data, anchors["l"]),
                "R": _internal_angle_deg(loop.simulation.mj_data, anchors["r"]),
            }
            velocities = {side: (angles[side] - previous_angles[side]) / timestep_s for side in ("L", "R")}
            previous_angles = angles
            side_signals = {
                side: _source_functions(angles[side], velocities[side], source_path)
                for side in ("L", "R")
            }
            activity = np.asarray([
                side_signals[side][function]
                for side, function in zip(sides, functions, strict=True)
            ], dtype=np.float64)
            if str(row["feco_native_representation"]) == "event_candidate":
                events = rng.poisson(activity * float(numeric["unresolved_event_intensity_ceiling_hz"]) * timestep_s)
                source_state = source_state * source_decay + events
                source_drive = source_state
                source_events += int(events.sum())
            else:
                source_drive = activity
            intermediate_drive = first_delay.step(source_drive @ first)
            intermediate_output, intermediate_event = intermediate.step(intermediate_drive)
            intermediate_spikes += int(intermediate_event.sum())
            motor_drive = second_delay.step((intermediate_output * signs) @ second) + direct_delay.step(source_drive @ direct)
            _motor_output, motor_event = motor.step(motor_drive)
            motor_spikes += int(motor_event.sum())
            route_event = int(motor_event[route_index])
            route_event_trace.append(route_event)
            force_uN, command_scalar = twitch.step(route_event)
            if not np.isfinite(command_scalar) or abs(command_scalar) > 0.01:
                raise DeclaredClosedLoopSentinelError("closed-loop command is non-finite or exceeds MOTOR limit")
            command = np.zeros(102, dtype=np.float64)
            command[target_id] = command_scalar
            addressed = loop.actuator_interface.step(command)
            loop.simulation.set_actuator_inputs("flybody", loop.actuator_type, addressed.values)
            loop.simulation.step()
            angle_trace.append([angles["L"], angles["R"]])
            source_sum_trace.append(float(source_drive.sum()))
            command_scalar_trace.append(command_scalar)
            force_scalar_trace.append(force_uN)
            if (step_index + 1) % substeps == 0:
                joint_state = loop.read_joint_state()
                contact_found, forces, _torques, _positions, _normals, _tangents = loop.simulation.get_ground_contact_info("flybody")
                records["timestamps_s"].append(float(loop.simulation.mj_data.time))
                records["qpos"].append(loop.simulation.mj_data.qpos.copy())
                records["qvel"].append(loop.simulation.mj_data.qvel.copy())
                records["joint_positions"].append(joint_state.positions.copy())
                records["joint_velocities"].append(joint_state.velocities.copy())
                records["actuator_forces"].append(np.asarray(loop.simulation.get_actuator_forces("flybody", loop.actuator_type), dtype=np.float64).copy())
                records["applied_commands"].append(addressed.values.copy())
                records["center_of_mass"].append(_center_of_mass(loop, metadata))
                records["root_up_z"].append(_root_up_z(loop.simulation.mj_data.qpos))
                records["ground_contact_found"].append(np.asarray(contact_found, dtype=np.float64).copy())
                records["ground_contact_force_norm"].append(np.linalg.norm(np.asarray(forces, dtype=np.float64), axis=1))

    episode = {key: np.asarray(values) for key, values in records.items()}
    angles_array = np.asarray(angle_trace, dtype=np.float64)
    source_array = np.asarray(source_sum_trace, dtype=np.float64)
    route_array = np.asarray(route_event_trace, dtype=np.int64)
    command_array = np.asarray(command_scalar_trace, dtype=np.float64)
    force_array = np.asarray(force_scalar_trace, dtype=np.float64)
    diagnostic = {
        "source_representation": str(row["feco_native_representation"]),
        "feco_projection_sha256": _canonical_hash(dict(zip(map(str, sensory_ids), functions, strict=True))),
        "angle_min_deg": {"L": float(angles_array[:, 0].min()), "R": float(angles_array[:, 1].min())},
        "angle_max_deg": {"L": float(angles_array[:, 0].max()), "R": float(angles_array[:, 1].max())},
        "source_nonzero_steps": int(np.count_nonzero(source_array)),
        "source_event_count": source_events,
        "intermediate_spike_count": intermediate_spikes,
        "motor_spike_count": motor_spikes,
        "route_motor_event_count": int(route_array.sum()),
        "peak_abs_command": float(np.max(np.abs(command_array), initial=0.0)),
        "active_actuator_ids": [target_id] if np.any(command_array != 0.0) else [],
        "route_body_id": route_body_id,
        "route_body_class": route_class,
        "target_actuator_id": target_id,
        "target_actuator_name": str(row["route_target_actuator_name"]),
        "trace_sha256": _array_hash(angles_array, source_array, route_array, force_array, command_array),
    }
    if not all(np.isfinite(value).all() for value in episode.values()) or not np.isfinite(angles_array).all():
        raise DeclaredClosedLoopSentinelError("episode contains non-finite state")
    return episode, metadata, diagnostic


def run_sentinel(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    run_root: Path = RUN_ROOT,
) -> dict[str, Any]:
    started = time.perf_counter()
    print("[1/7] Verifying preregistration and frozen neural/physical contracts", flush=True)
    campaign = _load_campaign(campaign_path)
    context = _verified_context(campaign)
    profiles = _profiles(context)
    selected = _selected_rows(campaign, context)
    first, second, direct, coupling_audit = _incoming_l1_matrices(context["inputs"])
    matrices = (first, second, direct)

    print("[2/7] Validating bilateral FlyBody-to-anatomical FeCO registration", flush=True)
    geometry = geometry_oracle()
    if not geometry["all_strictly_increasing"] or geometry["minimum_covered_span_deg"] < 120.0:
        raise DeclaredClosedLoopSentinelError("geometric registration oracle failed")

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    artifact_root = run_root / run_id
    artifact_root.mkdir(parents=True, exist_ok=False)
    perturbation = campaign["physical_protocol"]["perturbation"]
    outcomes: list[dict[str, Any]] = []
    print("[3/7] Executing causal paired body-neural-body episodes", flush=True)
    for index, row in enumerate(selected, start=1):
        print(f"[TUPLE {index}/{len(selected)}] {row['tuple_id']}", flush=True)
        outcome: dict[str, Any] = {"tuple_id": row["tuple_id"], "status": "error"}
        try:
            baseline, baseline_metadata, baseline_diag = _run_episode(campaign, row, context, profiles, matrices, perturbation=None)
            perturbed, perturbed_metadata, perturbed_diag = _run_episode(campaign, row, context, profiles, matrices, perturbation=perturbation)
            if baseline_metadata["model_contract"] != perturbed_metadata["model_contract"]:
                raise DeclaredClosedLoopSentinelError("paired model contracts differ")
            baseline_metrics = _episode_metrics(baseline, baseline_metadata)
            perturbed_metrics = _episode_metrics(perturbed, perturbed_metadata)
            recovery = paired_recovery_metrics(baseline, perturbed, int(campaign["physical_protocol"]["perturbation_step"]))
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

    print("[4/7] Accounting outcomes without ranking candidates", flush=True)
    counts = Counter(item["status"] for item in outcomes)
    completed = [item for item in outcomes if item["status"] == "completed_contract"]
    all_finite = len(completed) == len(selected)
    source_active = all(item["baseline_chain"]["source_nonzero_steps"] > 0 and item["perturbed_chain"]["source_nonzero_steps"] > 0 for item in completed)
    isolated = all(
        item[branch]["active_actuator_ids"] in ([], [item[branch]["target_actuator_id"]])
        for item in completed for branch in ("baseline_chain", "perturbed_chain")
    )
    causal_actuation_observed = any(
        item[branch]["peak_abs_command"] > 0.0
        for item in completed for branch in ("baseline_chain", "perturbed_chain")
    )
    perturbation_detected = all(
        float(item["paired_recovery"]["qvel"]["peak_l2"]) > 0.0
        for item in completed
    )
    checks = {
        "all_sentinel_tuples_accounted": len(outcomes) == len(selected),
        "all_paired_episodes_finite": all_finite,
        "bilateral_geometric_registration_passed": geometry["all_strictly_increasing"],
        "causal_source_path_active_in_every_episode": source_active,
        "non_scoped_actuator_outputs_zero": isolated,
        "at_least_one_causal_nonzero_actuator_command": causal_actuation_observed,
        "generic_perturbation_detected_in_every_pair": perturbation_detected,
        "incoming_L1_columns_exact": bool(coupling_audit["all_nonzero_columns_exact"]),
        "zero_fit_zero_selection_zero_behavior": True,
    }
    passed = all(checks.values())

    print("[5/7] Writing ignored heavy traces and compact hash-linked result", flush=True)
    elapsed = time.perf_counter() - started
    result = {
        "schema_version": 1,
        "id": "runner_result.neutral_embodied_declared_closed_loop_sentinel.v0",
        "campaign_id": campaign["id"],
        "status": "pass_causal_closed_loop_execution_no_fit_no_selection" if passed else "failed_causal_closed_loop_execution",
        "completed_at": datetime.now(UTC).isoformat(),
        "claim_label": campaign["claim_label"],
        "command": "neutral_embodied_declared_closed_loop_sentinel.bat",
        "frozen_input_sha256": context["frozen_hashes"],
        "geometry_registration": geometry,
        "structural_coupling_audit": coupling_audit,
        "accounting": {
            "sentinel_tuples": len(selected),
            "paired_physical_episodes": len(selected) * 2,
            "outcome_counts": dict(sorted(counts.items())),
            "optimized_parameters": 0,
            "promoted_parameter_values": 0,
            "selected_candidates": 0,
            "named_behavior_exposure": 0,
        },
        "checks": checks,
        "outcomes": outcomes,
        "scientific_boundary": campaign["scientific_boundary"],
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "wall_seconds": elapsed,
        "next_action": campaign["next_action"],
    }
    semantic_outcomes = [
        {key: value for key, value in item.items() if key != "artifacts"}
        for item in outcomes
    ]
    result["semantic_result_sha256"] = _canonical_hash({
        **{key: value for key, value in result.items() if key not in {"completed_at", "wall_seconds", "outcomes"}},
        "outcomes": semantic_outcomes,
    })
    result_path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.neutral_embodied_declared_closed_loop_sentinel.v0",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": result["semantic_result_sha256"],
        "status": "pass" if passed else "fail",
        "checks": checks,
        "stability_accepted": False,
        "population_assignment_accepted": False,
        "candidate_selected": False,
        "behavior_claimed": False,
        "interpretation": "A pass establishes a causal local body-neural-body execution and coordinate bridge only; it calibrates nothing.",
        "next_action": campaign["next_action"],
    }
    evaluation_path.write_text(yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8")

    print("[6/7] Verifying explicit scientific boundaries", flush=True)
    if not passed:
        failed = [key for key, value in checks.items() if not value]
        raise DeclaredClosedLoopSentinelError(f"closed-loop sentinel failed: {failed}")
    print("[7/7] PASS", flush=True)
    print(f"[GEOMETRY] bilateral span >= {geometry['minimum_covered_span_deg']:.3f} deg", flush=True)
    print(f"[ACCOUNTING] {len(selected)} tuples / {len(selected) * 2} paired episodes", flush=True)
    print("[BOUNDARY] 0 fit, 0 selection, 0 promotion, 0 behavior", flush=True)
    print(f"[HASH] {result['semantic_result_sha256']}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the declared causal body-neural-body sentinel")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    run_sentinel(campaign_path=args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

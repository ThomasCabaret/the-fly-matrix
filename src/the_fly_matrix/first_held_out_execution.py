from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml
from scipy import sparse

from . import front_leg_neutral_embodied_regime as fh07b
from .embodied_measurement_contract import _episode_metrics, _model_measurement_metadata
from .first_held_out_control_recalibration import replace_cone_recurrence
from .front_leg_coupled_identifiability import _functional_class_map
from .front_leg_coupled_identifiability_execution import _verify_campaign as verify_fh05
from .front_leg_integrated_lineage import _verify_inputs
from .front_leg_neutral_neural_regime import _paired_schedules
from .ledger import ROOT
from .neutral_embodied_declared_closed_loop_sentinel import (
    _front_leg_anchor_ids,
    _internal_angle_deg,
    _source_functions,
)
from .neutral_embodied_feedback_identifiability import _record_physical_frame
from .runtime import FlyBodyPhysicsLoop
from .typed_hybrid_runtime import EVENT, GRADED, TorchTypedHybridRuntime


CAMPAIGN_PATH = ROOT / "calibration/campaigns/first-held-out-execution-v2.yaml"
RESULT_PATH = ROOT / "calibration/runner/first-held-out-execution-v2.yaml"
EVALUATION_PATH = ROOT / "calibration/evaluations/first-held-out-execution-v2.yaml"
RUN_ROOT = ROOT / "runs/calibration/first-held-out-execution-v2"


class HeldOutExecutionError(RuntimeError):
    pass


def _step_without_diagnostic_metrics(
    runtime: TorchTypedHybridRuntime,
    *,
    forced_event_indices: Sequence[int] | np.ndarray = (),
    external_graded: np.ndarray | None = None,
) -> None:
    """Advance the canonical runtime state without unused per-step reductions.

    This is deliberately local to FH-09: changing the shared, frozen runtime
    implementation would invalidate earlier campaign hashes. The operations that
    mutate state are kept identical to ``TorchTypedHybridRuntime.step``; only its
    returned diagnostic reductions are omitted.
    """
    import torch

    c = runtime.constants
    slot = runtime.step_index % len(runtime.queue)
    arriving_sources = runtime.queue[slot]
    runtime.queue[slot] = torch.empty(0, dtype=torch.int64, device=runtime.device)

    runtime.refractory[runtime.refractory > 0] -= 1
    eligible = runtime.event_mask & (runtime.refractory == 0)
    previous_v = runtime.v[eligible]
    previous_g = runtime.g[eligible]
    runtime.v[eligible] = c.lif.v_rest_mV + (
        (previous_v - c.lif.v_rest_mV) * runtime.membrane_decay
        + previous_g * runtime.membrane_coupling
    )
    runtime.g[eligible] = previous_g * runtime.synaptic_decay
    generated = torch.nonzero(eligible & (runtime.v > c.lif.threshold_mV)).flatten()

    event_vector = torch.zeros(runtime.node_count, dtype=torch.float32, device=runtime.device)
    if arriving_sources.numel():
        event_vector[arriving_sources] = 1.0
    event_projection = runtime._projection(event_vector) if arriving_sources.numel() else event_vector
    runtime.g[runtime.event_mask] += c.event_to_event_mV * event_projection[runtime.event_mask]

    if generated.numel():
        runtime.v[generated] = c.lif.reset_mV
        runtime.g[generated] = 0.0
        runtime.refractory[generated] = runtime.refractory_steps

    forced_host = np.asarray(forced_event_indices, dtype=np.int64)
    if forced_host.size:
        if int(forced_host.min()) < 0 or int(forced_host.max()) >= runtime.node_count:
            raise HeldOutExecutionError("forced event index is outside the graph")
        if not np.all(runtime.assignment_np[forced_host] == EVENT):
            raise HeldOutExecutionError("forced event was assigned to a non-event population")
    forced = torch.as_tensor(forced_host, dtype=torch.int64, device=runtime.device)
    emitted = torch.unique(torch.cat((generated, forced)))
    destination = (runtime.step_index + runtime.delay_steps) % len(runtime.queue)
    runtime.queue[destination] = emitted

    graded_source = torch.where(
        runtime.graded_mask, runtime.graded, torch.zeros_like(runtime.graded)
    )
    graded_projection = (
        runtime._projection(graded_source)
        if np.any(runtime.assignment_np == GRADED)
        else graded_source
    )
    if external_graded is None:
        external = torch.zeros(runtime.node_count, dtype=torch.float32, device=runtime.device)
    else:
        external = torch.as_tensor(external_graded, dtype=torch.float32, device=runtime.device)
        if external.shape != (runtime.node_count,):
            raise HeldOutExecutionError("external graded vector has the wrong shape")
        nonzero = np.flatnonzero(external_graded)
        if nonzero.size and np.any(runtime.assignment_np[nonzero] != GRADED):
            raise HeldOutExecutionError("graded input was applied outside graded populations")
    proposal = torch.tanh(
        c.graded_to_graded * graded_projection
        + c.event_to_graded * event_projection
        + external
    )
    runtime.graded[runtime.graded_mask] = (
        runtime.graded_decay * runtime.graded[runtime.graded_mask]
        + (1.0 - runtime.graded_decay) * proposal[runtime.graded_mask]
    )
    runtime.graded[~runtime.graded_mask] = 0.0
    runtime.g[runtime.event_mask] += c.graded_to_event_mV * graded_projection[runtime.event_mask]
    runtime.g[~runtime.event_mask] = 0.0
    runtime.v[~runtime.event_mask] = c.lif.v_rest_mV
    runtime.refractory[~runtime.event_mask] = 0
    runtime.step_index += 1


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HeldOutExecutionError(f"{path} must contain a YAML mapping")
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


def _write_yaml(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(dict(value), sort_keys=False, allow_unicode=True), encoding="utf-8")


def _verify_frozen_inputs(campaign: Mapping[str, Any]) -> dict[str, Path]:
    if campaign.get("primary_class") != "evaluation_only":
        raise HeldOutExecutionError("FH-09 must remain evaluation_only")
    if campaign.get("optimization_exposure") != "evaluation_only":
        raise HeldOutExecutionError("FH-09 outcomes cannot be exposed to optimization")
    if campaign.get("parameter_changes_allowed") is not False:
        raise HeldOutExecutionError("FH-09 cannot change parameters")
    paths: dict[str, Path] = {}
    for name, record in campaign["frozen_inputs"].items():
        path = ROOT / str(record["path"])
        if not path.is_file():
            raise HeldOutExecutionError(f"missing frozen input {name}: {path}")
        observed = _sha256(path)
        if observed != str(record["sha256"]):
            raise HeldOutExecutionError(
                f"frozen input drift for {name}: {observed} != {record['sha256']}"
            )
        paths[str(name)] = path
    return paths


def _load_bundle(campaign_path: Path, result_path: Path) -> dict[str, Any]:
    campaign = fh07b._load_yaml(campaign_path)
    _hashes, documents = fh07b._verify_frozen_inputs(campaign)
    parent_campaign = documents["fh06_campaign"]
    verified = _verify_inputs(parent_campaign)
    fh05_paths = verify_fh05(verified["documents"]["coupled_campaign"])
    source_rows = pd.read_csv(fh05_paths["source_terminals"]).sort_values("body_id")
    result = _load_yaml(result_path)
    return {
        "campaign": campaign,
        "documents": documents,
        "parent_campaign": parent_campaign,
        "verified": verified,
        "source_families": source_rows.family_id.astype(str).to_numpy(),
        "routes": pd.read_parquet(ROOT / campaign["frozen_inputs"]["motor_routes"]["path"]),
        "neural_rows": {str(row["row_id"]): row for row in documents["fh07a_result"]["rows"]},
        "physical_rows": {str(row["row_id"]): row for row in result["rows"]},
    }


def _joint_address(loop: FlyBodyPhysicsLoop, side: str) -> tuple[int, int, str]:
    import mujoco

    prefix = "lf" if side == "left" else "rf"
    name = f"flybody/{prefix}_trochanterfemur-{prefix}_tibia-pitch"
    joint_id = int(mujoco.mj_name2id(loop.simulation.mj_model, mujoco.mjtObj.mjOBJ_JOINT, name))
    if joint_id < 0:
        raise HeldOutExecutionError(f"stimulus joint missing: {name}")
    return (
        int(loop.simulation.mj_model.jnt_qposadr[joint_id]),
        int(loop.simulation.mj_model.jnt_dofadr[joint_id]),
        name,
    )


def _extension_qpos_sign(loop: FlyBodyPhysicsLoop, side: str, qpos_address: int) -> float:
    import mujoco

    anchors = _front_leg_anchor_ids(loop)
    key = "l" if side == "left" else "r"
    baseline = float(loop.simulation.mj_data.qpos[qpos_address])
    epsilon = 1.0e-5
    loop.simulation.mj_data.qpos[qpos_address] = baseline + epsilon
    mujoco.mj_forward(loop.simulation.mj_model, loop.simulation.mj_data)
    plus = _internal_angle_deg(loop.simulation.mj_data, anchors[key])
    loop.simulation.mj_data.qpos[qpos_address] = baseline - epsilon
    mujoco.mj_forward(loop.simulation.mj_model, loop.simulation.mj_data)
    minus = _internal_angle_deg(loop.simulation.mj_data, anchors[key])
    loop.simulation.mj_data.qpos[qpos_address] = baseline
    mujoco.mj_forward(loop.simulation.mj_model, loop.simulation.mj_data)
    if math.isclose(plus, minus, abs_tol=1.0e-10):
        raise HeldOutExecutionError("cannot determine leg-local extension sign")
    return 1.0 if plus > minus else -1.0


def ramp_fraction(step: int, baseline_steps: int, ramp_steps: int) -> float | None:
    if step < baseline_steps or step >= baseline_steps + ramp_steps:
        return None
    return (step - baseline_steps + 1) / ramp_steps


def worker_group_indices(total: int, worker_index: int, worker_count: int) -> list[int]:
    if total < 0 or worker_count < 1 or not 0 <= worker_index < worker_count:
        raise HeldOutExecutionError("invalid parallel group partition")
    return list(range(worker_index, total, worker_count))


def _failure_counts(records: Mapping[str, np.ndarray], metadata: Mapping[str, Any]) -> dict[str, int]:
    masks = _episode_metrics(records, metadata)["failure_masks"]
    return {str(key): int(value) for key, value in masks.items() if str(key).endswith("_frames")}


def _run_episode(
    loop: FlyBodyPhysicsLoop,
    *,
    context: Mapping[str, Any],
    neural_row: Mapping[str, Any],
    physical_profile: Mapping[str, Any],
    documents: Mapping[str, Any],
    source_families: np.ndarray,
    routes: pd.DataFrame,
    protocol: Mapping[str, Any],
    execution: Mapping[str, Any],
    side: str,
    condition: str,
    trial_seed: int,
) -> dict[str, Any]:
    import mujoco
    import torch

    loop.reset()
    mujoco.mj_forward(loop.simulation.mj_model, loop.simulation.mj_data)
    metadata = _model_measurement_metadata(loop)
    dt_s = float(loop.simulation.mj_model.opt.timestep)
    if not math.isclose(dt_s, float(execution["timestep_s"]), abs_tol=1.0e-12, rel_tol=0.0):
        raise HeldOutExecutionError("frozen physical timestep drift")
    total_steps = int(protocol["stimulus"]["total_physics_steps"])
    baseline_steps = int(protocol["stimulus"]["baseline_physics_steps"])
    ramp_steps = int(protocol["stimulus"]["ramp_physics_steps"])
    response_stop = baseline_steps + ramp_steps + int(round(0.1 / dt_s))

    fixture = dict(documents["campaign"]["neural_execution_fixture"])
    fixture.update({"steps": total_steps, "pulse_start_step": 0, "pulse_stop_step": total_steps})
    schedules = _paired_schedules(
        assignment=context["assignment"],
        source_count=int(context["source_count"]),
        source_families=source_families,
        feco_indices=context["feco_indices"],
        profile=neural_row["profile"],
        source_profile=str(context["source_profile"]),
        fixture=fixture,
        seed=int(trial_seed),
    )
    basal_event, basal_graded = schedules[2], schedules[3]
    runtime = TorchTypedHybridRuntime(
        context["graph"], context["assignment"], context["constants"], str(execution["device"])
    )
    class_by_type = _functional_class_map(context["crosswalk"], context["routing"])
    functional_classes = [class_by_type[str(value)] for value in context["feco"].annotation_type]
    representations = context["native"]["representation_by_class"]
    source_candidates = context["source_path"]["candidate_by_class"]
    source_functions = {
        "claw_position": source_candidates["claw"],
        "club_vibration_and_speed": source_candidates["club"],
        "hook_flexion_direction": source_candidates["hook"],
    }
    feco_sides = [str(value) for value in context["feco"].side]
    motor_body_ids = list(map(int, context["motor"].body_id))
    route_map = fh07b._route_map(routes, motor_body_ids, str(physical_profile["route_selector"]))
    gains = documents["motor_bridge"]["conditional_gain_envelope"]["candidate_gains_command_per_uN"]
    bridge = float(gains[fh07b._selector_index(str(physical_profile["bridge_selector"]), len(gains))])
    filters = [
        fh07b._motor_filter_factory(
            str(physical_profile["motor_class"]),
            str(physical_profile["temporal_selector"]),
            bridge,
            documents["motor_temporal"],
            documents["motor_slow"],
            dt_s,
        )
        for _ in motor_body_ids
    ]
    for route in route_map:
        if loop.actuator_names[route["target_actuator_id"]] != route["target_actuator_name"]:
            raise HeldOutExecutionError("motor route address drift")

    anchors = _front_leg_anchor_ids(loop)
    target_key = "L" if side == "left" else "R"
    anchor_key = target_key.lower()
    qpos_address, qvel_address, joint_name = _joint_address(loop, side)
    reset_qpos = float(loop.simulation.mj_data.qpos[qpos_address])
    sign = _extension_qpos_sign(loop, side, qpos_address)
    displacement_rad = math.radians(float(protocol["stimulus"]["displacement_deg"]))
    speed_rad_s = displacement_rad / (ramp_steps * dt_s)
    phase = (np.arange(len(context["feco"]), dtype=np.float64) * 0.4142135623730951) % 1.0
    feco_ratio = float(neural_row["profile"]["feco_native_amplitude_ratio"])
    previous = {
        "L": _internal_angle_deg(loop.simulation.mj_data, anchors["l"]),
        "R": _internal_angle_deg(loop.simulation.mj_data, anchors["r"]),
    }
    motor_assignment = np.asarray(context["assignment"])[np.asarray(context["motor_indices"])]
    motor_index_tensor = torch.as_tensor(
        context["motor_indices"], dtype=torch.int64, device=runtime.device
    )
    event_counts = np.zeros(len(motor_body_ids), dtype=np.int64)
    graded_integrals = np.zeros(len(motor_body_ids), dtype=np.float64)
    target_angles: list[float] = []
    records: dict[str, list[Any]] = {}
    command_abs_max = 0.0
    command_nonzero_steps = 0
    source_nonzero_steps = 0

    for step in range(total_steps):
        fraction = ramp_fraction(step, baseline_steps, ramp_steps)
        if fraction is not None:
            applied = displacement_rad * fraction if condition == "stimulus" else 0.0
            loop.simulation.mj_data.qpos[qpos_address] = reset_qpos + sign * applied
            loop.simulation.mj_data.qvel[qvel_address] = (
                sign * speed_rad_s if condition == "stimulus" else 0.0
            )
            mujoco.mj_forward(loop.simulation.mj_model, loop.simulation.mj_data)

        angles = {
            "L": _internal_angle_deg(loop.simulation.mj_data, anchors["l"]),
            "R": _internal_angle_deg(loop.simulation.mj_data, anchors["r"]),
        }
        target_angles.append(float(angles[target_key]))
        velocities = {key: (angles[key] - previous[key]) / dt_s for key in ("L", "R")}
        previous = angles
        functions = {
            key: _source_functions(angles[key], velocities[key], source_functions)
            for key in ("L", "R")
        }
        activity = np.asarray(
            [
                functions[feco_side][
                    {
                        "claw": "claw_position",
                        "club": "club_vibration_and_speed",
                        "hook": "hook_flexion_direction",
                    }[functional_class]
                ]
                for feco_side, functional_class in zip(feco_sides, functional_classes, strict=True)
            ],
            dtype=np.float64,
        )
        source_nonzero_steps += int(np.any(activity != 0.0))
        forced = list(np.flatnonzero(basal_event[step]))
        external = np.asarray(basal_graded[step], dtype=np.float32).copy()
        for index, (node_index, functional_class) in enumerate(
            zip(context["feco_indices"], functional_classes, strict=True)
        ):
            if representations[functional_class] == "event_intensity_hz":
                phase[index] += activity[index] * float(fixture["feco_event_rate_hz"]) * feco_ratio * dt_s
                if phase[index] >= 1.0:
                    forced.append(int(node_index))
                    phase[index] %= 1.0
            else:
                external[int(node_index)] = activity[index] * float(fixture["feco_graded_drive"]) * feco_ratio
        with torch.inference_mode():
            _step_without_diagnostic_metrics(
                runtime,
                forced_event_indices=forced,
                external_graded=external,
            )
        motor_snapshot = torch.stack(
            (
                (runtime.refractory[motor_index_tensor] == runtime.refractory_steps).to(torch.float32),
                runtime.graded[motor_index_tensor],
            )
        ).detach().cpu().numpy()
        events = motor_snapshot[0].astype(bool)
        if baseline_steps <= step < response_stop:
            event_counts += events.astype(np.int64)
            graded_integrals += motor_snapshot[1] * dt_s
        command = np.zeros(len(loop.actuator_names), dtype=np.float64)
        for event, transfer, route in zip(events, filters, route_map, strict=True):
            _force, scalar = transfer.step(int(event))
            command[int(route["target_actuator_id"])] += scalar
        observed = float(np.max(np.abs(command), initial=0.0))
        command_abs_max = max(command_abs_max, observed)
        if observed > float(execution["direct_motor_abs_max"]):
            raise HeldOutExecutionError(
                f"direct-MOTOR guard violated in {side}/{condition}/seed-{trial_seed}: {observed}"
            )
        command_nonzero_steps += int(np.any(command != 0.0))
        addressed = loop.actuator_interface.step(command)
        loop.simulation.set_actuator_inputs("flybody", loop.actuator_type, addressed.values)
        loop.simulation.step()
        if (step + 1) % int(execution["record_stride"]) == 0:
            for key, value in _record_physical_frame(loop, metadata).items():
                records.setdefault(key, []).append(value)

    arrays = {key: np.asarray(value) for key, value in records.items()}
    finite = all(np.isfinite(value).all() for value in arrays.values())
    release_index = baseline_steps + ramp_steps - 1
    release_angle = float(target_angles[release_index])
    final_angle = float(target_angles[-1])
    return {
        "side": side,
        "condition": condition,
        "trial_seed": int(trial_seed),
        "stimulus_joint": joint_name,
        "finite": bool(finite),
        "event_motor_count": int(np.sum(event_counts[motor_assignment == EVENT])),
        "graded_motor_integral": float(np.sum(graded_integrals[motor_assignment != EVENT])),
        "event_motor_count_by_body": [int(value) for value in event_counts],
        "graded_motor_integral_by_body": [float(value) for value in graded_integrals],
        "event_motor_bodies": int(np.count_nonzero(motor_assignment == EVENT)),
        "graded_motor_bodies": int(np.count_nonzero(motor_assignment != EVENT)),
        "release_angle_deg": release_angle,
        "final_angle_deg": final_angle,
        "release_opposition_deg": release_angle - final_angle,
        "source_nonzero_steps": source_nonzero_steps,
        "command_nonzero_steps": command_nonzero_steps,
        "command_abs_max": command_abs_max,
        "failure_masks": _failure_counts(arrays, metadata),
    }


def _pair_outcomes(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, str, int], dict[str, Mapping[str, Any]]] = {}
    for row in rows:
        key = (str(row["topology_variant"]), str(row["member_id"]), str(row["side"]), int(row["trial_seed"]))
        by_key.setdefault(key, {})[str(row["condition"])] = row
    pairs: list[dict[str, Any]] = []
    for key, conditions in sorted(by_key.items()):
        if set(conditions) != {"stimulus", "sham"}:
            raise HeldOutExecutionError(f"unpaired held-out outcome: {key}")
        stimulus, sham = conditions["stimulus"], conditions["sham"]
        event_effect = int(stimulus["event_motor_count"]) - int(sham["event_motor_count"])
        graded_effect = float(stimulus["graded_motor_integral"]) - float(sham["graded_motor_integral"])
        event_present = int(stimulus["event_motor_bodies"]) > 0
        graded_present = int(stimulus["graded_motor_bodies"]) > 0
        neural_positive = (not event_present or event_effect > 0) and (
            not graded_present or graded_effect > 0.0
        )
        no_new_failure = all(
            int(stimulus["failure_masks"].get(name, 0)) <= int(value)
            for name, value in sham["failure_masks"].items()
        )
        pairs.append(
            {
                "topology_variant": key[0],
                "member_id": key[1],
                "side": key[2],
                "trial_seed": key[3],
                "event_count_effect": event_effect,
                "graded_integral_effect": graded_effect,
                "event_motor_bodies": int(stimulus["event_motor_bodies"]),
                "graded_motor_bodies": int(stimulus["graded_motor_bodies"]),
                "neural_expected_direction": bool(neural_positive),
                "physical_opposition_effect_deg": float(stimulus["release_opposition_deg"])
                - float(sham["release_opposition_deg"]),
                "physical_expected_direction": float(stimulus["release_opposition_deg"])
                - float(sham["release_opposition_deg"])
                > 0.0,
                "bounded": bool(stimulus["finite"] and sham["finite"] and no_new_failure),
            }
        )
    return pairs


def _member_side_summary(pairs: Sequence[Mapping[str, Any]], threshold: int) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for row in pairs:
        key = (str(row["topology_variant"]), str(row["member_id"]), str(row["side"]))
        groups.setdefault(key, []).append(row)
    result: list[dict[str, Any]] = []
    for key, values in sorted(groups.items()):
        if len(values) != 8:
            raise HeldOutExecutionError(f"expected eight paired seeds for {key}")
        neural = sum(bool(row["neural_expected_direction"]) for row in values)
        physical = sum(bool(row["physical_expected_direction"]) for row in values)
        bounded = all(bool(row["bounded"]) for row in values)
        result.append(
            {
                "topology_variant": key[0],
                "member_id": key[1],
                "side": key[2],
                "neural_positive_pairs": neural,
                "physical_positive_pairs": physical,
                "bounded_all_pairs": bounded,
                "primary_neural_pass": neural >= threshold and bounded,
                "secondary_physical_support": physical >= threshold and bounded,
            }
        )
    return result


def _analyse(rows: Sequence[Mapping[str, Any]], protocol: Mapping[str, Any]) -> dict[str, Any]:
    pairs = _pair_outcomes(rows)
    threshold = int(protocol["replication"]["minimum_directionally_consistent_pairs"])
    summaries = _member_side_summary(pairs, threshold)
    canonical = [row for row in summaries if row["topology_variant"] == "canonical"]
    canonical_fraction = {
        side: sum(row["primary_neural_pass"] for row in canonical if row["side"] == side)
        / max(1, sum(row["side"] == side for row in canonical))
        for side in ("left", "right")
    }
    recalibrated_comparisons: list[dict[str, Any]] = []
    for seed in (81701, 81702, 81703, 81704):
        variant = f"rewire-{seed}-recalibrated"
        for side in ("left", "right"):
            values = [row for row in summaries if row["topology_variant"] == variant and row["side"] == side]
            passed = sum(row["primary_neural_pass"] for row in values)
            denominator = len(values)
            fraction = passed / denominator
            recalibrated_comparisons.append(
                {
                    "rewire_seed": seed,
                    "side": side,
                    "canonical_numerator": int(round(canonical_fraction[side] * len(canonical) / 2)),
                    "canonical_denominator": len(canonical) // 2,
                    "control_numerator": passed,
                    "control_denominator": denominator,
                    "canonical_fraction": canonical_fraction[side],
                    "control_fraction": fraction,
                    "canonical_strictly_exceeds_control": canonical_fraction[side] > fraction,
                }
            )
    frozen_superiority: list[dict[str, Any]] = []
    pair_index = {
        (row["topology_variant"], row["member_id"], row["side"], row["trial_seed"]): row
        for row in pairs
    }
    for seed in (81701, 81702, 81703, 81704):
        for row in [item for item in canonical]:
            wins = 0
            for trial_seed in protocol["replication"]["paired_trial_seeds"]:
                base = pair_index[("canonical", row["member_id"], row["side"], int(trial_seed))]
                control = pair_index[(f"rewire-{seed}-frozen", row["member_id"], row["side"], int(trial_seed))]
                event_present = int(base["event_motor_bodies"]) > 0
                graded_present = int(base["graded_motor_bodies"]) > 0
                wins += int(
                    (not event_present or float(base["event_count_effect"]) > float(control["event_count_effect"]))
                    and (
                        not graded_present
                        or float(base["graded_integral_effect"]) > float(control["graded_integral_effect"])
                    )
                )
            frozen_superiority.append(
                {
                    "rewire_seed": seed,
                    "member_id": row["member_id"],
                    "side": row["side"],
                    "canonical_favored_pairs": wins,
                    "pass": wins >= threshold,
                }
            )
    all_primary = all(row["primary_neural_pass"] for row in canonical)
    all_physical = all(row["secondary_physical_support"] for row in canonical)
    none_primary = not any(row["primary_neural_pass"] for row in canonical)
    topology_specific = all(row["pass"] for row in frozen_superiority) and all(
        row["canonical_strictly_exceeds_control"] for row in recalibrated_comparisons
    )
    if all_primary and all_physical and topology_specific:
        disposition = "robust_positive"
    elif none_primary:
        disposition = "mechanism_limited_ambiguous_no_canonical_primary_pass"
    elif all_primary and not all_physical:
        disposition = "mechanism_limited_ambiguous_neural_without_physical_support"
    else:
        disposition = "member_conditioned_ambiguous"
    return {
        "paired_trials": len(pairs),
        "member_side_summaries": summaries,
        "canonical": {
            "member_side_rows": len(canonical),
            "primary_pass_rows": sum(row["primary_neural_pass"] for row in canonical),
            "physical_support_rows": sum(row["secondary_physical_support"] for row in canonical),
            "bounded_rows": sum(row["bounded_all_pairs"] for row in canonical),
            "pass_fraction_by_side": canonical_fraction,
        },
        "frozen_parameter_rewire_superiority": frozen_superiority,
        "same_recipe_recalibrated_comparisons": recalibrated_comparisons,
        "topology_specific": topology_specific,
        "disposition": disposition,
    }


def run_execution(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    run_root: Path = RUN_ROOT,
    worker_index: int | None = None,
    worker_count: int = 1,
    shards_only: bool = False,
    execute_groups: bool = True,
) -> dict[str, Any]:
    campaign = _load_yaml(campaign_path)
    paths = _verify_frozen_inputs(campaign)
    protocol = _load_yaml(paths["protocol_v2"])
    base_protocol = _load_yaml(paths["base_protocol_v1"])
    if protocol["execution_gate"]["outcome_rows_present"] != 0:
        raise HeldOutExecutionError("protocol v2 was not outcome-free before execution")
    schedule = pd.read_csv(paths["schedule"])
    if len(schedule) != 3072 or schedule.scenario_id.nunique() != 3072:
        raise HeldOutExecutionError("v2 schedule accounting drift")
    if set(schedule.outcome_status) != {"not_executed_outcome_blind_schedule_lock"}:
        raise HeldOutExecutionError("schedule already contains an outcome status")

    print("[1/7] Frozen v2 protocol, 3,072-row schedule and zero-outcome lineage verified", flush=True)
    canonical_bundle = _load_bundle(paths["canonical_fh07b_campaign"], paths["canonical_fh07b_result"])
    control_bundles = {
        seed: _load_bundle(
            ROOT / f"runs/calibration/first-held-out-control-recalibration-v1/rewire-{seed}/fh07b-campaign.yaml",
            ROOT / f"runs/calibration/first-held-out-control-recalibration-v1/rewire-{seed}/fh07b-result.yaml",
        )
        for seed in (81701, 81702, 81703, 81704)
    }
    preflight = _load_yaml(paths["preflight_v1"])
    canonical_cone = sparse.load_npz(ROOT / preflight["canonical_graph"]["artifact"]).tocsr()
    replacement_by_seed = {
        int(row["rewire_seed"]): sparse.load_npz(ROOT / row["artifact"]).tocsr()
        for row in preflight["topology_controls"]
        if row["control_family"] == "frozen_parameter_rewire"
    }
    print("[2/7] Canonical and four recalibrated lineages reconstructed; control graphs verified", flush=True)

    run_root.mkdir(parents=True, exist_ok=True)
    shard_root = run_root / "outcomes"
    shard_root.mkdir(parents=True, exist_ok=True)
    groups = list(schedule.groupby(["topology_variant", "member_id"], sort=False))
    started = time.perf_counter()
    if worker_index is not None:
        assigned_group_indices = set(worker_group_indices(len(groups), worker_index, worker_count))
        import torch

        torch.set_num_threads(1)
        print(
            f"[WORKER {worker_index + 1}/{worker_count}] assigned groups "
            f"{worker_index + 1}, {worker_index + 1 + worker_count}, ...",
            flush=True,
        )
    if execute_groups:
      with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=False) as loop:
        for group_index, ((topology_variant, member_id), group) in enumerate(groups, start=1):
            if worker_index is not None and group_index - 1 not in assigned_group_indices:
                continue
            safe_member = hashlib.sha256(str(member_id).encode("utf-8")).hexdigest()[:16]
            shard = shard_root / str(topology_variant) / f"{safe_member}.jsonl"
            if shard.is_file():
                print(f"  [{group_index:03d}/{len(groups):03d}] RESUME {topology_variant} / {member_id}", flush=True)
                continue
            seed_value = group.rewire_seed.dropna()
            rewire_seed = int(seed_value.iloc[0]) if len(seed_value) else None
            family = str(group.topology_family.iloc[0])
            bundle = control_bundles[rewire_seed] if family == "same_recipe_recalibrated_rewire" else canonical_bundle
            if str(member_id) not in bundle["physical_rows"]:
                raise HeldOutExecutionError(f"member missing from frozen FH-07b result: {topology_variant}/{member_id}")
            physical_row = bundle["physical_rows"][str(member_id)]
            neural_id = str(physical_row["neural_parent_row_id"])
            neural_row = bundle["neural_rows"][neural_id]
            profile = physical_row["physical_profile"]
            context = fh07b._neural_row_context(
                neural_row,
                str(profile["source_path_id"]),
                bundle["parent_campaign"],
                bundle["verified"],
            )
            if rewire_seed is not None:
                context = dict(context)
                context["graph"] = replace_cone_recurrence(
                    context["graph"],
                    source_count=int(context["source_count"]),
                    canonical_cone=canonical_cone,
                    replacement_cone=replacement_by_seed[rewire_seed],
                )
            documents = {
                "campaign": bundle["campaign"],
                "motor_temporal": bundle["documents"]["motor_temporal"],
                "motor_slow": bundle["documents"]["motor_slow"],
                "motor_bridge": bundle["documents"]["motor_bridge"],
            }
            outcomes: list[dict[str, Any]] = []
            for item in group.to_dict(orient="records"):
                episode = _run_episode(
                    loop,
                    context=context,
                    neural_row=neural_row,
                    physical_profile=profile,
                    documents=documents,
                    source_families=bundle["source_families"],
                    routes=bundle["routes"],
                    protocol={"stimulus": base_protocol["stimulus"]},
                    execution=campaign["execution"],
                    side=str(item["side"]),
                    condition=str(item["condition"]),
                    trial_seed=int(item["trial_seed"]),
                )
                outcomes.append(
                    {
                        "scenario_id": str(item["scenario_id"]),
                        "topology_variant": str(topology_variant),
                        "topology_family": family,
                        "rewire_seed": rewire_seed,
                        "member_id": str(member_id),
                        **episode,
                    }
                )
            shard.parent.mkdir(parents=True, exist_ok=True)
            with shard.open("x", encoding="utf-8", newline="\n") as stream:
                for outcome in outcomes:
                    stream.write(json.dumps(outcome, sort_keys=True, allow_nan=False) + "\n")
            elapsed = time.perf_counter() - started
            print(
                f"  [{group_index:03d}/{len(groups):03d}] DONE "
                f"worker={worker_index + 1 if worker_index is not None else 1} "
                f"{topology_variant} / {member_id} "
                f"({len(outcomes)} episodes; {elapsed:.1f}s)",
                flush=True,
            )

    if shards_only:
        completed = len(list(shard_root.rglob("*.jsonl")))
        print(
            f"[WORKER {worker_index + 1 if worker_index is not None else 1}] "
            f"shard phase complete; global shards now {completed}/{len(groups)}",
            flush=True,
        )
        return {"worker_index": worker_index, "global_complete_shards": completed}

    print("[3/7] Loading append-only outcome shards and enforcing exhaustive accounting", flush=True)
    outcomes: list[dict[str, Any]] = []
    for shard in sorted(shard_root.rglob("*.jsonl")):
        outcomes.extend(json.loads(line) for line in shard.read_text(encoding="utf-8").splitlines() if line)
    if len(outcomes) != 3072 or len({row["scenario_id"] for row in outcomes}) != 3072:
        raise HeldOutExecutionError(f"outcome accounting incomplete: {len(outcomes)}/3072")
    expected_ids = set(schedule.scenario_id.astype(str))
    if {row["scenario_id"] for row in outcomes} != expected_ids:
        raise HeldOutExecutionError("outcome scenario IDs differ from the locked schedule")
    print("[4/7] Applying the locked paired sign, physical-support and topology-control rules", flush=True)
    analysis = _analyse(outcomes, base_protocol)
    wall_seconds = time.perf_counter() - started
    outcome_manifest = {
        "rows": len(outcomes),
        "unique_scenarios": len(expected_ids),
        "shards": len(list(shard_root.rglob("*.jsonl"))),
        "semantic_sha256": _canonical_hash(outcomes),
    }
    semantic_payload = {
        "campaign_id": campaign["id"],
        "frozen_input_sha256": {name: _sha256(path) for name, path in paths.items()},
        "outcome_manifest": outcome_manifest,
        "analysis": analysis,
    }
    semantic_hash = _canonical_hash(semantic_payload)
    result = {
        "schema_version": 1,
        "id": "runner_result.first_held_out_execution.v2",
        "campaign_id": campaign["id"],
        "protocol_id": protocol["id"],
        "status": f"complete_{analysis['disposition']}",
        "completed_at": datetime.now(UTC).isoformat(),
        "command": "first_held_out_execution_v2.bat",
        "claim_label": campaign["claim_label"],
        "frozen_input_sha256": semantic_payload["frozen_input_sha256"],
        "outcome_manifest": outcome_manifest,
        "analysis": analysis,
        "members_ranked": False,
        "parameter_values_changed": 0,
        "protocol_closed_after_inspection": True,
        "wall_seconds": wall_seconds,
        "semantic_result_sha256": semantic_hash,
        "next_action": campaign["next_action_by_disposition"][analysis["disposition"]],
    }
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.first_held_out_execution.v2",
        "protocol_id": protocol["id"],
        "status": analysis["disposition"],
        "primary_class": "evaluation_only",
        "protocol_executed": True,
        "outcome_rows_consumed": len(outcomes),
        "members_ranked": False,
        "parameter_values_changed": 0,
        "result_ref": "calibration/runner/first-held-out-execution-v2.yaml",
        "semantic_result_sha256": semantic_hash,
        "summary": analysis,
        "interpretation_constraints": base_protocol["mechanism_coverage"]["interpretation_constraints"],
        "next_action": result["next_action"],
    }
    print("[5/7] Writing compact immutable result and evaluation records", flush=True)
    _write_yaml(result_path, result)
    _write_yaml(evaluation_path, evaluation)
    print(
        f"[6/7] RESULT {analysis['disposition']} | canonical primary "
        f"{analysis['canonical']['primary_pass_rows']}/22 | physical "
        f"{analysis['canonical']['physical_support_rows']}/22 | topology_specific="
        f"{analysis['topology_specific']}",
        flush=True,
    )
    print(f"[7/7] semantic_sha256={semantic_hash} wall={wall_seconds:.1f}s", flush=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute the immutable FH-09 held-out v2 protocol once")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--worker-index", type=int)
    parser.add_argument("--worker-count", type=int, default=1)
    parser.add_argument("--shards-only", action="store_true")
    args = parser.parse_args(argv)
    if args.worker_index is not None:
        run_execution(
            campaign_path=args.campaign,
            worker_index=args.worker_index,
            worker_count=args.worker_count,
            shards_only=args.shards_only,
        )
        return 0

    campaign = _load_yaml(args.campaign)
    parallel_workers = int(campaign["execution"].get("parallel_workers", 1))
    if parallel_workers > 1:
        env = os.environ.copy()
        env.update({"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "the_fly_matrix.first_held_out_execution",
                    "--campaign",
                    str(args.campaign),
                    "--worker-index",
                    str(index),
                    "--worker-count",
                    str(parallel_workers),
                    "--shards-only",
                ],
                cwd=ROOT,
                env=env,
            )
            for index in range(parallel_workers)
        ]
        failures = [process.wait() for process in processes]
        if any(failures):
            raise HeldOutExecutionError(f"parallel workers failed: {failures}")
        run_execution(campaign_path=args.campaign, execute_groups=False)
    else:
        run_execution(campaign_path=args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

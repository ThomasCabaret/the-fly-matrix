from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml

from .embodied_measurement_contract import _episode_metrics, _model_measurement_metadata, paired_recovery_metrics
from .front_leg_coupled_identifiability import _functional_class_map
from .front_leg_integrated_lineage import _fh05_runtime_context, _load_yaml, _verify_inputs
from .front_leg_neutral_neural_regime import (
    _constants,
    _paired_schedules,
    build_pairwise_profiles,
    pairwise_coverage,
)
from .ledger import ROOT
from .neutral_embodied_declared_closed_loop_sentinel import (
    _MotorTwitch,
    _front_leg_anchor_ids,
    _internal_angle_deg,
    _source_functions,
)
from .neutral_embodied_feedback_identifiability import _record_physical_frame
from .runtime import FlyBodyPhysicsLoop
from .typed_hybrid_runtime import EVENT, GRADED, TorchTypedHybridRuntime


CAMPAIGN_PATH = ROOT / "calibration/campaigns/front-leg-neutral-embodied-regime-v0.yaml"
RESULT_PATH = ROOT / "calibration/runner/front-leg-neutral-embodied-regime-v0.yaml"
EVALUATION_PATH = ROOT / "calibration/evaluations/front-leg-neutral-embodied-regime-v0.yaml"
PARAMETER_SET_PATH = ROOT / "calibration/parameter_sets/front-leg-neutral-embodied-regime-v0.yaml"


class NeutralEmbodiedRegimeError(RuntimeError):
    pass


class DirectMotorGuardError(NeutralEmbodiedRegimeError):
    def __init__(self, observed_abs_max: float, allowed_abs_max: float):
        super().__init__(
            f"live command violates direct-MOTOR guard: {observed_abs_max} > {allowed_abs_max}"
        )
        self.observed_abs_max = float(observed_abs_max)
        self.allowed_abs_max = float(allowed_abs_max)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _verify_frozen_inputs(campaign: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
    hashes: dict[str, str] = {}
    documents: dict[str, Any] = {}
    for name, spec in campaign["frozen_inputs"].items():
        path = ROOT / str(spec["path"])
        if not path.is_file():
            raise NeutralEmbodiedRegimeError(f"missing frozen input {name}: {path}")
        observed = _sha256(path)
        if observed != str(spec["sha256"]):
            raise NeutralEmbodiedRegimeError(
                f"frozen input hash drift for {name}: {observed} != {spec['sha256']}"
            )
        hashes[str(name)] = observed
        if path.suffix.lower() in {".yaml", ".yml"}:
            documents[str(name)] = _load_yaml(path)
    neural = documents["fh07a_result"]
    if neural.get("semantic_result_sha256") != campaign["frozen_inputs"]["fh07a_result"].get(
        "semantic_sha256"
    ):
        raise NeutralEmbodiedRegimeError("FH-07a semantic hash drift")
    accepted = list(map(str, neural.get("accepted_row_ids", [])))
    if len(accepted) != int(campaign["budget"]["expected_neural_parent_rows"]):
        raise NeutralEmbodiedRegimeError("FH-07a accepted-row count drift")
    return hashes, documents


def _selector_index(selector: str, count: int) -> int:
    if count <= 0:
        raise NeutralEmbodiedRegimeError("cannot select from an empty finite envelope")
    return {"low": 0, "middle": count // 2, "high": count - 1}[selector]


class _MotorTonic:
    def __init__(self, tau_s: float, delay_s: float, gain_uN_per_hz: float, dt_s: float, bridge: float):
        delay_float = delay_s / dt_s
        self.delay_steps = int(round(delay_float))
        if not math.isclose(delay_float, self.delay_steps, abs_tol=1e-9, rel_tol=0.0):
            raise NeutralEmbodiedRegimeError("slow delay is not an integer number of native steps")
        self.decay = math.exp(-dt_s / tau_s)
        self.increment_hz = 1.0 / tau_s
        self.gain_uN_per_hz = float(gain_uN_per_hz)
        self.bridge = float(bridge)
        self.state = 0.0
        self.queue = [0] * max(1, self.delay_steps)
        self.cursor = 0

    def step(self, event_count: int) -> tuple[float, float]:
        if self.delay_steps == 0:
            delivered = int(event_count)
        else:
            delivered = self.queue[self.cursor]
            self.queue[self.cursor] = int(event_count)
            self.cursor = (self.cursor + 1) % self.delay_steps
        self.state = self.state * self.decay + delivered * self.increment_hz
        force = self.state * self.gain_uN_per_hz
        return float(force), float(force * self.bridge)


def _motor_filter_factory(
    motor_class: str,
    selector: str,
    bridge: float,
    temporal: Mapping[str, Any],
    slow: Mapping[str, Any],
    dt_s: float,
) -> Any:
    if motor_class in {"fast", "intermediate"}:
        class_id = "fast_81A07" if motor_class == "fast" else "intermediate_22A08"
        row = temporal["class_results"][class_id]
        envelope = row["near_optimal_envelope"]
        fraction = {"low": 0.0, "middle": 0.5, "high": 1.0}[selector]
        rise = envelope["rise_time_s"][0] + fraction * (
            envelope["rise_time_s"][1] - envelope["rise_time_s"][0]
        )
        decay = envelope["decay_time_s"][0] + fraction * (
            envelope["decay_time_s"][1] - envelope["decay_time_s"][0]
        )
        force = float(row["observed_single_spike_summary"]["peak_force_uN_median"])
        return _MotorTwitch(force, float(rise), float(decay), dt_s, bridge)
    candidates = slow["slow_result"]["near_optimal_envelope"]["retained_candidates"]
    candidate = candidates[_selector_index(selector, len(candidates))]
    return _MotorTonic(
        float(candidate["tau_s"]),
        float(candidate["delay_s"]),
        float(candidate["gain_uN_per_hz"]),
        dt_s,
        bridge,
    )


def _neural_row_context(
    row: Mapping[str, Any],
    source_path_id: str,
    parent_campaign: Mapping[str, Any],
    verified: Mapping[str, Any],
) -> dict[str, Any]:
    fh05 = verified["documents"]["coupled_campaign"]
    anchor = next(item for item in fh05["execution_anchors"] if item["anchor_id"] == row["anchor_id"])
    campaign = copy.deepcopy(parent_campaign)
    witness = campaign["execution_witness"]
    witness["sensory"]["routing_profile_id"] = anchor["routing_profile_id"]
    witness["sensory"]["native_profile_id"] = anchor["native_profile_id"]
    witness["sensory"]["source_path_id"] = source_path_id
    witness["central_basal"]["member_id"] = f"{anchor['anchor_id']}__owner_00"
    witness["central_basal"]["source_native_mirror"] = row["source_native_mirror"]
    context = _fh05_runtime_context(campaign, verified)
    context["constants"] = _constants(
        _load_yaml(CAMPAIGN_PATH)["neural_execution_fixture"], row["profile"]
    )
    return context


def _route_map(routes: pd.DataFrame, motor_body_ids: Sequence[int], selector: str) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for body_id in motor_body_ids:
        candidates = routes.loc[routes.source_body_id.astype(int).eq(int(body_id))].sort_values(
            ["target_actuator_id", "parameter_id"]
        )
        if candidates.empty:
            raise NeutralEmbodiedRegimeError(f"motor body {body_id} has no actuator candidate")
        item = candidates.iloc[_selector_index(selector, len(candidates))]
        selected.append(
            {
                "body_id": int(body_id),
                "target_actuator_id": int(item["target_actuator_id"]),
                "target_actuator_name": str(item["target_actuator_name"]),
                "parameter_id": str(item["parameter_id"]),
            }
        )
    return selected


def _perturbation_address(loop: FlyBodyPhysicsLoop, perturbation: Mapping[str, Any]) -> int:
    import mujoco

    joint_id = int(
        mujoco.mj_name2id(
            loop.simulation.mj_model,
            mujoco.mjtObj.mjOBJ_JOINT,
            str(perturbation["joint_name"]),
        )
    )
    if joint_id < 0:
        raise NeutralEmbodiedRegimeError("declared generic perturbation joint is absent")
    return int(loop.simulation.mj_model.jnt_dofadr[joint_id])


def _episode_from_commands(
    commands: np.ndarray,
    protocol: Mapping[str, Any],
    perturbation: Mapping[str, Any] | None,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    import mujoco

    records: dict[str, list[Any]] = {}
    with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=False) as loop:
        loop.reset()
        metadata = _model_measurement_metadata(loop)
        mujoco.mj_forward(loop.simulation.mj_model, loop.simulation.mj_data)
        if commands.shape != (int(protocol["steps"]), len(loop.actuator_names)):
            raise NeutralEmbodiedRegimeError("frozen command matrix shape drift")
        if not np.isfinite(commands).all() or float(np.max(np.abs(commands), initial=0.0)) > float(
            protocol["direct_motor_abs_max"]
        ):
            raise NeutralEmbodiedRegimeError("frozen commands violate direct-MOTOR guard")
        address = _perturbation_address(loop, perturbation) if perturbation else -1
        for step, command in enumerate(commands):
            if perturbation is not None and step == int(protocol["perturbation_step"]):
                loop.simulation.mj_data.qvel[address] += float(perturbation["delta_rad_s"])
                mujoco.mj_forward(loop.simulation.mj_model, loop.simulation.mj_data)
            addressed = loop.actuator_interface.step(command)
            loop.simulation.set_actuator_inputs("flybody", loop.actuator_type, addressed.values)
            loop.simulation.step()
            if (step + 1) % int(protocol["record_stride"]) == 0:
                for key, value in _record_physical_frame(loop, metadata).items():
                    records.setdefault(key, []).append(value)
    episode = {key: np.asarray(value) for key, value in records.items()}
    if not all(np.isfinite(value).all() for value in episode.values()):
        raise NeutralEmbodiedRegimeError("frozen-command physical episode is non-finite")
    return episode, metadata


def _active_episode(
    context: Mapping[str, Any],
    neural_row: Mapping[str, Any],
    profile: Mapping[str, Any],
    campaign: Mapping[str, Any],
    documents: Mapping[str, Any],
    source_families: np.ndarray,
    routes: pd.DataFrame,
    perturbation: Mapping[str, Any] | None,
    seed: int,
) -> tuple[dict[str, np.ndarray], dict[str, Any], np.ndarray, dict[str, Any]]:
    import mujoco
    import torch

    protocol = campaign["physical_protocol"]
    steps = int(protocol["steps"])
    dt_s = float(context["constants"].dt_ms) / 1000.0
    fixture = dict(campaign["neural_execution_fixture"])
    fixture.update({"steps": steps, "pulse_start_step": 0, "pulse_stop_step": steps})
    schedules = _paired_schedules(
        assignment=context["assignment"],
        source_count=int(context["source_count"]),
        source_families=source_families,
        feco_indices=context["feco_indices"],
        profile=neural_row["profile"],
        source_profile=str(context["source_profile"]),
        fixture=fixture,
        seed=seed,
    )
    basal_event = schedules[2]
    basal_graded = schedules[3]
    runtime = TorchTypedHybridRuntime(
        context["graph"], context["assignment"], context["constants"], str(protocol["device"])
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
    sides = [str(value) for value in context["feco"].side]
    motor_body_ids = list(map(int, context["motor"].body_id))
    route_map = _route_map(routes, motor_body_ids, str(profile["route_selector"]))
    gains = documents["motor_bridge"]["conditional_gain_envelope"]["candidate_gains_command_per_uN"]
    bridge = float(gains[_selector_index(str(profile["bridge_selector"]), len(gains))])
    filters = [
        _motor_filter_factory(
            str(profile["motor_class"]),
            str(profile["temporal_selector"]),
            bridge,
            documents["motor_temporal"],
            documents["motor_slow"],
            dt_s,
        )
        for _ in motor_body_ids
    ]
    phase = (np.arange(len(context["feco"]), dtype=np.float64) * 0.4142135623730951) % 1.0
    feco_ratio = float(neural_row["profile"]["feco_native_amplitude_ratio"])
    records: dict[str, list[Any]] = {}
    command_trace: list[np.ndarray] = []
    motor_events = 0
    source_nonzero_steps = 0
    with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=False) as loop:
        loop.reset()
        metadata = _model_measurement_metadata(loop)
        mujoco.mj_forward(loop.simulation.mj_model, loop.simulation.mj_data)
        if not math.isclose(
            float(loop.simulation.mj_model.opt.timestep), dt_s, rel_tol=0.0, abs_tol=1e-12
        ):
            raise NeutralEmbodiedRegimeError("neural and physical timesteps differ")
        for route in route_map:
            if loop.actuator_names[route["target_actuator_id"]] != route["target_actuator_name"]:
                raise NeutralEmbodiedRegimeError("motor route address drift")
        address = _perturbation_address(loop, perturbation) if perturbation else -1
        anchors = _front_leg_anchor_ids(loop)
        previous = {
            "L": _internal_angle_deg(loop.simulation.mj_data, anchors["l"]),
            "R": _internal_angle_deg(loop.simulation.mj_data, anchors["r"]),
        }
        for step in range(steps):
            if perturbation is not None and step == int(protocol["perturbation_step"]):
                loop.simulation.mj_data.qvel[address] += float(perturbation["delta_rad_s"])
                mujoco.mj_forward(loop.simulation.mj_model, loop.simulation.mj_data)
            angles = {
                "L": _internal_angle_deg(loop.simulation.mj_data, anchors["l"]),
                "R": _internal_angle_deg(loop.simulation.mj_data, anchors["r"]),
            }
            velocities = {side: (angles[side] - previous[side]) / dt_s for side in ("L", "R")}
            previous = angles
            functions = {
                side: _source_functions(angles[side], velocities[side], source_functions)
                for side in ("L", "R")
            }
            activity = np.asarray(
                [
                    functions[side][
                        {"claw": "claw_position", "club": "club_vibration_and_speed", "hook": "hook_flexion_direction"}[
                            functional_class
                        ]
                    ]
                    for side, functional_class in zip(sides, functional_classes, strict=True)
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
                    phase[index] += (
                        activity[index]
                        * float(fixture["feco_event_rate_hz"])
                        * feco_ratio
                        * dt_s
                    )
                    if phase[index] >= 1.0:
                        forced.append(int(node_index))
                        phase[index] %= 1.0
                else:
                    external[int(node_index)] = (
                        activity[index] * float(fixture["feco_graded_drive"]) * feco_ratio
                    )
            with torch.inference_mode():
                runtime.step(forced_event_indices=forced, external_graded=external)
            refractory = runtime.refractory[context["motor_indices"]].detach().cpu().numpy()
            events = refractory == runtime.refractory_steps
            motor_events += int(np.count_nonzero(events))
            command = np.zeros(len(loop.actuator_names), dtype=np.float64)
            for event, transfer, route in zip(events, filters, route_map, strict=True):
                _force, scalar = transfer.step(int(event))
                command[route["target_actuator_id"]] += scalar
            command_abs_max = float(np.max(np.abs(command), initial=0.0))
            if command_abs_max > float(protocol["direct_motor_abs_max"]):
                raise DirectMotorGuardError(command_abs_max, float(protocol["direct_motor_abs_max"]))
            addressed = loop.actuator_interface.step(command)
            command_trace.append(addressed.values.copy())
            loop.simulation.set_actuator_inputs("flybody", loop.actuator_type, addressed.values)
            loop.simulation.step()
            if (step + 1) % int(protocol["record_stride"]) == 0:
                for key, value in _record_physical_frame(loop, metadata).items():
                    records.setdefault(key, []).append(value)
    episode = {key: np.asarray(value) for key, value in records.items()}
    commands = np.asarray(command_trace, dtype=np.float64)
    if not all(np.isfinite(value).all() for value in episode.values()) or not np.isfinite(commands).all():
        raise NeutralEmbodiedRegimeError("live embodied episode is non-finite")
    return episode, metadata, commands, {
        "motor_events": motor_events,
        "source_nonzero_steps": source_nonzero_steps,
        "command_nonzero_steps": int(np.count_nonzero(np.any(commands != 0.0, axis=1))),
        "command_abs_max": float(np.max(np.abs(commands), initial=0.0)),
        "route_parameter_ids": [route["parameter_id"] for route in route_map],
    }


def _max_delta(left: Mapping[str, np.ndarray], right: Mapping[str, np.ndarray], keys: Sequence[str]) -> float:
    return max(
        float(np.max(np.abs(np.asarray(left[key]) - np.asarray(right[key])), initial=0.0)) for key in keys
    )


def _failure_counts(episode: Mapping[str, np.ndarray], metadata: Mapping[str, Any]) -> dict[str, int]:
    masks = _episode_metrics(episode, metadata)["failure_masks"]
    return {key: int(value) for key, value in masks.items() if key.endswith("_frames")}


def _classify(
    baseline: Mapping[str, np.ndarray],
    replay: Mapping[str, np.ndarray],
    opened: Mapping[str, np.ndarray],
    closed: Mapping[str, np.ndarray],
    baseline_commands: np.ndarray,
    closed_commands: np.ndarray,
    metadata: Mapping[str, Any],
    protocol: Mapping[str, Any],
    acceptance: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    frame = int(protocol["perturbation_step"]) // int(protocol["record_stride"])
    open_recovery = paired_recovery_metrics(baseline, opened, frame)
    closed_recovery = paired_recovery_metrics(baseline, closed, frame)
    replay_error = _max_delta(baseline, replay, ("qpos", "qvel", "applied_commands"))
    perturbation_peak = float(open_recovery["qvel"]["peak_l2"])
    command_adaptation = float(np.max(np.abs(closed_commands - baseline_commands), initial=0.0))
    state_gap = _max_delta(opened, closed, ("qpos", "qvel"))
    open_failures = _failure_counts(opened, metadata)
    closed_failures = _failure_counts(closed, metadata)
    tolerance = float(acceptance["closed_vs_open_relative_tolerance"])
    absolute = float(acceptance["closed_vs_open_absolute_tolerance"])
    checks = {
        "all_finite": all(
            np.isfinite(value).all() for episode in (baseline, replay, opened, closed) for value in episode.values()
        ),
        "unperturbed_replay_exact": replay_error <= float(acceptance["replay_max_abs_error"]),
        "generic_perturbation_detected": perturbation_peak >= float(acceptance["perturbation_qvel_peak_min"]),
        "feedback_command_adapts": command_adaptation >= float(acceptance["command_adaptation_abs_min"]),
        "feedback_changes_physics": state_gap >= float(acceptance["closed_open_state_gap_abs_min"]),
        "closed_qpos_not_amplified": float(closed_recovery["qpos"]["final_l2"])
        <= float(open_recovery["qpos"]["final_l2"]) * (1.0 + tolerance) + absolute,
        "closed_qvel_not_amplified": float(closed_recovery["qvel"]["final_l2"])
        <= float(open_recovery["qvel"]["final_l2"]) * (1.0 + tolerance) + absolute,
        "closed_failure_masks_not_worse": all(
            closed_failures.get(key, 0) <= value for key, value in open_failures.items()
        ),
    }
    return {
        "accepted": all(checks.values()),
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }, {
        "replay_max_abs_error": replay_error,
        "perturbation_qvel_peak_l2": perturbation_peak,
        "feedback_command_adaptation_abs_max": command_adaptation,
        "closed_open_state_gap_abs_max": state_gap,
        "open_recovery": open_recovery,
        "closed_recovery": closed_recovery,
        "open_failure_masks": open_failures,
        "closed_failure_masks": closed_failures,
    }


def run_gate(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    parameter_set_path: Path = PARAMETER_SET_PATH,
) -> dict[str, Any]:
    campaign = _load_yaml(campaign_path)
    if campaign.get("behavior_targets") or campaign.get("topology_changes_allowed") is not False:
        raise NeutralEmbodiedRegimeError("FH-07b must remain behavior-naive and topology-frozen")
    frozen_hashes, documents = _verify_frozen_inputs(campaign)
    parent_campaign = documents["fh06_campaign"]
    verified = _verify_inputs(parent_campaign)
    neural_rows = {row["row_id"]: row for row in documents["fh07a_result"]["rows"]}
    parent_ids = list(map(str, documents["fh07a_result"]["accepted_row_ids"]))
    factors = campaign["physical_factor_levels"]
    profiles = build_pairwise_profiles(factors)
    coverage = pairwise_coverage(profiles, factors)
    if len(profiles) != int(campaign["budget"]["expected_pairwise_profiles"]):
        raise NeutralEmbodiedRegimeError("physical pairwise profile count drift")
    schedule = [
        {**profile, "neural_parent_row_id": parent_ids[index % len(parent_ids)]}
        for index, profile in enumerate(profiles)
    ]
    if set(parent_ids) != {row["neural_parent_row_id"] for row in schedule}:
        raise NeutralEmbodiedRegimeError("not every retained FH-07a row is scheduled")
    print(
        f"[1/7] Physical pairwise cover: {len(schedule)} composites, all {len(parent_ids)} FH-07a parents",
        flush=True,
    )
    print("[2/7] Verifying frozen mechanics, actuator, neural and motor dependencies", flush=True)
    fh05 = verified["documents"]["coupled_campaign"]
    from .front_leg_coupled_identifiability_execution import _verify_campaign as verify_fh05

    fh05_paths = verify_fh05(fh05)
    source_rows = pd.read_csv(fh05_paths["source_terminals"]).sort_values("body_id")
    source_families = source_rows.family_id.astype(str).to_numpy()
    routes = pd.read_parquet(ROOT / campaign["frozen_inputs"]["motor_routes"]["path"])
    perturbations = {row["perturbation_id"]: row for row in campaign["generic_perturbations"]}
    cache: dict[tuple[str, str], dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    accepted_ids: list[str] = []
    started = time.perf_counter()
    print("[3/7] Executing baseline/live, exact replay, frozen-open and perturbed-live branches", flush=True)
    for index, profile in enumerate(schedule):
        parent_id = str(profile["neural_parent_row_id"])
        source_path = str(profile["source_path_id"])
        key = (parent_id, source_path)
        if key not in cache:
            cache[key] = _neural_row_context(neural_rows[parent_id], source_path, parent_campaign, verified)
        context = cache[key]
        perturbation = perturbations[str(profile["perturbation_id"])]
        try:
            baseline, metadata, commands, baseline_diag = _active_episode(
                context,
                neural_rows[parent_id],
                profile,
                campaign,
                {
                    "motor_temporal": documents["motor_temporal"],
                    "motor_slow": documents["motor_slow"],
                    "motor_bridge": documents["motor_bridge"],
                },
                source_families,
                routes,
                None,
                int(campaign["physical_protocol"]["seed"]) + index * 104729,
            )
        except DirectMotorGuardError as error:
            row_id = f"physical_{index:03d}__{parent_id}"
            rows.append(
                {
                    "row_id": row_id,
                    "neural_parent_row_id": parent_id,
                    "physical_profile": {
                        key: value for key, value in profile.items() if key != "neural_parent_row_id"
                    },
                    "perturbation": perturbation,
                    "disposition": "blocked_preapplication_direct_motor_guard",
                    "metrics": {
                        "observed_command_abs_max": error.observed_abs_max,
                        "allowed_command_abs_max": error.allowed_abs_max,
                    },
                    "classification": {
                        "accepted": False,
                        "checks": {"direct_motor_guard": False},
                        "failed_checks": ["direct_motor_guard"],
                    },
                }
            )
            print(
                f"  [{index + 1:02d}/{len(schedule)}] BLOCKED direct-MOTOR guard "
                f"parent={parent_id} profile={profile['profile_id']}",
                flush=True,
            )
            continue
        replay, replay_metadata = _episode_from_commands(commands, campaign["physical_protocol"], None)
        opened, open_metadata = _episode_from_commands(commands, campaign["physical_protocol"], perturbation)
        closed, closed_metadata, closed_commands, closed_diag = _active_episode(
            context,
            neural_rows[parent_id],
            profile,
            campaign,
            {
                "motor_temporal": documents["motor_temporal"],
                "motor_slow": documents["motor_slow"],
                "motor_bridge": documents["motor_bridge"],
            },
            source_families,
            routes,
            perturbation,
            int(campaign["physical_protocol"]["seed"]) + index * 104729,
        )
        contracts = [
            item["model_contract"] for item in (metadata, replay_metadata, open_metadata, closed_metadata)
        ]
        if not all(item == contracts[0] for item in contracts[1:]):
            raise NeutralEmbodiedRegimeError("physical branch model contract drift")
        classification, metrics = _classify(
            baseline,
            replay,
            opened,
            closed,
            commands,
            closed_commands,
            metadata,
            campaign["physical_protocol"],
            campaign["acceptance"],
        )
        row_id = f"physical_{index:03d}__{parent_id}"
        row = {
            "row_id": row_id,
            "neural_parent_row_id": parent_id,
            "physical_profile": {key: value for key, value in profile.items() if key != "neural_parent_row_id"},
            "perturbation": perturbation,
            "disposition": "completed_four_branch_physical_probe",
            "baseline_chain": baseline_diag,
            "closed_chain": closed_diag,
            "metrics": metrics,
            "classification": classification,
        }
        rows.append(row)
        if classification["accepted"]:
            accepted_ids.append(row_id)
        print(
            f"  [{index + 1:02d}/{len(schedule)}] accepted={len(accepted_ids)} "
            f"parent={parent_id} profile={profile['profile_id']}",
            flush=True,
        )
    wall_seconds = time.perf_counter() - started
    print("[4/7] Accounting all physical branches and locked failure modes", flush=True)
    failure_counts: dict[str, int] = {}
    for row in rows:
        for reason in row["classification"]["failed_checks"]:
            failure_counts[reason] = failure_counts.get(reason, 0) + 1
    checks = {
        "pairwise_physical_factor_coverage_complete": bool(coverage["complete"]),
        "all_neural_parent_rows_executed": set(parent_ids)
        == {row["neural_parent_row_id"] for row in rows},
        "all_composites_accounted": len(rows) == len(schedule),
        "four_branches_per_guard_admitted_composite": all(
            row["disposition"]
            in {"completed_four_branch_physical_probe", "blocked_preapplication_direct_motor_guard"}
            for row in rows
        ),
        "mechanics_identical_across_branches": True,
        "no_named_behavior_exposure": campaign["behavior_targets"] == [],
        "no_topology_change": campaign["topology_changes_allowed"] is False,
        "no_reference_ranking": True,
    }
    if not all(checks.values()):
        raise NeutralEmbodiedRegimeError(f"FH-07b contract failed: {checks}")
    semantic_payload = {
        "campaign_id": campaign["id"],
        "frozen_input_sha256": frozen_hashes,
        "schedule": schedule,
        "coverage": coverage,
        "rows": rows,
        "accepted_row_ids": accepted_ids,
        "checks": checks,
    }
    semantic_hash = _canonical_hash(semantic_payload)
    status = (
        "accepted_nonempty_neutral_embodied_technical_ensemble_FH07_complete"
        if accepted_ids
        else "negative_no_embodied_regime_passes_replan_required"
    )
    result = {
        "schema_version": 1,
        "id": "runner_result.front_leg_neutral_embodied_regime.v0",
        "campaign_id": campaign["id"],
        "status": status,
        "completed_at": datetime.now(UTC).isoformat(),
        "command": "front_leg_neutral_embodied_regime.bat",
        "claim_label": campaign["claim_label"],
        "frozen_input_sha256": frozen_hashes,
        "design": {
            "physical_factor_profiles": len(profiles),
            "neural_parent_rows": len(parent_ids),
            "physical_composites": len(schedule),
            "physical_episode_branches_completed": 4
            * sum(row["disposition"] == "completed_four_branch_physical_probe" for row in rows),
            "physical_composites_blocked_preapplication": sum(
                row["disposition"] == "blocked_preapplication_direct_motor_guard" for row in rows
            ),
            "pairwise_coverage": coverage,
        },
        "physical_protocol": campaign["physical_protocol"],
        "acceptance": campaign["acceptance"],
        "rows": rows,
        "accepted_row_ids": accepted_ids,
        "accepted_rows": len(accepted_ids),
        "failure_counts": dict(sorted(failure_counts.items())),
        "checks": checks,
        "members_ranked": False,
        "reference_member_selected": False,
        "parameter_values_promoted": 0,
        "named_behavior_exposed": False,
        "wall_seconds": wall_seconds,
        "semantic_result_sha256": semantic_hash,
        "next_action": campaign["next_action_if_nonempty"] if accepted_ids else campaign["next_action_if_empty"],
    }
    parameter_set = {
        "schema_version": 1,
        "id": "parameters.front_leg_neutral_embodied_regime.v0",
        "title": "FH-07b unranked short-horizon embodied technical regime ensemble",
        "status": "accepted_technical_ensemble" if accepted_ids else "negative_no_member_promoted",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": semantic_hash,
        "parent_id": documents["fh07a_parameter_set"]["id"],
        "exact_member_ids": accepted_ids,
        "member_count": len(accepted_ids),
        "members_ranked": False,
        "selected_reference_member_id": None,
        "values_are_physiological": False,
        "body_outcomes_used_for_selection": True,
        "behavior_targets_exposed": [],
        "interpretation": campaign["parameter_set_interpretation"],
        "next_action": result["next_action"],
    }
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.front_leg_neutral_embodied_regime.v0",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "status": status,
        "claim_label": campaign["claim_label"],
        "accounting": {
            "scheduled_composites": len(rows),
            "accepted_composites": len(accepted_ids),
            "rejected_composites": len(rows) - len(accepted_ids),
            "all_fh07a_parents_covered": checks["all_neural_parent_rows_executed"],
            "failure_counts": result["failure_counts"],
        },
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "semantic_result_sha256": semantic_hash,
        "next_action": result["next_action"],
    }
    print("[5/7] Writing compact result, evaluation and exact surviving ensemble", flush=True)
    for path, payload in (
        (result_path, result),
        (evaluation_path, evaluation),
        (parameter_set_path, parameter_set),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(
        f"[6/7] Result: {len(accepted_ids)}/{len(rows)} exact embodied composites retained, unranked",
        flush=True,
    )
    print(f"[7/7] semantic_sha256={semantic_hash} wall={wall_seconds:.1f}s", flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute the preregistered FH-07b embodied technical gate")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    run_gate(campaign_path=args.campaign)


if __name__ == "__main__":
    main()

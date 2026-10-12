from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from .feco_observation import source_activation
from .ledger import ROOT
from .local_conversion import event_intensity_to_counts
from .neutral_embodied_adapter_sentinel import (
    _canonical_hash,
    _compact_episode,
    _load_campaign as _load_adapter_campaign,
    _load_compiler_inputs,
    _read_schedule,
    _run_command_episode,
    compile_motor_route_trace,
)
from .embodied_measurement_contract import _episode_metrics, paired_recovery_metrics
from .runtime import FlyBodyPhysicsLoop


CAMPAIGN_PATH = (
    ROOT / "calibration" / "campaigns" / "neutral-embodied-full-chain-sentinel-v0.yaml"
)
RESULT_PATH = (
    ROOT / "calibration" / "runner" / "neutral-embodied-full-chain-sentinel-v0.yaml"
)
EVALUATION_PATH = (
    ROOT / "calibration" / "evaluations" / "neutral-embodied-full-chain-sentinel-v0.yaml"
)
RUN_ROOT = ROOT / "runs" / "calibration" / "neutral-embodied-full-chain-sentinel-v0"


class FullChainSentinelError(RuntimeError):
    """Raised when a declared local-chain execution boundary is violated."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FullChainSentinelError(f"{path} must contain a YAML mapping")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = _load_yaml(path)
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise FullChainSentinelError("full-chain sentinel must remain diagnostic_only")
    if campaign.get("behavior_targets"):
        raise FullChainSentinelError("full-chain sentinel cannot expose behavior targets")
    if campaign.get("topology_changes_allowed") is not False:
        raise FullChainSentinelError("full-chain sentinel cannot change topology")
    boundary = campaign.get("scientific_boundary", {})
    for key in ("optimized_parameters", "promoted_parameter_values", "selected_candidates"):
        if int(boundary.get(key, -1)) != 0:
            raise FullChainSentinelError(f"full-chain sentinel requires zero {key}")
    if campaign["sentinel_selection"].get("selected_from_body_motion") is not False:
        raise FullChainSentinelError("sentinel tuple selection cannot use body motion")
    return campaign


def _verify_and_load_inputs(campaign: Mapping[str, Any]) -> dict[str, Any]:
    frozen = campaign["frozen_inputs"]
    adapter_campaign_path = ROOT / str(frozen["adapter_campaign"])
    if _sha256(adapter_campaign_path) != str(frozen["adapter_campaign_sha256"]):
        raise FullChainSentinelError("adapter campaign drift")
    adapter_campaign = _load_adapter_campaign(adapter_campaign_path)
    adapter_inputs = _load_compiler_inputs(adapter_campaign)

    paths = {
        key: ROOT / str(frozen[key])
        for key in (
            "central_paths",
            "population_members",
            "classified_intermediates",
            "transmitter_priors",
        )
    }
    observed = {key: _sha256(path) for key, path in paths.items()}
    if observed != campaign["frozen_input_sha256"]:
        raise FullChainSentinelError("full-chain frozen input drift")

    members = pd.read_csv(paths["population_members"])
    central_paths = pd.read_csv(paths["central_paths"])
    classified = pd.read_csv(paths["classified_intermediates"])
    priors = pd.read_parquet(paths["transmitter_priors"])
    sensory = np.sort(
        members.loc[
            members["population_id"].eq("population.front_leg_feco.v0"), "body_id"
        ].to_numpy(dtype=np.int64)
    )
    motor = np.sort(
        members.loc[
            members["population_id"].eq(
                "population.front_leg_tibia_flexor_motor.v0"
            ),
            "body_id",
        ].to_numpy(dtype=np.int64)
    )
    intermediate = np.sort(classified["body_id"].to_numpy(dtype=np.int64))
    if (len(sensory), len(intermediate), len(motor)) != (36, 150, 10):
        raise FullChainSentinelError("local-chain population accounting drift")
    if not set(sensory).isdisjoint(intermediate) or not set(motor).isdisjoint(intermediate):
        raise FullChainSentinelError("endpoint leaked into intermediate population")
    sensory_prior = priors.loc[priors["body_id"].isin(sensory)]
    if len(sensory_prior) != 36 or set(sensory_prior["sign_code"]) != {1}:
        raise FullChainSentinelError("FeCO endpoint sign prior drift")
    return {
        **adapter_inputs,
        "central_paths": central_paths,
        "classified": classified,
        "sensory_body_ids": sensory,
        "intermediate_body_ids": intermediate,
        "motor_body_ids": motor,
        "input_hashes": observed,
        "adapter_input_hashes": adapter_inputs["input_hashes"],
    }


def _normalize_trace(values: np.ndarray) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64)
    result = result - float(result.min())
    span = float(result.max())
    if span <= 0.0:
        return np.zeros_like(result)
    return result / span


def _functional_signals(
    position_deg: np.ndarray,
    source_path: Mapping[str, str],
    *,
    sampling_hz: float,
) -> dict[str, np.ndarray]:
    claw_id = str(source_path["claw_position"])
    club_id = str(source_path["club_vibration_and_speed"])
    hook_id = str(source_path["hook_flexion_direction"])
    claw_center = 80.0 if "center_80" in claw_id else 90.0
    club_threshold = 5.0 if "threshold_5" in club_id else 50.0
    hook_threshold = -5.0 if "minus_5" in hook_id else -50.0
    return {
        "claw_position": _normalize_trace(
            source_activation(
                position_deg,
                sampling_hz=sampling_hz,
                model_type="claw",
                claw_center_deg=claw_center,
            )
        ),
        "club_vibration_and_speed": _normalize_trace(
            source_activation(
                position_deg,
                sampling_hz=sampling_hz,
                model_type="club",
                threshold_deg_s=club_threshold,
            )
        ),
        "hook_flexion_direction": _normalize_trace(
            source_activation(
                position_deg,
                sampling_hz=sampling_hz,
                model_type="hook_flex",
                threshold_deg_s=hook_threshold,
            )
        ),
    }


def _delay(values: np.ndarray, steps: int) -> np.ndarray:
    result = np.zeros_like(values)
    if steps < len(values):
        result[steps:] = values[:-steps]
    return result


def _event_filter(events: np.ndarray, *, timestep_s: float, tau_s: float) -> np.ndarray:
    state = np.zeros(events.shape[1], dtype=np.float64)
    result = np.zeros(events.shape, dtype=np.float64)
    decay = float(np.exp(-timestep_s / tau_s))
    for index in range(len(events)):
        state = state * decay + events[index]
        result[index] = state
    return result


def _mixed_population(
    drive: np.ndarray,
    event_mask: np.ndarray,
    *,
    timestep_s: float,
    membrane_tau_s: float,
    synaptic_tau_s: float,
    refractory_s: float,
    threshold: float,
    input_gain: float,
) -> tuple[np.ndarray, np.ndarray]:
    channels = drive.shape[1]
    membrane = np.zeros(channels, dtype=np.float64)
    synaptic = np.zeros(channels, dtype=np.float64)
    output = np.zeros_like(drive, dtype=np.float64)
    spikes = np.zeros_like(drive, dtype=np.int64)
    refractory = np.zeros(channels, dtype=np.int64)
    refractory_steps = max(1, int(round(refractory_s / timestep_s)))
    synaptic_decay = float(np.exp(-timestep_s / synaptic_tau_s))
    alpha = timestep_s / membrane_tau_s
    graded_mask = ~event_mask
    for index in range(len(drive)):
        refractory = np.maximum(refractory - 1, 0)
        membrane[graded_mask] += alpha * (
            -membrane[graded_mask] + input_gain * drive[index, graded_mask]
        )
        active_event = event_mask & (refractory == 0)
        membrane[active_event] += alpha * (
            -membrane[active_event] + input_gain * drive[index, active_event]
        )
        fired = active_event & (membrane >= threshold)
        spikes[index, fired] = 1
        membrane[fired] = 0.0
        refractory[fired] = refractory_steps
        synaptic = synaptic * synaptic_decay + spikes[index]
        output[index, event_mask] = synaptic[event_mask]
        output[index, graded_mask] = np.maximum(membrane[graded_mask], 0.0)
    if not np.isfinite(output).all():
        raise FullChainSentinelError("typed population emitted non-finite state")
    return output, spikes


def _edge_matrices(inputs: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    paths = inputs["central_paths"]
    sensory = list(map(int, inputs["sensory_body_ids"]))
    intermediate = list(map(int, inputs["intermediate_body_ids"]))
    motor = list(map(int, inputs["motor_body_ids"]))
    sensory_index = {body_id: index for index, body_id in enumerate(sensory)}
    intermediate_index = {body_id: index for index, body_id in enumerate(intermediate)}
    motor_index = {body_id: index for index, body_id in enumerate(motor)}
    first = np.zeros((36, 150), dtype=np.float64)
    second = np.zeros((150, 10), dtype=np.float64)
    direct = np.zeros((36, 10), dtype=np.float64)
    two_hop = paths.loc[paths["hops"].eq(2)].copy()
    for row in two_hop.drop_duplicates(
        ["source_body_id", "intermediate_body_id"]
    ).itertuples(index=False):
        intermediate_body_id = int(row.intermediate_body_id)
        if intermediate_body_id not in intermediate_index:
            continue
        first[
            sensory_index[int(row.source_body_id)],
            intermediate_index[intermediate_body_id],
        ] = float(row.first_edge_weight)
    for row in two_hop.drop_duplicates(
        ["intermediate_body_id", "target_body_id"]
    ).itertuples(index=False):
        intermediate_body_id = int(row.intermediate_body_id)
        if intermediate_body_id not in intermediate_index:
            continue
        second[
            intermediate_index[intermediate_body_id],
            motor_index[int(row.target_body_id)],
        ] = float(row.second_edge_weight)
    for row in paths.loc[paths["hops"].eq(1)].itertuples(index=False):
        direct[sensory_index[int(row.source_body_id)], motor_index[int(row.target_body_id)]] = float(row.first_edge_weight)
    for matrix in (first, second, direct):
        denominator = np.abs(matrix).sum(axis=0)
        nonzero = denominator > 0.0
        matrix[:, nonzero] /= denominator[nonzero]
    if np.count_nonzero(first) == 0 or np.count_nonzero(second) == 0:
        raise FullChainSentinelError("local corridor matrices are empty")
    return first, second, direct


def execute_local_chain(
    row: Mapping[str, str],
    campaign: Mapping[str, Any],
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    probe = campaign["typed_execution_probe"]
    timestep_s = float(probe["timestep_s"])
    frame_dt_s = float(campaign["physical_protocol"]["expected_frame_dt_s"])
    substeps = int(round(frame_dt_s / timestep_s))
    frames = int(campaign["physical_protocol"]["frames"])
    if not np.isclose(substeps * timestep_s, frame_dt_s):
        raise FullChainSentinelError("neural timestep does not divide the physical frame")
    samples = frames * substeps
    time_axis = np.arange(samples, dtype=np.float64) * timestep_s
    fixture = campaign["synthetic_joint_fixture"]
    position_deg = float(fixture["center_deg"]) + float(fixture["amplitude_deg"]) * np.sin(
        2.0 * np.pi * float(fixture["frequency_hz"]) * time_axis
    )
    source_path_index = int(row["feco_source_path_index"])
    source_path = inputs["feco_paths"][source_path_index]
    signals = _functional_signals(
        position_deg, source_path, sampling_hz=1.0 / timestep_s
    )
    class_names = tuple(signals)
    sensory_ids = list(map(int, inputs["sensory_body_ids"]))
    projection = {
        body_id: class_names[index % len(class_names)]
        for index, body_id in enumerate(sensory_ids)
    }
    class_counts = {
        name: sum(value == name for value in projection.values()) for name in class_names
    }
    activity = np.column_stack([signals[projection[body_id]] for body_id in sensory_ids])
    representation = str(row["feco_native_representation"])
    if representation == "event_candidate":
        intensity_hz = activity * float(probe["source_event_intensity_max_hz"])
        source_events = event_intensity_to_counts(
            intensity_hz, timestep_s=timestep_s, seed=int(row["seed"])
        )
        source_drive = _event_filter(
            source_events,
            timestep_s=timestep_s,
            tau_s=float(probe["synaptic_tau_s"]),
        )
    elif representation == "graded_candidate":
        source_events = np.zeros(activity.shape, dtype=np.int64)
        source_drive = activity
    else:
        raise FullChainSentinelError("unsupported FeCO representation")

    first, second, direct = _edge_matrices(inputs)
    delay_steps = int(round(float(probe["transmission_delay_s"]) / timestep_s))
    if not np.isclose(delay_steps * timestep_s, float(probe["transmission_delay_s"])):
        raise FullChainSentinelError("transmission delay is not exactly representable")
    intermediate_drive = _delay(source_drive @ first, delay_steps)
    profile = inputs["profiles"][str(row["intermediate_profile_id"])]
    classified = inputs["classified"].set_index("body_id")
    intermediate_ids = list(map(int, inputs["intermediate_body_ids"]))
    event_mask = np.asarray(
        [
            classified.loc[body_id, "assignment"] == "event_required"
            or profile.get(body_id) == "event_candidate"
            for body_id in intermediate_ids
        ],
        dtype=bool,
    )
    if int(event_mask.sum()) + int((~event_mask).sum()) != 150:
        raise FullChainSentinelError("intermediate assignment accounting drift")
    intermediate_output, intermediate_spikes = _mixed_population(
        intermediate_drive,
        event_mask,
        timestep_s=timestep_s,
        membrane_tau_s=float(probe["intermediate_membrane_tau_s"]),
        synaptic_tau_s=float(probe["synaptic_tau_s"]),
        refractory_s=float(probe["intermediate_refractory_s"]),
        threshold=float(probe["event_threshold_normalized"]),
        input_gain=float(probe["intermediate_input_gain"]),
    )
    sign_codes = classified.loc[intermediate_ids, "sign_code"].to_numpy(dtype=np.int8)
    unknown_sign_count = int(np.count_nonzero(sign_codes == 0))
    effective_sign = sign_codes.astype(np.float64)
    effective_sign[effective_sign == 0] = float(probe["unknown_sign_diagnostic_candidate"])
    motor_from_intermediate = _delay(
        (intermediate_output * effective_sign) @ second, delay_steps
    )
    motor_direct = _delay(source_drive @ direct, delay_steps)
    motor_drive = motor_from_intermediate + motor_direct
    motor_output, motor_spikes = _mixed_population(
        motor_drive,
        np.ones(10, dtype=bool),
        timestep_s=timestep_s,
        membrane_tau_s=float(probe["motor_membrane_tau_s"]),
        synaptic_tau_s=float(probe["synaptic_tau_s"]),
        refractory_s=float(probe["motor_refractory_s"]),
        threshold=float(probe["event_threshold_normalized"]),
        input_gain=float(probe["motor_input_gain"]),
    )
    del motor_output
    frame_events = motor_spikes.reshape(frames, substeps, 10).sum(axis=1)
    route_body = int(row["route_body_id"])
    route_index = list(map(int, inputs["motor_body_ids"])).index(route_body)
    route_events = frame_events[:, route_index].astype(np.int64, copy=False)
    if not np.isfinite(intermediate_output).all() or not np.isfinite(motor_drive).all():
        raise FullChainSentinelError("local chain contains non-finite state")
    return {
        "route_event_counts": route_events,
        "trace": {
            "samples": samples,
            "timestep_s": timestep_s,
            "frame_dt_s": frame_dt_s,
            "transmission_delay_s": float(probe["transmission_delay_s"]),
            "transmission_delay_steps": delay_steps,
            "feco_source_path_index": source_path_index,
            "feco_representation": representation,
            "feco_projection_policy": probe["endpoint_functional_projection"],
            "feco_projection_class_counts": class_counts,
            "feco_event_count": int(source_events.sum()),
            "feco_nonzero_drive_samples": int(np.count_nonzero(source_drive)),
            "intermediate_event_candidates": int(event_mask.sum()),
            "intermediate_graded_candidates": int((~event_mask).sum()),
            "intermediate_spike_count": int(intermediate_spikes.sum()),
            "intermediate_nonzero_state_samples": int(np.count_nonzero(intermediate_output)),
            "unknown_sign_diagnostic_edges_sources": unknown_sign_count,
            "motor_spike_count_all_bodies": int(motor_spikes.sum()),
            "route_motor_event_count": int(route_events.sum()),
            "route_motor_body_id": route_body,
            "neural_trace_sha256": _canonical_hash(
                {
                    "route_events": route_events.tolist(),
                    "motor_frame_events": frame_events.tolist(),
                    "intermediate_spike_count": int(intermediate_spikes.sum()),
                    "intermediate_state_sum": float(intermediate_output.sum()),
                }
            ),
        },
    }


def compile_full_chain_sentinel(
    campaign_path: Path = CAMPAIGN_PATH,
    *,
    actuator_names: tuple[str, ...] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    campaign = _load_campaign(campaign_path)
    adapter_campaign = _load_adapter_campaign(
        ROOT / str(campaign["frozen_inputs"]["adapter_campaign"])
    )
    rows, schedule_result = _read_schedule(adapter_campaign)
    by_id = {row["tuple_id"]: row for row in rows}
    inputs = _verify_and_load_inputs(campaign)
    selected = list(campaign["sentinel_selection"]["tuple_ids"])
    if len(selected) != int(campaign["acceptance"]["sentinel_tuples"]):
        raise FullChainSentinelError("sentinel tuple count drift")
    compiled: list[dict[str, Any]] = []
    for tuple_id in selected:
        row = by_id[tuple_id]
        local = execute_local_chain(row, campaign, inputs)
        route = compile_motor_route_trace(
            row,
            inputs,
            local["route_event_counts"],
            frame_dt_s=float(campaign["physical_protocol"]["expected_frame_dt_s"]),
            actuator_names=actuator_names,
        )
        compiled.append(
            {
                "tuple_id": tuple_id,
                "row": row,
                "local_chain": local["trace"],
                "route": {
                    key: value
                    for key, value in route.items()
                    if key not in {"assignment", "command_trace"}
                },
                "command_trace": route["command_trace"],
            }
        )
    return campaign, compiled, {
        "scheduled_tuple_count": len(rows),
        "schedule_result_semantic_sha256": schedule_result["semantic_result_sha256"],
        "input_hashes": inputs["input_hashes"],
        "adapter_input_hashes": inputs["adapter_input_hashes"],
    }


def run_sentinel(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    run_root: Path = RUN_ROOT,
) -> dict[str, Any]:
    started = time.perf_counter()
    print("[1/6] Verifying frozen local-chain inputs and exact schedule", flush=True)
    with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=False) as probe_loop:
        actuator_names = tuple(probe_loop.actuator_names)
    campaign, compiled, context = compile_full_chain_sentinel(
        campaign_path, actuator_names=actuator_names
    )
    print("[2/6] Executing FeCO -> typed intermediates -> motor events", flush=True)
    for item in compiled:
        trace = item["local_chain"]
        print(
            f"  {item['tuple_id']}: {trace['feco_representation']}, "
            f"{trace['intermediate_event_candidates']} event / "
            f"{trace['intermediate_graded_candidates']} graded, "
            f"{trace['route_motor_event_count']} route events",
            flush=True,
        )

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    artifact_root = run_root / run_id
    artifact_root.mkdir(parents=True, exist_ok=False)
    outcomes: list[dict[str, Any]] = []
    print("[3/6] Running paired physical episodes from full-chain output", flush=True)
    for item in compiled:
        tuple_started = time.perf_counter()
        outcome: dict[str, Any] = {
            "tuple_id": item["tuple_id"],
            "status": "error",
            "local_chain": item["local_chain"],
            "route": item["route"],
        }
        try:
            command = item["command_trace"]
            perturbation = campaign["physical_protocol"]["perturbation"]
            baseline, baseline_metadata = _run_command_episode(
                campaign, command, perturbation=None
            )
            perturbed, perturbed_metadata = _run_command_episode(
                campaign, command, perturbation=perturbation
            )
            if (
                baseline_metadata["model_contract"]
                != perturbed_metadata["model_contract"]
            ):
                raise FullChainSentinelError("paired model metadata drift")
            baseline_metrics = _episode_metrics(baseline, baseline_metadata)
            perturbed_metrics = _episode_metrics(perturbed, perturbed_metadata)
            paired = paired_recovery_metrics(
                baseline,
                perturbed,
                int(campaign["physical_protocol"]["perturbation_step"]),
            )
            tuple_root = artifact_root / item["tuple_id"]
            tuple_root.mkdir(parents=True, exist_ok=False)
            np.savez_compressed(tuple_root / "baseline.npz", **baseline)
            np.savez_compressed(tuple_root / "perturbed.npz", **perturbed)
            outcome.update(
                {
                    "status": "completed_contract",
                    "baseline": _compact_episode(baseline_metrics),
                    "perturbed": _compact_episode(perturbed_metrics),
                    "paired_recovery": paired,
                    "artifacts": {
                        "baseline": str((tuple_root / "baseline.npz").relative_to(ROOT)).replace("\\", "/"),
                        "perturbed": str((tuple_root / "perturbed.npz").relative_to(ROOT)).replace("\\", "/"),
                    },
                }
            )
        except Exception as exc:  # retained in the compact accounting
            outcome["error"] = f"{type(exc).__name__}: {exc}"
        outcome["wall_seconds"] = time.perf_counter() - tuple_started
        outcomes.append(outcome)

    print("[4/6] Accounting outcomes and execution boundaries", flush=True)
    completed = sum(item["status"] == "completed_contract" for item in outcomes)
    all_axes_active = all(
        item["local_chain"]["feco_nonzero_drive_samples"] > 0
        and item["local_chain"]["intermediate_nonzero_state_samples"] > 0
        and item["local_chain"]["motor_spike_count_all_bodies"] > 0
        for item in outcomes
    )
    passed = completed == len(outcomes) and all_axes_active
    status = (
        "pass_full_local_chain_execution_sentinel_no_calibration"
        if passed
        else "failed_full_local_chain_execution_sentinel"
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
            "paired_physical_episodes": len(compiled) * 2,
            "completed_tuples": completed,
            "failed_tuples": len(compiled) - completed,
            "all_axes_active": all_axes_active,
        },
        "execution_boundary": {
            "feco_transduction_executed": True,
            "typed_intermediate_cns_executed": True,
            "motor_event_force_bridge_route_executed": True,
            "paired_mujoco_physics_executed": True,
            "local_chain_execution_contract_passed": passed,
            "population_assignments_promoted": 0,
            "candidate_selected_from_motion": False,
            "stability_evaluated": False,
            "optimized_parameters": 0,
            "promoted_parameter_values": 0,
        },
        "input_hashes": context["input_hashes"],
        "adapter_input_hashes": context["adapter_input_hashes"],
        "schedule_result_semantic_sha256": context["schedule_result_semantic_sha256"],
        "wall_seconds": time.perf_counter() - started,
        "tuple_outcomes": outcomes,
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    hash_payload = dict(summary)
    hash_payload.pop("generated_at")
    hash_payload.pop("run_id")
    hash_payload.pop("wall_seconds")
    hash_payload["tuple_outcomes"] = [
        {
            key: value
            for key, value in outcome.items()
            if key not in {"wall_seconds", "artifacts", "baseline", "perturbed", "paired_recovery"}
        }
        for outcome in outcomes
    ]
    summary["semantic_result_sha256"] = _canonical_hash(hash_payload)
    (artifact_root / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print("[5/6] Writing compact versioned result and evaluation", flush=True)
    compact = {
        key: summary[key]
        for key in (
            "schema_version",
            "campaign_id",
            "status",
            "claim_label",
            "accounting",
            "execution_boundary",
            "input_hashes",
            "adapter_input_hashes",
            "schedule_result_semantic_sha256",
            "tuple_outcomes",
            "accepted_claims",
            "forbidden_claims",
            "next_action",
            "semantic_result_sha256",
        )
    }
    compact.update(
        {
            "id": "runner_result.neutral_embodied_full_chain_sentinel.v0",
            "target_id": campaign["target_id"],
            "command": "neutral_embodied_full_chain_sentinel.bat",
            "behavior_targets": [],
            "campaign_sha256": _sha256(campaign_path),
            "implementation_sha256": _sha256(Path(__file__).resolve()),
            "artifact_ref": str((artifact_root / "summary.json").relative_to(ROOT)).replace("\\", "/"),
        }
    )
    result_path.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.neutral_embodied_full_chain_sentinel.v0",
        "title": "Neutral embodied full local-chain execution sentinel",
        "status": "evaluated" if passed else "failed",
        "campaign_id": campaign["id"],
        "target_id": campaign["target_id"],
        "primary_class": campaign["primary_class"],
        "optimization_exposure": campaign["optimization_exposure"],
        "claim_label": campaign["claim_label"],
        "behavior_targets": [],
        "acceptance_result": status,
        "runner_result_id": compact["id"],
        "runner_semantic_sha256": compact["semantic_result_sha256"],
        "parameter_values_promoted": 0,
        "stability_accepted": False,
        "full_local_chain_execution_contract": passed,
        "conclusion": (
            "The four fixed schedule tuples executed FeCO transduction, typed local CNS dynamics, motor events, the frozen physical adapter and paired MuJoCo episodes. This is an execution contract using declared diagnostic candidates, not calibration or stability evidence."
            if passed
            else "The full local-chain sentinel failed; the 120-tuple panel remains blocked."
        ),
        "next_action": campaign["next_action"],
    }
    evaluation_path.write_text(yaml.safe_dump(evaluation, sort_keys=False), encoding="utf-8")

    print("[6/6] Summary", flush=True)
    print(f"[ACCOUNTING] {completed}/{len(compiled)} tuples completed", flush=True)
    print(f"[AXES] FeCO + typed CNS + motor + physics active: {all_axes_active}", flush=True)
    print("[BOUNDARY] 0 fit, 0 selection, 0 promotion, 0 behavior, 0 stability claim", flush=True)
    print(f"[HASH] {summary['semantic_result_sha256']}", flush=True)
    return compact


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded full local-chain execution sentinel"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--output", type=Path, default=RUN_ROOT)
    args = parser.parse_args()
    result = run_sentinel(args.campaign, run_root=args.output)
    return 0 if result["status"].startswith("pass_") else 1


if __name__ == "__main__":
    raise SystemExit(main())

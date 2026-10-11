from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml

from .ledger import ROOT
from .physical_trajectory import model_contract
from .runtime import FlyBodyPhysicsLoop


CAMPAIGN_PATH = (
    ROOT / "calibration" / "campaigns" / "embodied-measurement-contract-v1.yaml"
)
RESULT_PATH = ROOT / "calibration" / "runner" / "embodied-measurement-contract-v1.yaml"
RUN_ROOT = ROOT / "runs" / "calibration" / "embodied-measurement-contract-v1"


class EmbodiedMeasurementError(RuntimeError):
    """Raised when the neutral embodied measurement contract is violated."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EmbodiedMeasurementError(f"{path} must contain a YAML mapping")
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
        raise EmbodiedMeasurementError("measurement contract must remain diagnostic_only")
    if campaign.get("behavior_targets"):
        raise EmbodiedMeasurementError("measurement contract cannot expose behavior")
    if int(campaign.get("budgets", {}).get("optimized_parameters", -1)) != 0:
        raise EmbodiedMeasurementError("measurement contract cannot optimize parameters")
    if campaign.get("acceptance", {}).get("stability_thresholds") != "unresolved":
        raise EmbodiedMeasurementError("measurement contract cannot select stability thresholds")
    return campaign


def joint_limit_metrics(
    positions: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    limited: np.ndarray,
) -> dict[str, Any]:
    values = np.asarray(positions, dtype=np.float64)
    low = np.asarray(lower, dtype=np.float64)
    high = np.asarray(upper, dtype=np.float64)
    mask = np.asarray(limited, dtype=bool)
    if values.ndim != 2 or low.shape != (values.shape[1],) or high.shape != low.shape:
        raise EmbodiedMeasurementError("joint-limit arrays have incompatible shapes")
    if mask.shape != low.shape or np.any(low[mask] > high[mask]):
        raise EmbodiedMeasurementError("joint-limit metadata is invalid")
    below = mask[None, :] & (values < low[None, :])
    above = mask[None, :] & (values > high[None, :])
    lower_margin = values[:, mask] - low[mask][None, :]
    upper_margin = high[mask][None, :] - values[:, mask]
    return {
        "channels": values.shape[1],
        "limited_channels": int(mask.sum()),
        "violation_samples": int(np.count_nonzero(below | above)),
        "violating_frames": int(np.count_nonzero(np.any(below | above, axis=1))),
        "minimum_margin_rad": float(min(lower_margin.min(), upper_margin.min())),
    }


def physical_kinematics(center_of_mass: np.ndarray, timestamps_s: np.ndarray) -> dict[str, Any]:
    com = np.asarray(center_of_mass, dtype=np.float64)
    time = np.asarray(timestamps_s, dtype=np.float64)
    if com.ndim != 2 or com.shape[1] != 3 or time.shape != (len(com),):
        raise EmbodiedMeasurementError("COM trajectory has incompatible shape")
    if len(time) < 5 or np.any(np.diff(time) <= 0):
        raise EmbodiedMeasurementError("physical jerk requires at least five ordered frames")
    edge_order = 2 if len(time) >= 3 else 1
    velocity = np.gradient(com, time, axis=0, edge_order=edge_order)
    acceleration = np.gradient(velocity, time, axis=0, edge_order=edge_order)
    jerk = np.gradient(acceleration, time, axis=0, edge_order=edge_order)
    acceleration_norm = np.linalg.norm(acceleration, axis=1)
    jerk_norm = np.linalg.norm(jerk, axis=1)
    return {
        "method": "finite_difference_of_mass_weighted_flybody_com",
        "velocity_l2_rms": float(np.sqrt(np.mean(np.square(np.linalg.norm(velocity, axis=1))))),
        "acceleration_l2_rms": float(np.sqrt(np.mean(np.square(acceleration_norm)))),
        "acceleration_l2_peak": float(acceleration_norm.max()),
        "jerk_l2_rms": float(np.sqrt(np.mean(np.square(jerk_norm)))),
        "jerk_l2_peak": float(jerk_norm.max()),
    }


def paired_recovery_metrics(
    baseline: Mapping[str, np.ndarray],
    perturbed: Mapping[str, np.ndarray],
    perturbation_step: int,
) -> dict[str, Any]:
    if perturbation_step < 0:
        raise EmbodiedMeasurementError("perturbation step must be non-negative")
    metrics: dict[str, Any] = {}
    for key in ("center_of_mass", "qpos", "qvel"):
        reference = np.asarray(baseline[key], dtype=np.float64)
        changed = np.asarray(perturbed[key], dtype=np.float64)
        if reference.shape != changed.shape or len(reference) <= perturbation_step:
            raise EmbodiedMeasurementError(f"paired {key} arrays have incompatible shapes")
        deviation = np.linalg.norm(changed - reference, axis=1)[perturbation_step:]
        peak_index = int(np.argmax(deviation))
        peak = float(deviation[peak_index])
        final = float(deviation[-1])
        stable_half_index = None
        if peak > 0:
            for index in range(peak_index, len(deviation)):
                if np.all(deviation[index:] <= 0.5 * peak):
                    stable_half_index = index
                    break
        metrics[key] = {
            "peak_l2": peak,
            "final_l2": final,
            "final_over_peak": float(final / peak) if peak > 0 else None,
            "stable_half_recovery_frame_after_perturbation": stable_half_index,
        }
    return metrics


def _model_measurement_metadata(loop: FlyBodyPhysicsLoop) -> dict[str, Any]:
    import mujoco

    model = loop.simulation.mj_model
    joint_ids = []
    for name in loop.joint_names:
        joint_id = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_JOINT, f"flybody/{name}"
        )
        if joint_id < 0:
            raise EmbodiedMeasurementError(f"joint absent from MuJoCo model: {name}")
        joint_ids.append(joint_id)
    body_names = [
        mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, index)
        for index in range(model.nbody)
    ]
    fly_body_ids = [
        index
        for index, name in enumerate(body_names)
        if name and name.startswith("flybody/") and model.body_mass[index] > 0
    ]
    if not fly_body_ids:
        raise EmbodiedMeasurementError("no positive-mass FlyBody bodies found")
    joint_ids_array = np.asarray(joint_ids, dtype=np.int64)
    return {
        "model_contract": model_contract(loop),
        "joint_names": list(loop.joint_names),
        "joint_ids": joint_ids_array,
        "joint_limited": np.asarray(model.jnt_limited[joint_ids_array], dtype=bool),
        "joint_ranges": np.asarray(model.jnt_range[joint_ids_array], dtype=np.float64),
        "fly_body_ids": np.asarray(fly_body_ids, dtype=np.int64),
        "fly_body_names": [body_names[index] for index in fly_body_ids],
        "fly_body_masses": np.asarray(model.body_mass[fly_body_ids], dtype=np.float64),
        "floor_z_model_units": 0.0,
    }


def _center_of_mass(loop: FlyBodyPhysicsLoop, metadata: Mapping[str, Any]) -> np.ndarray:
    positions = np.asarray(
        loop.simulation.mj_data.xipos[np.asarray(metadata["fly_body_ids"], dtype=np.int64)],
        dtype=np.float64,
    )
    masses = np.asarray(metadata["fly_body_masses"], dtype=np.float64)
    return np.average(positions, axis=0, weights=masses)


def _root_up_z(qpos: np.ndarray) -> float:
    quaternion = np.asarray(qpos[3:7], dtype=np.float64)
    norm = np.linalg.norm(quaternion)
    if norm == 0:
        return float("nan")
    w, x, y, z = quaternion / norm
    del w, z
    return float(1.0 - 2.0 * (x * x + y * y))


def _run_passive_episode(
    campaign: Mapping[str, Any], *, perturbation: Mapping[str, Any] | None
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    import mujoco

    protocol = campaign["paired_protocol"]
    frames = int(protocol["frames"])
    substeps = int(protocol["physics_substeps_per_frame"])
    perturbation_step = int(protocol["perturbation_step"])
    records: dict[str, list[np.ndarray | float]] = {
        key: []
        for key in (
            "timestamps_s",
            "qpos",
            "qvel",
            "joint_positions",
            "joint_velocities",
            "actuator_forces",
            "center_of_mass",
            "root_up_z",
            "ground_contact_found",
            "ground_contact_force_norm",
        )
    }
    with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=False) as loop:
        metadata = _model_measurement_metadata(loop)
        zero_commands = loop.actuator_interface.step(np.zeros(len(loop.actuator_names)))
        for frame_index in range(frames):
            if perturbation is not None and frame_index == perturbation_step:
                address = int(perturbation["qvel_address"])
                if not 0 <= address < len(loop.simulation.mj_data.qvel):
                    raise EmbodiedMeasurementError("perturbation qvel address is invalid")
                loop.simulation.mj_data.qvel[address] += float(perturbation["delta"])
                mujoco.mj_forward(loop.simulation.mj_model, loop.simulation.mj_data)
            step = loop.step(zero_commands, substeps=substeps)
            contact_found, forces, _torques, _positions, _normals, _tangents = (
                loop.simulation.get_ground_contact_info("flybody")
            )
            records["timestamps_s"].append(float(step.simulation_time))
            records["qpos"].append(loop.simulation.mj_data.qpos.copy())
            records["qvel"].append(loop.simulation.mj_data.qvel.copy())
            records["joint_positions"].append(step.joint_state.positions.copy())
            records["joint_velocities"].append(step.joint_state.velocities.copy())
            records["actuator_forces"].append(step.actuator_forces.copy())
            records["center_of_mass"].append(_center_of_mass(loop, metadata))
            records["root_up_z"].append(_root_up_z(loop.simulation.mj_data.qpos))
            records["ground_contact_found"].append(
                np.asarray(contact_found, dtype=np.float64).copy()
            )
            records["ground_contact_force_norm"].append(
                np.linalg.norm(np.asarray(forces, dtype=np.float64), axis=1)
            )
    return {key: np.asarray(values) for key, values in records.items()}, metadata


def _episode_metrics(
    episode: Mapping[str, np.ndarray], metadata: Mapping[str, Any]
) -> dict[str, Any]:
    arrays = [np.asarray(value) for value in episode.values()]
    finite_count = sum(int(np.isfinite(value).sum()) for value in arrays)
    value_count = sum(int(value.size) for value in arrays)
    joint_ranges = np.asarray(metadata["joint_ranges"], dtype=np.float64)
    limits = joint_limit_metrics(
        episode["joint_positions"],
        joint_ranges[:, 0],
        joint_ranges[:, 1],
        metadata["joint_limited"],
    )
    kinematics = physical_kinematics(episode["center_of_mass"], episode["timestamps_s"])
    com = np.asarray(episode["center_of_mass"], dtype=np.float64)
    up_z = np.asarray(episode["root_up_z"], dtype=np.float64)
    gross_fall = (up_z <= 0.0) | (com[:, 2] <= float(metadata["floor_z_model_units"]))
    timestamps = np.asarray(episode["timestamps_s"], dtype=np.float64)
    observed_frame_dt = np.diff(timestamps)
    dt = np.diff(timestamps, prepend=0.0)
    dt[0] = dt[1]
    contact_found = np.asarray(episode["ground_contact_found"], dtype=np.float64)
    contact_force = np.asarray(
        episode["ground_contact_force_norm"], dtype=np.float64
    )
    any_contact = np.any(contact_found > 0.5, axis=1)
    work_proxy = np.sum(
        np.abs(
            np.asarray(episode["actuator_forces"], dtype=np.float64)
            * np.asarray(episode["joint_velocities"], dtype=np.float64)
        )
        * dt[:, None]
    )
    return {
        "frames": len(com),
        "duration_s": float(episode["timestamps_s"][-1]),
        "finite_fraction": float(finite_count / value_count),
        "cadence": {
            "frame_dt_min_s": float(observed_frame_dt.min()),
            "frame_dt_median_s": float(np.median(observed_frame_dt)),
            "frame_dt_max_s": float(observed_frame_dt.max()),
        },
        "center_of_mass": {
            "source": "mass_weighted_mujoco_body_xipos_for_all_positive_mass_flybody_bodies",
            "body_count": len(metadata["fly_body_ids"]),
            "translation_from_initial_peak_l2": float(
                np.linalg.norm(com - com[0], axis=1).max()
            ),
            "height_minimum": float(com[:, 2].min()),
        },
        "joint_limits": limits,
        "physical_com_kinematics": kinematics,
        "declared_direct_motor_work_proxy": {
            "absolute_force_velocity_integral": float(work_proxy),
            "biological_energy_claimed": False,
        },
        "ground_contacts": {
            "channels": int(contact_found.shape[1]),
            "frames_with_any_contact": int(np.count_nonzero(any_contact)),
            "frames_without_contact": int(np.count_nonzero(~any_contact)),
            "contact_state_transitions": int(
                np.count_nonzero(any_contact[1:] != any_contact[:-1])
            ),
            "peak_force_norm": float(contact_force.max()),
            "force_is_finite": bool(np.all(np.isfinite(contact_force))),
        },
        "failure_masks": {
            "numerical_failure_frames": int(
                np.count_nonzero(
                    np.any(~np.isfinite(episode["qpos"]), axis=1)
                    | np.any(~np.isfinite(episode["qvel"]), axis=1)
                )
            ),
            "joint_limit_violation_frames": limits["violating_frames"],
            "gross_fall_proxy_frames": int(np.count_nonzero(gross_fall)),
            "gross_fall_proxy_definition": "root_up_z<=0 or mass_weighted_COM_z<=floor_z",
            "gross_fall_proxy_is_complete_fall_classifier": False,
        },
    }


def _uncertainty_axis_accounting(campaign: Mapping[str, Any]) -> dict[str, Any]:
    upstream_path = ROOT / str(campaign["frozen_inputs"]["uncertainty_propagation_result"])
    upstream = _load_yaml(upstream_path)
    panel = upstream["intermediate_panel"]
    feco = upstream["interface_decisions"]["feco"]
    motor = upstream["interface_decisions"]["motor"]
    result = {
        "intermediate_profiles": int(panel["diagnostic_profiles"]),
        "feco_alternatives": int(feco["boundary_alternatives"]),
        "motor_class_assignments_scientific": int(
            motor["scientific_class_assignment_upper_bound"]
        ),
        "motor_class_assignments_kernel_executable": int(
            motor["kernel_executable_fast_or_intermediate_assignments"]
        ),
        "motor_class_assignments_blocked_slow": int(
            motor["kernel_blocked_slow_containing_assignments"]
        ),
        "route_basis_edges": int(motor["route_basis_edges"]),
        "bridge_gain_candidates": int(motor["bridge_gain_candidates"]),
        "cartesian_product_materialized": False,
        "pilot_schedule_status": "must_be_declared_by_next_campaign",
    }
    expected = campaign["uncertainty_schedule_contract"]["expected_axes"]
    for key, value in expected.items():
        if int(result[key]) != int(value):
            raise EmbodiedMeasurementError(
                f"uncertainty-axis drift for {key}: {result[key]} != {value}"
            )
    return result


def _validate_frozen_gate_inputs(campaign: Mapping[str, Any]) -> None:
    frozen = campaign["frozen_inputs"]
    actuator_result = _load_yaml(ROOT / str(frozen["actuator_attribution_result"]))
    observed = actuator_result["frozen_inputs"]["actuator_contract_sha256"]
    expected = str(frozen["actuator_semantics_contract_sha256"])
    if observed != expected:
        raise EmbodiedMeasurementError(
            f"actuator semantics contract drift: {observed} != {expected}"
        )
    if actuator_result["status"] != "accepted_bounded_direct_motor_surrogate_initial_short_horizon":
        raise EmbodiedMeasurementError("bounded direct-motor surrogate gate is not accepted")
    prior_evaluation = _load_yaml(ROOT / str(frozen["prior_metric_evaluation"]))
    if prior_evaluation["acceptance_result"] != "pass_metric_extraction_stability_unresolved":
        raise EmbodiedMeasurementError("prior metric coverage gate is not accepted")


def run_embodied_measurement_contract(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    run_root: Path = RUN_ROOT,
) -> dict[str, Any]:
    campaign = _load_campaign(campaign_path)
    protocol = campaign["paired_protocol"]

    print("[1/7] Verification du contrat et des axes d'incertitude", flush=True)
    _validate_frozen_gate_inputs(campaign)
    axes = _uncertainty_axis_accounting(campaign)

    print("[2/7] Episode passif de reference A", flush=True)
    baseline_a, metadata = _run_passive_episode(campaign, perturbation=None)
    print("[3/7] Episode passif de reference B pour le determinisme", flush=True)
    baseline_b, metadata_b = _run_passive_episode(campaign, perturbation=None)
    if metadata["model_contract"] != metadata_b["model_contract"]:
        raise EmbodiedMeasurementError("paired baseline model contracts differ")
    if metadata["model_contract"]["contract_sha256"] != str(
        campaign["frozen_inputs"]["physical_model_contract_sha256"]
    ):
        raise EmbodiedMeasurementError("physical model contract hash drift")
    print("[4/7] Episode apparie avec impulsion generique", flush=True)
    perturbed, metadata_p = _run_passive_episode(
        campaign, perturbation=protocol["perturbation"]
    )
    if metadata["model_contract"] != metadata_p["model_contract"]:
        raise EmbodiedMeasurementError("perturbed model contract differs")

    print("[5/7] Mesures COM, limites, jerk, masques et recuperation", flush=True)
    baseline_metrics = _episode_metrics(baseline_a, metadata)
    perturbed_metrics = _episode_metrics(perturbed, metadata)
    recovery = paired_recovery_metrics(
        baseline_a, perturbed, int(protocol["perturbation_step"])
    )
    baseline_repeat_max_error = max(
        float(np.max(np.abs(baseline_a[key] - baseline_b[key])))
        for key in ("qpos", "qvel", "center_of_mass", "joint_positions")
    )
    perturbation_peak = float(recovery["qvel"]["peak_l2"])

    acceptance = campaign["acceptance"]
    checks = {
        "baseline_repeat_deterministic": bool(
            baseline_repeat_max_error
            <= float(acceptance["baseline_repeat_state_max_abs_error"])
        ),
        "all_recorded_values_finite": bool(
            baseline_metrics["finite_fraction"] == 1.0
            and perturbed_metrics["finite_fraction"] == 1.0
        ),
        "all_joint_limits_snapshotted": bool(
            baseline_metrics["joint_limits"]["limited_channels"]
            == int(acceptance["expected_limited_joint_channels"])
        ),
        "center_of_mass_available": bool(
            baseline_metrics["center_of_mass"]["body_count"]
            == int(acceptance["expected_positive_mass_fly_bodies"])
        ),
        "physical_jerk_available": bool(
            np.isfinite(perturbed_metrics["physical_com_kinematics"]["jerk_l2_peak"])
        ),
        "frame_cadence_matches_contract": bool(
            abs(
                baseline_metrics["cadence"]["frame_dt_median_s"]
                - float(protocol["expected_frame_dt_s"])
            )
            <= float(acceptance["frame_dt_abs_tolerance_s"])
            and abs(
                perturbed_metrics["cadence"]["frame_dt_median_s"]
                - float(protocol["expected_frame_dt_s"])
            )
            <= float(acceptance["frame_dt_abs_tolerance_s"])
        ),
        "ground_contact_channels_available": bool(
            baseline_metrics["ground_contacts"]["channels"]
            == int(acceptance["expected_ground_contact_channels"])
            and perturbed_metrics["ground_contacts"]["channels"]
            == int(acceptance["expected_ground_contact_channels"])
            and baseline_metrics["ground_contacts"]["force_is_finite"]
            and perturbed_metrics["ground_contacts"]["force_is_finite"]
        ),
        "paired_perturbation_detectable": bool(
            perturbation_peak >= float(acceptance["paired_qvel_response_l2_min"])
        ),
        "stability_thresholds_unselected": bool(
            acceptance["stability_thresholds"] == "unresolved"
        ),
    }
    if not all(checks.values()):
        failed = [key for key, passed in checks.items() if not passed]
        raise EmbodiedMeasurementError(f"measurement contract failed: {failed}")

    print("[6/7] Ecriture de la paire lourde et du resultat compact", flush=True)
    run_id = f"measurement-contract-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    pair_path = run_dir / "paired-passive-episodes.npz"
    payload: dict[str, np.ndarray] = {}
    for branch, episode in (("baseline", baseline_a), ("perturbed", perturbed)):
        for key, value in episode.items():
            payload[f"{branch}__{key}"] = np.asarray(value)
    payload["joint_ranges"] = np.asarray(metadata["joint_ranges"], dtype=np.float64)
    payload["joint_limited"] = np.asarray(metadata["joint_limited"], dtype=np.uint8)
    np.savez_compressed(pair_path, **payload)
    pair_hash = _sha256(pair_path)

    result = {
        "schema_version": 1,
        "id": "runner_result.embodied_measurement_contract.v1",
        "campaign_id": campaign["id"],
        "target_id": campaign["target_id"],
        "status": "measurement_contract_pass_stability_unresolved",
        "completed_at": datetime.now(UTC).isoformat(),
        "claim_label": campaign["claim_label"],
        "command": "embodied_measurement_contract_v1.bat",
        "model_contract": metadata["model_contract"],
        "paired_protocol": protocol,
        "uncertainty_axes": axes,
        "checks": checks,
        "accounting": {
            "branches": 3,
            "recorded_episode_branches": 2,
            "frames_per_branch": int(protocol["frames"]),
            "optimized_parameters": 0,
            "stability_thresholds_selected": 0,
            "behavior_targets_exposed": 0,
            "topology_changes": 0,
        },
        "baseline_repeat_state_max_abs_error": baseline_repeat_max_error,
        "baseline_metrics": baseline_metrics,
        "perturbed_metrics": perturbed_metrics,
        "paired_recovery": recovery,
        "interpretation": {
            "measurement_contract_complete_for_short_horizon_technical_pilot": True,
            "stability_accepted": False,
            "behavior_observed": False,
            "biological_energy_claimed": False,
            "gross_fall_proxy_complete": False,
            "thresholds_may_be_selected_from_these_episodes": False,
        },
        "heavy_artifact": {
            "path": str(pair_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": pair_hash,
            "git_policy": "ignored_heavy_run_output",
        },
        "next_action": campaign["next_action"],
    }
    result["semantic_result_sha256"] = _canonical_hash(
        {
            key: value
            for key, value in result.items()
            if key not in {"completed_at", "heavy_artifact"}
        }
    )
    result_path.write_text(yaml.safe_dump(result, sort_keys=False), encoding="utf-8")

    print("[7/7] Resume", flush=True)
    print(
        f"[MODEL] {baseline_metrics['joint_limits']['limited_channels']} limites; "
        f"{baseline_metrics['center_of_mass']['body_count']} corps masses dans le COM",
        flush=True,
    )
    print(
        f"[PAIR] erreur repetition={baseline_repeat_max_error:.3e}; "
        f"pic qvel perturbe={perturbation_peak:.3e}",
        flush=True,
    )
    print("[BOUNDARY] 0 parametre, 0 seuil, 0 comportement, 0 selection", flush=True)
    print(f"[HASH] {result['semantic_result_sha256']}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the complete short-horizon embodied measurement contract"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    run_embodied_measurement_contract(args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

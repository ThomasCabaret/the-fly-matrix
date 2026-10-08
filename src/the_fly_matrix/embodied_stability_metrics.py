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
from .physical_trajectory import PhysicalTrajectory


CAMPAIGN_PATH = (
    ROOT / "calibration" / "campaigns" / "embodied-stability-metric-contract-v0.yaml"
)
RESULT_PATH = ROOT / "calibration" / "runner" / "embodied-stability-metric-contract-v0.yaml"
RUN_ROOT = ROOT / "runs" / "calibration" / "embodied-stability-metric-contract-v0"


class StabilityMetricError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = yaml.safe_load(path.read_text(encoding="utf-8"))
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise StabilityMetricError("the metric contract must remain diagnostic_only")
    if campaign.get("behavior_targets"):
        raise StabilityMetricError("the metric contract cannot expose behavior targets")
    if int(campaign.get("budgets", {}).get("optimized_parameters", -1)) != 0:
        raise StabilityMetricError("the metric contract cannot optimize parameters")
    if campaign.get("acceptance", {}).get("stability_thresholds") != "unresolved":
        raise StabilityMetricError("v0 must not select stability thresholds from its baseline")
    return campaign


def _time_weights(timestamps: np.ndarray) -> np.ndarray:
    previous = np.concatenate(([0.0], timestamps[:-1]))
    weights = timestamps - previous
    if np.any(weights <= 0):
        raise StabilityMetricError("timestamps must imply positive sample durations")
    return weights


def _orientation_drift(qpos: np.ndarray) -> np.ndarray:
    if qpos.shape[1] < 7:
        raise StabilityMetricError("qpos lacks the free-joint quaternion")
    quaternions = np.asarray(qpos[:, 3:7], dtype=np.float64)
    norms = np.linalg.norm(quaternions, axis=1)
    if np.any(norms <= 0):
        raise StabilityMetricError("trajectory contains a zero-norm root quaternion")
    quaternions = quaternions / norms[:, None]
    dots = np.clip(np.abs(quaternions @ quaternions[0]), 0.0, 1.0)
    return 2.0 * np.arccos(dots)


def _require_sensor(
    sensory: Mapping[str, np.ndarray], name: str, width: int | None = None
) -> np.ndarray:
    if name not in sensory:
        raise StabilityMetricError(f"required sensory observation is absent: {name}")
    values = np.asarray(sensory[name], dtype=np.float64)
    if width is not None and values.shape[1] != width:
        raise StabilityMetricError(
            f"sensory observation {name} has width {values.shape[1]}, expected {width}"
        )
    return values


def measure_trajectory(trajectory: PhysicalTrajectory) -> dict[str, Any]:
    """Extract descriptive technical metrics without deciding that a fly is stable."""

    timestamps = np.asarray(trajectory.timestamps_s, dtype=np.float64)
    qpos = np.asarray(trajectory.qpos, dtype=np.float64)
    qvel = np.asarray(trajectory.qvel, dtype=np.float64)
    commands = np.asarray(trajectory.actuator_commands, dtype=np.float64)
    neural = np.asarray(trajectory.neural_summary, dtype=np.float64)
    weights = _time_weights(timestamps)
    dt = np.diff(np.concatenate(([0.0], timestamps)))

    actuator_count = commands.shape[1]
    joint_state = _require_sensor(
        trajectory.sensory_observations, "joint_state", width=2 * actuator_count
    )
    contacts_flat = _require_sensor(
        trajectory.sensory_observations, "ground_contacts", width=6 * 16
    )
    actuator_forces = _require_sensor(
        trajectory.sensory_observations, "actuator_forces", width=actuator_count
    )
    joint_positions = joint_state[:, :actuator_count]
    joint_velocities = joint_state[:, actuator_count:]
    contacts = contacts_flat.reshape(len(timestamps), 6, 16)
    contact_flags = contacts[:, :, 0] > 0.5
    contact_count = contact_flags.sum(axis=1)
    orientation = _orientation_drift(qpos)
    root_delta = qpos[:, :3] - qpos[0, :3]
    root_displacement = np.linalg.norm(root_delta, axis=1)

    if neural.shape[1] < 6:
        raise StabilityMetricError("neural summary must contain the declared six columns")
    state_max_abs = np.maximum(np.abs(neural[:, 2]), np.abs(neural[:, 3]))

    if len(timestamps) > 1:
        slew = np.diff(commands, axis=0) / np.diff(timestamps)[:, None]
        slew_l2 = np.linalg.norm(slew, axis=1)
        command_slew = {
            "available": True,
            "rms_l2_per_s": float(np.sqrt(np.mean(slew_l2**2))),
            "peak_l2_per_s": float(np.max(slew_l2)),
            "maximum_channel_abs_per_s": float(np.max(np.abs(slew))),
        }
    else:
        command_slew = {
            "available": False,
            "reason": "at_least_two_frames_required",
        }

    force_velocity_power = actuator_forces * joint_velocities
    transitions_by_leg = np.count_nonzero(
        contact_flags[1:] != contact_flags[:-1], axis=0
    ) if len(timestamps) > 1 else np.zeros(6, dtype=int)

    arrays = [qpos, qvel, commands, neural, joint_state, contacts_flat, actuator_forces]
    finite_count = sum(int(np.isfinite(values).sum()) for values in arrays)
    value_count = sum(int(values.size) for values in arrays)

    return {
        "timebase": {
            "frames": int(len(timestamps)),
            "duration_s": float(timestamps[-1]),
            "dt_s": {
                "minimum": float(np.min(dt)),
                "median": float(np.median(dt)),
                "maximum": float(np.max(dt)),
                "peak_absolute_jitter_from_median": float(
                    np.max(np.abs(dt - np.median(dt)))
                ),
            },
        },
        "numerical": {
            "finite_fraction": finite_count / max(value_count, 1),
            "arrays_accounted": 7,
        },
        "central_summary": {
            "contract": [
                "mean",
                "std",
                "minimum",
                "maximum",
                "active_fraction_abs_gt_1e-4",
                "saturated_fraction_abs_gt_0_95",
            ],
            "maximum_absolute_state_summary": float(np.max(state_max_abs)),
            "maximum_population_std": float(np.max(neural[:, 1])),
            "active_fraction": {
                "minimum": float(np.min(neural[:, 4])),
                "median": float(np.median(neural[:, 4])),
                "maximum": float(np.max(neural[:, 4])),
            },
            "saturated_fraction": {
                "mean": float(np.mean(neural[:, 5])),
                "maximum": float(np.max(neural[:, 5])),
            },
        },
        "root_state": {
            "coordinate_units": "FlyBody_model_length_units_not_relabelled_as_SI",
            "translation_from_initial": {
                "peak_l2": float(np.max(root_displacement)),
                "final_l2": float(root_displacement[-1]),
                "axis_peak_absolute": [
                    float(value) for value in np.max(np.abs(root_delta), axis=0)
                ],
            },
            "height": {
                "minimum": float(np.min(qpos[:, 2])),
                "initial": float(qpos[0, 2]),
                "final": float(qpos[-1, 2]),
                "maximum": float(np.max(qpos[:, 2])),
            },
            "orientation_drift_rad": {
                "peak": float(np.max(orientation)),
                "final": float(orientation[-1]),
            },
            "linear_velocity_l2": {
                "rms": float(np.sqrt(np.mean(np.sum(qvel[:, :3] ** 2, axis=1)))),
                "peak": float(np.max(np.linalg.norm(qvel[:, :3], axis=1))),
            },
            "angular_velocity_l2": {
                "rms": float(np.sqrt(np.mean(np.sum(qvel[:, 3:6] ** 2, axis=1)))),
                "peak": float(np.max(np.linalg.norm(qvel[:, 3:6], axis=1))),
            },
        },
        "joints": {
            "channels": int(actuator_count),
            "position_abs_max": float(np.max(np.abs(joint_positions))),
            "velocity_abs_max": float(np.max(np.abs(joint_velocities))),
            "velocity_rms": float(np.sqrt(np.mean(joint_velocities**2))),
            "limit_violation_count": None,
            "limit_violation_status": "unavailable_trajectory_contract_lacks_joint_limits",
        },
        "contacts": {
            "legs": 6,
            "contacting_legs": {
                "minimum": int(np.min(contact_count)),
                "mean": float(np.mean(contact_count)),
                "maximum": int(np.max(contact_count)),
            },
            "frames_without_ground_contact": int(np.count_nonzero(contact_count == 0)),
            "frames_with_all_six_contacts": int(np.count_nonzero(contact_count == 6)),
            "transitions_by_leg": [int(value) for value in transitions_by_leg],
            "transition_count_total": int(np.sum(transitions_by_leg)),
        },
        "actuation": {
            "command_abs_max": float(np.max(np.abs(commands))),
            "command_l2_rms": float(
                np.sqrt(np.average(np.sum(commands**2, axis=1), weights=weights))
            ),
            "command_squared_effort_integral": float(
                np.sum(np.sum(commands**2, axis=1) * weights)
            ),
            "command_slew_not_body_jerk": command_slew,
            "direct_motor_abs_force_velocity_integral": float(
                np.sum(np.sum(np.abs(force_velocity_power), axis=1) * weights)
            ),
            "energy_interpretation": (
                "mixed-coordinate direct-motor work proxy; not metabolic or muscle energy"
            ),
        },
        "unavailable_metrics": {
            "center_of_mass_displacement": "trajectory records root position, not COM",
            "joint_limit_violations": "joint limits are absent from physical trajectory schema v1",
            "biological_actuator_energy": "direct MOTOR forces omit muscles and metabolism",
            "body_jerk": "command slew is not body acceleration jerk",
            "recovery_after_perturbation": "requires matched baseline and perturbed trajectories",
        },
    }


def run_metric_contract(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    run_root: Path = RUN_ROOT,
) -> dict[str, Any]:
    campaign = _load_campaign(campaign_path)
    input_spec = campaign["pinned_input"]
    trajectory_path = ROOT / input_spec["path"]

    print("[1/5] Validation du contrat diagnostique préenregistré", flush=True)
    actual_hash = _sha256(trajectory_path)
    expected_hash = str(input_spec["sha256"])
    if actual_hash != expected_hash:
        raise StabilityMetricError(
            f"pinned trajectory hash drifted: {actual_hash} != {expected_hash}"
        )
    print(f"[OK] trajectoire gelée {actual_hash}", flush=True)

    print("[2/5] Chargement du replay physique indépendant du contrôleur", flush=True)
    trajectory = PhysicalTrajectory.load(trajectory_path)
    required_label = str(input_spec["claim_label"])
    if trajectory.metadata.get("claim_label") != required_label:
        raise StabilityMetricError("trajectory claim label differs from the preregistration")
    print(
        f"[OK] {trajectory.frame_count} frames / {trajectory.duration_s:.3f} s / "
        f"{trajectory.actuator_commands.shape[1]} actionneurs",
        flush=True,
    )

    print("[3/5] Mesure numérique, corps, articulations, contacts et commandes", flush=True)
    metrics = measure_trajectory(trajectory)
    print(
        "[OK] "
        f"orientation pic={metrics['root_state']['orientation_drift_rad']['peak']:.6g} rad; "
        f"déplacement racine={metrics['root_state']['translation_from_initial']['peak_l2']:.6g}; "
        f"transitions contact={metrics['contacts']['transition_count_total']}",
        flush=True,
    )

    print("[4/5] Comptabilité des métriques encore non identifiables", flush=True)
    unavailable = metrics["unavailable_metrics"]
    print(
        "[ATTENTION] seuils de stabilité non choisis; "
        f"{len(unavailable)} métriques/interprétations restent explicitement indisponibles",
        flush=True,
    )

    run_id = f"stability-metrics-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    heavy_path = run_dir / "metrics.json"
    heavy_payload = {
        "schema_version": 1,
        "run_id": run_id,
        "campaign_id": campaign["id"],
        "trajectory": {"path": str(input_spec["path"]), "sha256": actual_hash},
        "trajectory_metadata": dict(trajectory.metadata),
        "metrics": metrics,
    }
    heavy_path.write_text(
        json.dumps(heavy_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    semantic_payload = {
        "input_sha256": actual_hash,
        "accounting": {
            "optimized_parameters": 0,
            "behavior_targets_exposed": 0,
            "stability_thresholds_selected": 0,
            "topology_changes": 0,
            "supported_metric_groups": 7,
            "unavailable_metric_interpretations": len(unavailable),
        },
        "metrics": metrics,
        "interpretation": {
            "metric_extraction_passed": True,
            "stability_accepted": False,
            "baseline_is_uncalibrated_comparator": True,
            "motion_is_biological_behavior": False,
            "thresholds_may_be_selected_from_this_trace": False,
            "root_translation_is_center_of_mass": False,
            "command_slew_is_body_jerk": False,
            "force_velocity_proxy_is_biological_energy": False,
        },
    }
    result = {
        "schema_version": 1,
        "id": "runner_result.embodied_stability_metric_contract.v0",
        "campaign_id": campaign["id"],
        "status": "descriptive_metric_contract_pass_stability_unresolved",
        "completed_at": datetime.now(UTC).isoformat(),
        "claim_label": "DESCRIPTIVE TECHNICAL METRICS / NOT STABILITY / NO BEHAVIOR",
        "input": {
            "path": str(input_spec["path"]),
            "sha256": actual_hash,
            "claim_label": required_label,
        },
        "accounting": semantic_payload["accounting"],
        "metrics": metrics,
        "interpretation": semantic_payload["interpretation"],
        "semantic_result_sha256": _semantic_hash(semantic_payload),
        "heavy_artifact": {
            "path": str(heavy_path.relative_to(ROOT)),
            "sha256": _sha256(heavy_path),
            "git_policy": "ignored_heavy_run_output",
        },
        "next_action": (
            "Before a stability campaign, version a trajectory contract that snapshots joint "
            "limits and a paired perturbation protocol; choose acceptance thresholds from "
            "independent physical/biological evidence, never from this uncalibrated baseline."
        ),
    }
    result_path.write_text(
        yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    print("[5/5] Résultat compact versionné et sortie détaillée ignorée", flush=True)
    print(f"[OK] {result_path.relative_to(ROOT)}", flush=True)
    print("[LIMITE] Mesurer ce replay ne valide ni stabilité, ni calibration, ni comportement.", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure preregistered technical stability observables on a physical replay"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    run_metric_contract(campaign_path=args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

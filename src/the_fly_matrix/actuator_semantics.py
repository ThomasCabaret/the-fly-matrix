from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from .ledger import ROOT
from .physical_trajectory import model_contract
from .runtime import (
    FLYBODY_ACTUATOR_CHANNEL_PATH,
    ActuatorCommands,
    FlyBodyGroundContactSensor,
    FlyBodyPhysicsLoop,
)


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "actuator-semantics-gate-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "actuator-semantics-gate-v0.yaml"
RUN_ROOT = ROOT / "runs" / "calibration" / "actuator-semantics-gate-v0"


class ActuatorSemanticsError(RuntimeError):
    pass


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _float_rows(values: np.ndarray) -> list[list[float]]:
    return np.asarray(values, dtype=np.float64).tolist()


def _enum_name(enum_type: Any, value: int) -> str:
    return enum_type(int(value)).name


def homolog_key(name: str) -> tuple[str, str | None]:
    """Return a side-neutral actuator name and its explicit left/right side."""

    replacements = (
        ("lf_", "{side}f_"),
        ("lm_", "{side}m_"),
        ("lh_", "{side}h_"),
        ("rf_", "{side}f_"),
        ("rm_", "{side}m_"),
        ("rh_", "{side}h_"),
        ("l_", "{side}_"),
        ("r_", "{side}_"),
    )
    sides = {"l": ("lf_", "lm_", "lh_", "l_"), "r": ("rf_", "rm_", "rh_", "r_")}
    side = next((key for key, tokens in sides.items() if any(token in name for token in tokens)), None)
    if side is None:
        return name, None
    result = name
    for token, replacement in replacements:
        if token in result:
            result = result.replace(token, replacement)
    return result, side


def _load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = yaml.safe_load(path.read_text(encoding="utf-8"))
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise ActuatorSemanticsError("actuator audit must remain diagnostic_only")
    if campaign.get("behavior_targets"):
        raise ActuatorSemanticsError("actuator audit cannot expose behavior targets")
    probe = campaign.get("probe", {})
    required = {"settle_ms", "impulse_ms", "step_ms", "release_ms", "command", "saturation_command"}
    missing = required - set(probe)
    if missing:
        raise ActuatorSemanticsError(f"campaign probe is missing {sorted(missing)}")
    return campaign


def _actuator_contract(loop: FlyBodyPhysicsLoop, channels: pd.DataFrame) -> dict[str, Any]:
    import mujoco

    model = loop.simulation.mj_model
    entries = []
    for index, row in channels.sort_values("control_address").iterrows():
        actuator_id = int(row["control_address"])
        entries.append(
            {
                "control_address": actuator_id,
                "actuator_name": str(row["actuator_name"]),
                "target_joint_name": str(row["target_joint_name"]),
                "body_group": str(row["body_group"]),
                "actuator_config_group": None
                if pd.isna(row["actuator_config_group"])
                else str(row["actuator_config_group"]),
                "actuator_config_status": str(row["actuator_config_status"]),
                "transmission_type": _enum_name(mujoco.mjtTrn, model.actuator_trntype[actuator_id]),
                "gain_type": _enum_name(mujoco.mjtGain, model.actuator_gaintype[actuator_id]),
                "bias_type": _enum_name(mujoco.mjtBias, model.actuator_biastype[actuator_id]),
                "dynamics_type": _enum_name(mujoco.mjtDyn, model.actuator_dyntype[actuator_id]),
                "gain_parameters": np.asarray(model.actuator_gainprm[actuator_id]).tolist(),
                "bias_parameters": np.asarray(model.actuator_biasprm[actuator_id]).tolist(),
                "dynamics_parameters": np.asarray(model.actuator_dynprm[actuator_id]).tolist(),
                "gear": np.asarray(model.actuator_gear[actuator_id]).tolist(),
                "control_limited": bool(model.actuator_ctrllimited[actuator_id]),
                "control_range": np.asarray(model.actuator_ctrlrange[actuator_id]).tolist(),
                "force_limited": bool(model.actuator_forcelimited[actuator_id]),
                "force_range": np.asarray(model.actuator_forcerange[actuator_id]).tolist(),
            }
        )
    contract = {
        "flygym_version": importlib.metadata.version("flygym"),
        "mujoco_version": mujoco.__version__,
        "physics_timestep_s": float(model.opt.timestep),
        "model": model_contract(loop),
        "actuators": entries,
    }
    contract["actuator_contract_sha256"] = _canonical_hash(contract)
    return contract


def _commands(loop: FlyBodyPhysicsLoop, index: int | None, value: float) -> ActuatorCommands:
    values = np.zeros(len(loop.actuator_names), dtype=np.float64)
    if index is not None:
        values[index] = value
    return ActuatorCommands(actuator_names=loop.actuator_names, values=values)


def _steps(milliseconds: float, timestep_s: float) -> int:
    steps = int(round(milliseconds / (1000.0 * timestep_s)))
    if steps < 1 or not np.isclose(steps * timestep_s * 1000.0, milliseconds, atol=1e-9):
        raise ActuatorSemanticsError(
            f"probe duration {milliseconds} ms is not an integer multiple of {timestep_s} s"
        )
    return steps


def _snapshot(loop: FlyBodyPhysicsLoop) -> dict[str, np.ndarray | float]:
    state = loop.read_joint_state()
    return {
        "positions": state.positions.copy(),
        "velocities": state.velocities.copy(),
        "time_s": float(loop.simulation.mj_data.time),
    }


def _passive_reference(
    loop: FlyBodyPhysicsLoop,
    sensor: FlyBodyGroundContactSensor,
    checkpoints: dict[str, int],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    loop.reset()
    zero = _commands(loop, None, 0.0)
    snapshots: dict[str, dict[str, Any]] = {"initial": _snapshot(loop)}
    elapsed = 0
    for name, absolute_step in sorted(checkpoints.items(), key=lambda item: item[1]):
        loop.step(zero, substeps=absolute_step - elapsed)
        elapsed = absolute_step
        snapshots[name] = _snapshot(loop)
    contact = loop.read_ground_contact_state(sensor)
    contact_summary = {
        "contacting_legs": int(np.count_nonzero(contact.contact_found)),
        "contact_flags": dict(zip(contact.leg_names, contact.contact_found.astype(float).tolist())),
        "force_l2": float(np.linalg.norm(contact.forces)),
    }
    return snapshots, contact_summary


def _trial(
    loop: FlyBodyPhysicsLoop,
    actuator_index: int,
    command: float,
    settle_steps: int,
    active_steps: int,
    release_steps: int,
) -> dict[str, Any]:
    loop.reset()
    zero = _commands(loop, None, 0.0)
    loop.step(zero, substeps=settle_steps)
    baseline = _snapshot(loop)
    active = loop.step(_commands(loop, actuator_index, command), substeps=active_steps)
    active_snapshot = _snapshot(loop)
    release = loop.step(zero, substeps=release_steps)
    release_snapshot = _snapshot(loop)
    return {
        "baseline": baseline,
        "active": active_snapshot,
        "release": release_snapshot,
        "active_force": float(active.actuator_forces[actuator_index]),
        "release_force": float(release.actuator_forces[actuator_index]),
    }


def _response_record(
    row: pd.Series,
    impulse: dict[str, Any],
    step: dict[str, Any],
    saturation_force: float,
    passive: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    joint_index = int(row["target_joint_id"])

    def delta(trial: dict[str, Any], checkpoint: str, passive_checkpoint: str) -> np.ndarray:
        return np.asarray(trial[checkpoint]["positions"]) - np.asarray(passive[passive_checkpoint]["positions"])

    impulse_active = delta(impulse, "active", "impulse_end")
    impulse_release = delta(impulse, "release", "release_end")
    step_active = delta(step, "active", "step_end")
    step_release = delta(step, "release", "release_end")
    config_group = None if pd.isna(row["actuator_config_group"]) else str(row["actuator_config_group"])
    return {
        "actuator_id": int(row["actuator_id"]),
        "actuator_name": str(row["actuator_name"]),
        "target_joint_name": str(row["target_joint_name"]),
        "body_group": str(row["body_group"]),
        "actuator_class": f"{row['body_group']}:{config_group or 'unconfigured'}",
        "impulse": {
            "force": impulse["active_force"],
            "target_joint_delta_at_end": float(impulse_active[joint_index]),
            "target_joint_delta_after_release": float(impulse_release[joint_index]),
            "all_joint_delta_l2_at_end": float(np.linalg.norm(impulse_active)),
            "all_joint_delta_l2_after_release": float(np.linalg.norm(impulse_release)),
        },
        "step": {
            "force": step["active_force"],
            "target_joint_delta_at_end": float(step_active[joint_index]),
            "target_joint_delta_after_release": float(step_release[joint_index]),
            "all_joint_delta_l2_at_end": float(np.linalg.norm(step_active)),
            "all_joint_delta_l2_after_release": float(np.linalg.norm(step_release)),
        },
        "saturation_force": saturation_force,
    }


def _summarize_responses(records: list[dict[str, Any]], command: float) -> dict[str, Any]:
    by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_class[record["actuator_class"]].append(record)
    class_summary = {}
    for class_id, items in sorted(by_class.items()):
        class_summary[class_id] = {
            "actuator_count": len(items),
            "step_target_delta_abs_median": float(
                np.median([abs(item["step"]["target_joint_delta_at_end"]) for item in items])
            ),
            "step_release_residual_abs_median": float(
                np.median([abs(item["step"]["target_joint_delta_after_release"]) for item in items])
            ),
            "impulse_target_delta_abs_median": float(
                np.median([abs(item["impulse"]["target_joint_delta_at_end"]) for item in items])
            ),
        }

    indexed = {record["actuator_name"]: record for record in records}
    pairs: dict[str, dict[str, str]] = defaultdict(dict)
    for name in indexed:
        key, side = homolog_key(name)
        if side:
            pairs[key][side] = name
    differences = []
    complete_pairs = 0
    for pair in pairs.values():
        if set(pair) != {"l", "r"}:
            continue
        complete_pairs += 1
        left = abs(indexed[pair["l"]]["step"]["target_joint_delta_at_end"])
        right = abs(indexed[pair["r"]]["step"]["target_joint_delta_at_end"])
        denominator = max(left, right, 1e-15)
        differences.append(abs(left - right) / denominator)

    return {
        "actuators_probed": len(records),
        "class_count": len(class_summary),
        "class_summary": class_summary,
        "nonzero_step_local_responses": int(sum(
            abs(item["step"]["target_joint_delta_at_end"]) > 1e-12 for item in records
        )),
        "force_matches_command": int(sum(
            np.isclose(item["step"]["force"], command, atol=1e-12) for item in records
        )),
        "force_limit_clipped_count": int(sum(
            np.isclose(abs(item["saturation_force"]), 0.01, atol=1e-12) for item in records
        )),
        "complete_homolog_pairs": complete_pairs,
        "homolog_step_abs_relative_difference": {
            "median": float(np.median(differences)) if differences else None,
            "maximum": float(np.max(differences)) if differences else None,
        },
    }


def run_actuator_semantics_audit(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    run_root: Path = RUN_ROOT,
) -> dict[str, Any]:
    campaign = _load_campaign(campaign_path)
    probe = campaign["probe"]
    channels = pd.read_csv(FLYBODY_ACTUATOR_CHANNEL_PATH).sort_values("control_address").reset_index(drop=True)
    if len(channels) != 102:
        raise ActuatorSemanticsError(f"expected 102 actuator channels, got {len(channels)}")

    run_id = f"actuator-semantics-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    print(f"[1/4] Chargement de FlyBody et gel du contrat de {len(channels)} actionneurs", flush=True)

    with FlyBodyPhysicsLoop.from_generated_wiring() as loop:
        contract = _actuator_contract(loop, channels)
        timestep = contract["physics_timestep_s"]
        settle_steps = _steps(float(probe["settle_ms"]), timestep)
        impulse_steps = _steps(float(probe["impulse_ms"]), timestep)
        step_steps = _steps(float(probe["step_ms"]), timestep)
        release_steps = _steps(float(probe["release_ms"]), timestep)
        checkpoints = {
            "settled": settle_steps,
            "impulse_end": settle_steps + impulse_steps,
            "step_end": settle_steps + step_steps,
            "release_end": settle_steps + step_steps + release_steps,
        }
        sensor = FlyBodyGroundContactSensor.from_generated_wiring()
        passive, contact = _passive_reference(loop, sensor, checkpoints)
        passive_drift = float(
            np.linalg.norm(
                np.asarray(passive["release_end"]["positions"])
                - np.asarray(passive["settled"]["positions"])
            )
        )
        print(
            f"[2/4] Référence passive: {contact['contacting_legs']}/6 pattes en contact; "
            f"dérive articulaire L2={passive_drift:.6g}",
            flush=True,
        )

        records = []
        command = float(probe["command"])
        saturation_command = float(probe["saturation_command"])
        zero = _commands(loop, None, 0.0)
        for actuator_index, row in channels.iterrows():
            impulse = _trial(loop, actuator_index, command, settle_steps, impulse_steps, release_steps)
            step = _trial(loop, actuator_index, command, settle_steps, step_steps, release_steps)
            loop.reset()
            loop.step(zero, substeps=settle_steps)
            saturated = loop.step(_commands(loop, actuator_index, saturation_command), substeps=1)
            records.append(
                _response_record(
                    row,
                    impulse,
                    step,
                    float(saturated.actuator_forces[actuator_index]),
                    passive,
                )
            )
            if (actuator_index + 1) % 10 == 0 or actuator_index + 1 == len(channels):
                print(f"      {actuator_index + 1:3d}/{len(channels)} canaux sondés", flush=True)

    inventory = contract["actuators"]
    inventory_summary = {
        "actuator_count": len(inventory),
        "transmission_types": dict(Counter(item["transmission_type"] for item in inventory)),
        "gain_types": dict(Counter(item["gain_type"] for item in inventory)),
        "bias_types": dict(Counter(item["bias_type"] for item in inventory)),
        "dynamics_types": dict(Counter(item["dynamics_type"] for item in inventory)),
        "force_limited_count": sum(item["force_limited"] for item in inventory),
        "control_limited_count": sum(item["control_limited"] for item in inventory),
        "missing_configuration_count": sum(
            item["actuator_config_status"] != "configured" for item in inventory
        ),
    }
    response_summary = _summarize_responses(records, command)
    accepted_local = bool(
        inventory_summary["actuator_count"] == 102
        and inventory_summary["transmission_types"] == {"mjTRN_JOINT": 102}
        and inventory_summary["gain_types"] == {"mjGAIN_FIXED": 102}
        and inventory_summary["bias_types"] == {"mjBIAS_NONE": 102}
        and inventory_summary["dynamics_types"] == {"mjDYN_NONE": 102}
        and inventory_summary["force_limited_count"] == 102
        and response_summary["force_matches_command"] == 102
        and response_summary["force_limit_clipped_count"] == 102
        and response_summary["nonzero_step_local_responses"] == 102
    )
    full_result = {
        "schema_version": 1,
        "run_id": run_id,
        "campaign_id": campaign["id"],
        "claim_label": campaign["claim_label"],
        "accepted_local_open_loop_mechanics": accepted_local,
        "scientific_gate_closed": False,
        "unrun_required_metric": "open_loop_closed_loop_response_gap",
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "probe": probe,
        "contract": contract,
        "inventory_summary": inventory_summary,
        "passive": {
            "contact": contact,
            "joint_position_drift_l2": passive_drift,
            "snapshots": {
                key: {name: _float_rows(value) if np.asarray(value).ndim == 2 else np.asarray(value).tolist() if isinstance(value, np.ndarray) else value for name, value in snapshot.items()}
                for key, snapshot in passive.items()
            },
        },
        "response_summary": response_summary,
        "responses": records,
        "decision": {
            "status": "partial_local_mechanical_attribution_pass_closed_feedback_pending"
            if accepted_local
            else "local_mechanical_probe_failed",
            "supports": [
                "The resolved runtime uses force-limited direct joint motors with no internal actuator bias or activation dynamics.",
                "Every channel produces a measurable local joint response in the fixed standard-ground scene.",
            ],
            "does_not_support": [
                "biological muscle fidelity",
                "adequacy of the motor transfer box",
                "closed-loop MaleCNS causal attribution",
                "any behavior claim",
            ],
            "next_action": "Replay one frozen command trace open-loop and through the accepted closed MaleCNS/body loop, then attribute the response gap without freeing motor or mechanics parameters.",
        },
    }
    artifact_path = run_dir / "result.json"
    artifact_path.write_text(json.dumps(full_result, indent=2, sort_keys=True), encoding="utf-8")
    artifact_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    compact = {
        "schema_version": 1,
        "id": "runner_result.actuator_semantics_gate.v0",
        "campaign_id": campaign["id"],
        "target_id": campaign["target_id"],
        "run_id": run_id,
        "status": full_result["decision"]["status"],
        "claim_label": campaign["claim_label"],
        "behavior_targets": [],
        "actuator_contract_sha256": contract["actuator_contract_sha256"],
        "model_contract_sha256": contract["model"]["contract_sha256"],
        "inventory_summary": inventory_summary,
        "passive_summary": {
            "contacting_legs": contact["contacting_legs"],
            "joint_position_drift_l2": passive_drift,
        },
        "response_summary": response_summary,
        "accepted_local_open_loop_mechanics": accepted_local,
        "scientific_gate_closed": False,
        "unrun_required_metric": "open_loop_closed_loop_response_gap",
        "artifact": {"path": str(artifact_path.relative_to(ROOT)), "sha256": artifact_sha256},
        "decision": full_result["decision"],
    }
    result_path.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")
    print("[3/4] Résumé et preuves lourdes écrits sans paramètre calibré", flush=True)
    print(
        f"[4/4] local_open_loop={'PASS' if accepted_local else 'FAIL'}; "
        "gate_global=OPEN (comparaison boucle fermée non exécutée)",
        flush=True,
    )
    print(f"[ARTEFACT] {artifact_path}", flush=True)
    print(f"[RÉSULTAT COMPACT] {result_path}", flush=True)
    return compact


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit behavior-naive of the resolved FlyBody actuator semantics"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    result = run_actuator_semantics_audit(campaign_path=args.campaign)
    return 0 if result["accepted_local_open_loop_mechanics"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from .actuator_attribution import _build_tethered_loop
from .actuator_semantics import _commands, _steps
from .ledger import ROOT
from .runtime import FLYBODY_ACTUATOR_CHANNEL_PATH


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "motor-actuator-bridge-envelope-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "motor-actuator-bridge-envelope-v0.yaml"
OUTPUT_ROOT = ROOT / "data" / "derived" / "calibration" / "motor-actuator-bridge-envelope-v0"
ROUTE_PATH = ROOT / "data" / "derived" / "wiring" / "motor-actuator-candidates.parquet"
MOTOR_FIT_PATH = ROOT / "calibration" / "evaluations" / "motor-spike-force-pilot-fit-v0.yaml"
ACTUATOR_RESULT_PATH = ROOT / "calibration" / "runner" / "actuator-causal-attribution-v1.yaml"


class MotorActuatorBridgeError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = yaml.safe_load(path.read_text(encoding="utf-8"))
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise MotorActuatorBridgeError("bridge envelope must remain diagnostic_only")
    if campaign.get("behavior_targets"):
        raise MotorActuatorBridgeError("bridge envelope cannot expose behavior targets")
    if campaign.get("topology_changes_allowed") is not False:
        raise MotorActuatorBridgeError("bridge envelope cannot change topology")
    if campaign.get("selection_policy", {}).get("promote_reference_gain") is not False:
        raise MotorActuatorBridgeError("bridge envelope cannot promote a reference gain")
    return campaign


def derive_conditional_gain_envelope(
    *,
    force_candidates_uN: Mapping[str, float],
    worst_detectable_command: float,
    command_guard: float,
    candidate_count: int,
) -> dict[str, Any]:
    """Derive a technical gain interval conditional on unpromoted force evidence.

    The lower bound makes the weakest diagnostic force visible on every scoped
    actuator.  The upper bound keeps the strongest force below a preregistered
    fraction of the fixed MuJoCo force limit.  Neither bound estimates a muscle
    moment arm, so the resulting interval is a surrogate ensemble, not biology.
    """

    forces = {str(key): float(value) for key, value in force_candidates_uN.items()}
    if not forces or any(not np.isfinite(value) or value <= 0 for value in forces.values()):
        raise MotorActuatorBridgeError("force candidates must be finite and strictly positive")
    if not np.isfinite(worst_detectable_command) or worst_detectable_command <= 0:
        raise MotorActuatorBridgeError("worst detectable command must be positive")
    if not np.isfinite(command_guard) or command_guard <= 0:
        raise MotorActuatorBridgeError("command guard must be positive")
    if candidate_count < 2:
        raise MotorActuatorBridgeError("at least two gain candidates are required")

    weakest = min(forces.items(), key=lambda item: item[1])
    strongest = max(forces.items(), key=lambda item: item[1])
    lower = worst_detectable_command / weakest[1]
    upper = command_guard / strongest[1]
    feasible = bool(lower <= upper)
    gains = np.geomspace(lower, upper, candidate_count).tolist() if feasible else []
    projections = {
        name: [float(force * gain) for gain in gains]
        for name, force in sorted(forces.items())
    }
    return {
        "weakest_force_candidate": {"id": weakest[0], "value_uN": weakest[1]},
        "strongest_force_candidate": {"id": strongest[0], "value_uN": strongest[1]},
        "lower_gain_command_per_uN": float(lower),
        "upper_gain_command_per_uN": float(upper),
        "interval_ratio": float(upper / lower),
        "feasible": feasible,
        "candidate_gains_command_per_uN": gains,
        "projected_commands": projections,
    }


def _verify_inputs(
    campaign: Mapping[str, Any], campaign_path: Path
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float], dict[str, str]]:
    fit = yaml.safe_load(MOTOR_FIT_PATH.read_text(encoding="utf-8"))
    observed_forces = {
        str(key): float(value)
        for key, value in fit["procedure_readiness"]["fitted_slopes_uN_per_spike"].items()
    }
    declared_forces = {
        str(key): float(value)
        for key, value in campaign["conditional_force_evidence"]["diagnostic_uN_per_spike"].items()
    }
    if observed_forces != declared_forces:
        raise MotorActuatorBridgeError("diagnostic force evidence drifted")

    actuator_result = yaml.safe_load(ACTUATOR_RESULT_PATH.read_text(encoding="utf-8"))
    expected_contract = str(campaign["frozen_inputs"]["actuator_contract_sha256"])
    observed_contract = str(actuator_result["frozen_inputs"]["actuator_contract_sha256"])
    if observed_contract != expected_contract:
        raise MotorActuatorBridgeError("actuator contract drifted")
    if not actuator_result.get("passed"):
        raise MotorActuatorBridgeError("bounded direct-motor surrogate gate is not accepted")

    body_ids = {int(value) for value in campaign["scope"]["motor_body_ids"]}
    routes = pd.read_parquet(ROUTE_PATH)
    scoped_routes = routes[routes["source_body_id"].isin(body_ids)].copy()
    if set(scoped_routes["source_body_id"].astype(int)) != body_ids:
        raise MotorActuatorBridgeError("not every scoped motor body has candidate routes")
    expected_rows = int(campaign["scope"]["expected_candidate_routes"])
    if len(scoped_routes) != expected_rows:
        raise MotorActuatorBridgeError(
            f"expected {expected_rows} candidate routes, found {len(scoped_routes)}"
        )
    per_body = scoped_routes.groupby("source_body_id")["target_actuator_id"].nunique()
    expected_per_body = int(campaign["scope"]["expected_actuators_per_body"])
    if not (per_body == expected_per_body).all():
        raise MotorActuatorBridgeError("candidate actuator count drifted for a motor body")
    actuator_ids = set(scoped_routes["target_actuator_id"].astype(int))
    expected_actuators = int(campaign["scope"]["expected_unique_actuators"])
    if len(actuator_ids) != expected_actuators:
        raise MotorActuatorBridgeError(
            f"expected {expected_actuators} unique actuators, found {len(actuator_ids)}"
        )

    channels = pd.read_csv(FLYBODY_ACTUATOR_CHANNEL_PATH)
    scoped_channels = channels[channels["actuator_id"].isin(actuator_ids)].copy()
    if set(scoped_channels["actuator_id"].astype(int)) != actuator_ids:
        raise MotorActuatorBridgeError("actuator channel inventory does not cover the route scope")
    hashes = {
        "campaign_sha256": _sha256(campaign_path),
        "motor_fit_sha256": _sha256(MOTOR_FIT_PATH),
        "actuator_result_sha256": _sha256(ACTUATOR_RESULT_PATH),
        "route_table_sha256": _sha256(ROUTE_PATH),
    }
    return scoped_routes, scoped_channels.sort_values("actuator_id"), observed_forces, hashes


def _probe_tethered_commands(
    channels: pd.DataFrame,
    *,
    command_grid: list[float],
    settle_ms: float,
    step_ms: float,
    minimum_joint_delta_rad: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with _build_tethered_loop() as loop:
        timestep = float(loop.simulation.mj_model.opt.timestep)
        settle_steps = _steps(settle_ms, timestep)
        active_steps = _steps(step_ms, timestep)
        zero = _commands(loop, None, 0.0)
        loop.reset()
        loop.step(zero, substeps=settle_steps)
        passive = loop.step(zero, substeps=active_steps).joint_state.positions.copy()

        for row_index, row in channels.reset_index(drop=True).iterrows():
            actuator_id = int(row["actuator_id"])
            joint_id = int(row["target_joint_id"])
            for command in command_grid:
                loop.reset()
                loop.step(zero, substeps=settle_steps)
                active = loop.step(_commands(loop, actuator_id, command), substeps=active_steps)
                delta = float(active.joint_state.positions[joint_id] - passive[joint_id])
                records.append(
                    {
                        "actuator_id": actuator_id,
                        "actuator_name": str(row["actuator_name"]),
                        "target_joint_name": str(row["target_joint_name"]),
                        "command": command,
                        "actuator_force": float(active.actuator_forces[actuator_id]),
                        "target_joint_delta_rad": delta,
                        "detectable": abs(delta) >= minimum_joint_delta_rad,
                    }
                )
            print(
                f"      {row_index + 1:2d}/{len(channels)} actionneurs; "
                f"{len(command_grid)} commandes chacun",
                flush=True,
            )

    frame = pd.DataFrame(records)
    force_error = float(np.max(np.abs(frame["actuator_force"] - frame["command"])))
    detectable = frame[frame["detectable"]]
    minimum_by_actuator = (
        detectable.groupby("actuator_id")["command"].min().to_dict()
        if not detectable.empty
        else {}
    )
    ratios = frame.loc[frame["detectable"], "target_joint_delta_rad"].abs() / frame.loc[
        frame["detectable"], "command"
    ]
    summary = {
        "actuators_probed": int(frame["actuator_id"].nunique()),
        "commands_per_actuator": len(command_grid),
        "trials": len(frame),
        "maximum_force_command_abs_error": force_error,
        "actuators_with_detectable_response": len(minimum_by_actuator),
        "minimum_detectable_command_by_actuator": {
            str(key): float(value) for key, value in sorted(minimum_by_actuator.items())
        },
        "worst_minimum_detectable_command": (
            float(max(minimum_by_actuator.values())) if minimum_by_actuator else None
        ),
        "lowest_tested_command": float(min(command_grid)),
        "detection_floor_censored_actuators": int(
            sum(value == min(command_grid) for value in minimum_by_actuator.values())
        ),
        "detectable_response_per_command_abs": {
            "minimum": float(ratios.min()) if len(ratios) else None,
            "median": float(ratios.median()) if len(ratios) else None,
            "maximum": float(ratios.max()) if len(ratios) else None,
        },
    }
    return records, summary


def run_motor_actuator_bridge_envelope(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    campaign = _load_campaign(campaign_path)
    print("[1/5] Gel des preuves, de la topologie et du contrat actionneur", flush=True)
    routes, channels, forces, hashes = _verify_inputs(campaign, campaign_path)
    print(
        f"[OK] {routes['source_body_id'].nunique()} corps moteurs, {len(routes)} routes candidates, "
        f"{len(channels)} actionneurs",
        flush=True,
    )

    probe = campaign["mechanical_probe"]
    command_grid = [float(value) for value in probe["command_grid"]]
    print("[2/5] Mesure tethered du seuil local commande -> articulation", flush=True)
    records, mechanical = _probe_tethered_commands(
        channels,
        command_grid=command_grid,
        settle_ms=float(probe["settle_ms"]),
        step_ms=float(probe["step_ms"]),
        minimum_joint_delta_rad=float(probe["minimum_joint_delta_rad"]),
    )

    expected_actuators = int(campaign["scope"]["expected_unique_actuators"])
    if mechanical["actuators_with_detectable_response"] != expected_actuators:
        raise MotorActuatorBridgeError("not every scoped actuator has a detectable local response")
    if mechanical["maximum_force_command_abs_error"] > float(probe["force_command_atol"]):
        raise MotorActuatorBridgeError("direct-motor force no longer matches its command")

    print("[3/5] Calcul de l'enveloppe de gain conditionnelle", flush=True)
    hard_limit = float(campaign["frozen_inputs"]["direct_motor_force_limit_abs"])
    guard_fraction = float(campaign["selection_policy"]["maximum_force_limit_fraction"])
    envelope = derive_conditional_gain_envelope(
        force_candidates_uN=forces,
        worst_detectable_command=float(mechanical["worst_minimum_detectable_command"]),
        command_guard=hard_limit * guard_fraction,
        candidate_count=int(campaign["selection_policy"]["reported_candidate_count"]),
    )
    if not envelope["feasible"]:
        raise MotorActuatorBridgeError("no gain is both locally detectable and below the command guard")

    print("[4/5] Ecriture de l'artefact et du resultat compact", flush=True)
    artifact = {
        "schema_version": 1,
        "campaign_id": campaign["id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "claim_label": campaign["claim_label"],
        "status": "accepted_conditional_engineering_gain_ensemble_no_reference_selected",
        "hashes": hashes,
        "scope": {
            "motor_body_ids": sorted(routes["source_body_id"].astype(int).unique().tolist()),
            "candidate_routes": len(routes),
            "actuator_ids": sorted(channels["actuator_id"].astype(int).tolist()),
        },
        "conditional_force_evidence": forces,
        "mechanical_probe": mechanical,
        "conditional_gain_envelope": envelope,
        "accounting": {
            "promoted_parameter_values": 0,
            "selected_reference_gains": 0,
            "optimized_parameters": 0,
            "behavior_targets_exposed": 0,
            "topology_changes": 0,
            "command_offsets_allowed": 0,
        },
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    artifact["semantic_result_sha256"] = _canonical_hash(
        {key: value for key, value in artifact.items() if key != "generated_at"}
    )
    output_root.mkdir(parents=True, exist_ok=True)
    artifact_path = output_root / "summary.json"
    records_path = output_root / "mechanical-probes.csv"
    artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    pd.DataFrame(records).to_csv(records_path, index=False)
    compact = {
        "schema_version": 1,
        "id": "runner_result.motor_actuator_bridge_envelope.v0",
        "campaign_id": campaign["id"],
        "target_id": campaign["target_id"],
        "status": artifact["status"],
        "claim_label": campaign["claim_label"],
        "command": "motor_actuator_bridge_envelope.bat",
        "behavior_targets": [],
        "hashes": hashes,
        "scope": artifact["scope"],
        "mechanical_probe": mechanical,
        "conditional_gain_envelope": envelope,
        "accounting": artifact["accounting"],
        "artifact_ref": str(artifact_path.relative_to(ROOT)).replace("\\", "/"),
        "semantic_result_sha256": artifact["semantic_result_sha256"],
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    result_path.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")
    print("[5/5] Resume", flush=True)
    print(
        f"[OK] {mechanical['trials']} essais; {expected_actuators}/{expected_actuators} "
        "actionneurs detectables",
        flush=True,
    )
    print(
        f"[ENSEMBLE] gain conditionnel {envelope['lower_gain_command_per_uN']:.6g} .. "
        f"{envelope['upper_gain_command_per_uN']:.6g} commande/uN",
        flush=True,
    )
    print("[BOUNDARY] 0 valeur promue; conversion biologique toujours non identifiee", flush=True)
    print(f"[HASH] {artifact['semantic_result_sha256']}", flush=True)
    return compact


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure a conditional force-to-direct-motor surrogate gain envelope"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    run_motor_actuator_bridge_envelope(args.campaign, output_root=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

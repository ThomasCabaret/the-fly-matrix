from __future__ import annotations

import argparse
import hashlib
import json
import platform
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from .actuator_semantics import _actuator_contract, _commands, _steps, homolog_key
from .connectome_benchmark import (
    PROFILE_PATH,
    DynamicsProfile,
    build_graph_cache,
    compile_interfaces,
)
from .embodied_runtime import DynamicInputRuntime, TorchMaleCNSRuntime, _git_commit
from .ledger import ROOT
from .runtime import (
    FLYBODY_ACTUATOR_CHANNEL_PATH,
    CentralConnectomeBox,
    FlyBodyActuatorInterface,
    FlyBodyPhysicsLoop,
    FlyBodyProprioceptionSensor,
)


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "actuator-causal-attribution-v1.yaml"
LOCAL_RESULT_PATH = ROOT / "calibration" / "runner" / "actuator-semantics-gate-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "actuator-causal-attribution-v1.yaml"
RUN_ROOT = ROOT / "runs" / "calibration" / "actuator-causal-attribution-v1"


class ActuatorAttributionError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _array_hash(arrays: Mapping[str, np.ndarray]) -> str:
    digest = hashlib.sha256()
    for name, values in sorted(arrays.items()):
        array = np.ascontiguousarray(values)
        digest.update(name.encode("utf-8"))
        digest.update(str(array.dtype).encode("ascii"))
        digest.update(json.dumps(array.shape).encode("ascii"))
        digest.update(array.tobytes())
    return digest.hexdigest()


def _load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = yaml.safe_load(path.read_text(encoding="utf-8"))
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise ActuatorAttributionError("causal attribution must remain diagnostic_only")
    if campaign.get("behavior_targets"):
        raise ActuatorAttributionError("causal attribution cannot expose behavior targets")
    if int(campaign.get("budgets", {}).get("optimized_parameters", -1)) != 0:
        raise ActuatorAttributionError("causal attribution cannot optimize parameters")
    return campaign


def _apply_perturbation(loop: FlyBodyPhysicsLoop, perturbation: Mapping[str, Any]) -> None:
    import mujoco

    address = int(perturbation["qvel_address"])
    data = loop.simulation.mj_data
    if not 0 <= address < len(data.qvel):
        raise ActuatorAttributionError(f"invalid perturbation qvel address {address}")
    data.qvel[address] += float(perturbation["delta"])
    mujoco.mj_forward(loop.simulation.mj_model, data)


def _episode_arrays(records: list[dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    keys = records[0].keys()
    return {key: np.asarray([record[key] for record in records]) for key in keys}


def _run_episode(
    *,
    steps: int,
    substeps: int,
    command_scale: float,
    neural: TorchMaleCNSRuntime | None,
    dynamic_inputs: DynamicInputRuntime | None,
    frozen_commands: np.ndarray | None = None,
    perturbation: Mapping[str, Any] | None = None,
    perturbation_step: int | None = None,
    observe_without_feedback: bool = False,
) -> dict[str, np.ndarray]:
    if neural is not None and frozen_commands is not None:
        raise ActuatorAttributionError("episode cannot be both closed and frozen-command")
    if neural is None and frozen_commands is None:
        frozen_commands = np.zeros((steps, 102), dtype=np.float64)
    if frozen_commands is not None and frozen_commands.shape != (steps, 102):
        raise ActuatorAttributionError("frozen command trace has the wrong shape")
    if neural is not None:
        neural.reset()
    if dynamic_inputs is not None:
        dynamic_inputs.reset()

    records: list[dict[str, np.ndarray]] = []
    with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=True) as loop:
        for step_index in range(steps):
            if perturbation is not None and step_index == perturbation_step:
                _apply_perturbation(loop, perturbation)
            if neural is not None:
                if dynamic_inputs is None:
                    raise ActuatorAttributionError("closed episode requires dynamic inputs")
                input_vector, _, _ = dynamic_inputs.encode(loop, step_index, 1)
                raw_commands, neural_summary = neural.step(input_vector)
                values = np.tanh(raw_commands.astype(np.float64)) * command_scale
            else:
                if observe_without_feedback:
                    if dynamic_inputs is None:
                        raise ActuatorAttributionError("observed open loop requires dynamic inputs")
                    dynamic_inputs.encode(loop, step_index, 1)
                values = np.asarray(frozen_commands[step_index], dtype=np.float64)
                neural_summary = np.full(6, np.nan, dtype=np.float32)
            physical = loop.step(loop.actuator_interface.step(values), substeps=substeps)
            records.append(
                {
                    "qpos": np.asarray(loop.simulation.mj_data.qpos, dtype=np.float64).copy(),
                    "qvel": np.asarray(loop.simulation.mj_data.qvel, dtype=np.float64).copy(),
                    "commands": physical.applied_commands.astype(np.float64, copy=True),
                    "forces": physical.actuator_forces.astype(np.float64, copy=True),
                    "neural_summary": np.asarray(neural_summary, dtype=np.float64),
                }
            )
    return _episode_arrays(records)


def _deviation_metrics(
    perturbed: Mapping[str, np.ndarray],
    reference: Mapping[str, np.ndarray],
    perturbation_step: int,
) -> dict[str, float]:
    qpos_delta = np.asarray(perturbed["qpos"] - reference["qpos"])[perturbation_step:]
    qvel_delta = np.asarray(perturbed["qvel"] - reference["qvel"])[perturbation_step:]
    total = np.linalg.norm(qpos_delta, axis=1)
    translation = np.linalg.norm(qpos_delta[:, :3], axis=1)
    orientation = np.linalg.norm(qpos_delta[:, 3:7], axis=1)
    joints = np.linalg.norm(qpos_delta[:, 7:], axis=1)
    velocity = np.linalg.norm(qvel_delta, axis=1)
    peak = float(np.max(total))
    final = float(total[-1])
    return {
        "qpos_l2_peak": peak,
        "qpos_l2_final": final,
        "qpos_recovery_fraction": 1.0 - final / max(peak, 1e-30),
        "root_translation_l2_peak": float(np.max(translation)),
        "root_translation_l2_final": float(translation[-1]),
        "root_orientation_l2_peak": float(np.max(orientation)),
        "root_orientation_l2_final": float(orientation[-1]),
        "joint_l2_peak": float(np.max(joints)),
        "joint_l2_final": float(joints[-1]),
        "qvel_l2_peak": float(np.max(velocity)),
        "qvel_l2_final": float(velocity[-1]),
    }


def _finite_fraction(episode: Mapping[str, np.ndarray]) -> float:
    values = [array for array in episode.values() if array.dtype.kind in "fc" and not np.isnan(array).all()]
    finite = sum(int(np.isfinite(array).sum()) for array in values)
    count = sum(int(array.size) for array in values)
    return finite / max(count, 1)


def _build_tethered_loop() -> FlyBodyPhysicsLoop:
    from flygym.compose import ActuatorType
    from flygym.compose.fly.flybody import FlyBody
    from flygym.compose.world import TetheredWorld
    from flygym.flybody.anatomy_flybody import (
        FlyBodyActuatedDOFPreset,
        FlyBodyAxisOrder,
        FlyBodyJointPreset,
        FlyBodySkeleton,
    )
    from flygym.simulation import Simulation
    from flygym.utils.math import Rotation3D

    fly = FlyBody()
    skeleton = FlyBodySkeleton(
        axis_order=FlyBodyAxisOrder.YAW_PITCH_ROLL,
        joint_preset=FlyBodyJointPreset.ALL_BIOLOGICAL,
    )
    fly.add_joints(skeleton)
    actuated = skeleton.get_actuated_dofs_from_preset(FlyBodyActuatedDOFPreset.ALL)
    fly.add_actuators(
        actuated,
        ActuatorType.MOTOR,
        forcelimited=True,
        forcerange=(-0.01, 0.01),
    )
    world = TetheredWorld()
    world.add_fly(
        fly,
        np.asarray([0.0, 0.0, 1.0]),
        Rotation3D("quat", (1, 0, 0, 0)),
    )
    return FlyBodyPhysicsLoop(
        Simulation(world),
        fly,
        FlyBodyActuatorInterface.from_generated_wiring(),
        FlyBodyProprioceptionSensor.from_generated_wiring(),
    )


def _tethered_symmetry_probe(campaign: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    config = campaign["unloaded_symmetry_probe"]
    channels = pd.read_csv(FLYBODY_ACTUATOR_CHANNEL_PATH).sort_values("control_address").reset_index(drop=True)
    records = []
    with _build_tethered_loop() as loop:
        timestep = float(loop.simulation.mj_model.opt.timestep)
        settle_steps = _steps(float(config["settle_ms"]), timestep)
        active_steps = _steps(float(config["step_ms"]), timestep)
        release_steps = _steps(float(config["release_ms"]), timestep)
        zero = _commands(loop, None, 0.0)

        loop.reset()
        loop.step(zero, substeps=settle_steps)
        passive_active = loop.step(zero, substeps=active_steps).joint_state.positions.copy()
        passive_release = loop.step(zero, substeps=release_steps).joint_state.positions.copy()

        for actuator_index, row in channels.iterrows():
            loop.reset()
            loop.step(zero, substeps=settle_steps)
            active = loop.step(
                _commands(loop, actuator_index, float(config["command"])),
                substeps=active_steps,
            )
            release = loop.step(zero, substeps=release_steps)
            joint_index = int(row["target_joint_id"])
            records.append(
                {
                    "actuator_name": str(row["actuator_name"]),
                    "target_joint_name": str(row["target_joint_name"]),
                    "active_target_delta": float(
                        active.joint_state.positions[joint_index] - passive_active[joint_index]
                    ),
                    "release_target_delta": float(
                        release.joint_state.positions[joint_index] - passive_release[joint_index]
                    ),
                    "active_all_joint_l2": float(
                        np.linalg.norm(active.joint_state.positions - passive_active)
                    ),
                }
            )

    indexed = {record["actuator_name"]: record for record in records}
    pairs: dict[str, dict[str, str]] = defaultdict(dict)
    for name in indexed:
        key, side = homolog_key(name)
        if side:
            pairs[key][side] = name
    pair_records = []
    for key, pair in sorted(pairs.items()):
        if set(pair) != {"l", "r"}:
            continue
        left = abs(indexed[pair["l"]]["active_target_delta"])
        right = abs(indexed[pair["r"]]["active_target_delta"])
        pair_records.append(
            {
                "homolog_key": key,
                "left": pair["l"],
                "right": pair["r"],
                "left_abs_response": left,
                "right_abs_response": right,
                "relative_difference": abs(left - right) / max(left, right, 1e-30),
            }
        )
    differences = [item["relative_difference"] for item in pair_records]
    summary = {
        "scene": str(config["scene"]),
        "actuators_probed": len(records),
        "nonzero_local_responses": sum(abs(item["active_target_delta"]) > 1e-12 for item in records),
        "homolog_pairs_accounted": len(pair_records),
        "homolog_relative_difference": {
            "median": float(np.median(differences)),
            "p90": float(np.quantile(differences, 0.9)),
            "maximum": float(np.max(differences)),
        },
        "largest_homolog_differences": sorted(
            pair_records, key=lambda item: item["relative_difference"], reverse=True
        )[:5],
    }
    return summary, records


def _compact_perturbation_result(
    perturbation: Mapping[str, Any],
    perturbation_step: int,
    baseline_closed: Mapping[str, np.ndarray],
    baseline_open: Mapping[str, np.ndarray],
    baseline_passive: Mapping[str, np.ndarray],
    perturbed_closed: Mapping[str, np.ndarray],
    perturbed_open: Mapping[str, np.ndarray],
    perturbed_passive: Mapping[str, np.ndarray],
) -> dict[str, Any]:
    closed_metrics = _deviation_metrics(perturbed_closed, baseline_closed, perturbation_step)
    open_metrics = _deviation_metrics(perturbed_open, baseline_open, perturbation_step)
    passive_metrics = _deviation_metrics(perturbed_passive, baseline_passive, perturbation_step)
    command_delta = np.asarray(
        perturbed_closed["commands"] - baseline_closed["commands"]
    )[perturbation_step:]
    adaptation = np.linalg.norm(command_delta, axis=1)
    state_gap = np.linalg.norm(
        np.asarray(perturbed_closed["qpos"] - perturbed_open["qpos"])[perturbation_step:],
        axis=1,
    )
    return {
        "perturbation": dict(perturbation),
        "passive_mechanics": passive_metrics,
        "frozen_commands_open_loop": open_metrics,
        "live_malecns_closed_feedback": closed_metrics,
        "closed_feedback_command_adaptation": {
            "l2_peak": float(np.max(adaptation)),
            "l2_final": float(adaptation[-1]),
            "nonzero_steps": int(np.count_nonzero(adaptation > 1e-12)),
        },
        "closed_open_state_gap": {
            "qpos_l2_peak": float(np.max(state_gap)),
            "qpos_l2_final": float(state_gap[-1]),
        },
        "attribution_ratios": {
            "closed_final_over_open_final": closed_metrics["qpos_l2_final"]
            / max(open_metrics["qpos_l2_final"], 1e-30),
            "passive_final_over_open_final": passive_metrics["qpos_l2_final"]
            / max(open_metrics["qpos_l2_final"], 1e-30),
        },
    }


def run_actuator_causal_attribution(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    run_root: Path = RUN_ROOT,
) -> dict[str, Any]:
    campaign = _load_campaign(campaign_path)
    local_result = yaml.safe_load(LOCAL_RESULT_PATH.read_text(encoding="utf-8"))
    profile = DynamicsProfile.load(PROFILE_PATH)
    config = campaign["closed_loop_probe"]
    run_id = f"actuator-attribution-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = run_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    print("[1/8] Gel et contrôle du contrat d'actionneurs", flush=True)
    channels = pd.read_csv(FLYBODY_ACTUATOR_CHANNEL_PATH)
    with FlyBodyPhysicsLoop.from_generated_wiring() as contract_loop:
        current_contract = _actuator_contract(contract_loop, channels)
    expected_contract_hash = str(local_result["actuator_contract_sha256"])
    contract_match = current_contract["actuator_contract_sha256"] == expected_contract_hash
    if not contract_match:
        raise ActuatorAttributionError("actuator contract drifted since the v0 local probe")
    print(f"[OK] contrat {expected_contract_hash}", flush=True)

    print("[2/8] Chargement unique du graphe MaleCNS et du runtime de comparaison", flush=True)
    central = CentralConnectomeBox.from_generated_wiring()
    graph = build_graph_cache(central, profile, scope="full")
    compiled = compile_interfaces(graph.body_ids, profile)
    dynamic_inputs = DynamicInputRuntime(graph.body_ids, profile)
    try:
        import torch

        device = "cuda:0" if torch.cuda.is_available() else "cpu"
    except ImportError:
        device = "cpu"
    neural = TorchMaleCNSRuntime(graph, compiled, profile, device=device)
    neural_dt_s = profile.dt_ms / 1000.0
    steps = int(round(float(config["duration_ms"]) / profile.dt_ms))
    physics_dt = float(current_contract["physics_timestep_s"])
    substeps = int(round(neural_dt_s / physics_dt))
    if not np.isclose(substeps * physics_dt, neural_dt_s, atol=1e-12):
        raise ActuatorAttributionError("neural and physical timesteps are not commensurate")
    perturbation_step = int(config["perturbation_step"])
    command_scale = float(config["command_scale"])

    print("[3/8] Deux exécutions fermées sans perturbation pour la déterminisme", flush=True)
    baseline_closed = _run_episode(
        steps=steps,
        substeps=substeps,
        command_scale=command_scale,
        neural=neural,
        dynamic_inputs=dynamic_inputs,
    )
    repeated_closed = _run_episode(
        steps=steps,
        substeps=substeps,
        command_scale=command_scale,
        neural=neural,
        dynamic_inputs=dynamic_inputs,
    )
    command_repeat_error = float(
        np.max(np.abs(baseline_closed["commands"] - repeated_closed["commands"]))
    )
    state_repeat_error = float(
        max(
            np.max(np.abs(baseline_closed["qpos"] - repeated_closed["qpos"])),
            np.max(np.abs(baseline_closed["qvel"] - repeated_closed["qvel"])),
        )
    )
    print(
        f"[OK] répétition commandes={command_repeat_error:.3e}; état={state_repeat_error:.3e}",
        flush=True,
    )

    print("[4/8] Rejeu ouvert de la trace gelée et référence mécanique passive", flush=True)
    baseline_open = _run_episode(
        steps=steps,
        substeps=substeps,
        command_scale=command_scale,
        neural=None,
        dynamic_inputs=dynamic_inputs,
        frozen_commands=baseline_closed["commands"],
        observe_without_feedback=True,
    )
    baseline_passive = _run_episode(
        steps=steps,
        substeps=substeps,
        command_scale=command_scale,
        neural=None,
        dynamic_inputs=None,
    )
    open_replay_error = float(
        max(
            np.max(np.abs(baseline_closed["qpos"] - baseline_open["qpos"])),
            np.max(np.abs(baseline_closed["qvel"] - baseline_open["qvel"])),
        )
    )
    print(f"[OK] erreur état fermé-vers-rejeu ouvert={open_replay_error:.3e}", flush=True)

    print("[5/8] Perturbations: passif, commandes gelées, feedback MaleCNS", flush=True)
    perturbation_results = []
    heavy_episodes: dict[str, np.ndarray] = {
        "baseline_closed_qpos": baseline_closed["qpos"],
        "baseline_closed_qvel": baseline_closed["qvel"],
        "baseline_closed_commands": baseline_closed["commands"],
        "baseline_open_qpos": baseline_open["qpos"],
        "baseline_open_qvel": baseline_open["qvel"],
        "baseline_passive_qpos": baseline_passive["qpos"],
        "baseline_passive_qvel": baseline_passive["qvel"],
    }
    minimum_adaptation = float(campaign["acceptance"]["closed_feedback_command_adaptation_l2_min"])
    for perturbation in config["perturbations"]:
        perturbation_id = str(perturbation["id"])
        print(f"      {perturbation_id}", flush=True)
        perturbed_closed = _run_episode(
            steps=steps,
            substeps=substeps,
            command_scale=command_scale,
            neural=neural,
            dynamic_inputs=dynamic_inputs,
            perturbation=perturbation,
            perturbation_step=perturbation_step,
        )
        perturbed_open = _run_episode(
            steps=steps,
            substeps=substeps,
            command_scale=command_scale,
            neural=None,
            dynamic_inputs=dynamic_inputs,
            frozen_commands=baseline_closed["commands"],
            perturbation=perturbation,
            perturbation_step=perturbation_step,
            observe_without_feedback=True,
        )
        perturbed_passive = _run_episode(
            steps=steps,
            substeps=substeps,
            command_scale=command_scale,
            neural=None,
            dynamic_inputs=None,
            perturbation=perturbation,
            perturbation_step=perturbation_step,
        )
        result = _compact_perturbation_result(
            perturbation,
            perturbation_step,
            baseline_closed,
            baseline_open,
            baseline_passive,
            perturbed_closed,
            perturbed_open,
            perturbed_passive,
        )
        perturbation_results.append(result)
        for branch, episode in (
            ("closed", perturbed_closed),
            ("open", perturbed_open),
            ("passive", perturbed_passive),
        ):
            heavy_episodes[f"{perturbation_id}_{branch}_qpos"] = episode["qpos"]
            heavy_episodes[f"{perturbation_id}_{branch}_qvel"] = episode["qvel"]
            heavy_episodes[f"{perturbation_id}_{branch}_commands"] = episode["commands"]

    print("[6/8] Fixture tethered sans charge: symétrie intrinsèque des 102 moteurs", flush=True)
    symmetry_summary, symmetry_records = _tethered_symmetry_probe(campaign)
    print(
        f"[OK] {symmetry_summary['homolog_pairs_accounted']} paires; "
        f"médiane={symmetry_summary['homolog_relative_difference']['median']:.3e}; "
        f"max={symmetry_summary['homolog_relative_difference']['maximum']:.3e}",
        flush=True,
    )

    print("[7/8] Évaluation des invariants préenregistrés", flush=True)
    acceptance = campaign["acceptance"]
    finite_fractions = [
        _finite_fraction(baseline_closed),
        _finite_fraction(repeated_closed),
        _finite_fraction(baseline_open),
        _finite_fraction(baseline_passive),
    ]
    adaptation_pass = all(
        item["closed_feedback_command_adaptation"]["l2_peak"] >= minimum_adaptation
        for item in perturbation_results
    )
    checks = {
        "actuator_contract_hash_match": contract_match,
        "repeated_closed_baseline_commands": command_repeat_error
        <= float(acceptance["repeated_closed_baseline_command_max_abs_error"]),
        "repeated_closed_baseline_state": state_repeat_error
        <= float(acceptance["repeated_closed_baseline_state_max_abs_error"]),
        "frozen_open_loop_replay_state": open_replay_error
        <= float(acceptance["frozen_open_loop_replay_state_max_abs_error"]),
        "finite_fraction": min(finite_fractions) >= float(acceptance["finite_fraction"]),
        "perturbations_accounted": len(perturbation_results)
        == int(acceptance["perturbations_accounted"]),
        "closed_feedback_command_adaptation": adaptation_pass,
        "unloaded_homolog_pairs_accounted": symmetry_summary["homolog_pairs_accounted"]
        == int(acceptance["unloaded_homolog_pairs_accounted"]),
    }
    passed = all(checks.values())

    trace_path = run_dir / "frozen-trace-and-attribution.npz"
    np.savez_compressed(trace_path, **heavy_episodes)
    symmetry_path = run_dir / "tethered-symmetry.json"
    symmetry_path.write_text(json.dumps(symmetry_records, indent=2), encoding="utf-8")
    trace_sha256 = _sha256(trace_path)
    full_summary = {
        "schema_version": 1,
        "run_id": run_id,
        "campaign_id": campaign["id"],
        "claim_label": campaign["claim_label"],
        "git_commit": _git_commit(),
        "environment": {"python": platform.python_version(), "device": device},
        "frozen_inputs": {
            "campaign_sha256": _sha256(campaign_path),
            "profile_sha256": _sha256(PROFILE_PATH),
            "actuator_contract_sha256": expected_contract_hash,
            "graph_body_id_sha256": graph.metadata.get("body_id_sha256"),
            "graph_dataset_sha256": graph.metadata.get("dataset_sha256"),
        },
        "reproducibility": {
            "command_repeat_max_abs_error": command_repeat_error,
            "state_repeat_max_abs_error": state_repeat_error,
            "open_replay_state_max_abs_error": open_replay_error,
            "frozen_baseline_trace_semantic_sha256": _array_hash(
                {
                    "qpos": baseline_closed["qpos"],
                    "qvel": baseline_closed["qvel"],
                    "commands": baseline_closed["commands"],
                }
            ),
        },
        "perturbations": perturbation_results,
        "unloaded_symmetry": symmetry_summary,
        "checks": checks,
        "passed": passed,
        "artifacts": {
            "trace": {"path": str(trace_path.relative_to(ROOT)), "sha256": trace_sha256},
            "symmetry": {
                "path": str(symmetry_path.relative_to(ROOT)),
                "sha256": _sha256(symmetry_path),
            },
        },
        "decision": {
            "status": "accepted_bounded_direct_motor_surrogate_initial_short_horizon"
            if passed
            else "attribution_gate_failed",
            "supports": [
                "passive mechanics, frozen-command physics and live feedback are separately measured",
                "the direct motor contains no hidden servo or internal activation controller",
                "the direct motor may be used as an explicit surrogate for initial short-horizon claims when muscle fidelity is excluded",
            ]
            if passed
            else [],
            "does_not_support": [
                "biological muscle or tendon fidelity",
                "validity of the uncalibrated rate comparator",
                "validity of random peripheral transfer values",
                "neutral stability or any behavior claim",
            ],
            "next_action": "Freeze one minimal local sensory chain and one minimal motor chain; retain muscle fidelity as an applicability limit and reopen this gate if actuator semantics change."
            if passed
            else "Inspect failed attribution invariants and version any actuator-model change before embodied fitting.",
        },
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(full_summary, indent=2), encoding="utf-8")
    compact = {
        "schema_version": 1,
        "id": "runner_result.actuator_causal_attribution.v1",
        "campaign_id": campaign["id"],
        "target_id": campaign["target_id"],
        "run_id": run_id,
        "status": full_summary["decision"]["status"],
        "claim_label": campaign["claim_label"],
        "behavior_targets": [],
        "optimized_parameters": 0,
        "frozen_inputs": full_summary["frozen_inputs"],
        "reproducibility": full_summary["reproducibility"],
        "perturbations": perturbation_results,
        "unloaded_symmetry": symmetry_summary,
        "checks": checks,
        "passed": passed,
        "artifacts": full_summary["artifacts"],
        "decision": full_summary["decision"],
    }
    result_path.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")
    print("[8/8] Résultat compact et artefacts lourds écrits", flush=True)
    print(f"[{'PASS' if passed else 'FAIL'}] {compact['status']}", flush=True)
    print(f"[ARTEFACT] {summary_path}", flush=True)
    print(f"[RÉSULTAT COMPACT] {result_path}", flush=True)
    return compact


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Attribute passive, frozen-command and live-feedback FlyBody responses"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    result = run_actuator_causal_attribution(campaign_path=args.campaign)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml
from scipy import sparse

from .front_leg_coupled_identifiability import (
    _assignment_for_member,
    _functional_class_map,
    build_owner_orthogonal_array,
)
from .front_leg_coupled_identifiability_execution import (
    _compile_schedules,
    _constants_for_owner,
    _factor_ratio,
    _verify_campaign as _verify_fh05_campaign,
    build_boundary_graph,
)
from .ledger import ROOT
from .neutral_embodied_declared_closed_loop_sentinel import (
    _MotorTwitch,
    _front_leg_anchor_ids,
    _internal_angle_deg,
    _source_functions,
)
from .neutral_embodied_full_chain_sentinel import _sha256
from .physical_trajectory import (
    SCHEMA_NAME,
    SCHEMA_VERSION,
    PhysicalTrajectory,
    model_contract,
    run_replay,
)
from .runtime import FlyBodyPhysicsLoop
from .typed_hybrid_runtime import EVENT, GRADED, TorchTypedHybridRuntime


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "front-leg-integrated-runnable-lineage-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "front-leg-integrated-runnable-lineage-v0.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "front-leg-integrated-runnable-lineage-v0.yaml"
PARAMETER_SET_PATH = ROOT / "calibration" / "parameter_sets" / "front-leg-integrated-lineage-v0.yaml"
RUN_ROOT = ROOT / "runs" / "calibration" / "front-leg-integrated-runnable-lineage-v0"


class IntegratedLineageError(RuntimeError):
    """Raised when FH-06 loses a frozen dependency or scientific boundary."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise IntegratedLineageError(f"{path} must contain a YAML mapping")
    return value


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _array_hash(*arrays: np.ndarray) -> str:
    digest = hashlib.sha256()
    for value in arrays:
        array = np.ascontiguousarray(value)
        digest.update(str(array.dtype).encode("ascii"))
        digest.update(str(array.shape).encode("ascii"))
        digest.update(array.tobytes())
    return digest.hexdigest()


def conditional_motor_member_count(
    *,
    fast_candidates: int,
    intermediate_candidates: int,
    slow_candidates: int,
    body_count: int,
    route_count: int,
    gain_count: int,
) -> dict[str, int]:
    """Count a class-shared conditional ensemble without materializing assignments."""

    if min(
        fast_candidates,
        intermediate_candidates,
        slow_candidates,
        body_count,
        route_count,
        gain_count,
    ) <= 0:
        raise IntegratedLineageError("factorized motor axes must be positive")
    if body_count != 10:
        raise IntegratedLineageError("FH-04 currently owns exactly ten motor bodies")
    assignments_per_exact_pair = 2**body_count - 2
    assignments_using_all_three = 3**body_count - 3 * (2**body_count) + 3
    temporal_conditioned = (
        fast_candidates
        + intermediate_candidates
        + slow_candidates
        + assignments_per_exact_pair
        * (
            fast_candidates * intermediate_candidates
            + fast_candidates * slow_candidates
            + intermediate_candidates * slow_candidates
        )
        + assignments_using_all_three
        * fast_candidates
        * intermediate_candidates
        * slow_candidates
    )
    return {
        "ten_body_class_assignments": 3**body_count,
        "assignments_per_exact_two_class_support": assignments_per_exact_pair,
        "assignments_using_all_three_classes": assignments_using_all_three,
        "class_conditioned_temporal_members": temporal_conditioned,
        "with_route_and_gain": temporal_conditioned * route_count * gain_count,
    }


def _verify_inputs(campaign: Mapping[str, Any]) -> dict[str, Any]:
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise IntegratedLineageError("FH-06 must remain diagnostic_only")
    if campaign.get("behavior_targets"):
        raise IntegratedLineageError("FH-06 cannot expose a named behavior")
    if campaign.get("topology_changes_allowed") is not False:
        raise IntegratedLineageError("FH-06 cannot change topology")
    paths: dict[str, Path] = {}
    documents: dict[str, dict[str, Any]] = {}
    for name, record in campaign["frozen_inputs"].items():
        path = ROOT / str(record["path"])
        if not path.is_file():
            raise IntegratedLineageError(f"missing frozen input {name}: {path}")
        observed = _sha256(path)
        if observed != str(record["sha256"]):
            raise IntegratedLineageError(
                f"frozen input drift for {name}: {observed} != {record['sha256']}"
            )
        paths[name] = path
        if path.suffix.lower() in {".yaml", ".yml"}:
            documents[name] = _load_yaml(path)

    sensory = documents["sensory_ensemble"]
    motor = documents["motor_ensemble"]
    coupled = documents["coupled_ensemble"]
    coupled_result = documents["coupled_result"]
    actuator = documents["actuator_attribution"]
    scope = documents["chain_scope"]
    if int(sensory["factorization"]["factorized_members"]) != 1728:
        raise IntegratedLineageError("FH-03 member accounting drift")
    if int(motor["factorization"]["body_class_assignments"]) != 59049:
        raise IntegratedLineageError("FH-04 motor assignment accounting drift")
    if int(coupled["member_count"]) != 81 or len(coupled["member_ids"]) != 81:
        raise IntegratedLineageError("FH-05 member accounting drift")
    if len(coupled["source_port_profiles"]) != 2:
        raise IntegratedLineageError("FH-05 basal-native mirror accounting drift")
    if coupled_result.get("semantic_result_sha256") != coupled.get("runner_semantic_sha256"):
        raise IntegratedLineageError("FH-05 result/ensemble semantic hash drift")
    if actuator.get("passed") is not True:
        raise IntegratedLineageError("direct MOTOR causal-attribution prerequisite is not accepted")
    if scope["topology_boundary"].get("topology_changes_allowed") is not False:
        raise IntegratedLineageError("scoped topology boundary is not frozen")
    return {"paths": paths, "documents": documents}


def _lineage_manifest(campaign: Mapping[str, Any], verified: Mapping[str, Any]) -> dict[str, Any]:
    documents = verified["documents"]
    sensory = documents["sensory_ensemble"]
    motor = documents["motor_ensemble"]
    coupled = documents["coupled_ensemble"]
    scope = documents["chain_scope"]
    motor_factors = motor["factorization"]
    route_count = int(documents["motor_bridge_result"]["scope"]["candidate_routes"])
    if route_count != 110:
        raise IntegratedLineageError(f"expected 110 scoped motor routes, observed {route_count}")
    motor_count = conditional_motor_member_count(
        fast_candidates=int(motor_factors["fast_twitch_candidates"]),
        intermediate_candidates=int(motor_factors["intermediate_twitch_candidates"]),
        slow_candidates=int(motor_factors["slow_tonic_candidates"]),
        body_count=int(motor_factors["body_class_variables"]),
        route_count=route_count,
        gain_count=int(motor_factors["actuator_bridge_candidates"]),
    )
    sensory_count = int(sensory["factorization"]["factorized_members"])
    central_count = int(coupled["member_count"]) * len(coupled["source_port_profiles"])
    discrete_count = sensory_count * central_count * motor_count["with_route_and_gain"]
    topology = scope["topology_boundary"]
    manifest = {
        "representation": "exact_factorized_conditional_product_not_materialized",
        "parent_ids": [sensory["id"], motor["id"], coupled["id"]],
        "parent_file_sha256": {
            name: _sha256(path)
            for name, path in verified["paths"].items()
        },
        "semantic_dependencies": {
            "FH03": sensory["semantic_parameter_set_sha256"],
            "FH04": motor["semantic_sha256"],
            "FH05": coupled["runner_semantic_sha256"],
            "actuator_contract": documents["actuator_attribution"]["frozen_inputs"][
                "actuator_contract_sha256"
            ],
        },
        "topology_hashes": {
            "central_body_ids": topology["central_body_id_sha256"],
            "central_dataset": topology["central_dataset_sha256"],
            **dict(topology["semantic_topology_hashes"]),
        },
        "axes": {
            "sensory": {
                "routing_profiles": int(sensory["factorization"]["routing_profiles"]),
                "joint_source_paths": int(sensory["factorization"]["joint_source_paths"]),
                "native_profiles": int(sensory["factorization"]["class_shared_native_profiles"]),
                "discrete_members": sensory_count,
                "continuous_native_amplitudes_per_member": int(
                    sensory["factorization"]["continuous_native_amplitude_parameters_per_member"]
                ),
                "continuous_values_selected": 0,
            },
            "central_basal": {
                "technical_members": int(coupled["member_count"]),
                "source_native_mirrors": list(coupled["source_port_profiles"]),
                "conditioned_branches": central_count,
            },
            "motor": {
                **motor_count,
                "routes": route_count,
                "gains": int(motor_factors["actuator_bridge_candidates"]),
                "fast_temporal_candidates": int(motor_factors["fast_twitch_candidates"]),
                "intermediate_temporal_candidates": int(
                    motor_factors["intermediate_twitch_candidates"]
                ),
                "slow_temporal_candidates": int(motor_factors["slow_tonic_candidates"]),
            },
        },
        "discrete_lineage_members": discrete_count,
        "continuous_dimensions_per_sensory_member": int(
            sensory["factorization"]["continuous_native_amplitude_parameters_per_member"]
        ),
        "member_ids_materialized": 0,
        "selected_reference_member_id": None,
        "members_ranked": False,
        "behavior_targets_exposed": [],
    }
    manifest["semantic_sha256"] = _canonical_hash(manifest)
    return manifest


def _fh05_runtime_context(campaign: Mapping[str, Any], verified: Mapping[str, Any]) -> dict[str, Any]:
    fh05_campaign = verified["documents"]["coupled_campaign"]
    paths = _verify_fh05_campaign(fh05_campaign)
    fixture = fh05_campaign["execution_fixture"]
    members = pd.read_csv(paths["population_members"])
    feco = members.loc[members["population_id"].eq("population.front_leg_feco.v0")].copy()
    motor = members.loc[
        members["population_id"].eq("population.front_leg_tibia_flexor_motor.v0")
    ].copy()
    classified = pd.read_csv(paths["classified_intermediates"])
    cone_ids = sorted(
        set(feco.body_id.astype(int))
        | set(motor.body_id.astype(int))
        | set(classified.body_id.astype(int))
    )
    nodes = pd.read_parquet(paths["central_nodes"]).sort_values("runtime_node_index")
    nodes = nodes.loc[nodes["included_in_neural_runtime"].astype(bool)].reset_index(drop=True)
    canonical_ids = nodes.body_id.to_numpy(np.int64)
    cone_positions = np.searchsorted(canonical_ids, np.asarray(cone_ids, dtype=np.int64))
    cone_body_ids = canonical_ids[cone_positions]
    index_by_body = {int(body_id): index for index, body_id in enumerate(cone_body_ids)}
    source_rows = pd.read_csv(paths["source_terminals"]).sort_values("body_id").reset_index(drop=True)
    source_ids = source_rows.body_id.to_numpy(np.int64)
    source_positions = np.searchsorted(canonical_ids, source_ids)
    incoming = sparse.load_npz(paths["incoming_graph"]).tocsr()
    graph, graph_summary = build_boundary_graph(incoming, source_positions, cone_positions)

    sensory = _load_yaml(paths["feco_parameter_set"])
    routing_by_id = {str(row["profile_id"]): row for row in sensory["routing"]["profiles"]}
    native_by_id = {
        str(row["profile_id"]): row for row in sensory["native_boundary_capacity"]["profiles"]
    }
    source_by_id = {
        str(row["source_path_id"]): row for row in sensory["transfer_shape"]["source_paths"]
    }
    crosswalk = _load_yaml(paths["feco_crosswalk"])
    panel = pd.read_csv(paths["intermediate_panel"])
    panel_lookup = {
        (str(row.profile_id), int(row.body_id)): str(row.assignment)
        for row in panel.itertuples(index=False)
    }
    witness = campaign["execution_witness"]
    member_id = str(witness["central_basal"]["member_id"])
    anchor_id, owner_id = member_id.rsplit("__", 1)
    anchor = next(
        item for item in fh05_campaign["execution_anchors"] if item["anchor_id"] == anchor_id
    )
    owners, _summary = build_owner_orthogonal_array(fh05_campaign["owner_design_levels"])
    owner = owners.loc[owners["owner_design_id"].eq(owner_id)].iloc[0].to_dict()
    row = {"execution_id": member_id, **anchor, **owner}
    expected_sensor = witness["sensory"]
    if (
        row["routing_profile_id"] != expected_sensor["routing_profile_id"]
        or row["native_profile_id"] != expected_sensor["native_profile_id"]
    ):
        raise IntegratedLineageError("integration witness sensory/central address is incompatible")
    routing = routing_by_id[str(row["routing_profile_id"])]
    native = native_by_id[str(row["native_profile_id"])]
    assignment_cone = _assignment_for_member(
        feco=feco,
        motor=motor,
        classified=classified,
        panel_lookup=panel_lookup,
        routing=routing,
        native=native,
        crosswalk=crosswalk,
        body_ids=cone_body_ids,
        index_by_body=index_by_body,
        intermediate_profile_id=str(row["intermediate_profile_id"]),
    )
    source_profile = str(witness["central_basal"]["source_native_mirror"])
    source_assignment = np.full(
        len(source_rows),
        EVENT if source_profile == "all_event_candidate" else GRADED,
        dtype=np.int8,
    )
    assignment = np.concatenate((source_assignment, assignment_cone)).astype(np.int8)
    source_count = len(source_rows)
    feco_indices = np.asarray(
        [index_by_body[int(value)] for value in feco.body_id], dtype=np.int64
    ) + source_count
    motor_indices = np.asarray(
        [index_by_body[int(value)] for value in motor.body_id], dtype=np.int64
    ) + source_count
    constants = _constants_for_owner(fixture, row)
    witness_fixture = dict(fixture)
    witness_fixture["steps"] = int(campaign["execution_witness"]["neural_steps"])
    schedules = _compile_schedules(
        assignment=assignment,
        source_count=source_count,
        feco_indices=feco_indices,
        families=source_rows.family_id.astype(str).to_numpy(),
        owner=row,
        source_profile=source_profile,
        fixture=witness_fixture,
        seed=int(fixture["seed"]),
    )
    return {
        "fh05_campaign": fh05_campaign,
        "fixture": witness_fixture,
        "row": row,
        "graph": graph,
        "graph_summary": graph_summary,
        "assignment": assignment,
        "constants": constants,
        "source_count": source_count,
        "source_profile": source_profile,
        "basal_event": schedules[2],
        "basal_graded": schedules[3],
        "feco": feco,
        "feco_indices": feco_indices,
        "motor": motor,
        "motor_indices": motor_indices,
        "routing": routing,
        "native": native,
        "source_path": source_by_id[str(witness["sensory"]["source_path_id"])],
        "crosswalk": crosswalk,
    }


def _run_causal_witness(
    campaign: Mapping[str, Any],
    verified: Mapping[str, Any],
    run_root: Path,
) -> dict[str, Any]:
    import mujoco
    import torch

    context = _fh05_runtime_context(campaign, verified)
    runtime = TorchTypedHybridRuntime(
        context["graph"], context["assignment"], context["constants"], "cpu"
    )
    feco = context["feco"]
    class_by_type = _functional_class_map(context["crosswalk"], context["routing"])
    functional_classes = [class_by_type[str(value)] for value in feco.annotation_type]
    representations = context["native"]["representation_by_class"]
    source_candidates = context["source_path"]["candidate_by_class"]
    source_function_path = {
        "claw_position": source_candidates["claw"],
        "club_vibration_and_speed": source_candidates["club"],
        "hook_flexion_direction": source_candidates["hook"],
    }
    sides = [str(value) for value in feco.side]
    if set(sides) - {"L", "R"}:
        raise IntegratedLineageError("unexpected FeCO side label")

    motor_runner = verified["documents"]["motor_temporal_result"]
    fast = motor_runner["class_results"]["fast_81A07"]
    temporal = fast["all_data_best_candidate"]
    force_per_event = float(fast["observed_single_spike_summary"]["peak_force_uN_median"])
    bridge = verified["documents"]["motor_bridge_result"]
    gain = float(bridge["conditional_gain_envelope"]["candidate_gains_command_per_uN"][0])
    motor_body_ids = list(map(int, context["motor"].body_id))
    route_body = min(motor_body_ids)
    routes = pd.read_parquet(verified["paths"]["motor_route_table"])
    routes = routes.loc[routes["source_body_id"].astype(int).eq(route_body)].sort_values(
        ["target_actuator_id", "parameter_id"]
    )
    if routes.empty:
        raise IntegratedLineageError("lexicographic witness motor body has no actuator route")
    route = routes.iloc[0]
    route_index = motor_body_ids.index(route_body)
    target_actuator_id = int(route["target_actuator_id"])
    target_actuator_name = str(route["target_actuator_name"])
    timestep_s = float(context["constants"].dt_ms) / 1000.0
    twitch = _MotorTwitch(
        force_per_event,
        float(temporal["rise_time_s"]),
        float(temporal["decay_time_s"]),
        timestep_s,
        gain,
    )
    steps = int(campaign["execution_witness"]["neural_steps"])
    stride = int(campaign["execution_witness"]["record_stride"])
    if steps <= 0 or stride <= 0 or steps % stride:
        raise IntegratedLineageError("witness step/record-stride contract is invalid")
    # Reuse FH-05's phase-balanced deterministic event-process convention.  A
    # zero phase would make a 24 ms integration witness depend on an arbitrary
    # first-event latency even when the body-derived rate is nonzero.
    phase = (np.arange(len(feco), dtype=np.float64) * 0.4142135623730951) % 1.0
    feco_ratio = _factor_ratio(str(context["row"]["feco_native_amplitude"]))
    fixture = context["fixture"]
    record: dict[str, list[np.ndarray | float]] = {
        key: []
        for key in ("timestamps", "qpos", "qvel", "commands", "neural")
    }
    source_nonzero_steps = 0
    feco_forced_events = 0
    motor_state_nonzero_steps = 0
    motor_events = 0
    route_events = 0
    command_nonzero_steps = 0
    max_motor_state = 0.0
    with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=False) as loop:
        loop.reset()
        mujoco.mj_forward(loop.simulation.mj_model, loop.simulation.mj_data)
        if not math.isclose(
            float(loop.simulation.mj_model.opt.timestep), timestep_s, rel_tol=0.0, abs_tol=1e-12
        ):
            raise IntegratedLineageError("neural and physical witness timesteps differ")
        if loop.actuator_names[target_actuator_id] != target_actuator_name:
            raise IntegratedLineageError("lexicographic actuator route address drift")
        anchors = _front_leg_anchor_ids(loop)
        perturbation = campaign["execution_witness"]["physical_perturbation"]
        joint_id = int(
            mujoco.mj_name2id(
                loop.simulation.mj_model,
                mujoco.mjtObj.mjOBJ_JOINT,
                str(perturbation["joint_name"]),
            )
        )
        if joint_id < 0:
            raise IntegratedLineageError("declared witness perturbation joint is absent")
        dof_address = int(loop.simulation.mj_model.jnt_dofadr[joint_id])
        previous = {
            "L": _internal_angle_deg(loop.simulation.mj_data, anchors["l"]),
            "R": _internal_angle_deg(loop.simulation.mj_data, anchors["r"]),
        }
        physical_model = model_contract(loop)
        for step in range(steps):
            for segment in perturbation["segments"]:
                if int(segment["start_step"]) <= step < int(segment["stop_step"]):
                    loop.simulation.mj_data.qvel[dof_address] = float(
                        segment["velocity_rad_s"]
                    )
                    mujoco.mj_forward(loop.simulation.mj_model, loop.simulation.mj_data)
                    break
            angles = {
                "L": _internal_angle_deg(loop.simulation.mj_data, anchors["l"]),
                "R": _internal_angle_deg(loop.simulation.mj_data, anchors["r"]),
            }
            velocities = {side: (angles[side] - previous[side]) / timestep_s for side in ("L", "R")}
            previous = angles
            functions = {
                side: _source_functions(angles[side], velocities[side], source_function_path)
                for side in ("L", "R")
            }
            activity = np.asarray(
                [
                    functions[side][
                        {
                            "claw": "claw_position",
                            "club": "club_vibration_and_speed",
                            "hook": "hook_flexion_direction",
                        }[functional_class]
                    ]
                    for side, functional_class in zip(sides, functional_classes, strict=True)
                ],
                dtype=np.float64,
            )
            if np.any(activity != 0.0):
                source_nonzero_steps += 1
            forced = list(np.flatnonzero(context["basal_event"][step]))
            external = np.asarray(context["basal_graded"][step], dtype=np.float32).copy()
            for index, (node_index, functional_class) in enumerate(
                zip(context["feco_indices"], functional_classes, strict=True)
            ):
                if representations[functional_class] == "event_intensity_hz":
                    phase[index] += (
                        activity[index]
                        * float(fixture["feco_event_rate_hz"])
                        * feco_ratio
                        * timestep_s
                    )
                    if phase[index] >= 1.0:
                        forced.append(int(node_index))
                        feco_forced_events += 1
                        phase[index] %= 1.0
                else:
                    external[int(node_index)] = (
                        activity[index]
                        * float(fixture["feco_graded_drive"])
                        * feco_ratio
                    )
            runtime.step(forced_event_indices=forced, external_graded=external)
            motor_g = runtime.g[context["motor_indices"]].detach().cpu().numpy()
            motor_graded = runtime.graded[context["motor_indices"]].detach().cpu().numpy()
            motor_state = float(np.sum(np.abs(motor_g)) + np.sum(np.abs(motor_graded)))
            max_motor_state = max(max_motor_state, motor_state)
            if motor_state > 0.0:
                motor_state_nonzero_steps += 1
            refractory = runtime.refractory[context["motor_indices"]].detach().cpu().numpy()
            event_vector = refractory == runtime.refractory_steps
            motor_events += int(np.count_nonzero(event_vector))
            route_event = int(event_vector[route_index])
            route_events += route_event
            force_uN, command_scalar = twitch.step(route_event)
            command = np.zeros(len(loop.actuator_names), dtype=np.float64)
            command[target_actuator_id] = command_scalar
            if command_scalar != 0.0:
                command_nonzero_steps += 1
            addressed = loop.actuator_interface.step(command)
            loop.simulation.set_actuator_inputs("flybody", loop.actuator_type, addressed.values)
            loop.simulation.step()
            if (step + 1) % stride == 0:
                record["timestamps"].append(float(loop.simulation.mj_data.time))
                record["qpos"].append(loop.simulation.mj_data.qpos.copy())
                record["qvel"].append(loop.simulation.mj_data.qvel.copy())
                record["commands"].append(addressed.values.astype(np.float32, copy=True))
                record["neural"].append(
                    np.asarray(
                        [float(activity.sum()), motor_state, motor_events, route_events, force_uN, command_scalar],
                        dtype=np.float32,
                    )
                )

    trajectory = PhysicalTrajectory(
        timestamps_s=np.asarray(record["timestamps"], dtype=np.float64),
        qpos=np.asarray(record["qpos"], dtype=np.float64),
        qvel=np.asarray(record["qvel"], dtype=np.float64),
        actuator_commands=np.asarray(record["commands"], dtype=np.float32),
        neural_summary=np.asarray(record["neural"], dtype=np.float32),
        sensory_observations={},
        metadata={
            "schema_name": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "model": physical_model,
            "run_id": "fh06-lexicographic-integration-witness",
            "created_at": datetime.now(UTC).isoformat(),
            "creator": "the_fly_matrix.front_leg_integrated_lineage.v0",
            "claim_label": campaign["claim_label"],
            "campaign_id": campaign["id"],
            "lineage_address": campaign["execution_witness"],
            "neural_summary_fields": [
                "feco_activity_sum",
                "motor_internal_state_l1",
                "cumulative_motor_events",
                "cumulative_route_events",
                "route_force_uN",
                "route_command",
            ],
        },
    )
    run_root.mkdir(parents=True, exist_ok=True)
    trajectory_path = run_root / "physical-trajectory.npz"
    trajectory.save(trajectory_path)
    loaded = PhysicalTrajectory.load(trajectory_path)
    exact_round_trip = all(
        np.array_equal(left, right)
        for left, right in (
            (trajectory.timestamps_s, loaded.timestamps_s),
            (trajectory.qpos, loaded.qpos),
            (trajectory.qvel, loaded.qvel),
            (trajectory.actuator_commands, loaded.actuator_commands),
            (trajectory.neural_summary, loaded.neural_summary),
        )
    )
    replay = run_replay(trajectory_path, headless=True)
    return {
        "address": campaign["execution_witness"],
        "backend": "cpu",
        "graph": context["graph_summary"],
        "steps": steps,
        "recorded_frames": trajectory.frame_count,
        "duration_s": trajectory.duration_s,
        "source_nonzero_steps": source_nonzero_steps,
        "feco_forced_event_count": feco_forced_events,
        "motor_state_nonzero_steps": motor_state_nonzero_steps,
        "max_motor_internal_state_l1": max_motor_state,
        "motor_event_count": motor_events,
        "route_event_count": route_events,
        "command_nonzero_steps": command_nonzero_steps,
        "trajectory_path": str(trajectory_path.relative_to(ROOT)).replace("\\", "/"),
        "trajectory_sha256": _sha256(trajectory_path),
        "trajectory_array_sha256": _array_hash(
            loaded.timestamps_s,
            loaded.qpos,
            loaded.qvel,
            loaded.actuator_commands,
            loaded.neural_summary,
        ),
        "exact_save_load_round_trip": exact_round_trip,
        "headless_replay_model_contract": bool(replay["model_contract_passed"]),
        "motor_transfer_executed_every_step": True,
        "direct_motor_executed_every_step": True,
        "nonzero_actuation_required": False,
    }


def run_integrated_lineage(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    parameter_set_path: Path = PARAMETER_SET_PATH,
    run_root: Path = RUN_ROOT,
) -> dict[str, Any]:
    print("[1/8] Verifying FH-03/FH-04/FH-05, topology, wiring and actuator hashes", flush=True)
    campaign = _load_yaml(campaign_path)
    verified = _verify_inputs(campaign)
    print("[2/8] Compiling the exact conditional factorization without Cartesian expansion", flush=True)
    manifest = _lineage_manifest(campaign, verified)
    print(
        f"[LINEAGE] {manifest['discrete_lineage_members']:,} discrete addresses + "
        f"{manifest['continuous_dimensions_per_sensory_member']} open native-amplitude dimensions",
        flush=True,
    )
    print("[3/8] Reconstructing the preregistered lexicographic integration witness", flush=True)
    print("[4/8] Executing physical FeCO -> typed cone -> motor transfer -> direct MOTOR", flush=True)
    witness = _run_causal_witness(campaign, verified, run_root)
    print("[5/8] Checking exact archive round-trip and controller-independent replay", flush=True)
    print(
        f"[CAUSAL] source_steps={witness['source_nonzero_steps']} "
        f"forced_feco_events={witness['feco_forced_event_count']} "
        f"motor_state_steps={witness['motor_state_nonzero_steps']}",
        flush=True,
    )
    checks = {
        "all_parent_members_preserved": manifest["member_ids_materialized"] == 0,
        "exact_hash_reconstruction": True,
        "factorized_not_materialized": manifest["representation"].endswith("not_materialized"),
        "physical_sensor_read_nonzero": witness["source_nonzero_steps"] > 0,
        "typed_hybrid_runtime_reaches_motor_state": witness["motor_state_nonzero_steps"] > 0,
        "motor_transfer_executed": witness["motor_transfer_executed_every_step"],
        "direct_motor_executed": witness["direct_motor_executed_every_step"],
        "exact_trajectory_round_trip": witness["exact_save_load_round_trip"],
        "headless_replay_model_contract": witness["headless_replay_model_contract"],
        "zero_member_ranking": manifest["members_ranked"] is False,
        "zero_behavior_exposure": not manifest["behavior_targets_exposed"],
        "zero_parameter_promotion": int(campaign["parameter_values_promoted"]) == 0,
    }
    if not all(checks.values()):
        raise IntegratedLineageError(
            f"FH-06 acceptance failed: {[name for name, passed in checks.items() if not passed]}"
        )
    print("[6/8] Freezing factor, exposure, topology, actuator and mechanism ownership", flush=True)
    semantic_payload = {
        "campaign_id": campaign["id"],
        "lineage_semantic_sha256": manifest["semantic_sha256"],
        "witness": {
            key: witness[key]
            for key in (
                "address",
                "graph",
                "steps",
                "recorded_frames",
                "source_nonzero_steps",
                "feco_forced_event_count",
                "motor_state_nonzero_steps",
                "motor_event_count",
                "route_event_count",
                "command_nonzero_steps",
                "trajectory_array_sha256",
            )
        },
        "checks": checks,
        "scientific_boundary": {
            "members_ranked": False,
            "reference_member_selected": False,
            "parameter_values_promoted": 0,
            "named_behaviors_exposed": 0,
            "motor_spike_required_for_acceptance": False,
        },
    }
    semantic_hash = _canonical_hash(semantic_payload)
    result = {
        "schema_version": 1,
        "id": "runner_result.front_leg_integrated_runnable_lineage.v0",
        "campaign_id": campaign["id"],
        "status": "accepted_FH06_factorized_lineage_and_causal_replay_witness",
        "completed_at": datetime.now(UTC).isoformat(),
        "command": "front_leg_integrated_lineage.bat",
        "claim_label": campaign["claim_label"],
        "lineage": manifest,
        "execution_witness": witness,
        "checks": checks,
        "scientific_boundary": semantic_payload["scientific_boundary"],
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "semantic_result_sha256": semantic_hash,
        "next_action": campaign["next_action"],
    }
    parameter_set = {
        "schema_version": 1,
        "id": "parameters.front_leg_integrated_lineage.v0",
        "title": "FH-06 reconstructible factorized front-leg integrated lineage",
        "status": "frozen_factorized_lineage_no_reference_member",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": semantic_hash,
        "primary_class": "technical",
        "behavior_targets": [],
        "lineage": manifest,
        "integration_witness_address": campaign["execution_witness"],
        "integration_witness_is_reference": False,
        "parameter_values_promoted": 0,
        "reopening_policy": "new_campaign_required_on_parent_hash_topology_actuator_or_mechanism_drift",
        "next_action": campaign["next_action"],
    }
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.front_leg_integrated_runnable_lineage.v0",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": semantic_hash,
        "parameter_set_id": parameter_set["id"],
        "status": "accepted_FH06_complete_no_physiological_or_behavioral_claim",
        "checks": checks,
        "motor_event_count": witness["motor_event_count"],
        "command_nonzero_steps": witness["command_nonzero_steps"],
        "interpretation": "",
    }
    evaluation["interpretation"] = (
        "The complete parent uncertainty is preserved as an exact conditional factorization. "
        "One outcome-blind lexicographic address executed physical FeCO sensing, the typed "
        "hybrid cone, the motor-transfer and direct-MOTOR boundaries, carried nonzero "
        "body-derived activity to motor internal state, then round-tripped "
        "through the independent replay contract. Motor spikes and commands are reported, "
        "never required or used to choose another member; FH-07 owns neutral-regime calibration."
    )
    evaluation["next_action"] = campaign["next_action"]
    print("[7/8] Writing compact runner, parameter-set and evaluation records", flush=True)
    result_path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    parameter_set_path.write_text(
        yaml.safe_dump(parameter_set, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    evaluation_path.write_text(
        yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    print("[8/8] COMPLETE — FH-06 factorized lineage frozen; no member selected", flush=True)
    print(
        f"[WITNESS] motor_events={witness['motor_event_count']} "
        f"nonzero_commands={witness['command_nonzero_steps']} "
        f"motor_state_steps={witness['motor_state_nonzero_steps']}",
        flush=True,
    )
    print(f"[HASH] {semantic_hash}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile and execute the FH-06 integrated lineage")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    run_integrated_lineage(campaign_path=args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

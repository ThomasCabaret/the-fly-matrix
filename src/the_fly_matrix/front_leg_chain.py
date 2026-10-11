from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml
from scipy import sparse
from scipy.sparse.csgraph import shortest_path

from .ledger import ROOT
from .local_conversion import (
    ActuatorBridgeParameters,
    MotorTwitchParameters,
    force_uN_to_actuator_command,
    motor_events_to_force_uN,
)
from .runtime import CentralConnectomeBox


CAMPAIGN_PATH = (
    ROOT / "calibration" / "campaigns" / "front-leg-sensor-cns-motor-chain-v0.yaml"
)
RESULT_PATH = (
    ROOT / "calibration" / "runner" / "front-leg-sensor-cns-motor-chain-v0.yaml"
)
OUTPUT_ROOT = (
    ROOT / "data" / "derived" / "calibration" / "front-leg-sensor-cns-motor-chain-v0"
)


class FrontLegChainError(RuntimeError):
    """Raised when the frozen local chain or its uncertainty accounting drifts."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FrontLegChainError(f"{path} must contain a YAML mapping")
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


def _validate_campaign(campaign: Mapping[str, Any]) -> None:
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise FrontLegChainError("chain envelope must remain diagnostic_only")
    if campaign.get("behavior_targets"):
        raise FrontLegChainError("chain envelope cannot expose behavior targets")
    if campaign.get("topology_changes_allowed") is not False:
        raise FrontLegChainError("chain envelope cannot change topology")
    capacity = campaign.get("capacity_policy", {})
    if any(int(value) != 0 for value in capacity.values()):
        raise FrontLegChainError("chain envelope cannot select or promote parameters")
    probe = campaign.get("diagnostic_probe", {})
    if probe.get("inspect_body_trajectory") is not False or probe.get("run_mujoco") is not False:
        raise FrontLegChainError("chain accounting may not inspect body motion")


def compile_feco_source_path_product(feco_campaign: Mapping[str, Any]) -> list[dict[str, str]]:
    """Build the small cross-class source-path product without choosing a winner."""

    candidates: dict[str, list[str]] = {}
    for dataset in feco_campaign.get("inputs", {}).get("datasets", []):
        functional_class = str(dataset["functional_class"])
        values = [str(item["id"]) for item in dataset.get("candidates", [])]
        if not values or functional_class in candidates:
            raise FrontLegChainError("FeCO candidates must be nonempty and class-unique")
        candidates[functional_class] = values
    expected_classes = {
        "claw_position",
        "club_vibration_and_speed",
        "hook_flexion_direction",
    }
    if set(candidates) != expected_classes:
        raise FrontLegChainError(f"unexpected FeCO functional classes: {sorted(candidates)}")
    ordered = sorted(candidates)
    return [
        dict(zip(ordered, values, strict=True))
        for values in itertools.product(*(candidates[key] for key in ordered))
    ]


def _runtime_indices(body_ids: np.ndarray, selected: np.ndarray, label: str) -> np.ndarray:
    indices = np.searchsorted(body_ids, selected)
    clipped = np.minimum(indices, len(body_ids) - 1)
    if np.any(indices >= len(body_ids)) or not np.array_equal(body_ids[clipped], selected):
        raise FrontLegChainError(f"{label} contains bodies outside the canonical runtime")
    return indices.astype(np.int64, copy=False)


def compile_central_corridor(
    outgoing: sparse.csr_matrix,
    body_ids: np.ndarray,
    source_body_ids: np.ndarray,
    target_body_ids: np.ndarray,
    *,
    maximum_pair_distance: int,
) -> tuple[dict[str, Any], pd.DataFrame, np.ndarray]:
    """Account all direct/two-hop paths and every endpoint-pair distance."""

    sources = _runtime_indices(body_ids, source_body_ids, "FeCO scope")
    targets = _runtime_indices(body_ids, target_body_ids, "motor scope")
    distances = shortest_path(
        outgoing,
        directed=True,
        unweighted=True,
        indices=sources,
        return_predecessors=False,
    )[:, targets]
    if not np.isfinite(distances).all():
        raise FrontLegChainError("at least one FeCO-to-motor endpoint pair is unreachable")
    if int(np.max(distances)) > maximum_pair_distance:
        raise FrontLegChainError(
            f"endpoint pair exceeds {maximum_pair_distance} hops: {int(np.max(distances))}"
        )

    target_slot = np.full(outgoing.shape[0], -1, dtype=np.int32)
    target_slot[targets] = np.arange(len(targets), dtype=np.int32)
    records: list[dict[str, Any]] = []
    intermediate_indices: set[int] = set()
    target_local_path_counts = np.zeros(len(targets), dtype=np.int64)

    for source_slot, source_index in enumerate(sources):
        start, end = outgoing.indptr[source_index : source_index + 2]
        first_targets = outgoing.indices[start:end]
        first_weights = outgoing.data[start:end]
        direct_slots = target_slot[first_targets]
        for position in np.flatnonzero(direct_slots >= 0):
            target_index = int(direct_slots[position])
            target_local_path_counts[target_index] += 1
            records.append(
                {
                    "hops": 1,
                    "source_body_id": int(source_body_ids[source_slot]),
                    "intermediate_body_id": pd.NA,
                    "target_body_id": int(target_body_ids[target_index]),
                    "first_edge_weight": float(first_weights[position]),
                    "second_edge_weight": np.nan,
                }
            )

        for position, intermediate_index in enumerate(first_targets):
            second_start, second_end = outgoing.indptr[intermediate_index : intermediate_index + 2]
            second_targets = outgoing.indices[second_start:second_end]
            second_weights = outgoing.data[second_start:second_end]
            slots = target_slot[second_targets]
            for second_position in np.flatnonzero(slots >= 0):
                target_index = int(slots[second_position])
                target_local_path_counts[target_index] += 1
                intermediate_indices.add(int(intermediate_index))
                records.append(
                    {
                        "hops": 2,
                        "source_body_id": int(source_body_ids[source_slot]),
                        "intermediate_body_id": int(body_ids[intermediate_index]),
                        "target_body_id": int(target_body_ids[target_index]),
                        "first_edge_weight": float(first_weights[position]),
                        "second_edge_weight": float(second_weights[second_position]),
                    }
                )

    paths = pd.DataFrame.from_records(records)
    if (target_local_path_counts == 0).any():
        missing = target_body_ids[target_local_path_counts == 0].tolist()
        raise FrontLegChainError(f"local two-hop envelope misses motor bodies: {missing}")
    # A recurrent two-hop path may pass through a source or target endpoint. Keep
    # that path in the envelope, but do not overwrite the endpoint's already
    # accepted population assignment by counting it as a new intermediate.
    intermediate_indices.difference_update(int(value) for value in sources)
    intermediate_indices.difference_update(int(value) for value in targets)
    unique_distances, distance_counts = np.unique(distances.astype(np.int64), return_counts=True)
    summary = {
        "source_neurons": len(sources),
        "target_neurons": len(targets),
        "endpoint_pairs": int(distances.size),
        "reachable_endpoint_pairs": int(np.isfinite(distances).sum()),
        "endpoint_pair_distance_hops": {
            str(int(distance)): int(count)
            for distance, count in zip(unique_distances, distance_counts, strict=True)
        },
        "minimum_hops": int(np.min(distances)),
        "maximum_hops": int(np.max(distances)),
        "direct_edges": int((paths["hops"] == 1).sum()),
        "two_hop_paths": int((paths["hops"] == 2).sum()),
        "local_path_records": len(paths),
        "unique_intermediate_neurons": len(intermediate_indices),
        "paths_per_motor_min": int(target_local_path_counts.min()),
        "paths_per_motor_median": float(np.median(target_local_path_counts)),
        "paths_per_motor_max": int(target_local_path_counts.max()),
        "path_selected": False,
    }
    return summary, paths, np.asarray(sorted(intermediate_indices), dtype=np.int64)


def compile_motor_basis_probes(
    routes: pd.DataFrame,
    motor_ensemble: Mapping[str, Any],
    force_evaluation: Mapping[str, Any],
    temporal_result: Mapping[str, Any],
    bridge_result: Mapping[str, Any],
    *,
    timestep_s: float,
    samples: int,
    event_index: int,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Exercise every local class/route/gain basis case or report its blocker."""

    members = motor_ensemble.get("members", [])
    body_ids = [int(item["body_id"]) for item in members]
    scoped = routes.loc[routes["source_body_id"].isin(body_ids)].copy()
    route_counts = scoped.groupby("source_body_id").size()
    if set(route_counts.index.astype(int)) != set(body_ids) or set(route_counts.tolist()) != {11}:
        raise FrontLegChainError("motor route envelope is not 11 basis edges per body")

    amplitudes = force_evaluation["procedure_readiness"]["fitted_slopes_uN_per_spike"]
    class_results = temporal_result["class_results"]
    gains = bridge_result["conditional_gain_envelope"]["candidate_gains_command_per_uN"]
    if len(gains) != 3:
        raise FrontLegChainError("expected three conditional bridge gains")
    classes = [str(value) for value in motor_ensemble["admissible_classes"]]
    records: list[dict[str, Any]] = []
    supported_peaks: list[float] = []

    events = np.zeros((samples, 1), dtype=np.int64)
    events[event_index, 0] = 1
    for body_id in body_ids:
        body_routes = scoped.loc[scoped["source_body_id"].eq(body_id)].sort_values(
            "target_actuator_id"
        )
        for class_id in classes:
            result = class_results[class_id]
            if "all_data_best_candidate" not in result:
                for route in body_routes.itertuples(index=False):
                    for gain in gains:
                        records.append(
                            {
                                "body_id": body_id,
                                "class_id": class_id,
                                "target_actuator_id": int(route.target_actuator_id),
                                "target_actuator_name": str(route.target_actuator_name),
                                "bridge_gain_command_per_uN": float(gain),
                                "status": "blocked_missing_isolated_twitch_kernel",
                                "peak_force_uN": np.nan,
                                "peak_command": np.nan,
                            }
                        )
                continue
            kernel = result["all_data_best_candidate"]
            force = motor_events_to_force_uN(
                events,
                MotorTwitchParameters(
                    force_per_event_uN=np.asarray([float(amplitudes[class_id])]),
                    rise_time_s=np.asarray([float(kernel["rise_time_s"])]),
                    decay_time_s=np.asarray([float(kernel["decay_time_s"])]),
                ),
                timestep_s=timestep_s,
            )
            peak_force = float(np.max(force))
            for route in body_routes.itertuples(index=False):
                for gain in gains:
                    command = force_uN_to_actuator_command(
                        force,
                        ActuatorBridgeParameters(
                            command_per_uN=np.asarray([float(gain)]),
                            command_offset=np.asarray([0.0]),
                        ),
                    )
                    peak_command = float(np.max(command))
                    supported_peaks.append(peak_command)
                    records.append(
                        {
                            "body_id": body_id,
                            "class_id": class_id,
                            "target_actuator_id": int(route.target_actuator_id),
                            "target_actuator_name": str(route.target_actuator_name),
                            "bridge_gain_command_per_uN": float(gain),
                            "status": "executed_diagnostic_basis_only",
                            "peak_force_uN": peak_force,
                            "peak_command": peak_command,
                        }
                    )

    frame = pd.DataFrame.from_records(records)
    status_counts = frame["status"].value_counts().to_dict()
    fully_executable_assignments = 2 ** len(body_ids)
    assignment_upper_bound = int(motor_ensemble["factorized_assignment_upper_bound"])
    summary = {
        "motor_bodies": len(body_ids),
        "admissible_classes_per_body": len(classes),
        "factorized_class_assignment_upper_bound": assignment_upper_bound,
        "fully_kernel_executable_joint_assignments": fully_executable_assignments,
        "kernel_blocked_joint_assignments": assignment_upper_bound - fully_executable_assignments,
        "route_basis_edges": len(scoped),
        "routes_per_body": int(route_counts.iloc[0]),
        "local_routing_simplex_dof_upper_bound": int((route_counts - 1).sum()),
        "unique_actuators": int(scoped["target_actuator_id"].nunique()),
        "bridge_gain_candidates": len(gains),
        "basis_probes_total": len(frame),
        "basis_probes_executed": int(status_counts.get("executed_diagnostic_basis_only", 0)),
        "basis_probes_blocked": int(
            status_counts.get("blocked_missing_isolated_twitch_kernel", 0)
        ),
        "executed_peak_command_min": float(np.min(supported_peaks)),
        "executed_peak_command_median": float(np.median(supported_peaks)),
        "executed_peak_command_max": float(np.max(supported_peaks)),
        "selected_body_classes": 0,
        "selected_routes": 0,
        "selected_bridge_gains": 0,
    }
    return summary, frame


def run_front_leg_chain(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    campaign = _load_yaml(campaign_path)
    _validate_campaign(campaign)
    frozen = campaign["frozen_inputs"]
    acceptance = campaign["acceptance"]

    print("[1/7] Verification des entrees gelees et de leurs identifiants", flush=True)
    input_paths = {
        key: ROOT / str(relative)
        for key, relative in frozen.items()
        if key not in {"semantic_topology_hashes", "central_body_id_sha256", "central_dataset_sha256"}
    }
    missing = [str(path) for path in input_paths.values() if not path.is_file()]
    if missing:
        raise FrontLegChainError(f"missing frozen inputs: {missing}")
    input_hashes = {key: _sha256(path) for key, path in input_paths.items()}
    graph_metadata = json.loads(input_paths["graph_metadata"].read_text(encoding="utf-8"))
    if graph_metadata["body_id_sha256"] != frozen["central_body_id_sha256"]:
        raise FrontLegChainError("central body-id order drift")
    if graph_metadata["dataset_sha256"] != frozen["central_dataset_sha256"]:
        raise FrontLegChainError("central dataset drift")
    expected_topology = frozen["semantic_topology_hashes"]
    for key, family_key in (
        ("proprioception", "proprioception_family_record"),
        ("motor_output", "motor_family_record"),
    ):
        family = _load_yaml(input_paths[family_key])
        observed = family["scope"]["topology_snapshot"]["semantic_topology_sha256"]
        if observed != expected_topology[key]:
            raise FrontLegChainError(f"{key} semantic topology drift")

    print("[2/7] Compilation des chemins FeCO par classe fonctionnelle", flush=True)
    feco_campaign = _load_yaml(input_paths["feco_fit_campaign"])
    feco_evaluation = _load_yaml(input_paths["feco_fit_evaluation"])
    feco_joint_paths = compile_feco_source_path_product(feco_campaign)
    atomic_candidates = sum(
        len(dataset["candidates"]) for dataset in feco_campaign["inputs"]["datasets"]
    )
    if feco_evaluation["procedure_readiness"]["biological_folds_blocked"] != 0:
        raise FrontLegChainError("FeCO ensemble contains blocked biological folds")
    sensory = {
        "atomic_source_candidates": atomic_candidates,
        "joint_source_path_combinations": len(feco_joint_paths),
        "native_representation_candidates": 2,
        "boundary_alternatives": len(feco_joint_paths) * 2,
        "source_path_selected": False,
        "native_representation_selected": False,
    }

    print("[3/7] Chargement du graphe canonique et des 46 terminaux locaux", flush=True)
    members = pd.read_csv(input_paths["population_members"])
    source_body_ids = np.sort(
        members.loc[
            members["population_id"].eq("population.front_leg_feco.v0"), "body_id"
        ].to_numpy(dtype=np.int64)
    )
    target_body_ids = np.sort(
        members.loc[
            members["population_id"].eq("population.front_leg_tibia_flexor_motor.v0"),
            "body_id",
        ].to_numpy(dtype=np.int64)
    )
    if len(source_body_ids) != int(acceptance["expected_feco_neurons"]):
        raise FrontLegChainError("FeCO endpoint count drift")
    if len(target_body_ids) != int(acceptance["expected_motor_neurons"]):
        raise FrontLegChainError("motor endpoint count drift")
    outgoing = sparse.load_npz(input_paths["outgoing_graph_cache"]).tocsr()
    runtime_body_ids = CentralConnectomeBox.from_generated_wiring().body_ids
    if outgoing.shape != (len(runtime_body_ids), len(runtime_body_ids)):
        raise FrontLegChainError("outgoing graph shape differs from the canonical body order")

    print("[4/7] Distances CNS et enveloppe exhaustive des chemins a un/deux sauts", flush=True)
    central, central_paths, intermediate_indices = compile_central_corridor(
        outgoing,
        runtime_body_ids,
        source_body_ids,
        target_body_ids,
        maximum_pair_distance=int(
            campaign["central_corridor_policy"]["endpoint_pair_distance_max_hops"]
        ),
    )
    if int(campaign["central_corridor_policy"]["local_envelope_max_hops"]) != 2:
        raise FrontLegChainError("this chain compiler supports the locked two-hop envelope only")
    annotations = pd.read_feather(input_paths["body_annotations"])
    intermediate_body_ids = runtime_body_ids[intermediate_indices]
    intermediates = annotations.loc[
        annotations["bodyId"].isin(intermediate_body_ids),
        ["bodyId", "superclass", "class", "subclass", "type", "somaSide"],
    ].copy()
    intermediates = intermediates.rename(columns={"bodyId": "body_id"}).sort_values("body_id")
    intermediates["chain_assignment"] = "dual_unresolved"
    intermediates["parameter_values_emitted"] = False
    if len(intermediates) != central["unique_intermediate_neurons"]:
        raise FrontLegChainError("intermediate annotation accounting drift")
    central["intermediate_assignment"] = "dual_unresolved"
    central["intermediate_parameter_values"] = 0
    central["intermediate_superclass_counts"] = {
        str(key): int(value)
        for key, value in intermediates["superclass"].fillna("(unknown)").value_counts().items()
    }

    print("[5/7] Propagation des classes, routes et trois gains par probes de base", flush=True)
    motor, motor_probes = compile_motor_basis_probes(
        pd.read_parquet(input_paths["motor_route_table"]),
        _load_yaml(input_paths["motor_class_ensemble"]),
        _load_yaml(input_paths["motor_force_evaluation"]),
        _load_yaml(input_paths["motor_temporal_result"]),
        _load_yaml(input_paths["motor_bridge_result"]),
        timestep_s=float(campaign["diagnostic_probe"]["timestep_s"]),
        samples=int(campaign["diagnostic_probe"]["samples"]),
        event_index=int(campaign["diagnostic_probe"]["event_index"]),
    )

    expected_values = {
        "expected_feco_atomic_candidates": sensory["atomic_source_candidates"],
        "expected_feco_joint_source_paths": sensory["joint_source_path_combinations"],
        "expected_native_representations": sensory["native_representation_candidates"],
        "expected_feco_boundary_alternatives": sensory["boundary_alternatives"],
        "expected_endpoint_pairs": central["endpoint_pairs"],
        "expected_direct_edges": central["direct_edges"],
        "expected_two_hop_paths": central["two_hop_paths"],
        "expected_new_intermediate_neurons": central["unique_intermediate_neurons"],
        "expected_motor_class_assignment_upper_bound": motor[
            "factorized_class_assignment_upper_bound"
        ],
        "expected_motor_route_basis_edges": motor["route_basis_edges"],
        "expected_motor_routes_per_body": motor["routes_per_body"],
        "expected_unique_actuators": motor["unique_actuators"],
        "expected_bridge_gain_candidates": motor["bridge_gain_candidates"],
        "expected_motor_basis_probes_executed": motor["basis_probes_executed"],
        "expected_motor_basis_probes_blocked": motor["basis_probes_blocked"],
    }
    for key, observed in expected_values.items():
        if int(acceptance[key]) != int(observed):
            raise FrontLegChainError(f"acceptance drift for {key}: {observed}")
    if central["endpoint_pair_distance_hops"] != {
        str(key): int(value)
        for key, value in acceptance["expected_endpoint_pair_distance_hops"].items()
    }:
        raise FrontLegChainError("endpoint-pair distance distribution drift")
    if motor["executed_peak_command_max"] > float(
        acceptance["maximum_diagnostic_command_abs"]
    ) + 1e-12:
        raise FrontLegChainError("diagnostic motor basis probe exceeds the frozen command guard")

    print("[6/7] Ecriture des artefacts derives et du resultat compact", flush=True)
    output_root.mkdir(parents=True, exist_ok=True)
    central_paths.to_csv(output_root / "central-paths-up-to-two-hops.csv", index=False)
    intermediates.to_csv(output_root / "intermediate-populations.csv", index=False)
    motor_probes.to_csv(output_root / "motor-basis-probes.csv", index=False)
    (output_root / "feco-joint-source-paths.json").write_text(
        json.dumps(feco_joint_paths, indent=2), encoding="utf-8"
    )
    artifact = {
        "schema_version": 1,
        "campaign_id": campaign["id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "pass_factorized_chain_envelope_intermediate_assignments_open",
        "claim_label": campaign["claim_label"],
        "input_hashes": input_hashes,
        "sensory_ensemble": sensory,
        "central_corridor": central,
        "motor_ensemble": motor,
        "accounting": {
            "optimized_parameters": 0,
            "promoted_parameter_values": 0,
            "selected_candidates": 0,
            "behavior_targets_exposed": 0,
            "topology_changes": 0,
        },
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "open_blockers": [
            "All bounded CNS intermediate populations remain dual_unresolved; the path envelope is not an accepted neural dynamics model.",
            "The seven FeCO observation candidates and both native representations remain unselected.",
            "Slow motor-class cases lack an isolated single-spike temporal kernel.",
            "Motor class, routing simplex and force-to-command gain remain unresolved ensembles.",
        ],
        "next_action": campaign["next_action"],
    }
    artifact["semantic_result_sha256"] = _canonical_hash(
        {key: value for key, value in artifact.items() if key != "generated_at"}
    )
    artifact_path = output_root / "summary.json"
    artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    compact = {
        "schema_version": 1,
        "id": "runner_result.front_leg_sensor_cns_motor_chain.v0",
        "campaign_id": campaign["id"],
        "target_id": campaign["target_id"],
        "status": artifact["status"],
        "claim_label": campaign["claim_label"],
        "command": "front_leg_chain_envelope.bat",
        "behavior_targets": [],
        "campaign_sha256": _sha256(campaign_path),
        "semantic_result_sha256": artifact["semantic_result_sha256"],
        "sensory_ensemble": sensory,
        "central_corridor": central,
        "motor_ensemble": motor,
        "accounting": artifact["accounting"],
        "artifact_ref": str(artifact_path.relative_to(ROOT)).replace("\\", "/"),
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "open_blockers": artifact["open_blockers"],
        "next_action": campaign["next_action"],
    }
    result_path.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")

    print("[7/7] Resume", flush=True)
    print(
        f"[CNS] {central['endpoint_pairs']}/{central['endpoint_pairs']} couples atteignables "
        f"en {central['minimum_hops']}..{central['maximum_hops']} sauts; "
        f"{central['unique_intermediate_neurons']} intermediaires dual_unresolved",
        flush=True,
    )
    print(
        f"[SENSORIEL] {sensory['atomic_source_candidates']} candidats atomiques -> "
        f"{sensory['joint_source_path_combinations']} chemins joints -> "
        f"{sensory['boundary_alternatives']} alternatives avec representation",
        flush=True,
    )
    print(
        f"[MOTEUR] {motor['basis_probes_executed']} probes executees, "
        f"{motor['basis_probes_blocked']} bloquees explicitement (noyau slow absent)",
        flush=True,
    )
    print("[BOUNDARY] 0 selection, 0 promotion, 0 comportement, 0 changement topologique", flush=True)
    print(f"[HASH] {artifact['semantic_result_sha256']}", flush=True)
    return compact


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile the factorized front-leg sensor-CNS-motor chain envelope"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    run_front_leg_chain(args.campaign, output_root=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

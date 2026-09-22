from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from .ledger import ROOT
from .runtime import (
    BasalClampBox,
    ChannelActivity,
    CentralConnectomeBox,
    CNSInputBuffer,
    FlyBodyProprioceptionSensor,
    FlyBodyGroundContactSensor,
    FlyBodyActuatorInterface,
    FlyBodyVisionSensor,
    GroupedChannelActivity,
    MechanosensationRoutingBox,
    MechanosensationTransductionBox,
    MotorRoutingBox,
    MotorTransductionBox,
    ProprioceptionTransductionBox,
    ProprioceptionRoutingBox,
    SparseActivity,
    UnclassifiedSensoryRoutingBox,
    VisionRoutingBox,
)


OUTPUT = ROOT / "runs" / "wiring-smoke" / "latest.json"
CLAMP_IDS = ("clamp.olfaction", "clamp.gustation", "clamp.thermohygro")
SMOKE_SEED = 260919


def section(title: str) -> None:
    print(f"\n==> {title}", flush=True)


def _arbitrary_values(
    box: BasalClampBox
    | ProprioceptionRoutingBox
    | MechanosensationRoutingBox
    | VisionRoutingBox
    | UnclassifiedSensoryRoutingBox,
    seed: int,
) -> np.ndarray:
    # These values only exercise data flow. They are not physiological guesses.
    return np.random.default_rng(seed).uniform(0.0, 1.0, len(box.channel_ids))


def _digest(activity: SparseActivity) -> str:
    digest = hashlib.sha256()
    digest.update(activity.body_ids.tobytes())
    digest.update(activity.values.tobytes())
    return digest.hexdigest()


def _channel_digest(activity: ChannelActivity | GroupedChannelActivity) -> str:
    digest = hashlib.sha256()
    digest.update("\n".join(activity.channel_ids).encode("utf-8"))
    if isinstance(activity, GroupedChannelActivity):
        digest.update("\n".join(activity.group_ids).encode("utf-8"))
    digest.update(activity.values.tobytes())
    return digest.hexdigest()


def _render_flybody_vision_twice() -> tuple[np.ndarray, np.ndarray]:
    """Exercise FlyGym's real camera and retina path on a static local scene."""
    from flygym.compose.fly.flybody import FlyBody
    from flygym.compose.world import FlatGroundWorld
    from flygym.flybody.anatomy_flybody import FlyBodyContactBodiesPreset
    from flygym.simulation import Simulation
    from flygym.utils.math import Rotation3D

    fly = FlyBody()
    fly.add_vision()
    world = FlatGroundWorld()
    world.add_fly(
        fly,
        np.asarray([0.0, 0.0, 1.0]),
        Rotation3D("quat", (1, 0, 0, 0)),
        bodysegs_with_ground_contact=FlyBodyContactBodiesPreset.LEGS_THORAX_ABDOMEN_HEAD,
    )
    simulation = Simulation(world)
    try:
        return (
            simulation.get_ommatidia_readouts("flybody"),
            simulation.get_ommatidia_readouts("flybody"),
        )
    finally:
        simulation.close()


def run_smoke(output: Path = OUTPUT, seed: int = SMOKE_SEED) -> dict[str, object]:
    section("Chargement des boîtes abstraites générées")
    boxes = [BasalClampBox.from_generated_wiring(box_id) for box_id in CLAMP_IDS]
    for box in boxes:
        print(
            f"[OK] {box.box_id}: {len(box.channel_ids):,} instances/canaux, "
            f"{len(box.routes):,} destinations exactes"
        )

    proprio_sensor = FlyBodyProprioceptionSensor.from_generated_wiring()
    print(
        f"[OK] {proprio_sensor.box_id}: {len(proprio_sensor.joint_names):,} articulations, "
        f"{len(proprio_sensor.joint_names) * 2:,} observables position/vitesse exactes"
    )
    touch_sensor = FlyBodyGroundContactSensor.from_generated_wiring()
    print(
        f"[OK] {touch_sensor.box_id}: {len(touch_sensor.leg_names):,} capteurs de patte, "
        f"{touch_sensor.sensor_data_size:,} observables de contact au sol"
    )
    actuator_interface = FlyBodyActuatorInterface.from_generated_wiring()
    print(
        f"[OK] {actuator_interface.box_id}: {len(actuator_interface.actuator_names):,} "
        "adresses de commande d'actionneur exactes"
    )
    vision_sensor = FlyBodyVisionSensor.from_generated_wiring()
    print(
        f"[OK] {vision_sensor.box_id}: {vision_sensor.eye_count} yeux, "
        f"{vision_sensor.ommatidia_per_eye:,} ommatidies par œil, "
        f"{len(vision_sensor.channel_ids):,} échantillons actifs"
    )
    proprioception = ProprioceptionRoutingBox.from_generated_wiring()
    print(
        f"[OK] {proprioception.box_id}: {len(proprioception.channel_ids):,} instances/canaux, "
        f"{len(proprioception.routes):,} destinations exactes"
    )
    proprio_transduction = ProprioceptionTransductionBox.from_generated_wiring()
    print(
        f"[OK] {proprio_transduction.box_id}: "
        f"{len(proprio_transduction.parameter_ids):,} arêtes candidates pour "
        f"{len(proprio_transduction.resolved_channel_ids):,}/262 canaux; "
        f"{len(proprio_transduction.unresolved_channel_ids):,} observables manquantes explicites"
    )
    mechanosensation = MechanosensationRoutingBox.from_generated_wiring()
    print(
        f"[OK] {mechanosensation.box_id}: {len(mechanosensation.channel_ids):,} instances/canaux, "
        f"{len(mechanosensation.routes):,} destinations exactes"
    )
    mechano_transduction = MechanosensationTransductionBox.from_generated_wiring()
    print(
        f"[OK] {mechano_transduction.box_id}: "
        f"{len(mechano_transduction.parameter_ids):,} arêtes candidates pour "
        f"{len(mechano_transduction.resolved_channel_ids):,}/323 canaux; "
        f"{len(mechano_transduction.unresolved_channel_ids):,} observables manquantes explicites"
    )
    vision = VisionRoutingBox.from_generated_wiring()
    print(
        f"[OK] {vision.box_id}: {len(vision.channel_ids):,} instances/canaux, "
        f"{len(vision.routes):,} destinations exactes; rétinotopie physique différée"
    )
    motor = MotorRoutingBox.from_generated_wiring()
    print(
        f"[OK] {motor.box_id}: {len(motor.channel_ids):,} instances/canaux depuis "
        f"{len(motor.source_body_ids):,} neurones moteurs vers "
        f"{len(set(motor.motor_group_ids)):,} groupes annotés; transduction séparée"
    )
    motor_transduction = MotorTransductionBox.from_generated_wiring()
    print(
        f"[OK] {motor_transduction.box_id}: {len(motor_transduction.parameter_ids):,} "
        f"arêtes candidates vers {len(motor_transduction.covered_actuator_ids):,}/102 actionneurs; "
        f"{len(motor_transduction.unsupported_terminal_channel_ids):,} terminaux sans effecteur; "
        "paramètres non fixés"
    )
    unclassified = UnclassifiedSensoryRoutingBox.from_generated_wiring()
    print(
        f"[OK] {unclassified.box_id}: {len(unclassified.channel_ids):,} instances/canaux, "
        f"{len(unclassified.routes):,} destinations exactes; modalités physiques différées"
    )
    central = CentralConnectomeBox.from_generated_wiring()
    print(
        f"[OK] {central.box_id}: {len(central.body_ids):,} neurones annotés; "
        f"{central.expected_induced_edges:,} arêtes creuses à parcourir"
    )

    section("Exécution déterministe du rendu et des valeurs structurelles")
    vision_readouts_first, vision_readouts_second = _render_flybody_vision_twice()
    vision_samples_first = vision_sensor.step(vision_readouts_first)
    vision_samples_second = vision_sensor.step(vision_readouts_second)
    qpos_first = np.random.default_rng(seed - 2).uniform(-1.0, 1.0, proprio_sensor.qpos_size)
    qvel_first = np.random.default_rng(seed - 1).uniform(-1.0, 1.0, proprio_sensor.qvel_size)
    qpos_second = np.random.default_rng(seed - 2).uniform(-1.0, 1.0, proprio_sensor.qpos_size)
    qvel_second = np.random.default_rng(seed - 1).uniform(-1.0, 1.0, proprio_sensor.qvel_size)
    joint_state_first = proprio_sensor.step(qpos_first, qvel_first)
    joint_state_second = proprio_sensor.step(qpos_second, qvel_second)
    proprio_parameters_first = np.random.default_rng(seed + len(boxes) + 10).uniform(
        -1.0, 1.0, len(proprio_transduction.parameter_ids)
    )
    proprio_parameters_second = np.random.default_rng(seed + len(boxes) + 10).uniform(
        -1.0, 1.0, len(proprio_transduction.parameter_ids)
    )
    unresolved_proprio_first = np.random.default_rng(seed + len(boxes) + 11).uniform(
        -1.0, 1.0, len(proprio_transduction.unresolved_channel_ids)
    )
    unresolved_proprio_second = np.random.default_rng(seed + len(boxes) + 11).uniform(
        -1.0, 1.0, len(proprio_transduction.unresolved_channel_ids)
    )
    proprio_activity_first = proprio_transduction.step(
        joint_state_first, proprio_parameters_first, unresolved_proprio_first
    )
    proprio_activity_second = proprio_transduction.step(
        joint_state_second, proprio_parameters_second, unresolved_proprio_second
    )
    contact_data_first = np.random.default_rng(seed - 4).uniform(
        -1.0, 1.0, touch_sensor.sensor_data_size
    )
    contact_data_second = np.random.default_rng(seed - 4).uniform(
        -1.0, 1.0, touch_sensor.sensor_data_size
    )
    contact_state_first = touch_sensor.step(contact_data_first)
    contact_state_second = touch_sensor.step(contact_data_second)
    mechano_parameters_first = np.random.default_rng(seed + len(boxes) + 12).uniform(
        -1.0, 1.0, len(mechano_transduction.parameter_ids)
    )
    mechano_parameters_second = np.random.default_rng(seed + len(boxes) + 12).uniform(
        -1.0, 1.0, len(mechano_transduction.parameter_ids)
    )
    unresolved_mechano_first = np.random.default_rng(seed + len(boxes) + 13).uniform(
        -1.0, 1.0, len(mechano_transduction.unresolved_channel_ids)
    )
    unresolved_mechano_second = np.random.default_rng(seed + len(boxes) + 13).uniform(
        -1.0, 1.0, len(mechano_transduction.unresolved_channel_ids)
    )
    mechano_activity_first = mechano_transduction.step(
        contact_state_first, mechano_parameters_first, unresolved_mechano_first
    )
    mechano_activity_second = mechano_transduction.step(
        contact_state_second, mechano_parameters_second, unresolved_mechano_second
    )
    first_outputs = [box.step(_arbitrary_values(box, seed + index)) for index, box in enumerate(boxes)]
    second_outputs = [box.step(_arbitrary_values(box, seed + index)) for index, box in enumerate(boxes)]
    proprio_first = proprioception.step(proprio_activity_first.values)
    proprio_second = proprioception.step(proprio_activity_second.values)
    mechano_first = mechanosensation.step(mechano_activity_first.values)
    mechano_second = mechanosensation.step(mechano_activity_second.values)
    vision_first = vision.step(_arbitrary_values(vision, seed + len(boxes) + 2))
    vision_second = vision.step(_arbitrary_values(vision, seed + len(boxes) + 2))
    unclassified_first = unclassified.step(
        _arbitrary_values(unclassified, seed + len(boxes) + 3)
    )
    unclassified_second = unclassified.step(
        _arbitrary_values(unclassified, seed + len(boxes) + 3)
    )
    first = CNSInputBuffer.merge(
        *first_outputs, proprio_first, mechano_first, vision_first, unclassified_first
    )
    second = CNSInputBuffer.merge(
        *second_outputs, proprio_second, mechano_second, vision_second, unclassified_second
    )
    if not np.array_equal(first.body_ids, second.body_ids) or not np.array_equal(
        first.values, second.values
    ):
        raise RuntimeError("Le rejeu avec la même graine n'est pas déterministe")
    if len(first.body_ids) != 17884:
        raise RuntimeError(f"17884 destinations attendues, {len(first.body_ids)} obtenues")
    print("[INFO] Projection des entrées dans les 26 028 386 arêtes du sous-graphe annoté")
    central_first, central_second = central.project_many((first, second))
    if not np.array_equal(central_first.values, central_second.values):
        raise RuntimeError("Le rejeu de la projection creuse CNS n'est pas déterministe")
    if not np.count_nonzero(central_first.values):
        raise RuntimeError("La projection creuse CNS n'a produit aucun entraînement synaptique")
    motor_first = motor.step(central.select_values(central_first, motor.source_body_ids))
    motor_second = motor.step(central.select_values(central_second, motor.source_body_ids))
    transduction_parameters_first = np.random.default_rng(seed + len(boxes) + 5).uniform(
        -1.0, 1.0, len(motor_transduction.parameter_ids)
    )
    transduction_parameters_second = np.random.default_rng(seed + len(boxes) + 5).uniform(
        -1.0, 1.0, len(motor_transduction.parameter_ids)
    )
    transduced_commands_first = motor_transduction.step(
        motor_first, transduction_parameters_first
    )
    transduced_commands_second = motor_transduction.step(
        motor_second, transduction_parameters_second
    )
    actuator_commands_first = actuator_interface.step(transduced_commands_first.values)
    actuator_commands_second = actuator_interface.step(transduced_commands_second.values)
    if motor_first.channel_ids != motor_second.channel_ids or not np.array_equal(
        motor_first.values, motor_second.values
    ):
        raise RuntimeError("Le rejeu du routage moteur n'est pas déterministe")
    if len(motor_first.channel_ids) != 815:
        raise RuntimeError(f"815 sorties motrices attendues, {len(motor_first.channel_ids)} obtenues")
    if motor_first.group_ids != motor_second.group_ids or len(set(motor_first.group_ids)) != 441:
        raise RuntimeError("Le groupage moteur annoté n'est pas déterministe ou exhaustif")
    if not np.array_equal(transduced_commands_first.values, transduced_commands_second.values):
        raise RuntimeError("Le rejeu de la transduction motrice candidate n'est pas déterministe")
    if np.count_nonzero(transduced_commands_first.values[list(motor_transduction.uncovered_actuator_ids)]):
        raise RuntimeError("Des actionneurs sans candidat ont reçu une commande")
    terminal_values = np.asarray(
        [
            1.0 if channel_id in motor_transduction.unsupported_terminal_channel_ids else 0.0
            for channel_id in motor_first.channel_ids
        ],
        dtype=np.float64,
    )
    terminal_activity = GroupedChannelActivity(
        channel_ids=motor_first.channel_ids,
        group_ids=motor_first.group_ids,
        values=terminal_values,
    )
    terminal_commands = motor_transduction.step(
        terminal_activity, np.ones(len(motor_transduction.parameter_ids), dtype=np.float64)
    )
    if np.count_nonzero(terminal_commands.values):
        raise RuntimeError("Un terminal moteur sans effecteur a produit une commande")
    if joint_state_first.joint_names != joint_state_second.joint_names or not np.array_equal(
        joint_state_first.positions, joint_state_second.positions
    ) or not np.array_equal(joint_state_first.velocities, joint_state_second.velocities):
        raise RuntimeError("Le rejeu du capteur proprioceptif n'est pas déterministe")
    if len(joint_state_first.joint_names) != 102:
        raise RuntimeError(
            f"102 articulations proprioceptives attendues, {len(joint_state_first.joint_names)} obtenues"
        )
    if (
        proprio_activity_first.channel_ids != proprio_activity_second.channel_ids
        or proprio_activity_first.channel_ids != proprioception.channel_ids
        or not np.array_equal(proprio_activity_first.values, proprio_activity_second.values)
    ):
        raise RuntimeError("Le rejeu de la transduction proprioceptive n'est pas déterministe")
    if contact_state_first.leg_names != contact_state_second.leg_names or not all(
        np.array_equal(first_values, second_values)
        for first_values, second_values in (
            (contact_state_first.contact_found, contact_state_second.contact_found),
            (contact_state_first.forces, contact_state_second.forces),
            (contact_state_first.torques, contact_state_second.torques),
            (contact_state_first.positions, contact_state_second.positions),
            (contact_state_first.normals, contact_state_second.normals),
            (contact_state_first.tangents, contact_state_second.tangents),
        )
    ):
        raise RuntimeError("Le rejeu du capteur tactile n'est pas déterministe")
    if len(contact_state_first.leg_names) != 6:
        raise RuntimeError(
            f"6 capteurs de contact de patte attendus, {len(contact_state_first.leg_names)} obtenus"
        )
    if (
        mechano_activity_first.channel_ids != mechano_activity_second.channel_ids
        or mechano_activity_first.channel_ids != mechanosensation.channel_ids
        or not np.array_equal(mechano_activity_first.values, mechano_activity_second.values)
    ):
        raise RuntimeError("Le rejeu de la transduction mécanoréceptrice n'est pas déterministe")
    if actuator_commands_first.actuator_names != actuator_commands_second.actuator_names or not np.array_equal(
        actuator_commands_first.values, actuator_commands_second.values
    ):
        raise RuntimeError("Le rejeu de l'interface d'actionneurs n'est pas déterministe")
    if len(actuator_commands_first.actuator_names) != 102:
        raise RuntimeError(
            f"102 commandes d'actionneur attendues, {len(actuator_commands_first.actuator_names)} obtenues"
        )
    if vision_samples_first.channel_ids != vision_samples_second.channel_ids or not np.array_equal(
        vision_samples_first.values, vision_samples_second.values
    ):
        raise RuntimeError("Le rejeu du rendu visuel FlyBody n'est pas déterministe")
    if len(vision_samples_first.channel_ids) != 1442:
        raise RuntimeError(
            f"1442 échantillons visuels attendus, {len(vision_samples_first.channel_ids)} obtenus"
        )
    print("[OK] 102 articulations FlyBody extraites en 204 observables position/vitesse")
    print(
        f"[OK] {len(proprio_transduction.parameter_ids):,} arêtes proprioceptives candidates "
        f"exécutées vers {len(proprio_transduction.resolved_channel_ids):,} canaux"
    )
    print("[OK] 6 contacts de patte extraits en 96 observables physiques")
    print(
        f"[OK] {len(mechano_transduction.parameter_ids):,} arêtes mécanoréceptrices candidates "
        f"exécutées vers {len(mechano_transduction.resolved_channel_ids):,} canaux"
    )
    print("[OK] 102 commandes placées dans les 102 adresses ctrl FlyBody")
    print("[OK] Rendu réel de 2 × 721 ommatidies extrait de façon déterministe")
    print(f"[OK] {len(first.body_ids):,} entrées CNS uniques reçues")
    print(
        f"[OK] {central.expected_induced_edges:,} arêtes CNS parcourues vers "
        f"{np.count_nonzero(central_first.values):,} neurones entraînés"
    )
    print(f"[OK] {len(motor_first.channel_ids):,} sorties motrices CNS routées")
    print("[OK] 441 groupes moteurs annotés transportent les 815 valeurs sans agrégation")
    print(
        f"[OK] {len(motor_transduction.parameter_ids):,} paramètres injectés "
        "à travers la matrice candidate type F"
    )
    print("[OK] Rejeu bit-à-bit identique avec la même graine")

    result: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": "structural runtime smoke test with arbitrary non-calibrated values",
        "seed": seed,
        "boxes": [
            {
                "id": box.box_id,
                "adapter_type": box.adapter_type,
                "terminal_box_instances": len(box.channel_ids),
                "exact_routes": len(box.routes),
                "parameter_status": "arbitrary_smoke_only",
            }
            for box in boxes
        ]
        + [
            {
                "id": proprio_transduction.box_id,
                "adapter_type": proprio_transduction.adapter_type,
                "candidate_edges": len(proprio_transduction.parameter_ids),
                "resolved_terminal_channels": len(proprio_transduction.resolved_channel_ids),
                "unresolved_terminal_channels": len(
                    proprio_transduction.unresolved_channel_ids
                ),
                "parameter_status": "arbitrary_smoke_only",
            }
        ]
        + [
            {
                "id": proprioception.box_id,
                "adapter_type": proprioception.adapter_type,
                "terminal_box_instances": len(proprioception.channel_ids),
                "exact_routes": len(proprioception.routes),
                "upstream_physical_mapping": "candidates_known_with_missing_observables",
                "parameter_status": "arbitrary_smoke_only",
            }
        ]
        + [
            {
                "id": mechano_transduction.box_id,
                "adapter_type": mechano_transduction.adapter_type,
                "candidate_edges": len(mechano_transduction.parameter_ids),
                "resolved_terminal_channels": len(mechano_transduction.resolved_channel_ids),
                "unresolved_terminal_channels": len(
                    mechano_transduction.unresolved_channel_ids
                ),
                "parameter_status": "arbitrary_smoke_only",
            }
        ]
        + [
            {
                "id": mechanosensation.box_id,
                "adapter_type": mechanosensation.adapter_type,
                "terminal_box_instances": len(mechanosensation.channel_ids),
                "exact_routes": len(mechanosensation.routes),
                "upstream_physical_mapping": "candidates_known_with_missing_observables",
                "parameter_status": "arbitrary_smoke_only",
            }
        ]
        + [
            {
                "id": vision.box_id,
                "adapter_type": vision.adapter_type,
                "terminal_box_instances": len(vision.channel_ids),
                "exact_routes": len(vision.routes),
                "upstream_retinotopic_mapping": "deferred",
                "parameter_status": "arbitrary_smoke_only",
            }
        ]
        + [
            {
                "id": motor.box_id,
                "adapter_type": motor.adapter_type,
                "terminal_box_instances": len(motor.channel_ids),
                "exact_routes": len(motor.source_body_ids),
                "annotation_backed_motor_groups": len(set(motor.motor_group_ids)),
                "motor_group_membership": "fixed_lossless",
                "flybody_actuator_mapping": "deferred",
                "parameter_status": "arbitrary_smoke_only",
            }
        ]
        + [
            {
                "id": motor_transduction.box_id,
                "adapter_type": motor_transduction.adapter_type,
                "candidate_edges": len(motor_transduction.parameter_ids),
                "resolved_motor_channels": len(motor_transduction.source_channel_ids),
                "covered_actuators": len(motor_transduction.covered_actuator_ids),
                "unsupported_terminal_channels": len(
                    motor_transduction.unsupported_terminal_channel_ids
                ),
                "parameter_status": "arbitrary_smoke_only",
            }
        ]
        + [
            {
                "id": unclassified.box_id,
                "adapter_type": unclassified.adapter_type,
                "terminal_box_instances": len(unclassified.channel_ids),
                "exact_routes": len(unclassified.routes),
                "upstream_modality_mapping": "deferred",
                "parameter_status": "arbitrary_smoke_only",
            }
        ]
        + [
            {
                "id": central.box_id,
                "adapter_type": central.adapter_type,
                "annotated_nodes": len(central.body_ids),
                "induced_edges": central.expected_induced_edges,
                "operation": "one_hop_weighted_synaptic_drive",
                "parameter_status": "no_dynamics_selected",
            }
        ],
        "cns_ingress": {
            "adapter_type": CNSInputBuffer.adapter_type,
            "unique_body_ids": len(first.body_ids),
            "activity_digest": _digest(first),
        },
        "central_graph": {
            "adapter_type": central.adapter_type,
            "annotated_nodes": len(central.body_ids),
            "induced_edges": central.expected_induced_edges,
            "nonzero_projected_nodes": int(np.count_nonzero(central_first.values)),
            "motor_outputs_read": len(motor.source_body_ids),
            "operation": "raw_one_hop_synapse_count_projection",
            "activity_digest": _digest(central_first),
            "dynamics_status": "unassigned",
        },
        "motor_egress": {
            "adapter_type": motor.adapter_type,
            "unique_source_body_ids": len(motor.source_body_ids),
            "output_channels": len(motor_first.channel_ids),
            "annotation_backed_motor_groups": len(set(motor_first.group_ids)),
            "group_membership": "fixed_lossless",
            "flybody_actuator_mapping": "deferred",
            "activity_digest": _channel_digest(motor_first),
        },
        "motor_transduction": {
            "adapter_type": motor_transduction.adapter_type,
            "candidate_edges": len(motor_transduction.parameter_ids),
            "resolved_motor_channels": len(motor_transduction.source_channel_ids),
            "resolved_motor_groups": len(motor_transduction.resolved_group_ids),
            "covered_actuators": len(motor_transduction.covered_actuator_ids),
            "uncovered_actuators": len(motor_transduction.uncovered_actuator_ids),
            "unsupported_terminal_channels": len(
                motor_transduction.unsupported_terminal_channel_ids
            ),
            "parameter_status": "arbitrary_smoke_only",
        },
        "physical_proprioception": {
            "source_box_id": "body.flybody",
            "target_box_id": proprio_sensor.box_id,
            "joint_channels": len(joint_state_first.joint_names),
            "scalar_observables": len(joint_state_first.joint_names) * 2,
            "qpos_size": proprio_sensor.qpos_size,
            "qvel_size": proprio_sensor.qvel_size,
            "candidate_edges": len(proprio_transduction.parameter_ids),
            "resolved_terminal_channels": len(proprio_transduction.resolved_channel_ids),
            "unresolved_terminal_channels": len(proprio_transduction.unresolved_channel_ids),
            "biological_receptor_mapping": "candidates_known_with_missing_observables",
        },
        "physical_touch": {
            "source_box_id": "world.mujoco",
            "target_box_id": touch_sensor.box_id,
            "aggregate_leg_channels": len(contact_state_first.leg_names),
            "scalar_observables": touch_sensor.sensor_data_size,
            "candidate_edges": len(mechano_transduction.parameter_ids),
            "resolved_terminal_channels": len(mechano_transduction.resolved_channel_ids),
            "unresolved_terminal_channels": len(mechano_transduction.unresolved_channel_ids),
            "non_leg_local_load_mapping": "deferred",
            "biological_receptor_mapping": "candidates_known_with_missing_observables",
        },
        "physical_motor": {
            "source_box_id": "adapter.motor.transduction",
            "target_box_id": actuator_interface.box_id,
            "actuator_channels": len(actuator_commands_first.actuator_names),
            "control_vector_size": len(actuator_commands_first.values),
            "motor_neuron_to_actuator_mapping": "candidate_complete_with_explicit_terminals",
        },
        "physical_vision": {
            "source_box_id": "world.mujoco",
            "target_box_id": vision_sensor.box_id,
            "eye_cameras": vision_sensor.eye_count,
            "ommatidia_per_eye": vision_sensor.ommatidia_per_eye,
            "active_sample_channels": len(vision_samples_first.channel_ids),
            "actual_mujoco_render_executed": True,
            "malecns_retinotopic_mapping": "deferred",
        },
        "checks": {
            "all_routes_executed": True,
            "full_annotated_cns_graph_executed": True,
            "cns_dynamics_selected": False,
            "motor_routes_executed": True,
            "motor_group_membership_executed": True,
            "motor_transduction_candidates_executed": True,
            "unsupported_motor_terminals_executed_as_no_output": True,
            "body_to_proprioception_executed": True,
            "proprioception_transduction_candidates_executed": True,
            "world_to_touch_executed": True,
            "mechanosensation_transduction_candidates_executed": True,
            "motor_transduction_to_body_executed": True,
            "world_to_vision_executed": True,
            "deterministic_replay": True,
            "scientific_parameters_selected": False,
            "activity_values_persisted": False,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Compte rendu non scientifique : {output}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Teste le runtime du câblage sans calibration")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--seed", type=int, default=SMOKE_SEED)
    args = parser.parse_args()
    try:
        run_smoke(args.output, args.seed)
    except Exception as exc:
        print(f"\nWIRING_SMOKE_FAILED: {type(exc).__name__}: {exc}")
        return 1
    print("\nWIRING_SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

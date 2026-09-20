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
    CNSInputBuffer,
    FlyBodyProprioceptionSensor,
    MechanosensationRoutingBox,
    MotorRoutingBox,
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


def _channel_digest(activity: ChannelActivity) -> str:
    digest = hashlib.sha256()
    digest.update("\n".join(activity.channel_ids).encode("utf-8"))
    digest.update(activity.values.tobytes())
    return digest.hexdigest()


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
    proprioception = ProprioceptionRoutingBox.from_generated_wiring()
    print(
        f"[OK] {proprioception.box_id}: {len(proprioception.channel_ids):,} instances/canaux, "
        f"{len(proprioception.routes):,} destinations exactes; entrée physique différée"
    )
    mechanosensation = MechanosensationRoutingBox.from_generated_wiring()
    print(
        f"[OK] {mechanosensation.box_id}: {len(mechanosensation.channel_ids):,} instances/canaux, "
        f"{len(mechanosensation.routes):,} destinations exactes; contacts physiques différés"
    )
    vision = VisionRoutingBox.from_generated_wiring()
    print(
        f"[OK] {vision.box_id}: {len(vision.channel_ids):,} instances/canaux, "
        f"{len(vision.routes):,} destinations exactes; rétinotopie physique différée"
    )
    motor = MotorRoutingBox.from_generated_wiring()
    print(
        f"[OK] {motor.box_id}: {len(motor.channel_ids):,} instances/canaux depuis "
        f"{len(motor.source_body_ids):,} neurones moteurs; muscles différés"
    )
    unclassified = UnclassifiedSensoryRoutingBox.from_generated_wiring()
    print(
        f"[OK] {unclassified.box_id}: {len(unclassified.channel_ids):,} instances/canaux, "
        f"{len(unclassified.routes):,} destinations exactes; modalités physiques différées"
    )

    section("Injection déterministe de valeurs arbitraires")
    qpos_first = np.random.default_rng(seed - 2).uniform(-1.0, 1.0, proprio_sensor.qpos_size)
    qvel_first = np.random.default_rng(seed - 1).uniform(-1.0, 1.0, proprio_sensor.qvel_size)
    qpos_second = np.random.default_rng(seed - 2).uniform(-1.0, 1.0, proprio_sensor.qpos_size)
    qvel_second = np.random.default_rng(seed - 1).uniform(-1.0, 1.0, proprio_sensor.qvel_size)
    joint_state_first = proprio_sensor.step(qpos_first, qvel_first)
    joint_state_second = proprio_sensor.step(qpos_second, qvel_second)
    first_outputs = [box.step(_arbitrary_values(box, seed + index)) for index, box in enumerate(boxes)]
    second_outputs = [box.step(_arbitrary_values(box, seed + index)) for index, box in enumerate(boxes)]
    proprio_first = proprioception.step(_arbitrary_values(proprioception, seed + len(boxes)))
    proprio_second = proprioception.step(_arbitrary_values(proprioception, seed + len(boxes)))
    mechano_first = mechanosensation.step(_arbitrary_values(mechanosensation, seed + len(boxes) + 1))
    mechano_second = mechanosensation.step(_arbitrary_values(mechanosensation, seed + len(boxes) + 1))
    vision_first = vision.step(_arbitrary_values(vision, seed + len(boxes) + 2))
    vision_second = vision.step(_arbitrary_values(vision, seed + len(boxes) + 2))
    unclassified_first = unclassified.step(
        _arbitrary_values(unclassified, seed + len(boxes) + 3)
    )
    unclassified_second = unclassified.step(
        _arbitrary_values(unclassified, seed + len(boxes) + 3)
    )
    motor_values_first = np.random.default_rng(seed + len(boxes) + 4).uniform(
        0.0, 1.0, len(motor.source_body_ids)
    )
    motor_values_second = np.random.default_rng(seed + len(boxes) + 4).uniform(
        0.0, 1.0, len(motor.source_body_ids)
    )
    motor_first = motor.step(motor_values_first)
    motor_second = motor.step(motor_values_second)
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
    if motor_first.channel_ids != motor_second.channel_ids or not np.array_equal(
        motor_first.values, motor_second.values
    ):
        raise RuntimeError("Le rejeu du routage moteur n'est pas déterministe")
    if len(motor_first.channel_ids) != 815:
        raise RuntimeError(f"815 sorties motrices attendues, {len(motor_first.channel_ids)} obtenues")
    if joint_state_first.joint_names != joint_state_second.joint_names or not np.array_equal(
        joint_state_first.positions, joint_state_second.positions
    ) or not np.array_equal(joint_state_first.velocities, joint_state_second.velocities):
        raise RuntimeError("Le rejeu du capteur proprioceptif n'est pas déterministe")
    if len(joint_state_first.joint_names) != 102:
        raise RuntimeError(
            f"102 articulations proprioceptives attendues, {len(joint_state_first.joint_names)} obtenues"
        )
    print("[OK] 102 articulations FlyBody extraites en 204 observables position/vitesse")
    print(f"[OK] {len(first.body_ids):,} entrées CNS uniques reçues")
    print(f"[OK] {len(motor_first.channel_ids):,} sorties motrices CNS routées")
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
                "id": proprioception.box_id,
                "adapter_type": proprioception.adapter_type,
                "terminal_box_instances": len(proprioception.channel_ids),
                "exact_routes": len(proprioception.routes),
                "upstream_physical_mapping": "deferred",
                "parameter_status": "arbitrary_smoke_only",
            }
        ]
        + [
            {
                "id": mechanosensation.box_id,
                "adapter_type": mechanosensation.adapter_type,
                "terminal_box_instances": len(mechanosensation.channel_ids),
                "exact_routes": len(mechanosensation.routes),
                "upstream_physical_mapping": "deferred",
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
                "downstream_muscle_mapping": "deferred",
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
        ],
        "cns_ingress": {
            "adapter_type": CNSInputBuffer.adapter_type,
            "unique_body_ids": len(first.body_ids),
            "activity_digest": _digest(first),
        },
        "motor_egress": {
            "adapter_type": motor.adapter_type,
            "unique_source_body_ids": len(motor.source_body_ids),
            "output_channels": len(motor_first.channel_ids),
            "activity_digest": _channel_digest(motor_first),
        },
        "physical_proprioception": {
            "source_box_id": "body.flybody",
            "target_box_id": proprio_sensor.box_id,
            "joint_channels": len(joint_state_first.joint_names),
            "scalar_observables": len(joint_state_first.joint_names) * 2,
            "qpos_size": proprio_sensor.qpos_size,
            "qvel_size": proprio_sensor.qvel_size,
            "biological_receptor_mapping": "deferred",
        },
        "checks": {
            "all_routes_executed": True,
            "motor_routes_executed": True,
            "body_to_proprioception_executed": True,
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

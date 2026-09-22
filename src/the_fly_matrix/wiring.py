from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .central_graph import build_central_graph_index
from .ledger import ROOT


INVENTORY_ROOT = ROOT / "data" / "derived" / "inventory"
INVENTORY_PATH = INVENTORY_ROOT / "inventory.json"
SOURCE = INVENTORY_ROOT / "interface-neurons.parquet"
ANNOTATION_SOURCE = (
    ROOT
    / "data"
    / "raw"
    / "malecns"
    / "v1.0"
    / "body-annotations-male-cns-v1.0-minconf-0.5.feather"
)
OUTPUT_ROOT = ROOT / "data" / "derived" / "wiring"
SUMMARY_OUTPUT = OUTPUT_ROOT / "basal-clamp-routing.json"
CHANNEL_OUTPUT = OUTPUT_ROOT / "basal-clamp-channels.csv"
ROUTE_OUTPUT = OUTPUT_ROOT / "basal-clamp-routes.parquet"
PROPRIO_SUMMARY_OUTPUT = OUTPUT_ROOT / "proprioception-routing.json"
PROPRIO_CHANNEL_OUTPUT = OUTPUT_ROOT / "proprioception-channels.csv"
PROPRIO_ROUTE_OUTPUT = OUTPUT_ROOT / "proprioception-routes.parquet"
MECHANO_SUMMARY_OUTPUT = OUTPUT_ROOT / "mechanosensation-routing.json"
MECHANO_CHANNEL_OUTPUT = OUTPUT_ROOT / "mechanosensation-channels.csv"
MECHANO_ROUTE_OUTPUT = OUTPUT_ROOT / "mechanosensation-routes.parquet"
MECHANO_TRANSDUCTION_SUMMARY_OUTPUT = OUTPUT_ROOT / "mechanosensation-transduction-candidates.json"
MECHANO_INPUT_CANDIDATE_OUTPUT = OUTPUT_ROOT / "mechanosensation-input-candidates.parquet"
MECHANO_TRANSDUCTION_AUDIT_OUTPUT = OUTPUT_ROOT / "mechanosensation-transduction-channel-audit.csv"
VISION_SUMMARY_OUTPUT = OUTPUT_ROOT / "vision-routing.json"
VISION_CHANNEL_OUTPUT = OUTPUT_ROOT / "vision-channels.csv"
VISION_ROUTE_OUTPUT = OUTPUT_ROOT / "vision-routes.parquet"
MOTOR_SUMMARY_OUTPUT = OUTPUT_ROOT / "motor-routing.json"
MOTOR_CHANNEL_OUTPUT = OUTPUT_ROOT / "motor-channels.csv"
MOTOR_ROUTE_OUTPUT = OUTPUT_ROOT / "motor-routes.parquet"
MOTOR_GROUP_OUTPUT = OUTPUT_ROOT / "motor-muscle-groups.csv"
MOTOR_GROUP_MEMBER_OUTPUT = OUTPUT_ROOT / "motor-muscle-members.parquet"
MOTOR_TRANSDUCTION_SUMMARY_OUTPUT = OUTPUT_ROOT / "motor-transduction-candidates.json"
MOTOR_ACTUATOR_CANDIDATE_OUTPUT = OUTPUT_ROOT / "motor-actuator-candidates.parquet"
UNCLASSIFIED_SUMMARY_OUTPUT = OUTPUT_ROOT / "unclassified-sensory-routing.json"
UNCLASSIFIED_CHANNEL_OUTPUT = OUTPUT_ROOT / "unclassified-sensory-channels.csv"
UNCLASSIFIED_ROUTE_OUTPUT = OUTPUT_ROOT / "unclassified-sensory-routes.parquet"
FLYBODY_PROPRIO_SUMMARY_OUTPUT = OUTPUT_ROOT / "flybody-proprioception.json"
FLYBODY_PROPRIO_CHANNEL_OUTPUT = OUTPUT_ROOT / "flybody-proprioception-channels.csv"
PROPRIO_TRANSDUCTION_SUMMARY_OUTPUT = OUTPUT_ROOT / "proprioception-transduction-candidates.json"
PROPRIO_INPUT_CANDIDATE_OUTPUT = OUTPUT_ROOT / "proprioception-input-candidates.parquet"
FLYBODY_TOUCH_SUMMARY_OUTPUT = OUTPUT_ROOT / "flybody-touch.json"
FLYBODY_TOUCH_CHANNEL_OUTPUT = OUTPUT_ROOT / "flybody-touch-channels.csv"
FLYBODY_LOCAL_TOUCH_CHANNEL_OUTPUT = OUTPUT_ROOT / "flybody-local-touch-channels.csv"
FLYBODY_ACTUATOR_SUMMARY_OUTPUT = OUTPUT_ROOT / "flybody-actuators.json"
FLYBODY_ACTUATOR_CHANNEL_OUTPUT = OUTPUT_ROOT / "flybody-actuator-channels.csv"
FLYBODY_VISION_SUMMARY_OUTPUT = OUTPUT_ROOT / "flybody-vision.json"
FLYBODY_VISION_CHANNEL_OUTPUT = OUTPUT_ROOT / "flybody-vision-channels.csv"

CLAMP_SPECS = {
    "sensory.olfactory": {
        "clamp_id": "clamp.olfaction",
        "source_port": "olfactory_baseline",
        "axes": ["entryNerve", "type", "rootSide"],
    },
    "sensory.gustatory": {
        "clamp_id": "clamp.gustation",
        "source_port": "gustatory_baseline",
        "axes": ["entryNerve", "subclass", "type", "rootSide"],
    },
    "sensory.thermohygro": {
        "clamp_id": "clamp.thermohygro",
        "source_port": "thermohygro_baseline",
        "axes": ["class", "type", "rootSide"],
    },
}


def section(title: str) -> None:
    print(f"\n==> {title}", flush=True)


def _text(value: Any) -> str:
    if pd.isna(value):
        return "(unknown)"
    return str(value)


def _channel_id(group_id: str, axes: list[str], values: tuple[Any, ...]) -> str:
    key = "|".join([group_id, *(f"{axis}={_text(value)}" for axis, value in zip(axes, values))])
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"channel.{group_id}.{digest}"


def build_basal_clamp_wiring(
    source: Path = SOURCE,
    summary_output: Path = SUMMARY_OUTPUT,
    channel_output: Path = CHANNEL_OUTPUT,
    route_output: Path = ROUTE_OUTPUT,
) -> dict[str, Any]:
    if not source.is_file():
        raise FileNotFoundError(
            f"{source} absent; lancez d'abord l'inventaire MaleCNS"
        )
    section("Chargement des populations d'interface")
    frame = pd.read_parquet(source)
    output_frames: list[pd.DataFrame] = []
    channel_rows: list[dict[str, Any]] = []
    modality_rows: list[dict[str, Any]] = []

    for group_id, spec in CLAMP_SPECS.items():
        section(f"Câblage terminal {group_id}")
        selected = frame.loc[frame["group_id"].eq(group_id)].copy()
        if selected.empty:
            raise RuntimeError(f"Aucun neurone trouvé pour {group_id}")
        if selected["bodyId"].duplicated().any():
            duplicates = int(selected["bodyId"].duplicated().sum())
            raise RuntimeError(f"{group_id}: {duplicates} bodyId dupliqués")

        axes = list(spec["axes"])
        selected[axes] = selected[axes].fillna("(unknown)").astype(str)
        selected["clamp_id"] = spec["clamp_id"]
        selected["source_port"] = spec["source_port"]
        selected["target_box_id"] = "cns.malecns"
        selected["target_port"] = "basal_activity"
        selected["channel_id"] = [
            _channel_id(group_id, axes, tuple(row))
            for row in selected[axes].itertuples(index=False, name=None)
        ]
        selected["box_instance_id"] = selected["channel_id"].str.replace(
            "channel.", "box.", n=1, regex=False
        )
        selected["adapter_type"] = "A"

        grouped = selected.groupby(["channel_id", *axes], dropna=False, sort=True)
        for values, channel in grouped:
            channel_id, *axis_values = values
            item = {
                "channel_id": channel_id,
                "box_instance_id": str(channel.iloc[0]["box_instance_id"]),
                "group_id": group_id,
                "clamp_id": spec["clamp_id"],
                "adapter_type": "A",
                "source_port": spec["source_port"],
                "target_box_id": "cns.malecns",
                "target_port": "basal_activity",
                "neuron_count": int(len(channel)),
                "mapping_level": "exact_body_id",
                "free_discrete_parameters": 0,
                "continuous_parameter_values": "deferred",
            }
            item.update({axis: _text(value) for axis, value in zip(axes, axis_values)})
            channel_rows.append(item)

        route_columns = [
            "channel_id",
            "box_instance_id",
            "group_id",
            "clamp_id",
            "adapter_type",
            "source_port",
            "target_box_id",
            "target_port",
            "bodyId",
            "type",
            "instance",
            "class",
            "entryNerve",
            "subclass",
            "rootSide",
        ]
        routes = selected[route_columns].rename(columns={"bodyId": "target_body_id"})
        output_frames.append(routes)
        unknown_counts = {
            axis: int(
                selected[axis]
                .str.strip()
                .str.lower()
                .isin({"(unknown)", "unknown", "", "nan", "none"})
                .sum()
            )
            for axis in axes
        }
        channel_count = int(selected["channel_id"].nunique())
        modality_rows.append(
            {
                "group_id": group_id,
                "clamp_id": spec["clamp_id"],
                "partition_axes": axes,
                "neuron_count": int(len(selected)),
                "channel_count": channel_count,
                "unique_target_body_ids": int(selected["bodyId"].nunique()),
                "duplicate_target_body_ids": 0,
                "coverage_percent": 100.0,
                "unknown_axis_value_counts": unknown_counts,
                "mapping_level": "exact",
                "routing_status": "fixed",
                "free_discrete_parameters": 0,
                "continuous_parameters_deferred": True,
            }
        )
        print(
            f"[OK] {len(selected):,} neurones affectés exactement une fois "
            f"à {channel_count:,} canaux terminaux"
        )

    routes = pd.concat(output_frames, ignore_index=True)
    if routes.duplicated(["group_id", "target_body_id"]).any():
        raise RuntimeError("Le manifeste final contient des routes dupliquées")
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": str(source.relative_to(ROOT)).replace("\\", "/"),
        "purpose": "structural basal-clamp wiring; parameter values are deliberately absent",
        "method": {
            "terminal_channels": "one channel per unique annotated axis combination",
            "box_instances": "one generated type-A box instance owns each terminal channel",
            "target_mapping": "each channel fans out to an explicit, unique MaleCNS bodyId list",
            "parameter_policy": "all activity distributions and rates deferred to calibration",
        },
        "modalities": modality_rows,
        "totals": {
            "modalities": len(modality_rows),
            "terminal_channels": len(channel_rows),
            "generated_box_instances": len(channel_rows),
            "exact_routes": int(len(routes)),
            "duplicate_routes": 0,
            "unassigned_neurons": 0,
        },
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(channel_rows).to_csv(channel_output, index=False, encoding="utf-8")
    routes.to_parquet(route_output, index=False)
    print(f"\n[OK] Synthèse : {summary_output}")
    print(f"[OK] Canaux terminaux : {channel_output}")
    print(f"[OK] Routes bodyId exactes : {route_output}")
    return summary


def build_proprioception_wiring(
    source: Path = SOURCE,
    summary_output: Path = PROPRIO_SUMMARY_OUTPUT,
    channel_output: Path = PROPRIO_CHANNEL_OUTPUT,
    route_output: Path = PROPRIO_ROUTE_OUTPUT,
) -> dict[str, Any]:
    if not source.is_file():
        raise FileNotFoundError(f"{source} absent; lancez d'abord l'inventaire MaleCNS")
    section("Câblage terminal sensory.proprioceptive")
    frame = pd.read_parquet(source)
    selected = frame.loc[frame["group_id"].eq("sensory.proprioceptive")].copy()
    if selected.empty:
        raise RuntimeError("Aucun neurone proprioceptif trouvé")
    if selected["bodyId"].duplicated().any():
        raise RuntimeError("La population proprioceptive contient des bodyId dupliqués")

    axes = ["entryNerve", "subclass", "mancType", "type", "rootSide"]
    selected[axes] = selected[axes].fillna("(unknown)").astype(str)
    selected["routing_box_id"] = "adapter.proprioception.routing"
    selected["source_port"] = "proprioceptive_afferents"
    selected["target_box_id"] = "cns.malecns"
    selected["target_port"] = "sensory_afferents"
    selected["channel_id"] = [
        _channel_id("sensory.proprioceptive", axes, tuple(row))
        for row in selected[axes].itertuples(index=False, name=None)
    ]
    selected["box_instance_id"] = selected["channel_id"].str.replace(
        "channel.", "box.", n=1, regex=False
    )
    selected["adapter_type"] = "C"

    channel_rows: list[dict[str, Any]] = []
    grouped = selected.groupby(["channel_id", *axes], dropna=False, sort=True)
    for values, channel in grouped:
        channel_id, *axis_values = values
        item = {
            "channel_id": channel_id,
            "box_instance_id": str(channel.iloc[0]["box_instance_id"]),
            "group_id": "sensory.proprioceptive",
            "routing_box_id": "adapter.proprioception.routing",
            "adapter_type": "C",
            "source_port": "proprioceptive_afferents",
            "target_box_id": "cns.malecns",
            "target_port": "sensory_afferents",
            "neuron_count": int(len(channel)),
            "mapping_level": "exact_body_id",
            "free_discrete_parameters_downstream": 0,
            "upstream_physical_mapping": "deferred",
        }
        item.update({axis: _text(value) for axis, value in zip(axes, axis_values)})
        channel_rows.append(item)

    route_columns = [
        "channel_id",
        "box_instance_id",
        "group_id",
        "routing_box_id",
        "adapter_type",
        "source_port",
        "target_box_id",
        "target_port",
        "bodyId",
        "type",
        "instance",
        "entryNerve",
        "subclass",
        "mancType",
        "rootSide",
    ]
    routes = selected[route_columns].rename(columns={"bodyId": "target_body_id"})
    if routes.duplicated(["group_id", "target_body_id"]).any():
        raise RuntimeError("Le manifeste proprioceptif contient des routes dupliquées")
    unknown_counts = {
        axis: int(
            selected[axis]
            .str.strip()
            .str.lower()
            .isin({"(unknown)", "unknown", "", "nan", "none"})
            .sum()
        )
        for axis in axes
    }
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": str(source.relative_to(ROOT)).replace("\\", "/"),
        "purpose": "exact downstream proprioceptive routing; physical transduction is deferred",
        "method": {
            "terminal_channels": "one type-C instance per unique annotated axis combination",
            "target_mapping": "each instance fans out to an explicit, unique MaleCNS bodyId list",
            "upstream_policy": "joint/body observable assignment remains unknown until independently audited",
        },
        "group_id": "sensory.proprioceptive",
        "routing_box_id": "adapter.proprioception.routing",
        "partition_axes": axes,
        "neuron_count": int(len(selected)),
        "terminal_channels": len(channel_rows),
        "generated_box_instances": len(channel_rows),
        "exact_routes": int(len(routes)),
        "duplicate_routes": 0,
        "unassigned_neurons": 0,
        "unknown_axis_value_counts": unknown_counts,
        "downstream_routing_status": "fixed",
        "upstream_mapping_status": "unknown",
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(channel_rows).to_csv(channel_output, index=False, encoding="utf-8")
    routes.to_parquet(route_output, index=False)
    print(
        f"[OK] {len(selected):,} neurones affectés exactement une fois "
        f"à {len(channel_rows):,} instances type C"
    )
    print(f"[OK] Synthèse : {summary_output}")
    print(f"[OK] Canaux terminaux : {channel_output}")
    print(f"[OK] Routes bodyId exactes : {route_output}")
    return summary


def build_flybody_proprioception_wiring(
    inventory_path: Path = INVENTORY_PATH,
    summary_output: Path = FLYBODY_PROPRIO_SUMMARY_OUTPUT,
    channel_output: Path = FLYBODY_PROPRIO_CHANNEL_OUTPUT,
) -> dict[str, Any]:
    """Wire raw FlyBody joint state into the proprioception sensor box.

    This is deliberately the physical half only: it exposes joint positions and
    velocities but makes no claim about which biological receptor consumes them.
    """
    if not inventory_path.is_file():
        raise FileNotFoundError(f"{inventory_path} absent; lancez d'abord l'inventaire")
    section("Câblage FlyBody vers le capteur proprioceptif")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    flybody = inventory["flybody"]
    rows = flybody.get("joint_observables", [])
    if not rows:
        raise RuntimeError("L'inventaire FlyBody ne contient aucune observable articulaire")
    channels = pd.DataFrame(rows).sort_values("joint_id").reset_index(drop=True)
    channels.insert(
        0,
        "channel_id",
        channels["joint_id"].map(lambda value: f"channel.flybody.joint.{int(value):03d}"),
    )
    channels.insert(1, "source_box_id", "body.flybody")
    channels.insert(2, "source_port", "body_state")
    channels.insert(3, "target_box_id", "sensor.proprioception")
    channels.insert(4, "target_port", "body_state")
    channels["observables"] = "position,velocity"
    if channels["channel_id"].duplicated().any():
        raise RuntimeError("Les identifiants de canaux articulaires ne sont pas uniques")
    if channels["joint_name"].duplicated().any():
        raise RuntimeError("Les noms d'articulations FlyBody ne sont pas uniques")
    if channels["qpos_address"].duplicated().any() or channels["qvel_address"].duplicated().any():
        raise RuntimeError("Les adresses qpos/qvel articulaires ne sont pas injectives")
    expected = int(flybody["model"]["nq"])
    if len(channels) != expected or int(flybody["model"]["nv"]) != expected:
        raise RuntimeError("La cardinalité des observables ne correspond pas à nq/nv")
    group_counts = {
        str(key): int(value)
        for key, value in channels["body_group"].value_counts().sort_index().items()
    }
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": str(inventory_path.relative_to(ROOT)).replace("\\", "/"),
        "purpose": "exact FlyBody joint-state wiring; biological receptor assignment is deferred",
        "wire_id": "wire.body_to_proprioception",
        "source_box_id": "body.flybody",
        "target_box_id": "sensor.proprioception",
        "joint_channels": len(channels),
        "scalar_observables": len(channels) * 2,
        "position_observables": len(channels),
        "velocity_observables": len(channels),
        "joint_group_counts": group_counts,
        "qpos_addressing": "exact",
        "qvel_addressing": "exact",
        "biological_receptor_mapping": "deferred",
        "free_discrete_parameters": 0,
        "continuous_parameters_deferred": True,
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    channels.to_csv(channel_output, index=False, encoding="utf-8")
    print(f"[OK] {len(channels):,} articulations reliées par adresse qpos/qvel exacte")
    print(f"[OK] {len(channels) * 2:,} observables scalaires exposées sans calibration")
    print(f"[OK] Synthèse : {summary_output}")
    print(f"[OK] Canaux physiques : {channel_output}")
    return summary


def build_proprioception_transduction_candidates(
    receptor_channel_path: Path = PROPRIO_CHANNEL_OUTPUT,
    receptor_route_path: Path = PROPRIO_ROUTE_OUTPUT,
    joint_channel_path: Path = FLYBODY_PROPRIO_CHANNEL_OUTPUT,
    annotation_path: Path = ANNOTATION_SOURCE,
    summary_output: Path = PROPRIO_TRANSDUCTION_SUMMARY_OUTPUT,
    candidate_output: Path = PROPRIO_INPUT_CANDIDATE_OUTPUT,
) -> dict[str, Any]:
    """Build a sparse local joint-state-to-proprioceptor candidate matrix.

    Only explicit entry-nerve, side and receptor-class annotations are used.
    Missing strain and vibration observables remain explicit terminals instead
    of being replaced by joint angle proxies.
    """
    for path in (
        receptor_channel_path,
        receptor_route_path,
        joint_channel_path,
        annotation_path,
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{path} absent; reconstruisez d'abord le câblage")
    section("Construction de la matrice candidate proprioceptive")
    receptors = pd.read_csv(receptor_channel_path).fillna("(unknown)")
    routes = pd.read_parquet(receptor_route_path)
    joints = pd.read_csv(joint_channel_path).fillna("(unknown)")
    annotations = pd.read_feather(annotation_path, columns=["bodyId", "synonyms"])
    annotated_routes = routes[["channel_id", "target_body_id"]].merge(
        annotations,
        left_on="target_body_id",
        right_on="bodyId",
        how="left",
        validate="many_to_one",
    )
    synonym_sets = {
        str(channel_id): tuple(sorted(set(values.dropna().astype(str))))
        for channel_id, values in annotated_routes.groupby("channel_id")["synonyms"]
    }

    leg_nerve_to_segment = {
        "ProLN": "f",
        "ProAN": "f",
        "VProN": "f",
        "DProN": "f",
        "MesoLN": "m",
        "MetaLN": "h",
    }
    candidate_rows: list[dict[str, Any]] = []
    channel_results: list[dict[str, Any]] = []
    for receptor in receptors.itertuples(index=False):
        channel_id = str(receptor.channel_id)
        nerve = str(receptor.entryNerve)
        subclass = str(receptor.subclass)
        side = str(receptor.rootSide).lower()
        synonyms = synonym_sets.get(channel_id, ())
        candidates = joints.iloc[0:0]
        observables: tuple[str, ...] = ()
        basis = ""
        unresolved_reason = ""

        if subclass == "campaniform sensilla":
            unresolved_reason = "strain_observable_missing"
        elif subclass == "notum":
            unresolved_reason = "notum_strain_observable_missing"
        elif "FeCO club" in synonyms:
            unresolved_reason = "vibration_observable_missing"
        elif nerve in leg_nerve_to_segment and side in {"l", "r"}:
            prefix = f"{side}{leg_nerve_to_segment[nerve]}"
            candidates = joints.loc[
                joints["body_group"].eq("legs")
                & joints["joint_name"].str.contains(f"{prefix}_", regex=False)
            ]
            if subclass == "chordotonal organ":
                candidates = candidates.loc[
                    candidates["joint_name"].str.contains(
                        f"{prefix}_trochanterfemur-{prefix}_tibia-pitch",
                        regex=False,
                    )
                ]
                if "FeCO claw" in synonyms:
                    observables = ("position",)
                    basis = "annotated_feco_claw_position"
                elif "FeCO hook" in synonyms:
                    observables = ("velocity",)
                    basis = "annotated_feco_hook_movement"
                else:
                    observables = ("position", "velocity")
                    basis = "leg_nerve_side_femur_tibia_chordotonal"
            elif subclass == "hair plate":
                observables = ("position",)
                basis = "leg_nerve_side_hair_plate_position"
            else:
                observables = ("position", "velocity")
                basis = "leg_nerve_side_unspecified_joint_state"
        elif nerve == "DMetaN" and subclass == "haltere" and side in {"l", "r"}:
            candidates = joints.loc[
                joints["body_group"].eq("halteres")
                & joints["joint_name"].str.contains(f"-{side}_haltere", regex=False)
            ]
            observables = ("position", "velocity")
            basis = "entry_nerve_side_haltere_motion"
        elif nerve == "ADMN" and subclass == "wing" and side in {"l", "r"}:
            candidates = joints.loc[
                joints["body_group"].eq("wings")
                & joints["joint_name"].str.contains(f"-{side}_wing", regex=False)
            ]
            observables = ("position", "velocity")
            basis = "entry_nerve_side_wing_motion"
        elif nerve == "AbN3" and subclass == "abdomen":
            candidates = joints.loc[joints["body_group"].eq("abdomen")]
            observables = ("position", "velocity")
            basis = "entry_nerve_abdominal_joint_state"
        elif nerve == "ProCN" and subclass == "chordotonal organ":
            candidates = joints.loc[joints["body_group"].eq("head")]
            observables = ("position", "velocity")
            basis = "prothoracic_chordotonal_head_motion"
        elif nerve == "PrN" and subclass in {"hair plate", "neck"}:
            candidates = joints.loc[joints["body_group"].eq("head")]
            observables = ("position",) if subclass == "hair plate" else ("position", "velocity")
            basis = "prosternal_nerve_head_joint_state"
        else:
            unresolved_reason = "anatomical_assignment_unresolved"

        if not unresolved_reason and candidates.empty:
            raise RuntimeError(f"Aucune articulation candidate pour {channel_id} ({nerve}, {subclass})")
        if not unresolved_reason and not observables:
            raise RuntimeError(f"Aucune observable candidate pour {channel_id}")
        if unresolved_reason:
            channel_results.append(
                {
                    "channel_id": channel_id,
                    "neuron_count": int(receptor.neuron_count),
                    "status": "missing_physical_observable",
                    "reason": unresolved_reason,
                }
            )
            continue

        channel_results.append(
            {
                "channel_id": channel_id,
                "neuron_count": int(receptor.neuron_count),
                "status": "candidates_known",
                "reason": basis,
            }
        )
        for joint in candidates.itertuples(index=False):
            for observable in observables:
                parameter_key = f"{joint.channel_id}|{observable}|{channel_id}"
                candidate_rows.append(
                    {
                        "parameter_id": "parameter.proprioception.edge."
                        + hashlib.sha256(parameter_key.encode("utf-8")).hexdigest()[:16],
                        "source_channel_id": str(joint.channel_id),
                        "source_joint_id": int(joint.joint_id),
                        "source_joint_name": str(joint.joint_name),
                        "source_body_group": str(joint.body_group),
                        "source_observable": observable,
                        "target_channel_id": channel_id,
                        "entry_nerve": nerve,
                        "subclass": subclass,
                        "side": str(receptor.rootSide),
                        "candidate_basis": basis,
                        "parameter_status": "unassigned",
                    }
                )

    candidates = pd.DataFrame(candidate_rows).sort_values(
        ["target_channel_id", "source_joint_id", "source_observable"]
    ).reset_index(drop=True)
    results = pd.DataFrame(channel_results)
    if candidates["parameter_id"].duplicated().any():
        raise RuntimeError("La matrice proprioceptive contient des paramètres dupliqués")
    resolved_ids = set(candidates["target_channel_id"].astype(str))
    unresolved_ids = set(receptors["channel_id"].astype(str)) - resolved_ids
    if resolved_ids & unresolved_ids or resolved_ids | unresolved_ids != set(
        receptors["channel_id"].astype(str)
    ):
        raise RuntimeError("La partition des canaux proprioceptifs est incohérente")
    if (len(candidates), len(resolved_ids), len(unresolved_ids)) != (1439, 171, 91):
        raise RuntimeError(
            "Matrice proprioceptive inattendue: "
            f"{len(candidates)} arêtes, {len(resolved_ids)} résolus, {len(unresolved_ids)} non résolus"
        )
    unresolved = results.loc[results["status"].eq("missing_physical_observable")]
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": "sparse local joint-state-to-proprioceptor candidate matrix without fitted values",
        "scientific_basis": {
            "male_cns_annotations": "https://github.com/flyconnectome/2025malecns",
            "feco_publication": "https://doi.org/10.1038/s41467-025-59302-3",
            "used_claims": [
                "entryNerve and rootSide constrain the represented appendage",
                "FeCO claw, hook and club classes encode position, movement and vibration respectively",
                "unrepresented strain and vibration are not replaced by angle proxies",
            ],
        },
        "method": {
            "candidate_rule": "same annotated appendage and side; receptor subclass restricts local observable",
            "parameterization": "one free signed local coefficient per permitted observable-to-terminal edge",
            "initialization": "absent; all parameter values remain unassigned",
            "unresolved_policy": "runtime requires explicit external placeholder values for terminals whose physical observable is absent",
        },
        "source_joint_channels": int(len(joints)),
        "source_scalar_observables": int(len(joints) * 2),
        "target_terminal_channels": int(len(receptors)),
        "target_neurons": int(receptors["neuron_count"].sum()),
        "candidate_edges": int(len(candidates)),
        "free_continuous_parameters": int(len(candidates)),
        "resolved_terminal_channels": len(resolved_ids),
        "resolved_neurons": int(
            receptors.loc[receptors["channel_id"].isin(resolved_ids), "neuron_count"].sum()
        ),
        "unresolved_terminal_channels": len(unresolved_ids),
        "unresolved_neurons": int(unresolved["neuron_count"].sum()),
        "unresolved_reason_channel_counts": {
            str(key): int(value)
            for key, value in unresolved["reason"].value_counts().sort_index().items()
        },
        "candidate_basis_edge_counts": {
            str(key): int(value)
            for key, value in candidates["candidate_basis"].value_counts().sort_index().items()
        },
        "routing_status": "candidates_known_with_explicit_missing_observables",
        "parameter_status": "unassigned",
        "scientific_parameter_values_selected": False,
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    candidates.to_parquet(candidate_output, index=False)
    print(f"[OK] {len(candidates):,} arêtes locales candidates, toutes sans valeur")
    print(f"[OK] {len(resolved_ids):,}/262 canaux terminaux reliés à des observables articulaires")
    print(f"[INFO] {len(unresolved_ids):,}/262 terminaux attendent une observable de contrainte ou vibration")
    print(f"[OK] Synthèse : {summary_output}")
    print(f"[OK] Matrice candidate : {candidate_output}")
    return summary


def build_flybody_touch_wiring(
    inventory_path: Path = INVENTORY_PATH,
    summary_output: Path = FLYBODY_TOUCH_SUMMARY_OUTPUT,
    channel_output: Path = FLYBODY_TOUCH_CHANNEL_OUTPUT,
    local_channel_output: Path = FLYBODY_LOCAL_TOUCH_CHANNEL_OUTPUT,
) -> dict[str, Any]:
    """Wire FlyGym aggregate leg and selected body-segment contact observations."""
    if not inventory_path.is_file():
        raise FileNotFoundError(f"{inventory_path} absent; lancez d'abord l'inventaire")
    section("Câblage des contacts FlyBody vers le capteur tactile")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    interface = inventory["flybody"].get("contact_interface", {})
    sensor_rows = interface.get("aggregate_leg_sensors", [])
    segment_rows = interface.get("collision_enabled_segments", [])
    if not sensor_rows or not segment_rows:
        raise RuntimeError("L'inventaire FlyBody ne contient pas d'interface de contact")
    channels = pd.DataFrame(sensor_rows).sort_values("sensor_address").reset_index(drop=True)
    channels.insert(0, "channel_id", channels["leg"].map(lambda leg: f"channel.flybody.ground_contact.{leg}"))
    channels.insert(1, "source_box_id", "world.mujoco")
    channels.insert(2, "source_port", "contacts")
    channels.insert(3, "target_box_id", "sensor.touch")
    channels.insert(4, "target_port", "contacts")
    channels["scope"] = "aggregate_ground_contact_per_leg"
    channels["position_unit"] = "mm"
    channels["force_unit"] = "MuJoCo_model_unit"
    channels["torque_unit"] = "MuJoCo_model_unit"
    channels["direction_unit"] = "unitless"
    channels["observable_layout"] = channels["observable_layout"].map(
        lambda values: ",".join(values)
    )
    if channels["channel_id"].duplicated().any() or channels["sensor_name"].duplicated().any():
        raise RuntimeError("Les canaux de contact FlyBody ne sont pas uniques")
    if not channels["sensor_dimension"].eq(16).all():
        raise RuntimeError("Chaque capteur de contact au sol doit exposer 16 scalaires")
    expected_legs = {"lf", "lm", "lh", "rf", "rm", "rh"}
    if set(channels["leg"]) != expected_legs:
        raise RuntimeError("Les six pattes ne sont pas toutes couvertes exactement une fois")
    segment_frame = pd.DataFrame(segment_rows)
    local_segments = segment_frame.loc[
        segment_frame["segment_name"].isin({"c_thorax", "c_head"})
    ].copy()
    local_segments["channel_id"] = local_segments["segment_name"].map(
        lambda value: f"channel.flybody.local_contact.{value}"
    )
    local_segments["source_box_id"] = "world.mujoco"
    local_segments["source_port"] = "contacts"
    local_segments["target_box_id"] = "sensor.touch"
    local_segments["target_port"] = "contacts"
    local_segments["query_method"] = "Simulation.get_bodysegment_contact_forces"
    local_segments["ground_only"] = False
    local_segments["observable_layout"] = "force_world_x,force_world_y,force_world_z"
    local_segments["force_unit"] = "MuJoCo_model_unit"
    local_segments["geom_names"] = local_segments["geom_names"].map(
        lambda values: ",".join(values)
    )
    local_segments = local_segments.sort_values("segment_name").reset_index(drop=True)
    if set(local_segments["segment_name"]) != {"c_thorax", "c_head"}:
        raise RuntimeError("Les segments de contact tête et thorax ne sont pas tous représentés")
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": str(inventory_path.relative_to(ROOT)).replace("\\", "/"),
        "purpose": "exact FlyGym ground-contact sensor wiring; receptor assignment is deferred",
        "wire_id": "wire.world_to_touch",
        "source_box_id": "world.mujoco",
        "target_box_id": "sensor.touch",
        "collision_enabled_segments": len(segment_rows),
        "explicit_ground_contact_pairs": int(interface["explicit_ground_contact_pairs"]),
        "aggregate_leg_channels": len(channels),
        "scalars_per_leg": 16,
        "scalar_observables": int(channels["sensor_dimension"].sum()),
        "local_body_contact_channels": len(local_segments),
        "local_body_contact_scalar_observables": int(len(local_segments) * 3),
        "local_body_contact_segments": local_segments["segment_name"].tolist(),
        "legs": channels["leg"].tolist(),
        "ground_contact_sensor_mapping": "exact",
        "non_leg_local_load_mapping": "exact_for_head_and_thorax_net_force",
        "biological_receptor_mapping": "deferred",
        "free_discrete_parameters": 0,
        "continuous_parameters_deferred": True,
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    channels.to_csv(channel_output, index=False, encoding="utf-8")
    local_segments.to_csv(local_channel_output, index=False, encoding="utf-8")
    print(f"[OK] {len(segment_rows):,} segments de collision et {interface['explicit_ground_contact_pairs']:,} paires inventoriés")
    print(f"[OK] {len(channels):,} capteurs de patte reliés, {summary['scalar_observables']:,} scalaires exposés")
    print("[OK] 2 canaux de force nette locale ajoutés pour le thorax et la tête")
    print("[INFO] Les autres charges locales hors pattes restent différées")
    print(f"[OK] Synthèse : {summary_output}")
    print(f"[OK] Canaux physiques : {channel_output}")
    print(f"[OK] Contacts corporels locaux : {local_channel_output}")
    return summary


def build_flybody_actuator_wiring(
    inventory_path: Path = INVENTORY_PATH,
    summary_output: Path = FLYBODY_ACTUATOR_SUMMARY_OUTPUT,
    channel_output: Path = FLYBODY_ACTUATOR_CHANNEL_OUTPUT,
) -> dict[str, Any]:
    """Wire pre-transduced commands to exact FlyBody actuator addresses."""
    if not inventory_path.is_file():
        raise FileNotFoundError(f"{inventory_path} absent; lancez d'abord l'inventaire")
    section("Câblage des commandes vers les actionneurs FlyBody")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    flybody = inventory["flybody"]
    rows = flybody.get("actuator_channels", [])
    if not rows:
        raise RuntimeError("L'inventaire FlyBody ne contient aucun canal d'actionneur")
    channels = pd.DataFrame(rows).sort_values("control_address").reset_index(drop=True)
    channels.insert(
        0,
        "channel_id",
        channels["actuator_id"].map(lambda value: f"channel.flybody.actuator.{int(value):03d}"),
    )
    channels.insert(1, "source_box_id", "adapter.motor.transduction")
    channels.insert(2, "source_port", "actuator_commands")
    channels.insert(3, "target_box_id", "body.flybody")
    channels.insert(4, "target_port", "actuator_commands")
    if channels["channel_id"].duplicated().any() or channels["actuator_name"].duplicated().any():
        raise RuntimeError("Les canaux d'actionneur FlyBody ne sont pas uniques")
    if channels["control_address"].duplicated().any():
        raise RuntimeError("Les adresses de commande FlyBody ne sont pas injectives")
    expected = int(flybody["model"]["nu"])
    if len(channels) != expected:
        raise RuntimeError("La cardinalité des actionneurs ne correspond pas à nu")
    if channels["target_joint_id"].duplicated().any():
        raise RuntimeError("Plusieurs actionneurs ciblent le même joint dans ce contrat")
    status_counts = {
        str(key): int(value)
        for key, value in channels["actuator_config_status"].value_counts().items()
    }
    group_counts = {
        str(key): int(value)
        for key, value in channels["body_group"].value_counts().sort_index().items()
    }
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": str(inventory_path.relative_to(ROOT)).replace("\\", "/"),
        "purpose": "exact pre-transduced command wiring; motor-neuron-to-muscle mapping is deferred",
        "wire_id": "wire.motor_transduction_to_body",
        "source_box_id": "adapter.motor.transduction",
        "target_box_id": "body.flybody",
        "actuator_channels": len(channels),
        "unique_control_addresses": int(channels["control_address"].nunique()),
        "unique_target_joints": int(channels["target_joint_id"].nunique()),
        "body_group_counts": group_counts,
        "actuator_config_status_counts": status_counts,
        "missing_actuator_config_joints": channels.loc[
            channels["actuator_config_status"].eq("missing"), "target_joint_name"
        ].tolist(),
        "control_addressing": "exact",
        "motor_neuron_to_actuator_mapping": "deferred",
        "free_discrete_parameters_downstream": 0,
        "scientific_parameter_values_selected": False,
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    channels.to_csv(channel_output, index=False, encoding="utf-8")
    print(f"[OK] {len(channels):,} actionneurs reliés à des adresses ctrl exactes")
    print(
        f"[OK] {status_counts.get('configured', 0):,} actionneurs configurés; "
        f"{status_counts.get('missing', 0):,} sans configuration FlyBody spécifique"
    )
    print("[INFO] La correspondance neuronale est construite séparément par la transduction motrice")
    print(f"[OK] Synthèse : {summary_output}")
    print(f"[OK] Canaux physiques : {channel_output}")
    return summary


def build_flybody_vision_wiring(
    inventory_path: Path = INVENTORY_PATH,
    summary_output: Path = FLYBODY_VISION_SUMMARY_OUTPUT,
    channel_output: Path = FLYBODY_VISION_CHANNEL_OUTPUT,
) -> dict[str, Any]:
    """Enumerate the active per-ommatidium samples returned by FlyGym."""
    if not inventory_path.is_file():
        raise FileNotFoundError(f"{inventory_path} absent; lancez d'abord l'inventaire")
    section("Câblage des caméras FlyBody vers le capteur visuel")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    interface = inventory["flybody"].get("vision_interface", {})
    cameras = interface.get("cameras", [])
    ommatidium_types = interface.get("ommatidium_types", [])
    pixel_counts = interface.get("pixels_per_ommatidium", [])
    if len(cameras) != 2 or not ommatidium_types or len(ommatidium_types) != len(pixel_counts):
        raise RuntimeError("L'inventaire visuel FlyBody est incomplet")
    rows: list[dict[str, Any]] = []
    for camera in cameras:
        eye = str(camera["eye"])
        eye_code = "l" if eye == "left" else "r"
        for ommatidium_id, (ommatidium_type, pixel_count) in enumerate(
            zip(ommatidium_types, pixel_counts)
        ):
            component_index = 1 if ommatidium_type == "pale" else 0
            rows.append(
                {
                    "channel_id": f"channel.flybody.vision.{eye_code}.{ommatidium_id:03d}",
                    "source_box_id": "world.mujoco",
                    "source_port": "light",
                    "target_box_id": "sensor.vision",
                    "target_port": "light",
                    "eye_index": int(camera["eye_index"]),
                    "eye": eye,
                    "camera_name": camera["camera_name"],
                    "camera_id": int(camera["camera_id"]),
                    "ommatidium_id": ommatidium_id,
                    "ommatidium_type": ommatidium_type,
                    "component_index": component_index,
                    "raw_pixel_count": int(pixel_count),
                    "readout_unit": interface["readout_unit"],
                }
            )
    channels = pd.DataFrame(rows)
    if channels["channel_id"].duplicated().any():
        raise RuntimeError("Les canaux visuels FlyBody ne sont pas uniques")
    per_eye = int(interface["ommatidia_per_eye"])
    if len(channels) != 2 * per_eye:
        raise RuntimeError("La cardinalité des canaux visuels ne correspond pas aux yeux")
    type_counts_per_eye = {
        str(key): int(value)
        for key, value in channels.loc[channels["eye_index"].eq(0), "ommatidium_type"]
        .value_counts()
        .sort_index()
        .items()
    }
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": str(inventory_path.relative_to(ROOT)).replace("\\", "/"),
        "purpose": "exact FlyGym physical vision channels; MaleCNS retinotopy is deferred",
        "wire_ids": ["wire.world_to_vision", "wire.vision_sensor_to_transduction"],
        "source_box_id": "world.mujoco",
        "target_box_id": "sensor.vision",
        "eye_cameras": len(cameras),
        "ommatidia_per_eye": per_eye,
        "active_sample_channels": len(channels),
        "raw_readout_scalar_slots": int(2 * per_eye * 2),
        "raw_frame_shape": interface["raw_frame_shape"],
        "readout_shape": interface["readout_shape"],
        "field_of_view_degrees": [camera["field_of_view_degrees"] for camera in cameras],
        "ommatidium_type_counts_per_eye": type_counts_per_eye,
        "physical_channel_mapping": "exact",
        "malecns_retinotopic_mapping": "deferred",
        "scientific_parameter_values_selected": False,
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    channels.to_csv(channel_output, index=False, encoding="utf-8")
    print(f"[OK] {len(cameras)} caméras, {per_eye:,} ommatidies par œil")
    print(f"[OK] {len(channels):,} échantillons actifs reliés sans rétinotopie MaleCNS")
    print(f"[OK] Synthèse : {summary_output}")
    print(f"[OK] Canaux physiques : {channel_output}")
    return summary


def build_mechanosensation_wiring(
    source: Path = SOURCE,
    summary_output: Path = MECHANO_SUMMARY_OUTPUT,
    channel_output: Path = MECHANO_CHANNEL_OUTPUT,
    route_output: Path = MECHANO_ROUTE_OUTPUT,
) -> dict[str, Any]:
    """Build the exact downstream half of the mechanosensory type-C adapter."""
    if not source.is_file():
        raise FileNotFoundError(f"{source} absent; lancez d'abord l'inventaire MaleCNS")
    section("Câblage terminal des afférences mécanoréceptrices")
    frame = pd.read_parquet(source)
    group_ids = ("sensory.tactile", "sensory.mechanosensory_other")
    selected = frame.loc[frame["group_id"].isin(group_ids)].copy()
    if selected.empty:
        raise RuntimeError("Aucun neurone mécanorécepteur trouvé")
    if selected["bodyId"].duplicated().any():
        raise RuntimeError("Les populations mécanoréceptrices se chevauchent par bodyId")

    axes = ["entryNerve", "subclass", "mancType", "type", "rootSide"]
    selected[axes] = selected[axes].fillna("(unknown)").astype(str)
    selected["routing_box_id"] = "adapter.touch.routing"
    selected["source_port"] = "mechanosensory_afferents"
    selected["target_box_id"] = "cns.malecns"
    selected["target_port"] = "sensory_afferents"
    selected["channel_id"] = [
        _channel_id(str(group_id), axes, tuple(row))
        for group_id, row in zip(
            selected["group_id"], selected[axes].itertuples(index=False, name=None)
        )
    ]
    selected["box_instance_id"] = selected["channel_id"].str.replace(
        "channel.", "box.", n=1, regex=False
    )
    selected["adapter_type"] = "C"

    channel_rows: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []
    grouped = selected.groupby(["group_id", "channel_id", *axes], dropna=False, sort=True)
    for values, channel in grouped:
        group_id, channel_id, *axis_values = values
        item = {
            "channel_id": channel_id,
            "box_instance_id": str(channel.iloc[0]["box_instance_id"]),
            "group_id": group_id,
            "routing_box_id": "adapter.touch.routing",
            "adapter_type": "C",
            "source_port": "mechanosensory_afferents",
            "target_box_id": "cns.malecns",
            "target_port": "sensory_afferents",
            "neuron_count": int(len(channel)),
            "mapping_level": "exact_body_id",
            "free_discrete_parameters_downstream": 0,
            "upstream_physical_mapping": "deferred",
        }
        item.update({axis: _text(value) for axis, value in zip(axes, axis_values)})
        channel_rows.append(item)

    for group_id in group_ids:
        group = selected.loc[selected["group_id"].eq(group_id)]
        unknown_counts = {
            axis: int(
                group[axis]
                .str.strip()
                .str.lower()
                .isin({"(unknown)", "unknown", "", "nan", "none"})
                .sum()
            )
            for axis in axes
        }
        group_rows.append(
            {
                "group_id": group_id,
                "neuron_count": int(len(group)),
                "terminal_channels": int(group["channel_id"].nunique()),
                "unique_target_body_ids": int(group["bodyId"].nunique()),
                "unknown_axis_value_counts": unknown_counts,
                "coverage_percent": 100.0,
            }
        )
        print(
            f"[OK] {group_id}: {len(group):,} neurones, "
            f"{group['channel_id'].nunique():,} instances type C"
        )

    route_columns = [
        "channel_id",
        "box_instance_id",
        "group_id",
        "routing_box_id",
        "adapter_type",
        "source_port",
        "target_box_id",
        "target_port",
        "bodyId",
        "type",
        "instance",
        "entryNerve",
        "subclass",
        "mancType",
        "rootSide",
    ]
    routes = selected[route_columns].rename(columns={"bodyId": "target_body_id"})
    if routes["target_body_id"].duplicated().any():
        raise RuntimeError("Le manifeste mécanorécepteur contient des routes dupliquées")
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": str(source.relative_to(ROOT)).replace("\\", "/"),
        "purpose": "exact downstream mechanosensory routing; physical transduction is deferred",
        "method": {
            "terminal_channels": "one type-C instance per group and unique annotated axis combination",
            "target_mapping": "each instance fans out to an explicit, unique MaleCNS bodyId list",
            "classification_policy": "unknown annotations and unresolved mechanosensory modalities remain explicit",
            "upstream_policy": "body-surface observable assignment remains unknown until independently audited",
        },
        "group_ids": list(group_ids),
        "routing_box_id": "adapter.touch.routing",
        "partition_axes": axes,
        "groups": group_rows,
        "neuron_count": int(len(selected)),
        "terminal_channels": len(channel_rows),
        "generated_box_instances": len(channel_rows),
        "exact_routes": int(len(routes)),
        "duplicate_routes": 0,
        "unassigned_neurons": 0,
        "downstream_routing_status": "fixed",
        "upstream_mapping_status": "unknown",
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(channel_rows).to_csv(channel_output, index=False, encoding="utf-8")
    routes.to_parquet(route_output, index=False)
    print(
        f"[OK] Total: {len(selected):,} routes exactes vers "
        f"{len(channel_rows):,} instances type C"
    )
    print(f"[OK] Synthèse : {summary_output}")
    print(f"[OK] Canaux terminaux : {channel_output}")
    print(f"[OK] Routes bodyId exactes : {route_output}")
    return summary


def build_mechanosensation_transduction_candidates(
    receptor_channel_path: Path = MECHANO_CHANNEL_OUTPUT,
    contact_channel_path: Path = FLYBODY_TOUCH_CHANNEL_OUTPUT,
    local_contact_channel_path: Path = FLYBODY_LOCAL_TOUCH_CHANNEL_OUTPUT,
    joint_channel_path: Path = FLYBODY_PROPRIO_CHANNEL_OUTPUT,
    summary_output: Path = MECHANO_TRANSDUCTION_SUMMARY_OUTPUT,
    candidate_output: Path = MECHANO_INPUT_CANDIDATE_OUTPUT,
    audit_output: Path = MECHANO_TRANSDUCTION_AUDIT_OUTPUT,
) -> dict[str, Any]:
    """Constrain local contact and appendage-motion inputs to annotated afferents."""
    for path in (
        receptor_channel_path,
        contact_channel_path,
        local_contact_channel_path,
        joint_channel_path,
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{path} absent; reconstruisez d'abord le câblage")
    section("Construction de la matrice candidate mécanoréceptrice")
    receptors = pd.read_csv(receptor_channel_path).fillna("(unknown)")
    contacts = pd.read_csv(contact_channel_path).fillna("(unknown)")
    local_contacts = pd.read_csv(local_contact_channel_path).fillna("(unknown)")
    joints = pd.read_csv(joint_channel_path).fillna("(unknown)")
    leg_nerve_to_segment = {
        "ProLN": "f",
        "ProAN": "f",
        "VProN": "f",
        "DProN": "f",
        "MesoLN": "m",
        "MetaLN": "h",
    }
    local_contact_by_nerve = {
        "PDMN": (
            "c_thorax",
            "posterior_dorsal_mesothoracic_nerve_thorax_contact",
        ),
        "ON": ("c_head", "optic_nerve_head_contact"),
    }
    contact_observables = (
        "contact_found",
        "force_x",
        "force_y",
        "force_z",
        "torque_x",
        "torque_y",
        "torque_z",
    )
    contacts_by_leg = contacts.set_index("leg", drop=False)
    local_contacts_by_segment = local_contacts.set_index("segment_name", drop=False)
    candidate_rows: list[dict[str, Any]] = []
    channel_results: list[dict[str, Any]] = []
    for receptor in receptors.itertuples(index=False):
        channel_id = str(receptor.channel_id)
        nerve = str(receptor.entryNerve)
        side = str(receptor.rootSide).lower()
        segment = leg_nerve_to_segment.get(nerve)
        if segment is not None and side in {"l", "r"}:
            leg = f"{side}{segment}"
            if leg not in contacts_by_leg.index:
                raise RuntimeError(f"Capteur de contact de patte absent pour {channel_id}: {leg}")
            contact = contacts_by_leg.loc[leg]
            basis = "annotated_leg_entry_nerve_and_side"
            channel_results.append(
                {
                    "channel_id": channel_id,
                    "neuron_count": int(receptor.neuron_count),
                    "status": "candidates_known",
                    "reason": basis,
                }
            )
            for observable in contact_observables:
                parameter_key = f"{contact.channel_id}|{observable}|{channel_id}"
                candidate_rows.append(
                    {
                        "parameter_id": "parameter.mechanosensation.edge."
                        + hashlib.sha256(parameter_key.encode("utf-8")).hexdigest()[:16],
                        "source_kind": "contact_load",
                        "source_channel_id": str(contact.channel_id),
                        "source_leg": leg,
                        "source_joint_id": -1,
                        "source_joint_name": "",
                        "source_body_group": "legs",
                        "source_observable": observable,
                        "target_channel_id": channel_id,
                        "target_group_id": str(receptor.group_id),
                        "entry_nerve": nerve,
                        "subclass": str(receptor.subclass),
                        "side": str(receptor.rootSide),
                        "candidate_basis": basis,
                        "parameter_status": "unassigned",
                    }
                )
            continue

        joint_candidates = joints.iloc[0:0]
        basis = ""
        if side in {"l", "r"} and nerve == "AN":
            joint_candidates = joints.loc[
                joints["body_group"].eq("antennae")
                & joints["joint_name"].str.contains(f"-{side}_antenna-", regex=False)
            ]
            basis = "antennal_nerve_side_antenna_motion"
        elif side in {"l", "r"} and nerve == "ADMN":
            joint_candidates = joints.loc[
                joints["body_group"].eq("wings")
                & joints["joint_name"].str.contains(f"-{side}_wing-", regex=False)
            ]
            basis = "anterior_dorsal_mesothoracic_nerve_side_wing_motion"
        elif side in {"l", "r"} and nerve == "DMetaN":
            joint_candidates = joints.loc[
                joints["body_group"].eq("halteres")
                & joints["joint_name"].str.contains(f"-{side}_haltere-", regex=False)
            ]
            basis = "dorsal_metathoracic_nerve_side_haltere_motion"
        elif side in {"l", "r"} and nerve in {"MxLbN", "aPhN"}:
            is_labrum = joints["joint_name"].str.contains("_labrum-", regex=False)
            same_side_labrum = joints["joint_name"].str.contains(
                f"-{side}_labrum-", regex=False
            )
            joint_candidates = joints.loc[
                joints["body_group"].eq("proboscis") & (~is_labrum | same_side_labrum)
            ]
            basis = "mouthpart_nerve_side_proboscis_motion"

        if not joint_candidates.empty:
            channel_results.append(
                {
                    "channel_id": channel_id,
                    "neuron_count": int(receptor.neuron_count),
                    "status": "candidates_known",
                    "reason": basis,
                }
            )
            for joint in joint_candidates.itertuples(index=False):
                for observable in ("position", "velocity"):
                    parameter_key = f"{joint.channel_id}|{observable}|{channel_id}"
                    candidate_rows.append(
                        {
                            "parameter_id": "parameter.mechanosensation.edge."
                            + hashlib.sha256(parameter_key.encode("utf-8")).hexdigest()[:16],
                            "source_kind": "joint_state",
                            "source_channel_id": str(joint.channel_id),
                            "source_leg": "",
                            "source_joint_id": int(joint.joint_id),
                            "source_joint_name": str(joint.joint_name),
                            "source_body_group": str(joint.body_group),
                            "source_observable": observable,
                            "target_channel_id": channel_id,
                            "target_group_id": str(receptor.group_id),
                            "entry_nerve": nerve,
                            "subclass": str(receptor.subclass),
                            "side": str(receptor.rootSide),
                            "candidate_basis": basis,
                            "parameter_status": "unassigned",
                        }
                    )
            continue

        local_contact_match = local_contact_by_nerve.get(nerve)
        if local_contact_match is not None:
            segment_name, basis = local_contact_match
            if segment_name not in local_contacts_by_segment.index:
                raise RuntimeError(
                    f"Canal de contact local absent pour {channel_id}: {segment_name}"
                )
            local_contact = local_contacts_by_segment.loc[segment_name]
            channel_results.append(
                {
                    "channel_id": channel_id,
                    "neuron_count": int(receptor.neuron_count),
                    "status": "candidates_known",
                    "reason": basis,
                }
            )
            for observable in ("force_x", "force_y", "force_z"):
                parameter_key = f"{local_contact.channel_id}|{observable}|{channel_id}"
                candidate_rows.append(
                    {
                        "parameter_id": "parameter.mechanosensation.edge."
                        + hashlib.sha256(parameter_key.encode("utf-8")).hexdigest()[:16],
                        "source_kind": "body_contact",
                        "source_channel_id": str(local_contact.channel_id),
                        "source_leg": "",
                        "source_joint_id": -1,
                        "source_joint_name": "",
                        "source_body_group": segment_name,
                        "source_observable": observable,
                        "target_channel_id": channel_id,
                        "target_group_id": str(receptor.group_id),
                        "entry_nerve": nerve,
                        "subclass": str(receptor.subclass),
                        "side": str(receptor.rootSide),
                        "candidate_basis": basis,
                        "parameter_status": "unassigned",
                    }
                )
            continue

        channel_results.append(
            {
                "channel_id": channel_id,
                "neuron_count": int(receptor.neuron_count),
                "status": "missing_physical_observable",
                "reason": "anatomical_or_physical_observable_unresolved",
            }
        )
    candidates = pd.DataFrame(candidate_rows).sort_values(
        ["target_channel_id", "source_kind", "source_channel_id", "source_observable"]
    ).reset_index(drop=True)
    results = pd.DataFrame(channel_results).sort_values("channel_id").reset_index(drop=True)
    if candidates["parameter_id"].duplicated().any():
        raise RuntimeError("La matrice mécanoréceptrice contient des paramètres dupliqués")
    resolved_ids = set(candidates["target_channel_id"].astype(str))
    all_ids = set(receptors["channel_id"].astype(str))
    unresolved_ids = all_ids - resolved_ids
    if resolved_ids & unresolved_ids or resolved_ids | unresolved_ids != all_ids:
        raise RuntimeError("La partition des canaux mécanorécepteurs est incohérente")
    if (len(candidates), len(resolved_ids), len(unresolved_ids)) != (2108, 323, 0):
        raise RuntimeError(
            "Matrice mécanoréceptrice inattendue: "
            f"{len(candidates)} arêtes, {len(resolved_ids)} résolus, {len(unresolved_ids)} non résolus"
        )
    unresolved = results.loc[results["status"].eq("missing_physical_observable")]
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": "sparse local contact, body-contact and appendage-motion-to-mechanoreceptor candidate matrix without fitted values",
        "scientific_basis": {
            "male_cns_annotations": "https://github.com/flyconnectome/2025malecns",
            "manc_nerve_nomenclature": "https://pmc.ncbi.nlm.nih.gov/articles/PMC13384506/",
            "flybody_model": "https://doi.org/10.1038/s41586-025-09029-4",
            "johnstons_organ_review": "https://pmc.ncbi.nlm.nih.gov/articles/PMC4007284/",
            "used_claims": [
                "ProLN, ProAN, VProN and DProN carry annotated front-leg tactile afferents in the selected terminal rows",
                "MesoLN and MetaLN are the mesothoracic and metathoracic leg nerves",
                "rootSide identifies the paired appendage side",
                "non-leg nerves must not consume aggregate leg-ground contact values",
                "Johnston's organ responds to antennal motion caused by sound, wind and gravity",
                "FlyBody exposes explicit antenna, wing, haltere and mouthpart joint motion",
                "the selected PDMN and ON terminal groups are represented by FlyBody's central thorax and head net contact forces",
            ],
        },
        "method": {
            "candidate_rule": "same annotated appendage and root side; leg tactile channels use contact loads, represented non-leg appendages use joint motion, and PDMN/ON terminals use central thorax/head net contact force",
            "included_contact_observables": list(contact_observables),
            "included_body_contact_observables": ["force_x", "force_y", "force_z"],
            "included_joint_observables": ["position", "velocity"],
            "excluded_contact_geometry": [
                "world_position",
                "world_normal",
                "world_tangent",
            ],
            "parameterization": "one free signed local coefficient per permitted physical-observable-to-terminal edge",
            "initialization": "absent; all parameter values remain unassigned",
            "spatial_resolution_limit": "FlyBody exposes one central thorax and one head segment here; no unsupported left/right localization is invented",
            "unresolved_policy": "all selected mechanoreceptor terminals have a structural physical candidate; parameter values remain unassigned",
        },
        "source_contact_channels": int(len(contacts)),
        "source_scalar_observables_total": int(contacts["sensor_dimension"].sum()),
        "source_load_observables_used_per_leg": len(contact_observables),
        "source_local_body_contact_channels": int(len(local_contacts)),
        "source_local_body_contact_scalar_observables": int(len(local_contacts) * 3),
        "source_joint_channels_total": int(len(joints)),
        "source_joint_channels_used": int(
            candidates.loc[
                candidates["source_kind"].eq("joint_state"), "source_channel_id"
            ].nunique()
        ),
        "target_terminal_channels": int(len(receptors)),
        "target_neurons": int(receptors["neuron_count"].sum()),
        "candidate_edges": int(len(candidates)),
        "free_continuous_parameters": int(len(candidates)),
        "resolved_terminal_channels": len(resolved_ids),
        "resolved_neurons": int(
            receptors.loc[receptors["channel_id"].isin(resolved_ids), "neuron_count"].sum()
        ),
        "unresolved_terminal_channels": len(unresolved_ids),
        "unresolved_neurons": int(unresolved["neuron_count"].sum()),
        "unresolved_reason_channel_counts": {
            str(key): int(value)
            for key, value in unresolved["reason"].value_counts().sort_index().items()
        },
        "source_kind_edge_counts": {
            str(key): int(value)
            for key, value in candidates["source_kind"].value_counts().sort_index().items()
        },
        "candidate_basis_edge_counts": {
            str(key): int(value)
            for key, value in candidates["candidate_basis"].value_counts().sort_index().items()
        },
        "routing_status": "candidate_complete",
        "parameter_status": "unassigned",
        "scientific_parameter_values_selected": False,
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    candidates.to_parquet(candidate_output, index=False)
    results.to_csv(audit_output, index=False)
    print(f"[OK] {len(candidates):,} arêtes locales candidates, toutes sans valeur")
    print(f"[OK] {len(resolved_ids):,}/323 canaux terminaux reliés à une observable locale")
    print(f"[OK] {len(unresolved_ids):,}/323 terminaux sans observable physique candidate")
    print(f"[OK] Synthèse : {summary_output}")
    print(f"[OK] Matrice candidate : {candidate_output}")
    print(f"[OK] Audit exhaustif des canaux : {audit_output}")
    return summary


def build_vision_wiring(
    source: Path = SOURCE,
    annotations_source: Path = ANNOTATION_SOURCE,
    summary_output: Path = VISION_SUMMARY_OUTPUT,
    channel_output: Path = VISION_CHANNEL_OUTPUT,
    route_output: Path = VISION_ROUTE_OUTPUT,
) -> dict[str, Any]:
    """Build one exact downstream channel per optic-lobe sensory neuron."""
    if not source.is_file():
        raise FileNotFoundError(f"{source} absent; lancez d'abord l'inventaire MaleCNS")
    if not annotations_source.is_file():
        raise FileNotFoundError(f"Table d'annotations absente: {annotations_source}")
    section("Câblage terminal des afférences visuelles")
    frame = pd.read_parquet(source)
    selected = frame.loc[frame["group_id"].eq("sensory.optic_lobe")].copy()
    if selected.empty:
        raise RuntimeError("Aucun neurone sensoriel du lobe optique trouvé")
    if selected["bodyId"].duplicated().any():
        raise RuntimeError("La population sensorielle du lobe optique contient des bodyId dupliqués")

    selected["visual_subpopulation"] = "unclassified"
    selected.loc[selected["class"].eq("visual"), "visual_subpopulation"] = "photoreceptor"
    selected.loc[selected["type"].eq("HBeyelet"), "visual_subpopulation"] = "HBeyelet"
    text_axes = ["type", "instance", "class", "rootSide"]
    selected[text_axes] = selected[text_axes].fillna("(unknown)").astype(str)
    selected["routing_box_id"] = "adapter.vision.routing"
    selected["source_port"] = "visual_afferents"
    selected["target_box_id"] = "cns.malecns"
    selected["target_port"] = "sensory_afferents"
    selected["channel_id"] = [
        _channel_id("sensory.optic_lobe", ["bodyId"], (body_id,))
        for body_id in selected["bodyId"]
    ]
    selected["box_instance_id"] = selected["channel_id"].str.replace(
        "channel.", "box.", n=1, regex=False
    )
    selected["adapter_type"] = "C"

    channel_rows = [
        {
            "channel_id": row.channel_id,
            "box_instance_id": row.box_instance_id,
            "group_id": "sensory.optic_lobe",
            "visual_subpopulation": row.visual_subpopulation,
            "routing_box_id": "adapter.vision.routing",
            "adapter_type": "C",
            "source_port": "visual_afferents",
            "target_box_id": "cns.malecns",
            "target_port": "sensory_afferents",
            "target_body_id": int(row.bodyId),
            "type": row.type,
            "instance": row.instance,
            "rootSide": row.rootSide,
            "mapping_level": "exact_body_id",
            "free_discrete_parameters_downstream": 0,
            "upstream_retinotopic_mapping": "deferred",
        }
        for row in selected.itertuples(index=False)
    ]

    route_columns = [
        "channel_id",
        "box_instance_id",
        "group_id",
        "visual_subpopulation",
        "routing_box_id",
        "adapter_type",
        "source_port",
        "target_box_id",
        "target_port",
        "bodyId",
        "type",
        "instance",
        "class",
        "rootSide",
    ]
    routes = selected[route_columns].rename(columns={"bodyId": "target_body_id"})
    if routes["target_body_id"].duplicated().any():
        raise RuntimeError("Le manifeste visuel contient des routes dupliquées")

    annotations = pd.read_feather(
        annotations_source,
        columns=["bodyId", "superclass", "assignedOlHex1", "assignedOlHex2"],
    )
    has_hex = annotations["assignedOlHex1"].notna() | annotations["assignedOlHex2"].notna()
    has_both_hex = annotations["assignedOlHex1"].notna() & annotations["assignedOlHex2"].notna()
    hex_rows = annotations.loc[has_hex]
    input_ids = set(selected["bodyId"].astype(int))
    input_hex_rows = hex_rows.loc[hex_rows["bodyId"].astype(int).isin(input_ids)]
    hex_superclasses = {
        str(key): int(value)
        for key, value in hex_rows["superclass"].fillna("(unknown)").value_counts().items()
    }
    if len(input_hex_rows) != 0:
        raise RuntimeError("Des coordonnées hexagonales inattendues apparaissent sur l'interface visuelle")
    if hex_superclasses != {"ol_intrinsic": 23720}:
        raise RuntimeError(f"Signature hexagonale source inattendue: {hex_superclasses}")
    if int(has_both_hex.sum()) != 23720:
        raise RuntimeError("Les deux coordonnées hexagonales ne couvrent pas les mêmes 23 720 cellules")

    subpopulation_counts = {
        str(key): int(value)
        for key, value in selected["visual_subpopulation"].value_counts().items()
    }
    if subpopulation_counts != {"photoreceptor": 6091, "HBeyelet": 7}:
        raise RuntimeError(f"Partition visuelle inattendue: {subpopulation_counts}")
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": str(source.relative_to(ROOT)).replace("\\", "/"),
        "purpose": "exact downstream visual routing; physical retinotopy and phototransduction are deferred",
        "method": {
            "terminal_channels": "one type-C instance per unique optic-lobe sensory bodyId",
            "target_mapping": "each instance maps one-to-one to its MaleCNS bodyId",
            "retinotopy_policy": "optic-lobe intrinsic hex coordinates are not imputed onto sensory neurons",
            "upstream_policy": "pixel or ommatidium assignment remains unknown until independently sourced",
        },
        "group_id": "sensory.optic_lobe",
        "routing_box_id": "adapter.vision.routing",
        "subpopulation_counts": subpopulation_counts,
        "neuron_count": int(len(selected)),
        "terminal_channels": len(channel_rows),
        "generated_box_instances": len(channel_rows),
        "exact_routes": int(len(routes)),
        "duplicate_routes": 0,
        "unassigned_neurons": 0,
        "hex_assignment_audit": {
            "all_annotated_rows": int(len(hex_rows)),
            "rows_with_both_coordinates": int(has_both_hex.sum()),
            "annotated_superclasses": hex_superclasses,
            "sensory_input_rows": int(len(input_hex_rows)),
            "used_as_input_coordinates": False,
        },
        "downstream_routing_status": "fixed",
        "upstream_mapping_status": "unknown",
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(channel_rows).to_csv(channel_output, index=False, encoding="utf-8")
    routes.to_parquet(route_output, index=False)
    print("[OK] 6,091 photorécepteurs et 7 HBeyelet distingués")
    print("[OK] 23,720 coordonnées hexagonales réservées aux cellules ol_intrinsic")
    print(f"[OK] {len(routes):,} routes exactes et {len(channel_rows):,} instances type C")
    print(f"[OK] Synthèse : {summary_output}")
    print(f"[OK] Canaux terminaux : {channel_output}")
    print(f"[OK] Routes bodyId exactes : {route_output}")
    return summary


def build_motor_wiring(
    source: Path = SOURCE,
    summary_output: Path = MOTOR_SUMMARY_OUTPUT,
    channel_output: Path = MOTOR_CHANNEL_OUTPUT,
    route_output: Path = MOTOR_ROUTE_OUTPUT,
    group_output: Path = MOTOR_GROUP_OUTPUT,
    group_member_output: Path = MOTOR_GROUP_MEMBER_OUTPUT,
) -> dict[str, Any]:
    """Build exact motor routes and their annotation-backed muscle groups.

    The grouping is a lossless structural bundle: every motor-neuron activity
    remains present.  It deliberately does not sum activities, choose signs or
    assign any group to a FlyBody actuator.
    """
    if not source.is_file():
        raise FileNotFoundError(f"{source} absent; lancez d'abord l'inventaire MaleCNS")
    section("Câblage des sorties neuronales explicitement motrices")
    frame = pd.read_parquet(source)
    group_ids = ("motor.vnc", "motor.central_brain")
    selected = frame.loc[frame["group_id"].isin(group_ids)].copy()
    if selected.empty:
        raise RuntimeError("Aucun neurone moteur trouvé")
    if selected["bodyId"].duplicated().any():
        raise RuntimeError("Les populations motrices VNC et cerveau central se chevauchent")
    group_counts = {
        str(key): int(value) for key, value in selected["group_id"].value_counts().items()
    }
    if group_counts != {"motor.vnc": 708, "motor.central_brain": 107}:
        raise RuntimeError(f"Partition motrice inattendue: {group_counts}")

    text_axes = ["exitNerve", "somaSide", "somaNeuromere", "subclass", "type", "instance"]
    selected[text_axes] = selected[text_axes].fillna("(unknown)").astype(str)
    selected["grouping_type"] = selected["type"]
    unknown_type = selected["type"].eq("(unknown)")
    selected.loc[unknown_type, "grouping_type"] = selected.loc[unknown_type, "bodyId"].map(
        lambda body_id: f"(unknown bodyId={int(body_id)})"
    )
    group_axes = ["subclass", "grouping_type", "somaSide"]
    selected["motor_group_id"] = [
        _channel_id("motor.muscle_group", group_axes, tuple(row))
        for row in selected[group_axes].itertuples(index=False, name=None)
    ]
    selected["routing_box_id"] = "adapter.motor.routing"
    selected["source_box_id"] = "cns.malecns"
    selected["source_port"] = "motor_neuron_activity"
    selected["target_port"] = "motor_neuron_activity"
    selected["channel_id"] = [
        _channel_id("motor.output", ["bodyId"], (body_id,)) for body_id in selected["bodyId"]
    ]
    selected["box_instance_id"] = selected["channel_id"].str.replace(
        "channel.", "box.", n=1, regex=False
    )
    selected["adapter_type"] = "E"

    channel_rows = [
        {
            "channel_id": row.channel_id,
            "box_instance_id": row.box_instance_id,
            "group_id": row.group_id,
            "routing_box_id": "adapter.motor.routing",
            "adapter_type": "E",
            "source_box_id": "cns.malecns",
            "source_port": "motor_neuron_activity",
            "source_body_id": int(row.bodyId),
            "target_port": "motor_neuron_activity",
            "exitNerve": row.exitNerve,
            "somaSide": row.somaSide,
            "somaNeuromere": row.somaNeuromere,
            "subclass": row.subclass,
            "type": row.type,
            "instance": row.instance,
            "motor_group_id": row.motor_group_id,
            "mapping_level": "exact_body_id",
            "free_discrete_parameters_upstream": 0,
            "downstream_muscle_grouping": "fixed",
            "flybody_actuator_mapping": "deferred",
        }
        for row in selected.itertuples(index=False)
    ]
    route_columns = [
        "channel_id",
        "box_instance_id",
        "group_id",
        "routing_box_id",
        "adapter_type",
        "source_box_id",
        "source_port",
        "bodyId",
        "target_port",
        "exitNerve",
        "somaSide",
        "somaNeuromere",
        "subclass",
        "type",
        "instance",
        "motor_group_id",
    ]
    routes = selected[route_columns].rename(columns={"bodyId": "source_body_id"})
    if routes["source_body_id"].duplicated().any():
        raise RuntimeError("Le manifeste moteur contient des sources bodyId dupliquées")

    group_rows: list[dict[str, Any]] = []
    for motor_group_id, members in selected.groupby("motor_group_id", sort=True):
        subclass = str(members.iloc[0]["subclass"])
        motor_type = str(members.iloc[0]["type"])
        side = str(members.iloc[0]["somaSide"])
        if motor_type == "(unknown)":
            annotation_resolution = "unknown_singleton"
        elif motor_type.startswith(
            ("MNad", "MNfl", "MNhl", "MNhm", "MNml", "MNnm", "MNwm", "MNxm")
        ):
            annotation_resolution = "systematic_type"
        else:
            annotation_resolution = "named_type"
        group_rows.append(
            {
                "motor_group_id": str(motor_group_id),
                "source_box_id": "adapter.motor.routing",
                "source_port": "muscle_group_activity",
                "target_box_id": "adapter.motor.transduction",
                "target_port": "muscle_group_activity",
                "subclass": subclass,
                "type": motor_type,
                "side": side,
                "annotation_resolution": annotation_resolution,
                "member_neurons": int(len(members)),
                "member_channels": int(members["channel_id"].nunique()),
                "membership_mapping": "exact_body_id",
                "value_transformation": "none_preserve_members",
                "flybody_actuator_mapping": "deferred",
            }
        )
    groups = pd.DataFrame(group_rows).sort_values(
        ["subclass", "type", "side", "motor_group_id"]
    ).reset_index(drop=True)
    members = selected[
        [
            "motor_group_id",
            "channel_id",
            "bodyId",
            "group_id",
            "subclass",
            "type",
            "somaSide",
            "exitNerve",
            "somaNeuromere",
            "instance",
        ]
    ].rename(columns={"bodyId": "source_body_id", "somaSide": "side"})
    if members["source_body_id"].duplicated().any():
        raise RuntimeError("Un neurone moteur appartient à plusieurs groupes musculaires")
    if set(members["motor_group_id"]) != set(groups["motor_group_id"]):
        raise RuntimeError("Les membres et l'inventaire des groupes moteurs divergent")
    if len(groups) != 441:
        raise RuntimeError(f"441 groupes moteurs annotés attendus, {len(groups)} obtenus")

    exits = frame.loc[frame["group_id"].eq("motor.exit_nerve")].copy()
    excluded = exits.loc[~exits["bodyId"].isin(selected["bodyId"])]
    excluded_counts = {
        str(key): int(value)
        for key, value in excluded["superclass"].fillna("(unknown)").value_counts().items()
    }
    expected_excluded = {
        "vnc_efferent": 92,
        "cb_endocrine": 71,
        "vnc_endocrine": 18,
        "cb_efferent": 4,
        "efferent_ascending": 4,
        "cb_intrinsic": 2,
    }
    if excluded_counts != expected_excluded:
        raise RuntimeError(f"Partition des sorties non motrices inattendue: {excluded_counts}")
    unknown_counts = {
        axis: int(selected[axis].eq("(unknown)").sum()) for axis in text_axes
    }
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": str(source.relative_to(ROOT)).replace("\\", "/"),
        "purpose": "exact CNS-to-motor-router wiring; muscle and actuator assignment is deferred",
        "method": {
            "motor_population": "all neurons explicitly labelled vnc_motor or cb_motor",
            "terminal_channels": "one type-E instance per unique motor-neuron bodyId",
            "source_mapping": "each instance reads one explicit MaleCNS bodyId",
            "exclusion_policy": "endocrine and other efferent exits are inventoried but never treated as muscle commands",
            "muscle_groups": "lossless partition by annotated subclass, type and soma side; unknown types remain bodyId singletons",
            "value_policy": "member activities are preserved individually; no sum, sign or gain is selected",
            "downstream_policy": "mapping from annotated groups to FlyBody actuators remains unknown",
        },
        "scientific_basis": {
            "publication": "Organization of circuits linking descending input to motor output in the Drosophila Male Adult Nerve Cord connectome",
            "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC13384506/",
            "used_claim": "motor subclass encodes broad muscle category and type identifies the annotated motor-neuron type",
        },
        "group_ids": list(group_ids),
        "routing_box_id": "adapter.motor.routing",
        "group_counts": group_counts,
        "neuron_count": int(len(selected)),
        "terminal_channels": len(channel_rows),
        "generated_box_instances": len(channel_rows),
        "exact_routes": int(len(routes)),
        "duplicate_routes": 0,
        "unassigned_motor_neurons": 0,
        "unknown_axis_value_counts": unknown_counts,
        "muscle_group_inventory": {
            "groups": int(len(groups)),
            "exact_member_routes": int(len(members)),
            "subclass_group_counts": {
                str(key): int(value)
                for key, value in groups["subclass"].value_counts().sort_index().items()
            },
            "annotation_resolution_counts": {
                str(key): int(value)
                for key, value in groups["annotation_resolution"].value_counts().items()
            },
            "unknown_type_neurons_preserved_as_singletons": int(unknown_type.sum()),
            "value_transformation": "none_preserve_members",
            "membership_status": "fixed",
            "flybody_actuator_mapping": "deferred",
        },
        "exit_nerve_inventory": {
            "total": int(len(exits)),
            "explicit_motor": int(exits["bodyId"].isin(selected["bodyId"]).sum()),
            "non_motor_deferred": int(len(excluded)),
            "non_motor_superclass_counts": excluded_counts,
            "motor_without_exit_nerve": int(selected["exitNerve"].eq("(unknown)").sum()),
        },
        "upstream_routing_status": "fixed",
        "downstream_group_membership_status": "fixed",
        "flybody_actuator_mapping_status": "unknown",
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(channel_rows).to_csv(channel_output, index=False, encoding="utf-8")
    routes.to_parquet(route_output, index=False)
    groups.to_csv(group_output, index=False, encoding="utf-8")
    members.to_parquet(group_member_output, index=False)
    print("[OK] 708 moteurs VNC et 107 moteurs cerveau central distingués")
    print("[OK] 191 sorties endocrines/effectrices non motrices exclues des commandes musculaires")
    print("[OK] 1 neurone cb_motor conserve un nerf de sortie explicitement inconnu")
    print(f"[OK] {len(routes):,} routes exactes et {len(channel_rows):,} instances type E")
    print(f"[OK] {len(groups):,} groupes type/côté couvrent les {len(members):,} neurones sans agrégation")
    print(f"[OK] Synthèse : {summary_output}")
    print(f"[OK] Canaux moteurs : {channel_output}")
    print(f"[OK] Routes bodyId exactes : {route_output}")
    print(f"[OK] Groupes moteurs : {group_output}")
    print(f"[OK] Membres exacts des groupes : {group_member_output}")
    return summary


def build_motor_transduction_candidates(
    group_path: Path = MOTOR_GROUP_OUTPUT,
    member_path: Path = MOTOR_GROUP_MEMBER_OUTPUT,
    actuator_path: Path = FLYBODY_ACTUATOR_CHANNEL_OUTPUT,
    summary_output: Path = MOTOR_TRANSDUCTION_SUMMARY_OUTPUT,
    candidate_output: Path = MOTOR_ACTUATOR_CANDIDATE_OUTPUT,
) -> dict[str, Any]:
    """Constrain motor-to-actuator parameters by published broad anatomy only."""
    for path in (group_path, member_path, actuator_path):
        if not path.is_file():
            raise FileNotFoundError(f"{path} absent; reconstruisez d'abord le câblage")
    section("Construction de la matrice candidate moteur vers actionneurs")
    groups = pd.read_csv(group_path).fillna("(unknown)")
    members = pd.read_parquet(member_path).fillna("(unknown)")
    actuators = pd.read_csv(actuator_path).fillna("(unknown)")

    # The first seven categories are the broad muscle categories explicitly
    # defined by the MANC/MaleCNS motor annotation publication.  The head
    # appendage additions are constrained independently by the published exit
    # nerve annotations: AN for antennae, and PhN/MxLbN for the proboscis.
    subclass_specs = {
        "ad": {"body_group": "abdomen", "limb": None},
        "nm": {"body_group": "head", "limb": None},
        "wm": {"body_group": "wings", "limb": "wing"},
        "hm": {"body_group": "halteres", "limb": "haltere"},
        "fl": {"body_group": "legs", "limb": "f"},
        "ml": {"body_group": "legs", "limb": "m"},
        "hl": {"body_group": "legs", "limb": "h"},
        "am": {"body_group": "antennae", "limb": "antenna"},
        "pm": {"body_group": "proboscis", "limb": "proboscis"},
    }

    candidate_rows: list[dict[str, Any]] = []
    resolved_group_ids: set[str] = set()
    for group in groups.itertuples(index=False):
        subclass = str(group.subclass)
        spec = subclass_specs.get(subclass)
        # rm is a mixed residual class.  Its PS349 pair exits through AN and is
        # therefore eligible for antenna actuators; the five ON members are
        # retained below as unsupported physical effectors.
        if subclass == "rm" and str(group.type) == "PS349":
            spec = {"body_group": "antennae", "limb": "antenna"}
        if spec is None:
            continue
        group_members = members.loc[members["motor_group_id"].eq(group.motor_group_id)]
        if group_members.empty:
            raise RuntimeError(f"Groupe moteur sans membre: {group.motor_group_id}")
        exit_nerves = set(group_members["exitNerve"].astype(str))
        if subclass == "am" and exit_nerves != {"AN"}:
            raise RuntimeError(f"Nerf antennaire inattendu pour {group.motor_group_id}: {exit_nerves}")
        if subclass == "pm" and not exit_nerves <= {"PhN", "MxLbN", "(unknown)"}:
            raise RuntimeError(f"Nerf proboscis inattendu pour {group.motor_group_id}: {exit_nerves}")
        if subclass == "rm" and str(group.type) == "PS349" and exit_nerves != {"AN"}:
            raise RuntimeError(f"Nerf PS349 inattendu pour {group.motor_group_id}: {exit_nerves}")
        candidates = actuators.loc[actuators["body_group"].eq(spec["body_group"])].copy()
        side = str(group.side).lower()
        limb = spec["limb"]
        if limb in {"f", "m", "h"}:
            limb_code = f"{side}{limb}_"
            candidates = candidates.loc[candidates["target_joint_name"].str.contains(limb_code)]
        elif limb in {"wing", "haltere"}:
            marker = f"-{side}_{limb}"
            candidates = candidates.loc[candidates["target_joint_name"].str.contains(marker)]
        elif limb == "antenna":
            marker = f"-{side}_antenna"
            candidates = candidates.loc[candidates["target_joint_name"].str.contains(marker)]
        elif limb == "proboscis":
            # Three medial rostrum/haustellum joints are shared; only the
            # lateral labrum joint is side-filtered.
            is_labrum = candidates["target_joint_name"].str.contains("_labrum")
            same_labrum = candidates["target_joint_name"].str.contains(f"-{side}_labrum")
            candidates = candidates.loc[~is_labrum | same_labrum]
        if candidates.empty:
            raise RuntimeError(
                f"Aucun actionneur candidat pour {group.motor_group_id} ({group.subclass}, {group.side})"
            )
        resolved_group_ids.add(str(group.motor_group_id))
        candidate_basis = (
            "published_exit_nerve_effector_and_side"
            if subclass in {"am", "pm", "rm"}
            else "published_broad_category_and_side"
        )
        for member in group_members.itertuples(index=False):
            for actuator in candidates.itertuples(index=False):
                parameter_key = f"{int(member.source_body_id)}|{int(actuator.actuator_id)}"
                candidate_rows.append(
                    {
                        "parameter_id": "parameter.motor.edge."
                        + hashlib.sha256(parameter_key.encode("utf-8")).hexdigest()[:16],
                        "motor_group_id": str(group.motor_group_id),
                        "source_channel_id": str(member.channel_id),
                        "source_body_id": int(member.source_body_id),
                        "subclass": str(group.subclass),
                        "type": str(group.type),
                        "side": str(group.side),
                        "target_channel_id": str(actuator.channel_id),
                        "target_actuator_id": int(actuator.actuator_id),
                        "target_actuator_name": str(actuator.actuator_name),
                        "target_joint_name": str(actuator.target_joint_name),
                        "target_body_group": str(actuator.body_group),
                        "candidate_basis": candidate_basis,
                        "parameter_status": "unassigned",
                    }
                )
    candidates = pd.DataFrame(candidate_rows).sort_values(
        ["source_body_id", "target_actuator_id"]
    ).reset_index(drop=True)
    if candidates["parameter_id"].duplicated().any():
        raise RuntimeError("La matrice candidate contient des identifiants de paramètre dupliqués")
    resolved_members = set(candidates["source_body_id"].astype(int))
    all_members = set(members["source_body_id"].astype(int))
    unresolved_members = all_members - resolved_members
    covered_actuators = set(candidates["target_actuator_id"].astype(int))
    all_actuators = set(actuators["actuator_id"].astype(int))
    unresolved_groups = set(groups["motor_group_id"].astype(str)) - resolved_group_ids
    if (len(resolved_group_ids), len(unresolved_groups)) != (431, 10):
        raise RuntimeError(
            f"Partition candidate inattendue: {len(resolved_group_ids)} groupes résolus, "
            f"{len(unresolved_groups)} non résolus"
        )
    if (len(resolved_members), len(unresolved_members)) != (804, 11):
        raise RuntimeError(
            f"Couverture motrice candidate inattendue: {len(resolved_members)} neurones résolus, "
            f"{len(unresolved_members)} non résolus"
        )
    if (len(covered_actuators), len(all_actuators - covered_actuators)) != (102, 0):
        raise RuntimeError("La couverture candidate des actionneurs FlyBody est inattendue")

    unresolved = members.loc[members["source_body_id"].isin(unresolved_members)]
    uncovered = actuators.loc[actuators["actuator_id"].isin(all_actuators - covered_actuators)]
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": "sparse motor-transduction candidate matrix without fitted parameter values",
        "scientific_basis": {
            "publication": "Organization of circuits linking descending input to motor output in the Drosophila Male Adult Nerve Cord connectome",
            "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC13384506/",
            "used_claim": "subclass codes ad/nm/wm/hm/fl/ml/hl identify broad muscle categories",
            "head_appendage_evidence": [
                "https://pmc.ncbi.nlm.nih.gov/articles/PMC12154692/",
                "https://www.virtualflybrain.org/blog/2022/01/01/ps349_r-malecns10383-vfb_jrmc1k3g/",
            ],
            "head_appendage_claim": "AN motor neurons drive antennae; PhN/MxLbN motor neurons drive proboscis movements",
        },
        "method": {
            "candidate_rule": "same published broad category or supported exit-nerve effector and, for paired appendages, same soma side",
            "parameterization": "one free signed gain for each permitted motor-neuron-to-actuator edge",
            "initialization": "absent; all parameter values remain unassigned",
            "explicit_terminal_policy": "members without a represented FlyBody effector are consumed but emit no actuator command",
        },
        "source_motor_neurons": int(len(members)),
        "source_motor_groups": int(len(groups)),
        "target_actuators": int(len(actuators)),
        "candidate_edges": int(len(candidates)),
        "free_continuous_parameters": int(len(candidates)),
        "resolved_motor_groups": len(resolved_group_ids),
        "unresolved_motor_groups": len(unresolved_groups),
        "resolved_motor_neurons": len(resolved_members),
        "unresolved_motor_neurons": len(unresolved_members),
        "unresolved_subclass_neuron_counts": {
            str(key): int(value)
            for key, value in unresolved["subclass"].value_counts().sort_index().items()
        },
        "unresolved_exit_nerve_counts": {
            str(key): int(value)
            for key, value in unresolved["exitNerve"].value_counts().sort_index().items()
        },
        "unresolved_reason": "five optic-nerve rm effectors and six accessory-nerve xm effectors have no represented FlyBody actuator",
        "covered_actuators": len(covered_actuators),
        "uncovered_actuators": len(all_actuators - covered_actuators),
        "uncovered_actuator_body_group_counts": {
            str(key): int(value)
            for key, value in uncovered["body_group"].value_counts().sort_index().items()
        },
        "routing_status": "candidates_known_complete_with_explicit_unsupported_terminals",
        "parameter_status": "unassigned",
        "scientific_parameter_values_selected": False,
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    candidates.to_parquet(candidate_output, index=False)
    print(f"[OK] {len(candidates):,} arêtes candidates, toutes sans valeur de paramètre")
    print("[OK] 804 neurones / 431 groupes contraints vers les 102 actionneurs")
    print("[INFO] 11 neurones / 10 groupes sans effecteur FlyBody restent des terminaux explicites")
    print(f"[OK] Synthèse : {summary_output}")
    print(f"[OK] Matrice candidate : {candidate_output}")
    return summary


def build_unclassified_sensory_wiring(
    source: Path = SOURCE,
    summary_output: Path = UNCLASSIFIED_SUMMARY_OUTPUT,
    channel_output: Path = UNCLASSIFIED_CHANNEL_OUTPUT,
    route_output: Path = UNCLASSIFIED_ROUTE_OUTPUT,
) -> dict[str, Any]:
    """Route the exact complement of known sensory modalities without relabelling it."""
    if not source.is_file():
        raise FileNotFoundError(f"{source} absent; lancez d'abord l'inventaire MaleCNS")
    section("Câblage des afférences sensorielles non résolues")
    frame = pd.read_parquet(source)
    selected = frame.loc[frame["group_id"].eq("sensory.unclassified_residual")].copy()
    if selected.empty:
        raise RuntimeError("Aucune afférence sensorielle résiduelle trouvée")
    if selected["bodyId"].duplicated().any():
        raise RuntimeError("La population sensorielle résiduelle contient des bodyId dupliqués")

    known_group_ids = (
        "sensory.optic_lobe",
        "sensory.olfactory",
        "sensory.gustatory",
        "sensory.thermohygro",
        "sensory.tactile",
        "sensory.mechanosensory_other",
        "sensory.proprioceptive",
    )
    sensory_scope_group_ids = (
        "sensory.optic_lobe",
        "sensory.central_brain",
        "sensory.vnc",
        "sensory.unknown",
    )
    known_ids = set(
        frame.loc[frame["group_id"].isin(known_group_ids), "bodyId"].astype(int)
    )
    scope_ids = set(
        frame.loc[frame["group_id"].isin(sensory_scope_group_ids), "bodyId"].astype(int)
    )
    residual_ids = set(selected["bodyId"].astype(int))
    if residual_ids != scope_ids - known_ids:
        raise RuntimeError("Le groupe résiduel n'est pas le complément exact des modalités routées")
    if (len(scope_ids), len(known_ids & scope_ids), len(residual_ids)) != (17380, 15497, 1883):
        raise RuntimeError(
            "Couverture sensorielle inattendue: "
            f"scope={len(scope_ids)}, routed={len(known_ids & scope_ids)}, residual={len(residual_ids)}"
        )

    text_axes = ["superclass", "class", "entryNerve", "subclass", "type", "rootSide"]
    selected[text_axes] = selected[text_axes].fillna("(unknown)").astype(str)
    selected["routing_box_id"] = "adapter.sensory.unclassified.routing"
    selected["source_port"] = "sensory_afferents"
    selected["target_box_id"] = "cns.malecns"
    selected["target_port"] = "sensory_afferents"
    selected["channel_id"] = [
        _channel_id("sensory.unclassified_residual", ["bodyId"], (body_id,))
        for body_id in selected["bodyId"]
    ]
    selected["box_instance_id"] = selected["channel_id"].str.replace(
        "channel.", "box.", n=1, regex=False
    )
    selected["adapter_type"] = "C"

    channel_rows = [
        {
            "channel_id": row.channel_id,
            "box_instance_id": row.box_instance_id,
            "group_id": "sensory.unclassified_residual",
            "routing_box_id": "adapter.sensory.unclassified.routing",
            "adapter_type": "C",
            "source_port": "sensory_afferents",
            "target_box_id": "cns.malecns",
            "target_port": "sensory_afferents",
            "target_body_id": int(row.bodyId),
            "superclass": row.superclass,
            "entryNerve": row.entryNerve,
            "subclass": row.subclass,
            "type": row.type,
            "rootSide": row.rootSide,
            "mapping_level": "exact_body_id",
            "free_discrete_parameters_downstream": 0,
            "upstream_modality_mapping": "deferred",
        }
        for row in selected.itertuples(index=False)
    ]
    # `class` is a Python keyword; assign it directly rather than depending on
    # pandas' generated itertuples field name.
    for item, class_value in zip(channel_rows, selected["class"]):
        item["class"] = class_value

    route_columns = [
        "channel_id",
        "box_instance_id",
        "group_id",
        "routing_box_id",
        "adapter_type",
        "source_port",
        "target_box_id",
        "target_port",
        "bodyId",
        "superclass",
        "class",
        "entryNerve",
        "subclass",
        "type",
        "rootSide",
    ]
    routes = selected[route_columns].rename(columns={"bodyId": "target_body_id"})
    if routes["target_body_id"].duplicated().any():
        raise RuntimeError("Le manifeste sensoriel résiduel contient des routes dupliquées")

    class_counts = {
        str(key): int(value) for key, value in selected["class"].value_counts().items()
    }
    expected_class_counts = {
        "unknown_sensory": 1712,
        "(unknown)": 103,
        "chemosensory": 57,
        "mechanosensory_tbc": 11,
    }
    if class_counts != expected_class_counts:
        raise RuntimeError(f"Partition résiduelle par classe inattendue: {class_counts}")
    superclass_counts = {
        str(key): int(value) for key, value in selected["superclass"].value_counts().items()
    }
    expected_superclass_counts = {
        "vnc_sensory": 1709,
        "cb_sensory": 130,
        "sensory_ascending": 32,
        "sensory_descending": 12,
    }
    if superclass_counts != expected_superclass_counts:
        raise RuntimeError(f"Partition résiduelle anatomique inattendue: {superclass_counts}")
    unknown_counts = {
        axis: int(selected[axis].str.lower().isin({"(unknown)", "unknown", ""}).sum())
        for axis in text_axes
    }
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": str(source.relative_to(ROOT)).replace("\\", "/"),
        "purpose": "exact residual sensory routing without inferred modality or physical transduction",
        "method": {
            "residual_definition": "inventoried sensory union minus routed modality classes and the fully routed ol_sensory population",
            "terminal_channels": "one type-C instance per unique residual bodyId",
            "target_mapping": "each instance maps one-to-one to its MaleCNS bodyId",
            "classification_policy": "all missing and unresolved labels remain explicit",
            "upstream_policy": "physical modality and transduction remain unknown",
        },
        "group_id": "sensory.unclassified_residual",
        "routing_box_id": "adapter.sensory.unclassified.routing",
        "class_counts": class_counts,
        "superclass_counts": superclass_counts,
        "unknown_axis_value_counts": unknown_counts,
        "neuron_count": int(len(selected)),
        "terminal_channels": len(channel_rows),
        "generated_box_instances": len(channel_rows),
        "exact_routes": int(len(routes)),
        "duplicate_routes": 0,
        "unassigned_neurons": 0,
        "sensory_coverage": {
            "anatomical_scope_unique_body_ids": len(scope_ids),
            "known_modalities_inside_anatomical_scope": len(known_ids & scope_ids),
            "inventoried_unique_body_ids": len(scope_ids | known_ids),
            "previously_routed_unique_body_ids": len(known_ids),
            "newly_routed_unique_body_ids": len(residual_ids),
            "total_routed_unique_body_ids": len(known_ids | residual_ids),
            "coverage_percent": 100.0,
        },
        "downstream_routing_status": "fixed",
        "upstream_mapping_status": "unknown",
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(channel_rows).to_csv(channel_output, index=False, encoding="utf-8")
    routes.to_parquet(route_output, index=False)
    print("[OK] 1,883 afférences résiduelles isolées sans reclassification")
    print("[OK] 17,884 neurones sensoriels inventoriés disposent maintenant d'une route CNS")
    print(f"[OK] Synthèse : {summary_output}")
    print(f"[OK] Canaux résiduels : {channel_output}")
    print(f"[OK] Routes bodyId exactes : {route_output}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Construit le câblage structurel des clamps basaux")
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--summary-output", type=Path, default=SUMMARY_OUTPUT)
    parser.add_argument("--channel-output", type=Path, default=CHANNEL_OUTPUT)
    parser.add_argument("--route-output", type=Path, default=ROUTE_OUTPUT)
    args = parser.parse_args()
    try:
        build_basal_clamp_wiring(
            args.source,
            args.summary_output,
            args.channel_output,
            args.route_output,
        )
        build_proprioception_wiring(args.source)
        build_flybody_proprioception_wiring()
        build_proprioception_transduction_candidates()
        build_flybody_touch_wiring()
        build_flybody_actuator_wiring()
        build_flybody_vision_wiring()
        build_mechanosensation_wiring(args.source)
        build_mechanosensation_transduction_candidates()
        build_vision_wiring(args.source)
        build_motor_wiring(args.source)
        build_motor_transduction_candidates()
        build_unclassified_sensory_wiring(args.source)
        build_central_graph_index()
    except Exception as exc:
        print(f"\nWIRING_FAILED: {type(exc).__name__}: {exc}")
        return 1
    print("\nWIRING_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

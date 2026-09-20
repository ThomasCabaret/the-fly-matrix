from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

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
VISION_SUMMARY_OUTPUT = OUTPUT_ROOT / "vision-routing.json"
VISION_CHANNEL_OUTPUT = OUTPUT_ROOT / "vision-channels.csv"
VISION_ROUTE_OUTPUT = OUTPUT_ROOT / "vision-routes.parquet"
MOTOR_SUMMARY_OUTPUT = OUTPUT_ROOT / "motor-routing.json"
MOTOR_CHANNEL_OUTPUT = OUTPUT_ROOT / "motor-channels.csv"
MOTOR_ROUTE_OUTPUT = OUTPUT_ROOT / "motor-routes.parquet"
UNCLASSIFIED_SUMMARY_OUTPUT = OUTPUT_ROOT / "unclassified-sensory-routing.json"
UNCLASSIFIED_CHANNEL_OUTPUT = OUTPUT_ROOT / "unclassified-sensory-channels.csv"
UNCLASSIFIED_ROUTE_OUTPUT = OUTPUT_ROOT / "unclassified-sensory-routes.parquet"
FLYBODY_PROPRIO_SUMMARY_OUTPUT = OUTPUT_ROOT / "flybody-proprioception.json"
FLYBODY_PROPRIO_CHANNEL_OUTPUT = OUTPUT_ROOT / "flybody-proprioception-channels.csv"

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
) -> dict[str, Any]:
    """Build the exact CNS-to-router half of the motor type-E adapter."""
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
            "mapping_level": "exact_body_id",
            "free_discrete_parameters_upstream": 0,
            "downstream_muscle_mapping": "deferred",
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
    ]
    routes = selected[route_columns].rename(columns={"bodyId": "source_body_id"})
    if routes["source_body_id"].duplicated().any():
        raise RuntimeError("Le manifeste moteur contient des sources bodyId dupliquées")

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
            "downstream_policy": "muscle and FlyBody actuator assignment remains unknown",
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
        "exit_nerve_inventory": {
            "total": int(len(exits)),
            "explicit_motor": int(exits["bodyId"].isin(selected["bodyId"]).sum()),
            "non_motor_deferred": int(len(excluded)),
            "non_motor_superclass_counts": excluded_counts,
            "motor_without_exit_nerve": int(selected["exitNerve"].eq("(unknown)").sum()),
        },
        "upstream_routing_status": "fixed",
        "downstream_mapping_status": "unknown",
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(channel_rows).to_csv(channel_output, index=False, encoding="utf-8")
    routes.to_parquet(route_output, index=False)
    print("[OK] 708 moteurs VNC et 107 moteurs cerveau central distingués")
    print("[OK] 191 sorties endocrines/effectrices non motrices exclues des commandes musculaires")
    print("[OK] 1 neurone cb_motor conserve un nerf de sortie explicitement inconnu")
    print(f"[OK] {len(routes):,} routes exactes et {len(channel_rows):,} instances type E")
    print(f"[OK] Synthèse : {summary_output}")
    print(f"[OK] Canaux moteurs : {channel_output}")
    print(f"[OK] Routes bodyId exactes : {route_output}")
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
        build_mechanosensation_wiring(args.source)
        build_vision_wiring(args.source)
        build_motor_wiring(args.source)
        build_unclassified_sensory_wiring(args.source)
    except Exception as exc:
        print(f"\nWIRING_FAILED: {type(exc).__name__}: {exc}")
        return 1
    print("\nWIRING_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

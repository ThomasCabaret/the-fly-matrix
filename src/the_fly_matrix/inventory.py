from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mujoco
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
from flygym.compose import ActuatorType
from flygym.compose.fly.flybody import FlyBody
from flygym.flybody.anatomy_flybody import (
    FlyBodyActuatedDOFPreset,
    FlyBodyAxisOrder,
    FlyBodyJointPreset,
    FlyBodySkeleton,
)


ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data" / "raw" / "malecns" / "v1.0"
OUTPUT = ROOT / "data" / "derived" / "inventory" / "inventory.json"
DATASETS = {
    "annotations": "body-annotations-male-cns-v1.0-minconf-0.5.feather",
    "neurotransmitters": "body-neurotransmitters-male-cns-v1.0.feather",
    "connectome_weights": "connectome-weights-male-cns-v1.0-minconf-0.5.feather",
}

DECOMPOSITION_AXES = {
    "sensory.visual": ["type"],
    "sensory.olfactory": ["entryNerve", "type", "rootSide"],
    "sensory.gustatory": ["entryNerve", "subclass", "type", "rootSide"],
    "sensory.tactile": ["entryNerve", "subclass", "type", "rootSide"],
    "sensory.mechanosensory_other": ["entryNerve", "subclass", "type", "rootSide"],
    "sensory.proprioceptive": ["entryNerve", "subclass", "mancType", "type", "rootSide"],
    "sensory.unknown": ["entryNerve", "subclass", "type", "rootSide"],
    "sensory.optic_lobe": ["type"],
    "sensory.central_brain": ["entryNerve", "subclass", "type", "rootSide"],
    "sensory.thermohygro": ["class", "type", "rootSide"],
    "sensory.vnc": ["entryNerve", "subclass", "mancType", "type", "rootSide"],
    "motor.vnc": ["exitNerve", "somaSide", "somaNeuromere", "subclass", "type"],
    "motor.exit_nerve": ["exitNerve", "somaSide", "somaNeuromere", "subclass", "type"],
    "projection.ascending": ["somaNeuromere", "somaSide", "subclass", "type"],
    "projection.descending": ["subclass", "somaSide", "somaNeuromere", "type"],
}


def section(title: str) -> None:
    print(f"\n==> {title}", flush=True)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)


def _profile_column(column: pa.ChunkedArray, top_limit: int = 12) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "type": str(column.type),
        "null_count": column.null_count,
    }
    try:
        profile["distinct_count"] = pc.count_distinct(column).as_py()
        counts = pc.value_counts(column).to_pylist()
        counts.sort(key=lambda item: item["counts"], reverse=True)
        profile["top_values"] = [
            {"value": _json_value(item["values"]), "count": item["counts"]}
            for item in counts[:top_limit]
        ]
    except (pa.ArrowInvalid, pa.ArrowNotImplementedError, TypeError):
        profile["distinct_count"] = None
        profile["top_values"] = []
    return profile


def audit_dataset(label: str, filename: str) -> dict[str, Any]:
    path = DATA_ROOT / filename
    if not path.is_file():
        raise FileNotFoundError(path)
    dataset = ds.dataset(path, format="ipc")
    row_count = dataset.count_rows()
    print(f"[{label}] {row_count:,} lignes, {len(dataset.schema.names)} colonnes")
    result: dict[str, Any] = {
        "path": str(path.relative_to(ROOT)),
        "bytes": path.stat().st_size,
        "rows": row_count,
        "columns": [
            {"name": field.name, "type": str(field.type)} for field in dataset.schema
        ],
    }
    if label in {"annotations", "neurotransmitters"}:
        table = dataset.to_table()
        result["profiles"] = {
            name: _profile_column(table[name]) for name in table.column_names
        }
        print(f"  profils calculés pour {len(table.column_names)} colonnes")
    return result


def _mujoco_names(model: mujoco.MjModel, object_type: mujoco.mjtObj, count: int) -> list[str]:
    return [
        mujoco.mj_id2name(model, object_type, index) or f"unnamed-{index}"
        for index in range(count)
    ]


def _body_group(name: str) -> str:
    lowered = name.lower()
    leg_tokens = (
        "-lf_", "-lm_", "-lh_", "-rf_", "-rm_", "-rh_",
        "lf_", "lm_", "lh_", "rf_", "rm_", "rh_",
    )
    if any(token in lowered for token in leg_tokens):
        return "legs"
    for token, group in (
        ("leg", "legs"),
        ("wing", "wings"),
        ("haltere", "halteres"),
        ("antenna", "antennae"),
        ("probosc", "proboscis"),
        ("rostrum", "proboscis"),
        ("haustellum", "proboscis"),
        ("labrum", "proboscis"),
        ("head", "head"),
        ("abdomen", "abdomen"),
    ):
        if token in lowered:
            return group
    return "other"


def audit_flybody() -> dict[str, Any]:
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
    model = fly.mjcf_root.compile()
    joints = _mujoco_names(model, mujoco.mjtObj.mjOBJ_JOINT, model.njnt)
    actuators = _mujoco_names(model, mujoco.mjtObj.mjOBJ_ACTUATOR, model.nu)
    bodies = _mujoco_names(model, mujoco.mjtObj.mjOBJ_BODY, model.nbody)
    actuator_groups = dict(sorted(Counter(_body_group(name) for name in actuators).items()))
    joint_groups = dict(sorted(Counter(_body_group(name) for name in joints).items()))
    print(f"FlyBody: {len(joints)} joints, {len(actuators)} actionneurs, {len(bodies)} corps")
    print("  actionneurs par groupe: " + ", ".join(f"{k}={v}" for k, v in actuator_groups.items()))
    return {
        "model": {"nq": model.nq, "nv": model.nv, "nu": model.nu, "nbody": model.nbody},
        "joints": joints,
        "actuators": actuators,
        "bodies": bodies,
        "joint_groups": joint_groups,
        "actuator_groups": actuator_groups,
    }


def audit_interface_groups(output_dir: Path) -> list[dict[str, Any]]:
    path = DATA_ROOT / DATASETS["annotations"]
    columns = [
        "bodyId", "type", "instance", "class", "subclass", "superclass",
        "somaSide", "rootSide", "somaNeuromere", "entryNerve", "exitNerve", "mancType",
        "assignedOlHex1", "assignedOlHex2",
    ]
    frame = ds.dataset(path, format="ipc").to_table(columns=columns).to_pandas()
    group_masks = {
        "sensory.visual": ("class == visual", frame["class"].eq("visual")),
        "sensory.olfactory": ("class == olfactory", frame["class"].eq("olfactory")),
        "sensory.gustatory": ("class == gustatory", frame["class"].eq("gustatory")),
        "sensory.tactile": (
            "class == mechanosensory_tactile", frame["class"].eq("mechanosensory_tactile")
        ),
        "sensory.mechanosensory_other": (
            "class == mechanosensory", frame["class"].eq("mechanosensory")
        ),
        "sensory.proprioceptive": (
            "class == mechanosensory_proprioceptive",
            frame["class"].eq("mechanosensory_proprioceptive"),
        ),
        "sensory.unknown": ("class == unknown_sensory", frame["class"].eq("unknown_sensory")),
        "sensory.optic_lobe": (
            "superclass == ol_sensory", frame["superclass"].eq("ol_sensory")
        ),
        "sensory.central_brain": (
            "superclass == cb_sensory", frame["superclass"].eq("cb_sensory")
        ),
        "sensory.thermohygro": (
            "class in [thermosensory, hygrosensory]",
            frame["class"].isin(["thermosensory", "hygrosensory"]),
        ),
        "sensory.vnc": ("superclass == vnc_sensory", frame["superclass"].eq("vnc_sensory")),
        "motor.vnc": ("superclass == vnc_motor", frame["superclass"].eq("vnc_motor")),
        "motor.exit_nerve": ("exitNerve is not null", frame["exitNerve"].notna()),
        "projection.ascending": (
            "superclass == ascending_neuron", frame["superclass"].eq("ascending_neuron")
        ),
        "projection.descending": (
            "superclass == descending_neuron", frame["superclass"].eq("descending_neuron")
        ),
    }
    summaries: list[dict[str, Any]] = []
    membership_frames: list[pd.DataFrame] = []
    subgroup_rows: list[dict[str, Any]] = []
    first_tier_rows: list[dict[str, Any]] = []
    axis_audit_rows: list[dict[str, Any]] = []
    for group_id, (query, mask) in group_masks.items():
        selected = frame.loc[mask].copy()
        selected.insert(0, "group_id", group_id)
        membership_frames.append(selected)
        axes = DECOMPOSITION_AXES[group_id]
        for axis_index, axis in enumerate(axes):
            known = selected[axis].notna()
            axis_audit_rows.append(
                {
                    "group_id": group_id,
                    "axis": axis,
                    "priority": axis_index + 1,
                    "known_neurons": int(known.sum()),
                    "coverage_percent": round(100 * float(known.mean()), 2) if len(selected) else 0.0,
                    "distinct_known_values": int(selected.loc[known, axis].nunique()),
                    "recommended_primary": axis_index == 0,
                }
            )
        grouping_columns = list(dict.fromkeys([*axes, "bodyId", "type"]))
        grouping = selected[grouping_columns].copy()
        grouping[axes] = grouping[axes].fillna("(unknown)").astype(str)
        candidates = (
            grouping.groupby(axes, dropna=False)
            .agg(neurons=("bodyId", "size"), named_types=("type", "nunique"))
            .reset_index()
        )
        for candidate in candidates.to_dict(orient="records"):
            key = "|".join(str(candidate[axis]) for axis in axes)
            digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
            subgroup_rows.append(
                {
                    "subgroup_id": f"{group_id}.{digest}",
                    "parent_group_id": group_id,
                    **candidate,
                    "decomposition_status": "proposed",
                    "routing_status": "unknown",
                }
            )
        primary_axis = axes[0]
        primary_columns = list(dict.fromkeys([primary_axis, "bodyId", "type"]))
        primary = selected[primary_columns].copy()
        primary[primary_axis] = primary[primary_axis].fillna("(unknown)").astype(str)
        first_tier = (
            primary.groupby(primary_axis, dropna=False)
            .agg(neurons=("bodyId", "size"), named_types=("type", "nunique"))
            .reset_index()
        )
        for tier in first_tier.to_dict(orient="records"):
            value = str(tier[primary_axis])
            digest = hashlib.sha256(f"{primary_axis}|{value}".encode("utf-8")).hexdigest()[:10]
            query = f"{primary_axis} is null" if value == "(unknown)" else f"{primary_axis} == {value}"
            first_tier_rows.append(
                {
                    "subgroup_id": f"{group_id}.{digest}",
                    "parent_group_id": group_id,
                    "partition_axis": primary_axis,
                    "partition_value": value,
                    "query": query,
                    "neurons": tier["neurons"],
                    "named_types": tier["named_types"],
                    "inventory_status": "complete",
                    "decomposition_status": "proposed",
                    "routing_status": "unknown",
                    "validation_status": "not_run",
                }
            )
        summaries.append(
            {
                "id": group_id,
                "query": query,
                "neurons": int(len(selected)),
                "named_types": int(selected["type"].nunique(dropna=True)),
                "typed_neurons": int(selected["type"].notna().sum()),
                "candidate_subgroups": int(len(candidates)),
                "first_tier_subgroups": int(len(first_tier)),
                "recommended_axes": axes,
                "entry_nerves": {
                    str(key): int(value) for key, value in selected["entryNerve"].value_counts().items()
                },
                "exit_nerves": {
                    str(key): int(value) for key, value in selected["exitNerve"].value_counts().items()
                },
                "sides": {
                    str(key): int(value) for key, value in selected["somaSide"].value_counts().items()
                },
                "subclasses": {
                    str(key): int(value) for key, value in selected["subclass"].value_counts().items()
                },
            }
        )
        print(
            f"  {group_id:32} {len(selected):6,} neurones, "
            f"{selected['type'].nunique(dropna=True):5,} types"
        )

    pd.DataFrame(
        [
            {
                "group_id": item["id"],
                "query": item["query"],
                "neurons": item["neurons"],
                "named_types": item["named_types"],
                "typed_neurons": item["typed_neurons"],
            }
            for item in summaries
        ]
    ).to_csv(output_dir / "interface-groups.csv", index=False, encoding="utf-8")
    pd.concat(membership_frames, ignore_index=True).to_parquet(
        output_dir / "interface-neurons.parquet", index=False
    )
    pd.DataFrame(subgroup_rows).to_csv(
        output_dir / "interface-subgroups.csv", index=False, encoding="utf-8"
    )
    pd.DataFrame(first_tier_rows).to_csv(
        output_dir / "interface-first-tier.csv", index=False, encoding="utf-8"
    )
    pd.DataFrame(axis_audit_rows).to_csv(
        output_dir / "interface-decomposition-audit.csv", index=False, encoding="utf-8"
    )
    print(
        f"  {len(first_tier_rows):,} groupes de premier niveau et "
        f"{len(subgroup_rows):,} sous-groupes fins proposés"
    )
    return summaries


def build_inventory(output: Path = OUTPUT) -> dict[str, Any]:
    section("Audit des tables MaleCNS locales")
    datasets = {
        label: audit_dataset(label, filename) for label, filename in DATASETS.items()
    }
    section("Audit du modèle physique FlyBody")
    body = audit_flybody()
    section("Découpage reproductible des populations d'interface")
    output.parent.mkdir(parents=True, exist_ok=True)
    interface_groups = audit_interface_groups(output.parent)
    inventory = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "local reproducible audit; no neuPrint token used",
        "datasets": datasets,
        "flybody": body,
        "interface_groups": interface_groups,
    }
    output.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    section("Résultat")
    print(f"Inventaire écrit dans {output}")
    return inventory


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit local MaleCNS et FlyBody")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    try:
        build_inventory(args.output)
    except Exception as exc:
        print(f"\nINVENTORY_FAILED: {type(exc).__name__}: {exc}")
        return 1
    print("\nINVENTORY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

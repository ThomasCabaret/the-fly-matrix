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
SOURCE = INVENTORY_ROOT / "interface-neurons.parquet"
OUTPUT_ROOT = ROOT / "data" / "derived" / "wiring"
SUMMARY_OUTPUT = OUTPUT_ROOT / "basal-clamp-routing.json"
CHANNEL_OUTPUT = OUTPUT_ROOT / "basal-clamp-channels.csv"
ROUTE_OUTPUT = OUTPUT_ROOT / "basal-clamp-routes.parquet"

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
            "entryNerve",
            "subclass",
            "rootSide",
        ]
        routes = selected[route_columns].rename(columns={"bodyId": "target_body_id"})
        output_frames.append(routes)
        unknown_counts = {
            axis: int(selected[axis].eq("(unknown)").sum()) for axis in axes
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
    except Exception as exc:
        print(f"\nWIRING_FAILED: {type(exc).__name__}: {exc}")
        return 1
    print("\nWIRING_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from .ledger import ROOT, build_summary, load_ledger


DERIVED_WIRING = ROOT / "data" / "derived" / "wiring"
DEFAULT_OUTPUT = ROOT / "reports" / "generated" / "wiring-map" / "wiring-map.json"

INPUT_SPACING = 7.0
OUTPUT_SPACING = 12.0
SECTOR_GAP = 210.0
TOP_MARGIN = 220.0

LANE_X = {
    "physical_input": 400.0,
    "source_model": 1_850.0,
    "input_adapter": 3_150.0,
    "cns_input": 4_250.0,
    "cns_core": 4_850.0,
    "cns_output": 5_450.0,
    "output_adapter": 6_650.0,
    "physical_output": 8_050.0,
}

SECTOR_ORDER = [
    "vision",
    "proprioception",
    "mechanosensation",
    "basal_clamps",
    "unclassified_sensory",
]

SECTOR_LABELS = {
    "vision": "Vision",
    "proprioception": "Proprioception",
    "mechanosensation": "Mechanosensation",
    "basal_clamps": "Basal sensory sources",
    "unclassified_sensory": "Unclassified sensory inputs",
    "motor_output": "Motor output",
}

INPUT_FILES = {
    "vision": ("vision-channels.csv", "vision-routes.parquet"),
    "proprioception": ("proprioception-channels.csv", "proprioception-routes.parquet"),
    "mechanosensation": (
        "mechanosensation-channels.csv",
        "mechanosensation-routes.parquet",
    ),
    "basal_clamps": ("basal-clamp-channels.csv", "basal-clamp-routes.parquet"),
    "unclassified_sensory": (
        "unclassified-sensory-channels.csv",
        "unclassified-sensory-routes.parquet",
    ),
}


class WiringMapError(RuntimeError):
    pass


def _stable_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _clean(value: Any) -> Any:
    if value is None:
        return None
    try:
        if bool(value != value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _compact(record: dict[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    return {
        key: cleaned
        for key in keys
        if key in record and (cleaned := _clean(record[key])) not in (None, "")
    }


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_parquet(path: Path) -> list[dict[str, Any]]:
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - depends on selected setup profile
        raise WiringMapError(
            "pandas/pyarrow are required for the wiring map. "
            "Run setup.bat -Profile audit or setup.bat -Profile full."
        ) from exc
    return pd.read_parquet(path).to_dict("records")


def _require_files(paths: Iterable[Path]) -> None:
    missing = [path for path in paths if not path.is_file()]
    if missing:
        rendered = "\n".join(
            f"  - {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}"
            for path in missing
        )
        raise WiringMapError(
            "The derived wiring inventory is incomplete. Run run_analysis.bat first.\n"
            f"Missing files:\n{rendered}"
        )


def _median(values: Iterable[float], fallback: float) -> float:
    materialized = list(values)
    return float(median(materialized)) if materialized else fallback


def _channel_label(record: dict[str, Any]) -> str:
    for key in ("type", "mancType", "class", "channel_id"):
        value = _clean(record.get(key))
        if value and value not in {"(unknown)", "unknown"}:
            return str(value)
    return str(record["channel_id"])


def _node(
    node_id: str,
    *,
    label: str,
    kind: str,
    lane: str,
    sector: str,
    x: float,
    y: float,
    state: str = "structural",
    details: dict[str, Any] | None = None,
    width: float | None = None,
    height: float | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": node_id,
        "label": label,
        "kind": kind,
        "lane": lane,
        "sector": sector,
        "state": state,
        "details": details or {},
    }
    if width is not None:
        data["width"] = width
    if height is not None:
        data["height"] = height
    return {"data": data, "position": {"x": x, "y": y}}


def _edge(
    edge_id: str,
    *,
    source: str,
    target: str,
    kind: str,
    sector: str,
    state: str,
    count: int = 1,
    label: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "data": {
            "id": edge_id,
            "source": source,
            "target": target,
            "kind": kind,
            "sector": sector,
            "state": state,
            "count": int(count),
            "label": label,
            "details": details or {},
        }
    }


def _aggregate_candidates(
    rows: list[dict[str, Any]],
    source_key: str,
    target_key: str,
    detail_keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        source = str(row[source_key])
        target = str(row[target_key])
        key = (source, target)
        item = grouped.setdefault(
            key,
            {
                "source": source,
                "target": target,
                "count": 0,
                "values": {name: set() for name in detail_keys},
            },
        )
        item["count"] += 1
        for name in detail_keys:
            value = _clean(row.get(name))
            if value not in (None, ""):
                item["values"][name].add(str(value))
    result = []
    for item in grouped.values():
        details = {
            name: sorted(values)
            for name, values in item.pop("values").items()
            if values
        }
        result.append({**item, "details": details})
    return sorted(result, key=lambda item: (item["source"], item["target"]))


def build_wiring_map(derived_root: Path = DERIVED_WIRING) -> dict[str, Any]:
    required = [derived_root / name for pair in INPUT_FILES.values() for name in pair]
    required.extend(
        derived_root / name
        for name in (
            "flybody-proprioception-channels.csv",
            "flybody-touch-channels.csv",
            "flybody-local-touch-channels.csv",
            "flybody-vision-channels.csv",
            "vision-optic-columns.csv",
            "vision-column-photoreceptors.parquet",
            "vision-remainder-transduction.parquet",
            "proprioception-input-candidates.parquet",
            "proprioception-proxy-candidates.parquet",
            "mechanosensation-input-candidates.parquet",
            "motor-channels.csv",
            "motor-routes.parquet",
            "motor-muscle-groups.csv",
            "motor-actuator-candidates.parquet",
            "flybody-actuator-channels.csv",
        )
    )
    _require_files(required)

    ledger = load_ledger()
    summary = build_summary(ledger)
    boxes = {box["id"]: box for box in ledger["boxes"]}

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    edge_ids: set[str] = set()

    def add_node(item: dict[str, Any]) -> None:
        node_id = str(item["data"]["id"])
        if node_id in nodes:
            raise WiringMapError(f"Duplicate map node {node_id}")
        nodes[node_id] = item

    def add_edge(item: dict[str, Any]) -> None:
        edge_id = str(item["data"]["id"])
        if edge_id in edge_ids:
            raise WiringMapError(f"Duplicate map edge {edge_id}")
        edge_ids.add(edge_id)
        edges.append(item)

    input_channels: dict[str, dict[str, Any]] = {}
    input_routes: dict[str, list[dict[str, Any]]] = {}
    channel_sector: dict[str, str] = {}
    route_source_files: dict[str, str] = {}

    for sector in SECTOR_ORDER:
        channel_name, route_name = INPUT_FILES[sector]
        channel_path = derived_root / channel_name
        route_path = derived_root / route_name
        for row in _read_csv(channel_path):
            channel_id = str(row["channel_id"])
            if channel_id in input_channels:
                raise WiringMapError(f"Input channel appears twice: {channel_id}")
            input_channels[channel_id] = row
            channel_sector[channel_id] = sector
        input_routes[sector] = _read_parquet(route_path)
        route_source_files[sector] = str(route_path.relative_to(ROOT)).replace("\\", "/")

    sector_spans: dict[str, dict[str, float | int | str]] = {}
    channel_y: dict[str, float] = {}
    input_body_ids: set[int] = set()
    cursor = TOP_MARGIN

    for sector in SECTOR_ORDER:
        start = cursor
        sector_channels = sorted(
            (row for cid, row in input_channels.items() if channel_sector[cid] == sector),
            key=lambda row: (
                str(_clean(row.get("group_id")) or ""),
                str(_clean(row.get("type")) or ""),
                str(_clean(row.get("rootSide")) or ""),
                str(row["channel_id"]),
            ),
        )
        routes_by_channel: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for route in input_routes[sector]:
            routes_by_channel[str(route["channel_id"])].append(route)

        for channel in sector_channels:
            channel_id = str(channel["channel_id"])
            routes = sorted(
                routes_by_channel.get(channel_id, []),
                key=lambda row: int(row["target_body_id"]),
            )
            if not routes:
                raise WiringMapError(f"No MaleCNS route for input channel {channel_id}")
            target_positions: list[float] = []
            adapter_id = f"adapter:{channel_id}"
            for route in routes:
                body_id = int(route["target_body_id"])
                if body_id in input_body_ids:
                    raise WiringMapError(f"MaleCNS input bodyId routed twice: {body_id}")
                input_body_ids.add(body_id)
                y = cursor
                cursor += INPUT_SPACING
                target_positions.append(y)
                terminal_id = f"cns-input:{body_id}"
                terminal_details = _compact(
                    route,
                    (
                        "target_body_id",
                        "type",
                        "instance",
                        "class",
                        "subclass",
                        "entryNerve",
                        "rootSide",
                        "group_id",
                        "channel_id",
                    ),
                )
                terminal_details["source_file"] = route_source_files[sector]
                add_node(
                    _node(
                        terminal_id,
                        label=f"{body_id} · {_channel_label(route)}",
                        kind="cns_input_terminal",
                        lane="cns_input",
                        sector=sector,
                        x=LANE_X["cns_input"],
                        y=y,
                        state="exact",
                        details=terminal_details,
                    )
                )
                add_edge(
                    _edge(
                        f"edge:route-in:{body_id}",
                        source=adapter_id,
                        target=terminal_id,
                        kind="input_route",
                        sector=sector,
                        state="exact",
                        details={
                            "mapping_level": "exact_body_id",
                            "source_file": route_source_files[sector],
                        },
                    )
                )
                add_edge(
                    _edge(
                        f"edge:cns-interface-in:{body_id}",
                        source=terminal_id,
                        target="cns-core",
                        kind="cns_interface",
                        sector=sector,
                        state="structural",
                        details={
                            "mapping_level": "MaleCNS boundary terminal",
                            "internal_graph": "collapsed in this view",
                        },
                    )
                )
            y = _median(target_positions, cursor)
            channel_y[channel_id] = y
            routing_box_id = str(
                _clean(channel.get("routing_box_id") or channel.get("clamp_id")) or ""
            )
            ledger_box = boxes.get(routing_box_id, {})
            details = _compact(
                channel,
                (
                    "channel_id",
                    "box_instance_id",
                    "group_id",
                    "adapter_type",
                    "type",
                    "class",
                    "subclass",
                    "entryNerve",
                    "rootSide",
                    "neuron_count",
                    "mapping_level",
                    "upstream_physical_mapping",
                    "upstream_retinotopic_mapping",
                    "upstream_modality_mapping",
                    "source_model_box_id",
                    "source_policy",
                    "source_parameter_id",
                ),
            )
            details.update(
                {
                    "ledger_box_id": routing_box_id,
                    "ledger_path": ledger_box.get("_path"),
                    "evidence": ledger_box.get("evidence", []),
                    "validation_ids": ledger_box.get("validation_ids", []),
                    "source_file": str(channel_path.relative_to(ROOT)).replace("\\", "/"),
                }
            )
            add_node(
                _node(
                    adapter_id,
                    label=_channel_label(channel),
                    kind="input_adapter_channel",
                    lane="input_adapter",
                    sector=sector,
                    x=LANE_X["input_adapter"],
                    y=y,
                    state="blocked",
                    details=details,
                )
            )

        end = max(cursor - INPUT_SPACING, start)
        sector_spans[sector] = {
            "id": sector,
            "label": SECTOR_LABELS[sector],
            "start_y": start,
            "end_y": end,
            "terminal_count": sum(len(rows) for rows in routes_by_channel.values()),
            "channel_count": len(sector_channels),
        }
        add_node(
            _node(
                f"sector-label:{sector}",
                label=(
                    f"{SECTOR_LABELS[sector]} · "
                    f"{sector_spans[sector]['terminal_count']:,} terminals · "
                    f"{len(sector_channels):,} boxes"
                ),
                kind="sector_label",
                lane="input_adapter",
                sector=sector,
                x=LANE_X["input_adapter"] - 250,
                y=start - 80,
            )
        )
        cursor += SECTOR_GAP

    source_targets: dict[str, list[float]] = defaultdict(list)
    inbound_states: dict[str, set[str]] = defaultdict(set)

    physical_specs = [
        ("vision", "flybody-vision-channels.csv", "physical_visual_observable"),
        ("proprioception", "flybody-proprioception-channels.csv", "physical_joint_observable"),
        ("mechanosensation", "flybody-touch-channels.csv", "physical_contact_observable"),
        (
            "mechanosensation",
            "flybody-local-touch-channels.csv",
            "physical_contact_observable",
        ),
    ]
    physical_records: dict[str, tuple[str, str, dict[str, Any], str]] = {}
    for sector, filename, kind in physical_specs:
        path = derived_root / filename
        for row in _read_csv(path):
            channel_id = str(row["channel_id"])
            physical_records[channel_id] = (sector, kind, row, filename)

    proprio_candidates = _aggregate_candidates(
        _read_parquet(derived_root / "proprioception-input-candidates.parquet"),
        "source_channel_id",
        "target_channel_id",
        ("source_observable", "candidate_basis", "parameter_status"),
    )
    proprio_proxies = _aggregate_candidates(
        _read_parquet(derived_root / "proprioception-proxy-candidates.parquet"),
        "source_channel_id",
        "target_channel_id",
        ("source_observable", "candidate_basis", "proxy_for", "parameter_status"),
    )
    mechano_candidates = _aggregate_candidates(
        _read_parquet(derived_root / "mechanosensation-input-candidates.parquet"),
        "source_channel_id",
        "target_channel_id",
        ("source_kind", "source_observable", "candidate_basis", "parameter_status"),
    )
    for sector, candidates, filename in (
        ("proprioception", proprio_candidates, "proprioception-input-candidates.parquet"),
        (
            "mechanosensation",
            mechano_candidates,
            "mechanosensation-input-candidates.parquet",
        ),
    ):
        for candidate in candidates:
            source_channel = candidate["source"]
            target_channel = candidate["target"]
            if target_channel not in channel_y:
                raise WiringMapError(f"Unknown candidate target {target_channel}")
            source_targets[source_channel].append(channel_y[target_channel])
            inbound_states[target_channel].add("parameterized")
            add_edge(
                _edge(
                    f"edge:candidate-in:{_stable_id(sector, source_channel, target_channel)}",
                    source=f"physical:{source_channel}",
                    target=f"adapter:{target_channel}",
                    kind="physical_candidate",
                    sector=sector,
                    state="parameterized",
                    count=candidate["count"],
                    label=str(candidate["count"]) if candidate["count"] > 1 else "",
                    details={
                        **candidate["details"],
                        "free_parameter_edges": candidate["count"],
                        "source_file": f"data/derived/wiring/{filename}",
                    },
                )
            )
    for candidate in proprio_proxies:
        source_channel = candidate["source"]
        target_channel = candidate["target"]
        if target_channel not in channel_y:
            raise WiringMapError(f"Unknown proprioception proxy target {target_channel}")
        source_targets[source_channel].append(channel_y[target_channel])
        inbound_states[target_channel].add("proxy")
        add_edge(
            _edge(
                "edge:proxy-in:"
                f"{_stable_id('proprioception', source_channel, target_channel)}",
                source=f"physical:{source_channel}",
                target=f"adapter:{target_channel}",
                kind="physical_proxy",
                sector="proprioception",
                state="proxy",
                count=candidate["count"],
                label=str(candidate["count"]) if candidate["count"] > 1 else "",
                details={
                    **candidate["details"],
                    "free_parameter_edges": candidate["count"],
                    "terminal_disposition": "proxy",
                    "source_file": (
                        "data/derived/wiring/proprioception-proxy-candidates.parquet"
                    ),
                },
            )
        )

    for channel_id, (sector, kind, row, filename) in physical_records.items():
        span = sector_spans[sector]
        targets = source_targets.get(channel_id, [])
        if targets:
            y = _median(targets, float(span["start_y"]))
            state = "parameterized"
        else:
            same_sector = sorted(
                cid for cid, spec in physical_records.items() if spec[0] == sector
            )
            index = same_sector.index(channel_id)
            fraction = (index + 0.5) / max(len(same_sector), 1)
            y = float(span["start_y"]) + fraction * (
                float(span["end_y"]) - float(span["start_y"])
            )
            state = "blocked"
        details = _compact(
            row,
            (
                "channel_id",
                "joint_name",
                "body_group",
                "observables",
                "sensor_name",
                "sensor_dimension",
                "observable_layout",
                "eye",
                "ommatidium_id",
                "ommatidium_type",
                "segment_name",
            ),
        )
        details["source_file"] = f"data/derived/wiring/{filename}"
        add_node(
            _node(
                f"physical:{channel_id}",
                label=str(
                    _clean(
                        row.get("joint_name")
                        or row.get("sensor_name")
                        or row.get("segment_name")
                        or channel_id
                    )
                ),
                kind=kind,
                lane="physical_input",
                sector=sector,
                x=LANE_X["physical_input"],
                y=y,
                state=state,
                details=details,
            )
        )

    optic_assignments = _read_parquet(derived_root / "vision-column-photoreceptors.parquet")
    vision_remainder = _read_parquet(derived_root / "vision-remainder-transduction.parquet")
    optic_columns = {row["column_id"]: row for row in _read_csv(derived_root / "vision-optic-columns.csv")}
    assignments_by_column: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in optic_assignments:
        assignments_by_column[str(row["column_id"])].append(row)
    for column_id, column in sorted(optic_columns.items()):
        assignments = assignments_by_column.get(column_id, [])
        ys = [channel_y[str(row["target_channel_id"])] for row in assignments]
        y = _median(ys, float(sector_spans["vision"]["start_y"]))
        column_node_id = f"source-model:optic-column:{column_id}"
        add_node(
            _node(
                column_node_id,
                label=column_id,
                kind="anatomical_source_model",
                lane="source_model",
                sector="vision",
                x=LANE_X["source_model"],
                y=y,
                state="parameterized",
                details={
                    **_compact(
                        column,
                        (
                            "column_id",
                            "side",
                            "column_u",
                            "column_v",
                            "column_type",
                            "expected_flybody_sample_type",
                            "registration_status",
                        ),
                    ),
                    "source_file": "data/derived/wiring/vision-optic-columns.csv",
                    "free_parameter": "FlyBody ommatidium registration",
                },
            )
        )
        for assignment in assignments:
            target_channel = str(assignment["target_channel_id"])
            inbound_states[target_channel].add("parameterized")
            add_edge(
                _edge(
                    f"edge:optic-column:{assignment['parameter_id']}",
                    source=column_node_id,
                    target=f"adapter:{target_channel}",
                    kind="anatomical_assignment",
                    sector="vision",
                    state="exact",
                    details={
                        **_compact(
                            assignment,
                            (
                                "parameter_id",
                                "receptor_class",
                                "receptor_type",
                                "target_body_id",
                                "registration_status",
                                "parameter_status",
                            ),
                        ),
                        "source_file": (
                            "data/derived/wiring/vision-column-photoreceptors.parquet"
                        ),
                    },
                )
            )

    remainder_by_channel = {
        str(row["target_channel_id"]): row for row in vision_remainder
    }
    published_vision_channels = {
        str(row["target_channel_id"]) for row in optic_assignments
    }
    all_vision_channels = {
        channel_id
        for channel_id, sector in channel_sector.items()
        if sector == "vision"
    }
    if published_vision_channels | set(remainder_by_channel) != all_vision_channels:
        raise WiringMapError("Visual transduction does not cover every terminal channel")
    vision_box_id = "box:adapter.vision.transduction"
    add_node(
        _node(
            vision_box_id,
            label="Visual transduction\n6,098 terminal channels",
            kind="input_transform_box",
            lane="source_model",
            sector="vision",
            x=2_500.0,
            y=(
                float(sector_spans["vision"]["start_y"])
                + float(sector_spans["vision"]["end_y"])
            )
            / 2,
            state="parameterized",
            width=170,
            height=80,
            details={
                "ledger_box_id": "adapter.vision.transduction",
                "ledger_path": boxes["adapter.vision.transduction"]["_path"],
                "physical_inputs": 1442,
                "published_column_channels": len(published_vision_channels),
                "parameterized_remainder_channels": sum(
                    row["terminal_disposition"] == "parameterized"
                    for row in vision_remainder
                ),
                "proxy_hbeyelet_channels": sum(
                    row["terminal_disposition"] == "proxy"
                    for row in vision_remainder
                ),
                "source_file": "data/derived/wiring/vision-remainder-transduction.parquet",
            },
        )
    )
    for physical_channel_id, (sector, _kind, _row, _filename) in physical_records.items():
        if sector != "vision":
            continue
        nodes[f"physical:{physical_channel_id}"]["data"]["state"] = "exact"
        add_edge(
            _edge(
                f"edge:vision-sample:{_stable_id(physical_channel_id)}",
                source=f"physical:{physical_channel_id}",
                target=vision_box_id,
                kind="physical_sample_input",
                sector="vision",
                state="exact",
                details={"mapping_level": "exact FlyBody sample channel"},
            )
        )
    for channel_id in sorted(all_vision_channels):
        remainder = remainder_by_channel.get(channel_id)
        disposition = (
            str(remainder["terminal_disposition"])
            if remainder is not None
            else "parameterized"
        )
        inbound_states[channel_id].add(disposition)
        add_edge(
            _edge(
                f"edge:vision-transduction:{_stable_id(channel_id)}",
                source=vision_box_id,
                target=f"adapter:{channel_id}",
                kind="visual_transduction",
                sector="vision",
                state=disposition,
                details={
                    "terminal_disposition": disposition,
                    "mapping_level": (
                        "published column with external retinal registration"
                        if channel_id in published_vision_channels
                        else str(remainder["source_policy"])
                    ),
                },
            )
        )

    basal_channels: dict[str, list[str]] = defaultdict(list)
    for channel_id, channel in input_channels.items():
        if channel_sector[channel_id] == "basal_clamps":
            basal_channels[str(channel["clamp_id"])].append(channel_id)
    for clamp_id, channel_ids in sorted(basal_channels.items()):
        y = _median(
            (channel_y[channel_id] for channel_id in channel_ids),
            float(sector_spans["basal_clamps"]["start_y"]),
        )
        source_id = f"source-model:{clamp_id}"
        ledger_box = boxes.get(clamp_id, {})
        add_node(
            _node(
                source_id,
                label=str(ledger_box.get("name", clamp_id)),
                kind="basal_source",
                lane="source_model",
                sector="basal_clamps",
                x=LANE_X["source_model"],
                y=y,
                state="basal",
                details={
                    "ledger_box_id": clamp_id,
                    "ledger_path": ledger_box.get("_path"),
                    "evidence": ledger_box.get("evidence", []),
                    "parameter_family_ids": ledger_box.get("parameter_family_ids", []),
                },
            )
        )
        for channel_id in channel_ids:
            inbound_states[channel_id].add("basal")
            add_edge(
                _edge(
                    f"edge:basal:{_stable_id(clamp_id, channel_id)}",
                    source=source_id,
                    target=f"adapter:{channel_id}",
                    kind="basal_generation",
                    sector="basal_clamps",
                    state="basal",
                    details={"disposition": "basal"},
                )
            )

    residual_source_channels: dict[str, list[str]] = defaultdict(list)
    for channel_id, channel in input_channels.items():
        if channel_sector[channel_id] == "unclassified_sensory":
            source_box_id = str(_clean(channel.get("source_model_box_id")) or "")
            if not source_box_id:
                raise WiringMapError(
                    f"Residual sensory channel has no declared source model: {channel_id}"
                )
            residual_source_channels[source_box_id].append(channel_id)
    for source_box_id, channel_ids in sorted(residual_source_channels.items()):
        y = _median(
            (channel_y[channel_id] for channel_id in channel_ids),
            float(sector_spans["unclassified_sensory"]["start_y"]),
        )
        source_id = f"source-model:{source_box_id}"
        ledger_box = boxes.get(source_box_id, {})
        add_node(
            _node(
                source_id,
                label=str(ledger_box.get("name", source_box_id)),
                kind="nominal_source",
                lane="source_model",
                sector="unclassified_sensory",
                x=LANE_X["source_model"],
                y=y,
                state="basal",
                details={
                    "ledger_box_id": source_box_id,
                    "ledger_path": ledger_box.get("_path"),
                    "evidence": ledger_box.get("evidence", []),
                    "parameter_family_ids": ledger_box.get("parameter_family_ids", []),
                    "physical_modality_claim": "none",
                    "replaceable_policy": True,
                },
            )
        )
        for channel_id in channel_ids:
            inbound_states[channel_id].add("basal")
            channel = input_channels[channel_id]
            add_edge(
                _edge(
                    f"edge:residual-nominal:{_stable_id(source_box_id, channel_id)}",
                    source=source_id,
                    target=f"adapter:{channel_id}",
                    kind="nominal_generation",
                    sector="unclassified_sensory",
                    state="basal",
                    details={
                        "disposition": "basal",
                        "source_policy": channel.get("source_policy"),
                        "source_parameter_id": channel.get("source_parameter_id"),
                        "physical_modality_claim": "none",
                    },
                )
            )

    for channel_id, sector in channel_sector.items():
        states = inbound_states.get(channel_id, set())
        if "basal" in states:
            state = "basal"
        elif "proxy" in states:
            state = "proxy"
        elif "parameterized" in states:
            state = "parameterized"
        else:
            state = "blocked"
        nodes[f"adapter:{channel_id}"]["data"]["state"] = state
        nodes[f"adapter:{channel_id}"]["data"]["details"]["terminal_disposition"] = state

    motor_routes = _read_parquet(derived_root / "motor-routes.parquet")
    motor_groups = {
        str(row["motor_group_id"]): row
        for row in _read_csv(derived_root / "motor-muscle-groups.csv")
    }
    motor_members: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in motor_routes:
        motor_members[str(row["motor_group_id"])].append(row)

    output_body_ids: set[int] = set()
    output_group_y: dict[str, float] = {}
    output_cursor = TOP_MARGIN
    for group_id, group in sorted(
        motor_groups.items(),
        key=lambda item: (
            str(item[1].get("subclass", "")),
            str(item[1].get("type", "")),
            str(item[1].get("side", "")),
            item[0],
        ),
    ):
        members = sorted(motor_members.get(group_id, []), key=lambda row: int(row["source_body_id"]))
        member_positions: list[float] = []
        for member in members:
            body_id = int(member["source_body_id"])
            if body_id in output_body_ids:
                raise WiringMapError(f"MaleCNS output bodyId routed twice: {body_id}")
            output_body_ids.add(body_id)
            y = output_cursor
            output_cursor += OUTPUT_SPACING
            member_positions.append(y)
            terminal_id = f"cns-output:{body_id}"
            add_node(
                _node(
                    terminal_id,
                    label=f"{body_id} · {_channel_label(member)}",
                    kind="cns_output_terminal",
                    lane="cns_output",
                    sector="motor_output",
                    x=LANE_X["cns_output"],
                    y=y,
                    state="exact",
                    details={
                        **_compact(
                            member,
                            (
                                "source_body_id",
                                "type",
                                "instance",
                                "subclass",
                                "exitNerve",
                                "somaSide",
                                "somaNeuromere",
                                "channel_id",
                                "motor_group_id",
                            ),
                        ),
                        "source_file": "data/derived/wiring/motor-routes.parquet",
                    },
                )
            )
            add_edge(
                _edge(
                    f"edge:motor-member:{body_id}",
                    source=terminal_id,
                    target=f"motor-group:{group_id}",
                    kind="motor_group_membership",
                    sector="motor_output",
                    state="exact",
                    details={"mapping_level": "exact_body_id"},
                )
            )
            add_edge(
                _edge(
                    f"edge:cns-interface-out:{body_id}",
                    source="cns-core",
                    target=terminal_id,
                    kind="cns_interface",
                    sector="motor_output",
                    state="structural",
                    details={
                        "mapping_level": "MaleCNS boundary terminal",
                        "internal_graph": "collapsed in this view",
                    },
                )
            )
        y = _median(member_positions, output_cursor)
        output_group_y[group_id] = y
        add_node(
            _node(
                f"motor-group:{group_id}",
                label=str(_clean(group.get("type")) or group_id),
                kind="motor_group",
                lane="output_adapter",
                sector="motor_output",
                x=LANE_X["output_adapter"],
                y=y,
                state="blocked",
                details={
                    **_compact(
                        group,
                        (
                            "motor_group_id",
                            "subclass",
                            "type",
                            "side",
                            "annotation_resolution",
                            "member_neurons",
                            "member_channels",
                            "membership_mapping",
                            "flybody_actuator_mapping",
                        ),
                    ),
                    "source_file": "data/derived/wiring/motor-muscle-groups.csv",
                },
            )
        )

    motor_candidates = _aggregate_candidates(
        _read_parquet(derived_root / "motor-actuator-candidates.parquet"),
        "motor_group_id",
        "target_channel_id",
        ("candidate_basis", "parameter_status", "target_body_group"),
    )
    actuator_group_ys: dict[str, list[float]] = defaultdict(list)
    resolved_motor_groups: set[str] = set()
    for candidate in motor_candidates:
        group_id = candidate["source"]
        actuator_channel = candidate["target"]
        resolved_motor_groups.add(group_id)
        actuator_group_ys[actuator_channel].append(output_group_y[group_id])
        add_edge(
            _edge(
                f"edge:motor-candidate:{_stable_id(group_id, actuator_channel)}",
                source=f"motor-group:{group_id}",
                target=f"actuator:{actuator_channel}",
                kind="motor_candidate",
                sector="motor_output",
                state="parameterized",
                count=candidate["count"],
                label=str(candidate["count"]) if candidate["count"] > 1 else "",
                details={
                    **candidate["details"],
                    "free_parameter_edges": candidate["count"],
                    "source_file": "data/derived/wiring/motor-actuator-candidates.parquet",
                },
            )
        )
    for group_id in motor_groups:
        nodes[f"motor-group:{group_id}"]["data"]["state"] = (
            "parameterized" if group_id in resolved_motor_groups else "sink"
        )
        nodes[f"motor-group:{group_id}"]["data"]["details"]["terminal_disposition"] = (
            "parameterized" if group_id in resolved_motor_groups else "sink"
        )

    actuator_rows = _read_csv(derived_root / "flybody-actuator-channels.csv")
    for index, actuator in enumerate(actuator_rows):
        channel_id = str(actuator["channel_id"])
        fallback = TOP_MARGIN + index * OUTPUT_SPACING
        y = _median(actuator_group_ys.get(channel_id, []), fallback)
        add_node(
            _node(
                f"actuator:{channel_id}",
                label=str(actuator.get("actuator_name") or channel_id),
                kind="physical_actuator",
                lane="physical_output",
                sector="motor_output",
                x=LANE_X["physical_output"],
                y=y,
                state="parameterized" if actuator_group_ys.get(channel_id) else "blocked",
                details={
                    **_compact(
                        actuator,
                        (
                            "channel_id",
                            "actuator_id",
                            "actuator_name",
                            "body_group",
                            "target_joint_name",
                            "control_address",
                            "actuator_config_group",
                            "actuator_config_status",
                            "command_unit",
                        ),
                    ),
                    "source_file": "data/derived/wiring/flybody-actuator-channels.csv",
                },
            )
        )

    max_y = max(cursor, output_cursor, *(node["position"]["y"] for node in nodes.values()))
    core_height = max_y - TOP_MARGIN + 360
    add_node(
        _node(
            "cns-core",
            label="MaleCNS\n211,577 annotated neurons\n26,028,386 induced edges",
            kind="cns_core",
            lane="cns_core",
            sector="central_nervous_system",
            x=LANE_X["cns_core"],
            y=TOP_MARGIN + core_height / 2 - 100,
            state="structural",
            width=560,
            height=core_height,
            details={
                "ledger_box_id": "cns.malecns",
                "ledger_path": boxes["cns.malecns"]["_path"],
                "note": "The internal recurrent graph is collapsed in this interface view.",
                "source_file": "data/derived/wiring/central-connectome.json",
            },
        )
    )

    lane_labels = [
        ("physical_input", "PHYSICAL / EXTERNAL OBSERVABLES"),
        ("source_model", "SOURCE MODELS"),
        ("input_adapter", "INPUT BOXES"),
        ("cns_input", "MALECNS INPUTS"),
        ("cns_output", "MALECNS OUTPUTS"),
        ("output_adapter", "OUTPUT BOXES"),
        ("physical_output", "ACTUATORS"),
    ]
    for lane, label in lane_labels:
        add_node(
            _node(
                f"lane-label:{lane}",
                label=label,
                kind="lane_label",
                lane=lane,
                sector="layout",
                x=LANE_X[lane],
                y=40,
            )
        )

    input_state_counts: dict[str, int] = defaultdict(int)
    for channel_id in input_channels:
        input_state_counts[str(nodes[f"adapter:{channel_id}"]["data"]["state"])] += 1
    motor_state_counts: dict[str, int] = defaultdict(int)
    for group_id in motor_groups:
        motor_state_counts[str(nodes[f"motor-group:{group_id}"]["data"]["state"])] += 1

    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "project": "The Fly Matrix",
        "source_of_truth": "ledger/ plus reproducible data/derived/wiring manifests",
        "meta": {
            "wiring_progress": summary["wiring_progress"],
            "counts": {
                "nodes": len(nodes),
                "edges": len(edges),
                "cns_inputs": len(input_body_ids),
                "input_boxes": len(input_channels),
                "physical_observables": len(physical_records),
                "optic_columns": len(optic_columns),
                "cns_outputs": len(output_body_ids),
                "motor_groups": len(motor_groups),
                "actuators": len(actuator_rows),
            },
            "input_box_states": dict(sorted(input_state_counts.items())),
            "motor_group_states": dict(sorted(motor_state_counts.items())),
            "layout": {
                "kind": "deterministic_fixed_lanes",
                "semantic_zoom": "presentation_only",
                "topology_hidden_by_default": False,
            },
        },
        "sectors": [sector_spans[sector] for sector in SECTOR_ORDER],
        "elements": {
            "nodes": list(nodes.values()),
            "edges": edges,
        },
    }


def write_wiring_map(output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    print("The Fly Matrix - exhaustive interactive wiring map")
    print("[1/3] Loading canonical ledger and derived terminal manifests...")
    payload = build_wiring_map()
    counts = payload["meta"]["counts"]
    print(
        "[2/3] Built "
        f"{counts['nodes']:,} nodes and {counts['edges']:,} edges "
        f"({counts['cns_inputs']:,} CNS inputs, {counts['cns_outputs']:,} CNS outputs)."
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    size_mib = output.stat().st_size / (1024 * 1024)
    print(f"[3/3] Wrote {output.relative_to(ROOT)} ({size_mib:.1f} MiB).")
    print(
        "Input boxes by terminal disposition: "
        + ", ".join(
            f"{state}={count:,}"
            for state, count in payload["meta"]["input_box_states"].items()
        )
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the interactive wiring-map data")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        write_wiring_map(args.output)
    except WiringMapError as exc:
        print(f"[FAILED] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

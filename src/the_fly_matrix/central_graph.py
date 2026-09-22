from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa

from .ledger import ROOT


RAW_ROOT = ROOT / "data" / "raw" / "malecns" / "v1.0"
ANNOTATION_SOURCE = RAW_ROOT / "body-annotations-male-cns-v1.0-minconf-0.5.feather"
WEIGHT_SOURCE = RAW_ROOT / "connectome-weights-male-cns-v1.0-minconf-0.5.feather"
OUTPUT_ROOT = ROOT / "data" / "derived" / "wiring"
SUMMARY_OUTPUT = OUTPUT_ROOT / "central-connectome.json"
NODE_OUTPUT = OUTPUT_ROOT / "central-node-index.parquet"

EXPECTED_ANNOTATED_NODES = 211_577
EXPECTED_RAW_EDGES = 151_856_684
EXPECTED_INDUCED_EDGES = 26_028_386
EXPECTED_RAW_WEIGHT = 311_833_243
EXPECTED_INDUCED_WEIGHT = 125_365_933


def section(title: str) -> None:
    print(f"\n==> {title}", flush=True)


def _locate(sorted_body_ids: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    indices = np.searchsorted(sorted_body_ids, values)
    clipped = np.minimum(indices, len(sorted_body_ids) - 1)
    valid = (indices < len(sorted_body_ids)) & (sorted_body_ids[clipped] == values)
    return indices, valid


def _role_coverage(nodes: pd.DataFrame, superclass: str) -> dict[str, int]:
    selected = nodes.loc[nodes["superclass"].eq(superclass)]
    return {
        "nodes": int(len(selected)),
        "with_incoming_edges": int(selected["has_incoming_edge"].sum()),
        "with_outgoing_edges": int(selected["has_outgoing_edge"].sum()),
        "connected_union": int(
            (selected["has_incoming_edge"] | selected["has_outgoing_edge"]).sum()
        ),
        "isolated": int(
            (~(selected["has_incoming_edge"] | selected["has_outgoing_edge"])).sum()
        ),
    }


def build_central_graph_index(
    annotation_source: Path = ANNOTATION_SOURCE,
    weight_source: Path = WEIGHT_SOURCE,
    summary_output: Path = SUMMARY_OUTPUT,
    node_output: Path = NODE_OUTPUT,
) -> dict[str, Any]:
    """Index the annotated-neuron subgraph without duplicating the 1 GB edge file."""
    for path in (annotation_source, weight_source):
        if not path.is_file():
            raise FileNotFoundError(f"Source MaleCNS absente: {path}")

    section("Index creux du graphe central MaleCNS")
    columns = ["bodyId", "superclass", "class", "type", "instance", "somaSide", "status"]
    nodes = pd.read_feather(annotation_source, columns=columns)
    for column in columns[1:]:
        nodes[column] = nodes[column].fillna("(unknown)").astype(str)
    nodes = nodes.sort_values("bodyId").reset_index(drop=True)
    if len(nodes) != EXPECTED_ANNOTATED_NODES or nodes["bodyId"].duplicated().any():
        raise RuntimeError("L'univers des neurones annotés MaleCNS est inattendu")
    body_ids = nodes["bodyId"].to_numpy(dtype=np.int64)

    incoming_edge_count = np.zeros(len(nodes), dtype=np.int64)
    outgoing_edge_count = np.zeros(len(nodes), dtype=np.int64)
    incoming_synapse_weight = np.zeros(len(nodes), dtype=np.int64)
    outgoing_synapse_weight = np.zeros(len(nodes), dtype=np.int64)
    scope_counts = {
        "annotated_to_annotated": 0,
        "annotated_to_fragment": 0,
        "fragment_to_annotated": 0,
        "fragment_to_fragment": 0,
    }
    raw_edges = 0
    raw_weight = 0
    induced_weight = 0
    self_edges = 0
    minimum_weight: int | None = None
    maximum_weight = 0

    with pa.memory_map(str(weight_source), "r") as mapped:
        reader = pa.ipc.open_file(mapped)
        batch_count = reader.num_record_batches
        for batch_index in range(batch_count):
            batch = reader.get_batch(batch_index)
            pre = batch.column(0).to_numpy()
            post = batch.column(1).to_numpy()
            weight = batch.column(2).to_numpy()
            pre_indices, pre_annotated = _locate(body_ids, pre)
            post_indices, post_annotated = _locate(body_ids, post)
            induced = pre_annotated & post_annotated
            annotated_fragment = pre_annotated & ~post_annotated
            fragment_annotated = ~pre_annotated & post_annotated
            fragment_fragment = ~pre_annotated & ~post_annotated

            scope_counts["annotated_to_annotated"] += int(induced.sum())
            scope_counts["annotated_to_fragment"] += int(annotated_fragment.sum())
            scope_counts["fragment_to_annotated"] += int(fragment_annotated.sum())
            scope_counts["fragment_to_fragment"] += int(fragment_fragment.sum())
            raw_edges += len(weight)
            raw_weight += int(weight.sum())
            if induced.any():
                source = pre_indices[induced]
                target = post_indices[induced]
                selected_weight = weight[induced].astype(np.int64, copy=False)
                np.add.at(outgoing_edge_count, source, 1)
                np.add.at(incoming_edge_count, target, 1)
                np.add.at(outgoing_synapse_weight, source, selected_weight)
                np.add.at(incoming_synapse_weight, target, selected_weight)
                induced_weight += int(selected_weight.sum())
                self_edges += int(np.count_nonzero(pre[induced] == post[induced]))
                local_minimum = int(selected_weight.min())
                minimum_weight = (
                    local_minimum if minimum_weight is None else min(minimum_weight, local_minimum)
                )
                maximum_weight = max(maximum_weight, int(selected_weight.max()))
            if (batch_index + 1) % 500 == 0 or batch_index + 1 == batch_count:
                print(
                    f"[INFO] {batch_index + 1:,}/{batch_count:,} lots; "
                    f"{scope_counts['annotated_to_annotated']:,} arêtes neuronales",
                    flush=True,
                )

    if raw_edges != EXPECTED_RAW_EDGES or raw_weight != EXPECTED_RAW_WEIGHT:
        raise RuntimeError(f"Cardinalité brute inattendue: {raw_edges} arêtes, poids {raw_weight}")
    if (
        scope_counts["annotated_to_annotated"] != EXPECTED_INDUCED_EDGES
        or induced_weight != EXPECTED_INDUCED_WEIGHT
    ):
        raise RuntimeError(
            "Sous-graphe annoté inattendu: "
            f"{scope_counts['annotated_to_annotated']} arêtes, poids {induced_weight}"
        )
    if sum(scope_counts.values()) != raw_edges:
        raise RuntimeError("La partition annoté/fragment ne couvre pas toutes les arêtes")

    nodes.insert(0, "node_index", np.arange(len(nodes), dtype=np.int64))
    nodes = nodes.rename(columns={"bodyId": "body_id"})
    nodes["incoming_edge_count"] = incoming_edge_count
    nodes["outgoing_edge_count"] = outgoing_edge_count
    nodes["incoming_synapse_weight"] = incoming_synapse_weight
    nodes["outgoing_synapse_weight"] = outgoing_synapse_weight
    nodes["has_incoming_edge"] = incoming_edge_count > 0
    nodes["has_outgoing_edge"] = outgoing_edge_count > 0
    connected = nodes["has_incoming_edge"] | nodes["has_outgoing_edge"]

    summary: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": "streamable sparse structural CNS graph without fitted dynamics",
        "sources": {
            "annotations": str(annotation_source.relative_to(ROOT)).replace("\\", "/"),
            "weights": str(weight_source.relative_to(ROOT)).replace("\\", "/"),
        },
        "representation": {
            "node_order": "ascending annotated bodyId",
            "edge_storage": "original Arrow IPC/Feather batches streamed without duplication",
            "edge_scope": "induced subgraph whose pre and post bodyIds are both annotated",
            "weight_semantics": "published integer synapse-count weight",
            "batch_count": batch_count,
        },
        "annotated_nodes": int(len(nodes)),
        "connected_nodes": int(connected.sum()),
        "isolated_annotated_nodes": int((~connected).sum()),
        "nodes_with_incoming_edges": int(nodes["has_incoming_edge"].sum()),
        "nodes_with_outgoing_edges": int(nodes["has_outgoing_edge"].sum()),
        "raw_edge_rows": raw_edges,
        "induced_edge_rows": scope_counts["annotated_to_annotated"],
        "excluded_fragment_edge_rows": raw_edges - scope_counts["annotated_to_annotated"],
        "edge_scope_counts": scope_counts,
        "raw_synapse_weight": raw_weight,
        "induced_synapse_weight": induced_weight,
        "self_edges": self_edges,
        "minimum_edge_weight": minimum_weight,
        "maximum_edge_weight": maximum_weight,
        "role_coverage": {
            role: _role_coverage(nodes, role)
            for role in (
                "ascending_neuron",
                "descending_neuron",
                "vnc_motor",
                "cb_motor",
            )
        },
        "runtime_operation": "one-hop weighted synaptic-drive projection",
        "dynamics_status": "unassigned",
        "scientific_parameter_values_selected": False,
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    nodes.to_parquet(node_output, index=False, compression="zstd")
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] {len(nodes):,} neurones annotés indexés; {connected.sum():,} connectés")
    print(
        f"[OK] {scope_counts['annotated_to_annotated']:,} arêtes neuronales "
        f"sur {raw_edges:,} lignes brutes"
    )
    print(f"[INFO] {raw_edges - scope_counts['annotated_to_annotated']:,} arêtes de fragments exclues")
    print(f"[OK] Index des nœuds : {node_output}")
    print(f"[OK] Synthèse CNS : {summary_output}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Indexe le sous-graphe MaleCNS annoté")
    parser.add_argument("--annotations", type=Path, default=ANNOTATION_SOURCE)
    parser.add_argument("--weights", type=Path, default=WEIGHT_SOURCE)
    parser.add_argument("--summary-output", type=Path, default=SUMMARY_OUTPUT)
    parser.add_argument("--node-output", type=Path, default=NODE_OUTPUT)
    args = parser.parse_args()
    try:
        build_central_graph_index(
            args.annotations, args.weights, args.summary_output, args.node_output
        )
    except Exception as exc:
        print(f"\nCENTRAL_GRAPH_FAILED: {type(exc).__name__}: {exc}")
        return 1
    print("\nCENTRAL_GRAPH_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

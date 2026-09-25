from __future__ import annotations

import argparse
import hashlib
import html
import json
import webbrowser
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import breadth_first_order, connected_components

from .central_graph import (
    EXPECTED_ANNOTATED_NODES,
    EXPECTED_CANONICAL_NEURONS,
    EXPECTED_INDUCED_EDGES,
    EXPECTED_RUNTIME_EDGES,
    NODE_OUTPUT,
    WEIGHT_SOURCE,
    _locate,
)
from .ledger import ROOT


ROUTE_ROOT = ROOT / "data" / "derived" / "wiring"
INPUT_ROUTE_FILES = (
    "basal-clamp-routes.parquet",
    "proprioception-routes.parquet",
    "mechanosensation-routes.parquet",
    "vision-routes.parquet",
    "unclassified-sensory-routes.parquet",
)
OUTPUT_ROUTE_FILE = "motor-routes.parquet"
CACHE_ROOT = ROOT / "data" / "derived" / "analysis" / "cycle-topology"
REPORT_OUTPUT = ROOT / "reports" / "generated" / "connectome-cycle-topology.html"
SUMMARY_OUTPUT = CACHE_ROOT / "summary.json"
NODE_CLASSIFICATION_OUTPUT = CACHE_ROOT / "node-classification.parquet"


def _section(title: str) -> None:
    print(f"\n==> {title}", flush=True)


def _fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _cache_matches(metadata_path: Path, expected: dict[str, Any]) -> bool:
    if not metadata_path.is_file():
        return False
    try:
        actual = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return actual.get("cache_key") == expected


def build_or_load_adjacency(
    body_ids: np.ndarray,
    weight_source: Path = WEIGHT_SOURCE,
    cache_root: Path = CACHE_ROOT,
) -> tuple[np.ndarray, np.ndarray, bool]:
    """Build a topology-only CSR cache with two bounded-memory Arrow scans."""
    cache_root.mkdir(parents=True, exist_ok=True)
    indptr_path = cache_root / "adjacency-indptr.npy"
    indices_path = cache_root / "adjacency-indices.npy"
    metadata_path = cache_root / "adjacency-cache.json"
    cache_key = {
        "schema_version": 1,
        "node_count": int(len(body_ids)),
        "first_body_id": int(body_ids[0]),
        "last_body_id": int(body_ids[-1]),
        "weight_source": _fingerprint(weight_source),
    }
    if (
        indptr_path.is_file()
        and indices_path.is_file()
        and _cache_matches(metadata_path, cache_key)
    ):
        print("[CACHE] Adjacence CSR topologique reutilisee.", flush=True)
        return (
            np.load(indptr_path, mmap_mode="r"),
            np.load(indices_path, mmap_mode="r"),
            True,
        )

    node_count = len(body_ids)
    out_degree = np.zeros(node_count, dtype=np.int64)
    induced_edges = 0
    with pa.memory_map(str(weight_source), "r") as mapped:
        reader = pa.ipc.open_file(mapped)
        batch_count = reader.num_record_batches
        names = reader.schema.names
        pre_column = names.index("body_pre")
        post_column = names.index("body_post")
        print(
            f"[1/2] Comptage des aretes annotees dans {batch_count:,} lots Arrow...",
            flush=True,
        )
        for batch_index in range(batch_count):
            batch = reader.get_batch(batch_index)
            pre = batch.column(pre_column).to_numpy()
            post = batch.column(post_column).to_numpy()
            pre_indices, pre_valid = _locate(body_ids, pre)
            _, post_valid = _locate(body_ids, post)
            selected = pre_indices[pre_valid & post_valid]
            if len(selected):
                out_degree += np.bincount(selected, minlength=node_count)
                induced_edges += int(len(selected))
            if (batch_index + 1) % 250 == 0 or batch_index + 1 == batch_count:
                print(
                    f"      {batch_index + 1:,}/{batch_count:,} lots; "
                    f"{induced_edges:,} aretes retenues",
                    flush=True,
                )

    if induced_edges != EXPECTED_INDUCED_EDGES:
        raise RuntimeError(
            f"Sous-graphe inattendu: {induced_edges:,} aretes au lieu de "
            f"{EXPECTED_INDUCED_EDGES:,}"
        )
    indptr = np.empty(node_count + 1, dtype=np.int64)
    indptr[0] = 0
    np.cumsum(out_degree, out=indptr[1:])
    indices = np.lib.format.open_memmap(
        indices_path, mode="w+", dtype=np.int32, shape=(induced_edges,)
    )
    cursor = indptr[:-1].copy()

    with pa.memory_map(str(weight_source), "r") as mapped:
        reader = pa.ipc.open_file(mapped)
        names = reader.schema.names
        pre_column = names.index("body_pre")
        post_column = names.index("body_post")
        print("[2/2] Remplissage de l'adjacence CSR...", flush=True)
        for batch_index in range(reader.num_record_batches):
            batch = reader.get_batch(batch_index)
            pre = batch.column(pre_column).to_numpy()
            post = batch.column(post_column).to_numpy()
            source, pre_valid = _locate(body_ids, pre)
            target, post_valid = _locate(body_ids, post)
            valid = pre_valid & post_valid
            if valid.any():
                source = source[valid].astype(np.int32, copy=False)
                target = target[valid].astype(np.int32, copy=False)
                order = np.argsort(source, kind="stable")
                source = source[order]
                target = target[order]
                unique, starts, counts = np.unique(
                    source, return_index=True, return_counts=True
                )
                positions = (
                    np.repeat(cursor[unique], counts)
                    + np.arange(len(source), dtype=np.int64)
                    - np.repeat(starts, counts)
                )
                indices[positions] = target
                cursor[unique] += counts
            if (batch_index + 1) % 250 == 0 or batch_index + 1 == reader.num_record_batches:
                print(
                    f"      {batch_index + 1:,}/{reader.num_record_batches:,} lots ecrits",
                    flush=True,
                )

    if not np.array_equal(cursor, indptr[1:]):
        raise RuntimeError("Remplissage incomplet de l'adjacence CSR")
    indices.flush()
    np.save(indptr_path, indptr)
    metadata = {
        "cache_key": cache_key,
        "edge_count": induced_edges,
        "representation": "directed topology-only CSR; one entry per published edge row",
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"[OK] Cache CSR: {induced_edges:,} aretes.", flush=True)
    return np.load(indptr_path, mmap_mode="r"), np.load(indices_path, mmap_mode="r"), False


def _load_boundary_ids(
    body_ids: np.ndarray,
    route_root: Path = ROUTE_ROOT,
) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    input_frames: list[pd.DataFrame] = []
    counts: dict[str, int] = {}
    for name in INPUT_ROUTE_FILES:
        path = route_root / name
        if not path.is_file():
            raise FileNotFoundError(f"Route d'entree absente: {path}")
        frame = pd.read_parquet(path, columns=["target_body_id"])
        input_frames.append(frame)
        counts[name] = int(len(frame))
    output_path = route_root / OUTPUT_ROUTE_FILE
    if not output_path.is_file():
        raise FileNotFoundError(f"Route de sortie absente: {output_path}")
    output_frame = pd.read_parquet(output_path, columns=["source_body_id"])
    counts[OUTPUT_ROUTE_FILE] = int(len(output_frame))

    input_body_ids = np.unique(
        pd.concat(input_frames, ignore_index=True)["target_body_id"].to_numpy(np.int64)
    )
    output_body_ids = np.unique(output_frame["source_body_id"].to_numpy(np.int64))

    def map_ids(values: np.ndarray, label: str) -> np.ndarray:
        mapped, valid = _locate(body_ids, values)
        if not valid.all():
            missing = values[~valid][:10]
            raise RuntimeError(f"{label}: body IDs absents de l'index central: {missing}")
        return mapped.astype(np.int32, copy=False)

    return map_ids(input_body_ids, "inputs"), map_ids(output_body_ids, "outputs"), counts


def bfs_generations(
    indptr: np.ndarray,
    indices: np.ndarray,
    source_indices: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return shortest input depth, BFS predecessor, and discovery order."""
    node_count = len(indptr) - 1
    edge_count = len(indices)
    sources = np.unique(np.asarray(source_indices, dtype=np.int32))
    augmented_indptr = np.empty(node_count + 2, dtype=np.int64)
    augmented_indptr[: node_count + 1] = indptr
    augmented_indptr[node_count + 1] = edge_count + len(sources)
    augmented_indices = np.empty(edge_count + len(sources), dtype=np.int32)
    augmented_indices[:edge_count] = indices
    augmented_indices[edge_count:] = sources
    augmented_data = np.ones(edge_count + len(sources), dtype=np.uint8)
    augmented = csr_matrix(
        (augmented_data, augmented_indices, augmented_indptr),
        shape=(node_count + 1, node_count + 1),
        copy=False,
    )
    order, predecessor = breadth_first_order(
        augmented, node_count, directed=True, return_predecessors=True
    )
    depth = np.full(node_count, -1, dtype=np.int32)
    original_order = order[order != node_count].astype(np.int32, copy=False)
    for node in original_order:
        parent = int(predecessor[node])
        depth[node] = 0 if parent == node_count else depth[parent] + 1
    parent = predecessor[:node_count].astype(np.int32, copy=True)
    parent[parent == node_count] = -1
    return depth, parent, original_order


def tree_intervals(parent: np.ndarray, order: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Compute DFS intervals for exact ancestor tests in the chosen BFS forest."""
    node_count = len(parent)
    child_nodes = np.flatnonzero(parent >= 0).astype(np.int32)
    child_parents = parent[child_nodes]
    sort_order = np.argsort(child_parents, kind="stable")
    child_nodes = child_nodes[sort_order]
    counts = np.bincount(child_parents, minlength=node_count)
    child_indptr = np.empty(node_count + 1, dtype=np.int64)
    child_indptr[0] = 0
    np.cumsum(counts, out=child_indptr[1:])

    entry = np.full(node_count, -1, dtype=np.int64)
    exit_ = np.full(node_count, -1, dtype=np.int64)
    timer = 0
    roots = order[parent[order] < 0]
    for root in roots[::-1]:
        stack = [int(root)]
        while stack:
            encoded = stack.pop()
            if encoded >= 0:
                node = encoded
                entry[node] = timer
                timer += 1
                stack.append(~node)
                start, end = int(child_indptr[node]), int(child_indptr[node + 1])
                stack.extend(int(child) for child in child_nodes[start:end][::-1])
            else:
                exit_[~encoded] = timer
    return entry, exit_


def _extend_histogram(histogram: np.ndarray, required: int) -> np.ndarray:
    if required < len(histogram):
        return histogram
    return np.pad(histogram, (0, required + 1 - len(histogram)))


def characterize_cycles(
    indptr: np.ndarray,
    indices: np.ndarray,
    depth: np.ndarray,
    parent: np.ndarray,
    order: np.ndarray,
    component_labels: np.ndarray,
    component_sizes: np.ndarray,
    *,
    chunk_nodes: int = 4096,
) -> dict[str, Any]:
    """Count exact BFS-tree closures and SCC-confirmed feedback depth gaps."""
    node_count = len(depth)
    entry, exit_ = tree_intervals(parent, order)
    exact_cycle_hist = np.zeros(1, dtype=np.int64)
    feedback_gap_hist = np.zeros(1, dtype=np.int64)
    same_generation_edges = 0
    forward_edges = 0
    backward_edges = 0
    unreachable_edges = 0
    recurrent_edges = 0
    fundamental_edges = 0
    self_loop_nodes = np.zeros(node_count, dtype=bool)

    for start_node in range(0, node_count, chunk_nodes):
        end_node = min(start_node + chunk_nodes, node_count)
        row_counts = np.diff(indptr[start_node : end_node + 1])
        source = np.repeat(np.arange(start_node, end_node, dtype=np.int32), row_counts)
        target = np.asarray(indices[indptr[start_node] : indptr[end_node]])
        if not len(target):
            continue
        self_mask = source == target
        self_loop_nodes[source[self_mask]] = True
        reachable = (depth[source] >= 0) & (depth[target] >= 0)
        unreachable_edges += int((~reachable).sum())
        delta = depth[target] - depth[source]
        forward_edges += int((reachable & (delta > 0)).sum())
        same_generation_edges += int((reachable & (delta == 0)).sum())
        backward_edges += int((reachable & (delta < 0)).sum())

        same_component = component_labels[source] == component_labels[target]
        cyclic_component = (component_sizes[component_labels[source]] > 1) | self_mask
        recurrent = reachable & same_component & cyclic_component
        recurrent_edges += int(recurrent.sum())
        feedback = recurrent & (delta <= 0)
        if feedback.any():
            gaps = (-delta[feedback]).astype(np.int64, copy=False)
            local = np.bincount(gaps)
            feedback_gap_hist = _extend_histogram(feedback_gap_hist, len(local) - 1)
            feedback_gap_hist[: len(local)] += local

        ancestor = reachable & (entry[target] <= entry[source]) & (entry[source] < exit_[target])
        if ancestor.any():
            lengths = (depth[source[ancestor]] - depth[target[ancestor]] + 1).astype(
                np.int64, copy=False
            )
            local = np.bincount(lengths)
            exact_cycle_hist = _extend_histogram(exact_cycle_hist, len(local) - 1)
            exact_cycle_hist[: len(local)] += local
            fundamental_edges += int(ancestor.sum())

    cyclic_components = (component_sizes > 1).copy()
    cyclic_components[component_labels[self_loop_nodes]] = True
    return {
        "exact_tree_cycle_histogram": exact_cycle_hist.tolist(),
        "feedback_generation_gap_histogram": feedback_gap_hist.tolist(),
        "edge_depth_classes": {
            "forward": forward_edges,
            "same_generation": same_generation_edges,
            "backward": backward_edges,
            "unreachable_endpoint": unreachable_edges,
        },
        "recurrent_edges": recurrent_edges,
        "fundamental_cycle_closing_edges": fundamental_edges,
        "self_loop_nodes": int(self_loop_nodes.sum()),
        "cyclic_component_mask": cyclic_components,
    }


def _histogram(values: np.ndarray) -> list[int]:
    if not len(values):
        return []
    return np.bincount(values.astype(np.int64)).astype(np.int64).tolist()


def _sparse_histogram(values: np.ndarray) -> list[dict[str, int]]:
    dense = np.bincount(values.astype(np.int64))
    return [
        {"value": int(value), "count": int(dense[value])}
        for value in np.flatnonzero(dense)
    ]


def _expand_sparse_histogram(records: list[dict[str, int]]) -> list[int]:
    if not records:
        return []
    dense = np.zeros(max(record["value"] for record in records) + 1, dtype=np.int64)
    for record in records:
        dense[record["value"]] = record["count"]
    return dense.tolist()


def _compact_bins(histogram: list[int], exact_until: int = 32) -> list[dict[str, Any]]:
    hist = np.asarray(histogram, dtype=np.int64)
    if not len(hist) or not hist.any():
        return []
    first = int(np.flatnonzero(hist)[0])
    last = len(hist) - 1
    bins: list[dict[str, Any]] = []
    for value in range(first, min(last, exact_until) + 1):
        bins.append({"start": value, "end": value, "count": int(hist[value])})
    start = max(exact_until + 1, first)
    width = 1
    while start <= last:
        width *= 2
        end = min(last, exact_until + width)
        if end < start:
            continue
        bins.append({"start": start, "end": end, "count": int(hist[start : end + 1].sum())})
        start = end + 1
    return bins


def _bar_chart(
    title: str,
    histogram: list[int],
    *,
    exact_until: int = 32,
    zero_label: str | None = None,
) -> str:
    bins = _compact_bins(histogram, exact_until)
    if not bins:
        return f"<section class='panel'><h2>{html.escape(title)}</h2><p>No observations.</p></section>"
    width, height = 920, 310
    left, right, top, bottom = 64, 20, 32, 62
    plot_width = width - left - right
    plot_height = height - top - bottom
    maximum = max(item["count"] for item in bins)
    denominator = np.log10(maximum + 1) or 1.0
    slot = plot_width / len(bins)
    bar_width = max(1.0, slot * 0.78)
    parts = [
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='{html.escape(title)}'>",
        f"<line x1='{left}' y1='{top + plot_height}' x2='{width-right}' y2='{top+plot_height}' class='axis'/>",
    ]
    for index, item in enumerate(bins):
        count = item["count"]
        bar_height = 0 if count == 0 else np.log10(count + 1) / denominator * plot_height
        x = left + index * slot + (slot - bar_width) / 2
        y = top + plot_height - bar_height
        start, end = item["start"], item["end"]
        label = zero_label if start == 0 and zero_label else (str(start) if start == end else f"{start}-{end}")
        parts.append(
            f"<rect x='{x:.2f}' y='{y:.2f}' width='{bar_width:.2f}' height='{bar_height:.2f}' class='bar'>"
            f"<title>{html.escape(label)}: {count:,}</title></rect>"
        )
        if len(bins) <= 48 or index % max(1, len(bins) // 20) == 0 or index == len(bins) - 1:
            center = x + bar_width / 2
            parts.append(
                f"<text x='{center:.2f}' y='{height-bottom+18}' class='tick' "
                f"transform='rotate(48 {center:.2f} {height-bottom+18})'>{html.escape(label)}</text>"
            )
    parts.extend(
        [
            f"<text x='16' y='{top + plot_height/2}' class='ylabel' transform='rotate(-90 16 {top + plot_height/2})'>count (log10)</text>",
            f"<text x='{left + plot_width/2}' y='{height-5}' class='xlabel'>exact values, then logarithmic tail bins</text>",
            "</svg>",
        ]
    )
    return f"<section class='panel'><h2>{html.escape(title)}</h2>{''.join(parts)}</section>"


def _format_int(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _summary_digest(summary: dict[str, Any]) -> str:
    payload = json.dumps(summary, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def render_report(summary: dict[str, Any], output: Path = REPORT_OUTPUT) -> None:
    graph = summary["graph"]
    traversal = summary["traversal"]
    cycles = summary["cycles"]
    scc = summary["strongly_connected_components"]
    top_rows = "".join(
        "<tr>"
        f"<td>{row['rank']}</td><td>{_format_int(row['nodes'])}</td>"
        f"<td>{_format_int(row['reachable_nodes'])}</td><td>{row['minimum_input_depth']}</td>"
        f"<td>{row['maximum_input_depth']}</td></tr>"
        for row in scc["largest"]
    )
    body = f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>MaleCNS cycle topology</title><style>
:root{{--bg:#08111d;--panel:#101d2b;--ink:#eef6ff;--muted:#9eb2c8;--line:#29445f;--accent:#57d7b5;--accent2:#7ab7ff}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at top,#15283b 0,#08111d 45%);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}main{{max-width:1220px;margin:auto;padding:32px}}h1{{font-size:clamp(2rem,5vw,4.2rem);line-height:1;margin:.2em 0}}h2{{margin:0 0 14px;font-size:1.15rem}}.lede{{max-width:900px;color:var(--muted);font-size:1.05rem}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:24px 0}}.kpi,.panel,.note{{background:rgba(16,29,43,.92);border:1px solid var(--line);border-radius:16px;padding:18px;box-shadow:0 12px 30px #0004}}.kpi strong{{display:block;font-size:1.75rem;color:var(--accent)}}.kpi span{{color:var(--muted)}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr));gap:16px}}.panel{{overflow:auto}}svg{{width:100%;min-width:680px}}.axis{{stroke:#6e88a2;stroke-width:1}}.bar{{fill:var(--accent2)}}.bar:hover{{fill:var(--accent)}}.tick,.xlabel,.ylabel{{fill:var(--muted);font-size:10px;text-anchor:middle}}
.note{{margin:18px 0;border-left:5px solid #f1c75b}}code{{color:#aee8ff}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid var(--line);text-align:right}}th:first-child,td:first-child{{text-align:left}}.good{{color:var(--accent)}}footer{{color:var(--muted);margin:30px 0}}
</style></head><body><main><p class='good'>THE FLY MATRIX · STRUCTURAL ANALYSIS · NO CALIBRATION</p><h1>Cycle topology of MaleCNS</h1>
<p class='lede'>All 211,577 annotation rows are retained and classified. Graph metrics below use only the 166,700 bodies explicitly flagged as canonical neurons. Multi-source breadth-first generations begin at every declared connectome input and run to exhaustion.</p>
<div class='note'><strong>Important correction.</strong> Shortest-path depth from 17,884 simultaneous inputs is strongly compressed and is <em>not</em> a measure of biological processing depth or actual cycle length. A same-generation edge may participate in a macroscopic cycle. SCC size is exact; the feedback-depth charts are traversal diagnostics only.</div>
<div class='kpis'><div class='kpi'><strong>{_format_int(graph['canonical_neurons'])}</strong><span>canonical neurons</span></div><div class='kpi'><strong>{_format_int(graph['annotated_body_rows'])}</strong><span>retained annotation rows</span></div><div class='kpi'><strong>{_format_int(graph['canonical_edges'])}</strong><span>neuron-to-neuron connections</span></div><div class='kpi'><strong>{traversal['reachable_percent']:.2f}%</strong><span>neurons reachable from inputs</span></div><div class='kpi'><strong>{_format_int(scc['largest_component_nodes'])}</strong><span>largest exact SCC</span></div><div class='kpi'><strong>{_format_int(summary['behavioral_relevance']['causal_core'])}</strong><span>input→motor causal core</span></div></div>
<div class='grid'>{_bar_chart('Neurons by shortest input depth', traversal['depth_histogram'], exact_until=48)}{_bar_chart('Motor outputs by shortest input depth', traversal['output_depth_histogram'], exact_until=48)}{_bar_chart('SCC sizes (number of components)', _expand_sparse_histogram(scc['size_histogram']), exact_until=16)}{_bar_chart('SCC-confirmed feedback generation gaps', cycles['feedback_generation_gap_histogram'], exact_until=32, zero_label='same depth')}{_bar_chart('Exact BFS-tree cycle lengths', cycles['exact_tree_cycle_histogram'], exact_until=32)}</div>
<section class='panel' style='margin-top:16px'><h2>Largest strongly connected components</h2><table><thead><tr><th>Rank</th><th>Nodes</th><th>Input-reachable</th><th>Min depth</th><th>Max depth</th></tr></thead><tbody>{top_rows}</tbody></table></section>
<section class='panel' style='margin-top:16px'><h2>Scope, causal relevance and edge classes</h2><table><tbody><tr><th>Non-neuronal or unresolved bodies retained but excluded from neural metrics</th><td>{_format_int(graph['noncanonical_annotated_bodies'])}</td></tr><tr><th>Declared input terminals (all canonical)</th><td>{_format_int(traversal['input_count'])}</td></tr><tr><th>Declared motor outputs (all canonical)</th><td>{_format_int(traversal['output_count'])}</td></tr><tr><th>Input→motor causal core</th><td>{_format_int(summary['behavioral_relevance']['causal_core'])}</td></tr><tr><th>Input-reachable, cannot reach modeled motor output</th><td>{_format_int(summary['behavioral_relevance']['input_reachable_no_modeled_motor_output'])}</td></tr><tr><th>No declared input, can reach modeled motor output</th><td>{_format_int(summary['behavioral_relevance']['no_declared_input_can_reach_motor_output'])}</td></tr><tr><th>Neither input-reachable nor motor-output-relevant</th><td>{_format_int(summary['behavioral_relevance']['neither'])}</td></tr><tr><th>Forward edges by input depth</th><td>{_format_int(cycles['edge_depth_classes']['forward'])}</td></tr><tr><th>Same-generation edges</th><td>{_format_int(cycles['edge_depth_classes']['same_generation'])}</td></tr><tr><th>Backward edges by input depth</th><td>{_format_int(cycles['edge_depth_classes']['backward'])}</td></tr></tbody></table></section>
<div class='note'><strong>Interpretation boundary.</strong> The giant SCC proves macroscopic recurrence, but this report does not yet recover a feed-forward backbone. That requires a weighted hierarchy / feedback-arc analysis. Synapse signs, time constants and dynamics remain outside this structural report.</div>
<footer>Generated {html.escape(summary['generated_at'])} · MaleCNS v1.0 minconf 0.5 · summary digest <code>{summary['summary_sha256'][:16]}</code> · machine-readable data: <code>data/derived/analysis/cycle-topology/summary.json</code></footer></main></body></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(body, encoding="utf-8")


def analyze_connectome_topology(
    *,
    node_path: Path = NODE_OUTPUT,
    weight_source: Path = WEIGHT_SOURCE,
    route_root: Path = ROUTE_ROOT,
    cache_root: Path = CACHE_ROOT,
    summary_output: Path = SUMMARY_OUTPUT,
    report_output: Path = REPORT_OUTPUT,
    classification_output: Path = NODE_CLASSIFICATION_OUTPUT,
) -> dict[str, Any]:
    for path in (node_path, weight_source):
        if not path.is_file():
            raise FileNotFoundError(f"Source requise absente: {path}")

    _section("Univers neuronal et frontieres du connectome")
    required_columns = ["node_index", "body_id", "population_scope", "scope_reason", "is_canonical_neuron", "included_in_neural_runtime", "runtime_node_index"]
    nodes = pd.read_parquet(node_path, columns=required_columns).sort_values("node_index").reset_index(drop=True)
    body_ids = nodes["body_id"].to_numpy(np.int64)
    if len(body_ids) != EXPECTED_ANNOTATED_NODES or not np.all(body_ids[:-1] < body_ids[1:]):
        raise RuntimeError("Index central inattendu ou non trie")
    canonical_mask = nodes["is_canonical_neuron"].to_numpy(dtype=bool)
    if int(canonical_mask.sum()) != EXPECTED_CANONICAL_NEURONS:
        raise RuntimeError("Classification neuronale centrale inattendue")
    input_full_indices, output_full_indices, route_counts = _load_boundary_ids(body_ids, route_root)
    if not canonical_mask[input_full_indices].all() or not canonical_mask[output_full_indices].all():
        raise RuntimeError("Une route d'interface vise un corps non canonique")
    full_to_runtime = np.full(len(nodes), -1, dtype=np.int32)
    full_to_runtime[canonical_mask] = np.arange(int(canonical_mask.sum()), dtype=np.int32)
    input_indices = full_to_runtime[input_full_indices]
    output_indices = full_to_runtime[output_full_indices]
    print(f"[OK] {len(input_indices):,} entrees CNS uniques; {len(output_indices):,} sorties motrices uniques.", flush=True)

    _section("Adjacence topologique")
    full_indptr, full_indices, cache_reused = build_or_load_adjacency(body_ids, weight_source, cache_root)
    full_graph = csr_matrix((np.ones(len(full_indices), dtype=np.uint8), full_indices, full_indptr), shape=(len(body_ids), len(body_ids)), copy=False)
    graph = full_graph[canonical_mask][:, canonical_mask].tocsr()
    if graph.nnz != EXPECTED_RUNTIME_EDGES:
        raise RuntimeError(f"Arêtes neuronales inattendues: {graph.nnz}")
    indptr, indices = graph.indptr, graph.indices

    _section("Generations BFS depuis toutes les entrees")
    depth, parent, order = bfs_generations(indptr, indices, input_indices)
    reachable = depth >= 0
    reachable_outputs_mask = depth[output_indices] >= 0
    reverse_graph = graph.transpose().tocsr()
    output_distance, _, _ = bfs_generations(reverse_graph.indptr, reverse_graph.indices, output_indices)
    can_reach_output = output_distance >= 0
    print(f"[OK] {reachable.sum():,}/{len(depth):,} neurones canoniques atteints; {reachable_outputs_mask.sum():,}/{len(output_indices):,} sorties atteintes; profondeur maximale {depth[reachable].max() if reachable.any() else -1}.", flush=True)

    _section("Composantes fortement connexes exactes")
    component_count, labels = connected_components(graph, directed=True, connection="strong", return_labels=True)
    component_sizes = np.bincount(labels, minlength=component_count).astype(np.int64)
    print(f"[OK] {component_count:,} SCC; plus grande: {component_sizes.max():,} neurones.", flush=True)

    _section("Retours de generation et cycles fondamentaux")
    cycle_data = characterize_cycles(indptr, indices, depth, parent, order, labels, component_sizes)
    cyclic_mask = cycle_data.pop("cyclic_component_mask")
    cyclic_nodes = int(component_sizes[cyclic_mask].sum())
    cyclic_component_count = int(cyclic_mask.sum())
    print(f"[OK] {cyclic_component_count:,} SCC cycliques couvrant {cyclic_nodes:,} neurones; {cycle_data['fundamental_cycle_closing_edges']:,} fermetures exactes du foret BFS.", flush=True)

    relevance = np.full(len(nodes), "excluded_noncanonical_body", dtype=object)
    canonical_relevance = np.select(
        [reachable & can_reach_output, reachable & ~can_reach_output, ~reachable & can_reach_output],
        ["causal_core", "input_reachable_no_modeled_motor_output", "no_declared_input_can_reach_motor_output"],
        default="neither",
    )
    relevance[canonical_mask] = canonical_relevance
    node_classification = nodes.copy()
    node_classification["reachable_from_declared_input"] = False
    node_classification["can_reach_modeled_motor_output"] = False
    node_classification["shortest_input_depth"] = -1
    node_classification.loc[canonical_mask, "reachable_from_declared_input"] = reachable
    node_classification.loc[canonical_mask, "can_reach_modeled_motor_output"] = can_reach_output
    node_classification.loc[canonical_mask, "shortest_input_depth"] = depth
    node_classification["behavioral_relevance"] = relevance
    classification_output.parent.mkdir(parents=True, exist_ok=True)
    node_classification.to_parquet(classification_output, index=False, compression="zstd")

    largest: list[dict[str, Any]] = []
    for rank, component in enumerate(np.argsort(component_sizes)[::-1][:12], start=1):
        members = labels == component
        member_depths = depth[members & reachable]
        largest.append({
            "rank": rank,
            "component_id": int(component),
            "nodes": int(component_sizes[component]),
            "reachable_nodes": int(len(member_depths)),
            "minimum_input_depth": int(member_depths.min()) if len(member_depths) else None,
            "maximum_input_depth": int(member_depths.max()) if len(member_depths) else None,
        })

    summary: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "analysis_status": "structural_only_no_calibration",
        "definitions": {
            "generation": "shortest directed path length from any declared CNS input",
            "feedback_generation_gap": "depth(source)-depth(target), restricted to edges inside a cyclic SCC and target depth <= source depth",
            "exact_tree_cycle_length": "BFS-tree ancestor path plus its directed closing edge; an exact traversal-dependent subset, not all simple cycles",
            "scc": "maximal set in which every neuron can reach every other neuron",
        },
        "limitations": [
            "All simple directed cycles are not enumerated because their number can be exponential.",
            "Generation is a shortest-path layer, not a biological time step.",
            "Synapse signs, weights and dynamics are not analyzed here.",
            "A feedback depth gap is a recurrent-span proxy, not generally the exact length of a simple cycle.",
        ],
        "sources": {"node_index": _fingerprint(node_path), "connectome_edges": _fingerprint(weight_source), "route_files": route_counts},
        "graph": {"annotated_body_rows": int(len(body_ids)), "canonical_neurons": int(canonical_mask.sum()), "noncanonical_annotated_bodies": int((~canonical_mask).sum()), "annotated_body_edges": int(len(full_indices)), "canonical_edges": int(len(indices)), "cache_reused": cache_reused},
        "behavioral_relevance": {
            "causal_core": int((reachable & can_reach_output).sum()),
            "input_reachable_no_modeled_motor_output": int((reachable & ~can_reach_output).sum()),
            "no_declared_input_can_reach_motor_output": int((~reachable & can_reach_output).sum()),
            "neither": int((~reachable & ~can_reach_output).sum()),
        },
        "traversal": {
            "input_count": int(len(input_indices)), "output_count": int(len(output_indices)),
            "reachable_nodes": int(reachable.sum()), "unreachable_nodes": int((~reachable).sum()),
            "reachable_percent": float(reachable.mean() * 100),
            "reachable_outputs": int(reachable_outputs_mask.sum()), "unreachable_outputs": int((~reachable_outputs_mask).sum()),
            "maximum_depth": int(depth[reachable].max()) if reachable.any() else -1,
            "depth_histogram": _histogram(depth[reachable]),
            "output_depth_histogram": _histogram(depth[output_indices][reachable_outputs_mask]),
        },
        "strongly_connected_components": {
            "component_count": int(component_count), "cyclic_component_count": cyclic_component_count,
            "cyclic_nodes": cyclic_nodes, "largest_component_nodes": int(component_sizes.max()),
            "size_histogram": _sparse_histogram(component_sizes), "largest": largest,
        },
        "cycles": cycle_data,
    }
    summary["summary_sha256"] = _summary_digest(summary)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    render_report(summary, report_output)
    print(f"[OK] Donnees: {summary_output}", flush=True)
    print(f"[OK] Classification par corps: {classification_output}", flush=True)
    print(f"[OK] Rapport: {report_output}", flush=True)
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyse les generations, SCC et retours cycliques du MaleCNS")
    parser.add_argument("--no-open", action="store_true", help="N'ouvre pas le rapport HTML")
    parser.add_argument("--report", type=Path, default=REPORT_OUTPUT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        summary = analyze_connectome_topology(report_output=args.report)
    except Exception as exc:
        print(f"\nCYCLE_TOPOLOGY_FAILED: {type(exc).__name__}: {exc}", flush=True)
        return 1
    traversal = summary["traversal"]
    print("\nCYCLE_TOPOLOGY_OK", flush=True)
    print(f"Resume: {traversal['reachable_percent']:.2f}% atteignables; {summary['strongly_connected_components']['cyclic_nodes']:,} neurones cycliques; profondeur max {traversal['maximum_depth']}.", flush=True)
    if not args.no_open:
        try:
            webbrowser.open(args.report.resolve().as_uri())
        except Exception as exc:
            print(f"[WARN] Ouverture automatique impossible: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

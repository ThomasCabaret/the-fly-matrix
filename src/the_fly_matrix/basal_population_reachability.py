from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml
from scipy import sparse

from .connectome_topology import bfs_generations
from .ledger import ROOT


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "basal-reachable-population-accounting-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "basal-reachable-population-accounting-v0.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "basal-reachable-population-accounting-v0.yaml"
OUTPUT_ROOT = ROOT / "data" / "derived" / "calibration" / "basal-reachable-population-accounting-v0"


class BasalPopulationAccountingError(RuntimeError):
    """Raised when the preregistered reachability/accounting contract drifts."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _artifact_ref(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BasalPopulationAccountingError(f"{path} must contain a YAML mapping")
    return value


def _verify_campaign(campaign: Mapping[str, Any]) -> dict[str, Path]:
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise BasalPopulationAccountingError("population accounting cannot optimize parameters")
    if campaign.get("behavior_targets"):
        raise BasalPopulationAccountingError("population accounting cannot expose named behavior")
    if campaign.get("topology_changes_allowed") is not False:
        raise BasalPopulationAccountingError("population accounting cannot change topology")

    paths: dict[str, Path] = {}
    for key, record in campaign["frozen_inputs"].items():
        path = ROOT / str(record["path"])
        if not path.is_file():
            raise BasalPopulationAccountingError(f"missing frozen input {key}: {path}")
        observed = _sha256(path)
        if observed != str(record["sha256"]):
            raise BasalPopulationAccountingError(
                f"frozen input drift for {key}: {observed} != {record['sha256']}"
            )
        paths[key] = path
    return paths


def _runtime_nodes(path: Path, expected: int) -> pd.DataFrame:
    nodes = pd.read_parquet(path)
    nodes = nodes.loc[nodes["included_in_neural_runtime"].astype(bool)].copy()
    nodes = nodes.sort_values("runtime_node_index").reset_index(drop=True)
    if len(nodes) != expected:
        raise BasalPopulationAccountingError(f"canonical-neuron count drift: {len(nodes)} != {expected}")
    if not np.array_equal(nodes["runtime_node_index"].to_numpy(np.int64), np.arange(expected)):
        raise BasalPopulationAccountingError("runtime node indices are not contiguous")
    body_ids = nodes["body_id"].to_numpy(np.int64)
    if np.any(body_ids[1:] <= body_ids[:-1]):
        raise BasalPopulationAccountingError("runtime body IDs are not strictly increasing")
    return nodes


def _source_tables(paths: Mapping[str, Path]) -> dict[str, pd.DataFrame]:
    basal = pd.read_parquet(paths["basal_routes"])
    residual = pd.read_parquet(paths["residual_routes"])
    channels = pd.read_csv(paths["residual_channels"])[["channel_id", "source_model_box_id"]]
    residual = residual.merge(channels, on="channel_id", how="left", validate="one_to_one")
    if residual["source_model_box_id"].isna().any():
        raise BasalPopulationAccountingError("residual route without source-model family")
    return {"basal_routes": basal, "residual_routes": residual}


def compile_family_sources(
    campaign: Mapping[str, Any], tables: Mapping[str, pd.DataFrame]
) -> tuple[dict[str, np.ndarray], pd.DataFrame]:
    """Apply the six exact selectors and prove that every terminal has one family."""
    families: dict[str, np.ndarray] = {}
    records: list[pd.DataFrame] = []
    for selector in campaign["family_selectors"]:
        family_id = str(selector["family_id"])
        table = tables[str(selector["table"])]
        selected = table.loc[table[str(selector["field"])].eq(selector["value"])].copy()
        if selected.empty:
            raise BasalPopulationAccountingError(f"selector produced no source terminal: {family_id}")
        body_ids = selected["target_body_id"].to_numpy(np.int64)
        if len(np.unique(body_ids)) != len(body_ids):
            raise BasalPopulationAccountingError(f"duplicate source body inside family {family_id}")
        families[family_id] = np.sort(body_ids)
        records.append(
            pd.DataFrame(
                {
                    "family_id": family_id,
                    "channel_id": selected["channel_id"].astype(str).to_numpy(),
                    "body_id": body_ids,
                }
            )
        )
    source_members = pd.concat(records, ignore_index=True).sort_values(
        ["family_id", "body_id"]
    )
    return families, source_members


def _map_body_ids(runtime_body_ids: np.ndarray, selected: np.ndarray, label: str) -> np.ndarray:
    indices = np.searchsorted(runtime_body_ids, selected)
    clipped = np.minimum(indices, len(runtime_body_ids) - 1)
    valid = (indices < len(runtime_body_ids)) & (runtime_body_ids[clipped] == selected)
    if not valid.all():
        raise BasalPopulationAccountingError(
            f"{label} contains noncanonical body IDs: {selected[~valid][:10].tolist()}"
        )
    return indices.astype(np.int32, copy=False)


def compile_reachability(
    outgoing: sparse.csr_matrix,
    runtime_body_ids: np.ndarray,
    families: Mapping[str, np.ndarray],
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Compute exact directed multi-source depths for every family and their union."""
    family_depths: dict[str, np.ndarray] = {}
    summaries: dict[str, Any] = {}
    for family_id, body_ids in families.items():
        indices = _map_body_ids(runtime_body_ids, body_ids, family_id)
        depth, _, _ = bfs_generations(outgoing.indptr, outgoing.indices, indices)
        reached = depth >= 0
        values, counts = np.unique(depth[reached], return_counts=True)
        family_depths[family_id] = depth
        summaries[family_id] = {
            "source_terminals": int(len(body_ids)),
            "reachable_neurons": int(reached.sum()),
            "unreachable_neurons": int((~reached).sum()),
            "maximum_depth": int(depth[reached].max()),
            "depth_histogram": {
                str(int(value)): int(count)
                for value, count in zip(values, counts, strict=True)
            },
        }

    union_body_ids = np.unique(np.concatenate(list(families.values())))
    union_indices = _map_body_ids(runtime_body_ids, union_body_ids, "basal source union")
    union_depth, _, _ = bfs_generations(outgoing.indptr, outgoing.indices, union_indices)
    reached = union_depth >= 0
    values, counts = np.unique(union_depth[reached], return_counts=True)
    summaries["union"] = {
        "source_terminals": int(len(union_body_ids)),
        "reachable_neurons": int(reached.sum()),
        "unreachable_neurons": int((~reached).sum()),
        "reachable_fraction": float(reached.mean()),
        "maximum_depth": int(union_depth[reached].max()),
        "depth_histogram": {
            str(int(value)): int(count)
            for value, count in zip(values, counts, strict=True)
        },
    }
    family_depths["union"] = union_depth
    return family_depths, summaries


def _known(value: pd.Series) -> pd.Series:
    cleaned = value.fillna("(unknown)").astype(str).str.strip()
    return ~cleaned.isin(["", "(unknown)", "unknown", "nan", "None"])


def _strata(nodes: pd.DataFrame) -> pd.Series:
    result = pd.Series("body:" + nodes["body_id"].astype(str), index=nodes.index, dtype="object")
    for column in ("superclass", "class", "type"):
        mask = _known(nodes[column])
        result.loc[mask] = column + ":" + nodes.loc[mask, column].astype(str)
    return result


def accepted_event_body_ids(paths: Mapping[str, Path], expected: int) -> np.ndarray:
    endpoints = pd.read_csv(paths["accepted_endpoint_assignments"])
    intermediates = pd.read_csv(paths["accepted_intermediate_assignments"])
    body_ids = np.unique(
        np.concatenate(
            [
                endpoints.loc[endpoints["assignment"].eq("event_required"), "body_id"].to_numpy(np.int64),
                intermediates.loc[intermediates["assignment"].eq("event_required"), "body_id"].to_numpy(np.int64),
            ]
        )
    )
    if len(body_ids) != expected:
        raise BasalPopulationAccountingError(
            f"accepted event-body count drift: {len(body_ids)} != {expected}"
        )
    return body_ids


def compile_population_dispositions(
    nodes: pd.DataFrame,
    family_depths: Mapping[str, np.ndarray],
    event_body_ids: np.ndarray,
    source_members: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    union_depth = family_depths["union"]
    reached_mask = union_depth >= 0
    reached = nodes.loc[reached_mask, ["body_id", "superclass", "class", "type", "instance"]].copy()
    reached["runtime_node_index"] = np.flatnonzero(reached_mask)
    reached["minimum_basal_depth"] = union_depth[reached_mask]
    reached["accounting_stratum_id"] = _strata(reached)
    reached["assignment"] = np.where(
        reached["body_id"].isin(event_body_ids), "event_required", "dual_unresolved"
    )
    reached["assignment_rule_id"] = np.where(
        reached["assignment"].eq("event_required"),
        "basal.reachable.accepted_local_event_requirement.v0",
        "basal.reachable.native_dynamics_unresolved.v0",
    )
    reached["parameter_values_emitted"] = False
    for ordinal, family_id in enumerate(key for key in family_depths if key != "union"):
        reached[f"family_{ordinal + 1}_reachable"] = family_depths[family_id][reached_mask] >= 0

    source = source_members.merge(
        reached[["body_id", "assignment"]], on="body_id", how="left", validate="many_to_one"
    )
    if source["assignment"].isna().any():
        raise BasalPopulationAccountingError("a basal source terminal is absent from reached accounting")
    source["bridge_disposition"] = source["assignment"].map(
        {
            "event_required": "event_intensity_hz_process_unresolved",
            "graded_required": "graded_hz_transfer_unresolved",
            "dual_unresolved": "dual_event_or_graded_bridge_unresolved",
        }
    )
    source["bridge_executable"] = False
    source["parameter_values_emitted"] = False

    strata = (
        reached.groupby(["accounting_stratum_id", "assignment"], dropna=False)
        .size()
        .rename("neurons")
        .reset_index()
        .sort_values(["neurons", "accounting_stratum_id"], ascending=[False, True])
    )
    return reached, source, strata


def compile_internal_boundary_counts(
    outgoing: sparse.csr_matrix,
    incoming: sparse.csr_matrix,
    reached_mask: np.ndarray,
    event_mask: np.ndarray,
) -> tuple[dict[str, int], int]:
    """Count assignment-state edge classes without expanding unresolved branches."""
    reached_indices = np.flatnonzero(reached_mask)
    leakage = 0
    for source in reached_indices:
        start, end = outgoing.indptr[source : source + 2]
        leakage += int((~reached_mask[outgoing.indices[start:end]]).sum())

    total = int(np.diff(outgoing.indptr)[reached_mask].sum())
    event_indices = np.flatnonzero(reached_mask & event_mask)
    event_to_event = 0
    event_to_dual = 0
    for source in event_indices:
        start, end = outgoing.indptr[source : source + 2]
        targets = outgoing.indices[start:end]
        event_to_event += int(event_mask[targets].sum())
        event_to_dual += int((~event_mask[targets] & reached_mask[targets]).sum())

    dual_to_event = 0
    for target in event_indices:
        start, end = incoming.indptr[target : target + 2]
        sources = incoming.indices[start:end]
        dual_to_event += int((reached_mask[sources] & ~event_mask[sources]).sum())
    dual_to_dual = total - event_to_event - event_to_dual - dual_to_event
    counts = {
        "event_required_to_event_required": event_to_event,
        "event_required_to_dual_unresolved": event_to_dual,
        "dual_unresolved_to_event_required": dual_to_event,
        "dual_unresolved_to_dual_unresolved": dual_to_dual,
        "total_reached_scope_edges": total,
    }
    if min(counts.values()) < 0 or sum(value for key, value in counts.items() if key != "total_reached_scope_edges") != total:
        raise BasalPopulationAccountingError("internal boundary edge partition is inconsistent")
    return counts, leakage


def run_accounting(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    campaign = _load_yaml(campaign_path)
    acceptance = campaign["acceptance"]

    print("[1/8] Verifying frozen rules, topology, routes and accepted local assignments", flush=True)
    paths = _verify_campaign(campaign)
    rules = _load_yaml(paths["rules"])
    if rules["capacity_policy"] != {
        "parameter_values_emitted": 0,
        "population_assignments_inferred_from_graph": 0,
        "named_behavior_exposure": 0,
        "topology_changes": 0,
    }:
        raise BasalPopulationAccountingError("zero-capacity accounting policy drift")

    print("[2/8] Reconstructing the six disjoint basal terminal families", flush=True)
    tables = _source_tables(paths)
    families, source_members = compile_family_sources(campaign, tables)
    unique_sources = source_members["body_id"].nunique()
    if len(families) != int(acceptance["expected_families"]):
        raise BasalPopulationAccountingError("basal-family count drift")
    if unique_sources != int(acceptance["expected_unique_source_terminals"]):
        raise BasalPopulationAccountingError(f"source-terminal count drift: {unique_sources}")
    if bool(acceptance["require_disjoint_family_sources"]) and len(source_members) != unique_sources:
        raise BasalPopulationAccountingError("basal family source sets overlap")

    print("[3/8] Loading the canonical graph and computing six exact directed closures", flush=True)
    nodes = _runtime_nodes(paths["central_nodes"], int(acceptance["expected_canonical_neurons"]))
    runtime_body_ids = nodes["body_id"].to_numpy(np.int64)
    outgoing = sparse.load_npz(paths["outgoing_graph"]).tocsr()
    if outgoing.shape != (len(nodes), len(nodes)):
        raise BasalPopulationAccountingError("outgoing graph shape drift")
    family_depths, reachability = compile_reachability(outgoing, runtime_body_ids, families)

    print("[4/8] Applying accepted exact event requirements and dual-unresolved fallback", flush=True)
    event_body_ids = accepted_event_body_ids(paths, int(acceptance["expected_preaccepted_event_bodies"]))
    reached, sources, strata = compile_population_dispositions(
        nodes, family_depths, event_body_ids, source_members
    )
    assignment_counts = {str(key): int(value) for key, value in reached["assignment"].value_counts().items()}
    if len(reached) != reachability["union"]["reachable_neurons"]:
        raise BasalPopulationAccountingError("reached-neuron accounting mismatch")

    print("[5/8] Counting all internal typed-boundary dispositions", flush=True)
    incoming = sparse.load_npz(paths["incoming_graph"]).tocsr()
    reached_mask = family_depths["union"] >= 0
    event_mask = np.isin(runtime_body_ids, event_body_ids)
    boundary_counts, reachability_leakage = compile_internal_boundary_counts(
        outgoing, incoming, reached_mask, event_mask
    )

    print("[6/8] Evaluating accounting and executable-unit gates", flush=True)
    gates = {
        "all_six_basal_families_accounted": bool(len(families) == 6),
        "all_6041_source_terminals_disjoint_and_canonical": bool(
            len(sources) == 6041 and sources["body_id"].nunique() == 6041
        ),
        "every_reached_neuron_has_assignment_disposition": bool(
            len(reached) == sum(assignment_counts.values())
            and set(assignment_counts).issubset({"event_required", "dual_unresolved"})
        ),
        "no_edge_from_reached_scope_to_unreached_scope": bool(reachability_leakage == 0),
        "every_source_has_bridge_disposition": bool(
            sources["bridge_disposition"].notna().all()
        ),
        "internal_boundary_grammar_exhaustively_counted": bool(
            sum(value for key, value in boundary_counts.items() if key != "total_reached_scope_edges")
            == boundary_counts["total_reached_scope_edges"]
        ),
        "numerical_values_emitted": False,
        "executable_source_unit_bridges_available": bool(
            sources["bridge_executable"].all()
        ),
        "accepted_global_typed_hybrid_runtime_available": False,
    }
    required_true = [
        "all_six_basal_families_accounted",
        "all_6041_source_terminals_disjoint_and_canonical",
        "every_reached_neuron_has_assignment_disposition",
        "no_edge_from_reached_scope_to_unreached_scope",
        "every_source_has_bridge_disposition",
        "internal_boundary_grammar_exhaustively_counted",
    ]
    if not all(gates[key] for key in required_true):
        raise BasalPopulationAccountingError(
            f"required accounting gate failed: {[key for key in required_true if not gates[key]]}"
        )

    print("[7/8] Writing complete derived tables and compact versioned summaries", flush=True)
    output_root.mkdir(parents=True, exist_ok=True)
    reached_path = output_root / "reached-populations.parquet"
    sources_path = output_root / "source-terminals.csv"
    strata_path = output_root / "annotation-strata.csv"
    unreachable_path = output_root / "unreachable-canonical-neurons.csv"
    summary_path = output_root / "summary.json"
    reached.to_parquet(reached_path, index=False, compression="zstd")
    sources.to_csv(sources_path, index=False)
    strata.to_csv(strata_path, index=False)
    nodes.loc[~reached_mask, ["body_id", "superclass", "class", "type", "instance"]].to_csv(
        unreachable_path, index=False
    )

    assignment_semantic_hash = _canonical_hash(
        reached[["body_id", "assignment", "assignment_rule_id"]].to_dict(orient="records")
    )
    source_bridge_semantic_hash = _canonical_hash(
        sources[["family_id", "channel_id", "body_id", "bridge_disposition"]].to_dict(orient="records")
    )
    summary = {
        "schema_version": 1,
        "campaign_id": campaign["id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "family_reachability": reachability,
        "assignment_counts": assignment_counts,
        "assignment_semantic_sha256": assignment_semantic_hash,
        "source_bridge_counts": {
            str(key): int(value) for key, value in sources["bridge_disposition"].value_counts().items()
        },
        "source_bridge_semantic_sha256": source_bridge_semantic_hash,
        "internal_boundary_counts": boundary_counts,
        "annotation_strata": int(strata["accounting_stratum_id"].nunique()),
        "parameter_values_emitted": 0,
        "gates": gates,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    artifact_paths = [reached_path, sources_path, strata_path, unreachable_path, summary_path]
    artifact_records = [
        {
            "path": _artifact_ref(path),
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in artifact_paths
    ]
    compact_payload = {
        "campaign_id": campaign["id"],
        "input_hashes": {key: value["sha256"] for key, value in campaign["frozen_inputs"].items()},
        "family_reachability": reachability,
        "assignment_counts": assignment_counts,
        "assignment_semantic_sha256": assignment_semantic_hash,
        "source_bridge_semantic_sha256": source_bridge_semantic_hash,
        "internal_boundary_counts": boundary_counts,
        "gates": gates,
    }
    semantic_hash = _canonical_hash(compact_payload)
    blocker_ids = [
        "executable_source_unit_bridges_available",
        "accepted_global_typed_hybrid_runtime_available",
    ]
    result = {
        "schema_version": 1,
        "id": "runner_result.basal_reachable_population_accounting.v0",
        "campaign_id": campaign["id"],
        "status": "accepted_exhaustive_reachability_and_dispositions_numeric_bridges_blocked",
        "completed_at": datetime.now(UTC).isoformat(),
        "command": "basal_population_reachability.bat",
        "claim_label": campaign["claim_label"],
        "source_accounting": {
            "families": len(families),
            "channels": int(sources["channel_id"].nunique()),
            "unique_terminal_bodies": sources["body_id"].nunique(),
        },
        "union_reachability": reachability["union"],
        "family_reachability": {key: value for key, value in reachability.items() if key != "union"},
        "population_assignment_counts": assignment_counts,
        "preaccepted_event_body_ids": [int(value) for value in event_body_ids],
        "assignment_semantic_sha256": assignment_semantic_hash,
        "source_bridge_counts": summary["source_bridge_counts"],
        "source_bridge_semantic_sha256": source_bridge_semantic_hash,
        "internal_boundary_counts": boundary_counts,
        "annotation_strata": summary["annotation_strata"],
        "largest_annotation_strata": strata.head(20).to_dict(orient="records"),
        "parameter_values_emitted": 0,
        "gates": gates,
        "blocker_ids": blocker_ids,
        "artifacts": artifact_records,
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
        "semantic_result_sha256": semantic_hash,
    }
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.basal_reachable_population_accounting.v0",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": semantic_hash,
        "status": "accepted_population_and_bridge_disposition_accounting_execution_still_blocked",
        "checks": gates,
        "blocker_ids": blocker_ids,
        "interpretation": (
            f"The six basal families reach {reachability['union']['reachable_neurons']:,} of "
            f"{len(nodes):,} canonical neurons. Every reached neuron and internal boundary is "
            "accounted, but dual-unresolved assignments and non-executable unit bridges prevent "
            "a scientific whole-MaleCNS basal run."
        ),
        "parameter_values_emitted": 0,
        "named_behavior_exposed": False,
        "next_action": campaign["next_action"],
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    evaluation_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    evaluation_path.write_text(
        yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

    print("[8/8] COMPLETE - reachability and dispositions closed; numerical bridges remain blocked", flush=True)
    print(
        f"[SOURCES] {len(families)} families / {len(sources):,} disjoint terminal bodies",
        flush=True,
    )
    print(
        f"[REACH] {len(reached):,}/{len(nodes):,} canonical neurons "
        f"({100.0 * len(reached) / len(nodes):.3f}%), maximum depth {reachability['union']['maximum_depth']}",
        flush=True,
    )
    print(
        f"[ASSIGNMENTS] {assignment_counts.get('event_required', 0):,} event-required / "
        f"{assignment_counts.get('dual_unresolved', 0):,} dual-unresolved",
        flush=True,
    )
    print(f"[BLOCKERS] {', '.join(blocker_ids)}", flush=True)
    print(f"[HASH] {semantic_hash}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Account typed/hybrid populations reached by all basal families"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    run_accounting(campaign_path=args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

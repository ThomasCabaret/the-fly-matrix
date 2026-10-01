from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pyarrow as pa
import yaml

from .central_graph import _locate, classify_population_scope
from .ledger import ROOT


RECIPE_PATH = ROOT / "calibration" / "evidence" / "transmitter-sign-prior-v0.yaml"


class EvidenceCompilationError(ValueError):
    """Raised when evidence inputs or derived accounting violate the recipe."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_recipe(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvidenceCompilationError(f"{path} must contain a YAML mapping")
    return value


def _source_path(recipe: Mapping[str, Any], key: str) -> Path:
    return ROOT / recipe["sources"][key]["path"]


def _normalized_text(series: pd.Series, missing: str = "") -> pd.Series:
    return series.fillna(missing).astype(str).str.strip().str.lower()


def compile_neuron_priors(
    annotations: pd.DataFrame,
    transmitters: pd.DataFrame,
    sign_rules: Mapping[str, Mapping[str, Any]],
) -> pd.DataFrame:
    """Compile one auditable prior row per canonical neuron without fitting values."""
    required_annotations = {"bodyId", "superclass", "status"}
    required_transmitters = {
        "body",
        "cell_type",
        "total_nt_predictions",
        "predicted_nt_confidence",
        "predicted_nt",
        "ground_truth",
        "celltype_total_nt_predictions",
        "celltype_predicted_nt",
        "celltype_predicted_nt_confidence",
        "consensus_nt",
    }
    if missing := required_annotations - set(annotations):
        raise EvidenceCompilationError(f"Missing annotation columns: {sorted(missing)}")
    if missing := required_transmitters - set(transmitters):
        raise EvidenceCompilationError(f"Missing transmitter columns: {sorted(missing)}")
    if annotations["bodyId"].duplicated().any():
        raise EvidenceCompilationError("Annotation bodyId values must be unique")
    if transmitters["body"].duplicated().any():
        raise EvidenceCompilationError("Transmitter body values must be unique")

    ordered = annotations.sort_values("bodyId").reset_index(drop=True)
    classified = classify_population_scope(ordered)
    canonical = classified.loc[
        classified["is_canonical_neuron"], ["bodyId", "runtime_node_index"]
    ].copy()
    canonical = canonical.rename(columns={"bodyId": "body_id"})
    source = transmitters.rename(columns={"body": "body_id"}).copy()
    result = canonical.merge(source, on="body_id", how="left", validate="one_to_one")
    result["source_record_present"] = result["consensus_nt"].notna()

    ground_truth = _normalized_text(result["ground_truth"])
    consensus = _normalized_text(result["consensus_nt"], missing="missing")
    predicted = _normalized_text(result["predicted_nt"])
    celltype_predicted = _normalized_text(result["celltype_predicted_nt"])
    has_ground_truth = ground_truth.ne("")

    effective_label = consensus.copy()
    effective_label.loc[has_ground_truth] = ground_truth.loc[has_ground_truth]
    effective_label.loc[~result["source_record_present"]] = "missing"
    result["effective_transmitter"] = effective_label

    origin = np.full(len(result), "source_consensus_other_rule", dtype=object)
    origin[~result["source_record_present"].to_numpy()] = "missing_record"
    origin[(result["source_record_present"] & effective_label.eq("unclear")).to_numpy()] = (
        "unresolved_source_consensus"
    )
    origin[has_ground_truth.to_numpy()] = "source_curated_ground_truth"
    no_gt_clear = result["source_record_present"] & ~has_ground_truth & effective_label.ne(
        "unclear"
    )
    matches_neuron = no_gt_clear & effective_label.eq(predicted)
    matches_celltype = no_gt_clear & effective_label.eq(celltype_predicted)
    origin[(matches_neuron & matches_celltype).to_numpy()] = (
        "neuron_and_cell_type_prediction"
    )
    origin[(matches_neuron & ~matches_celltype).to_numpy()] = "neuron_prediction"
    origin[(~matches_neuron & matches_celltype).to_numpy()] = "cell_type_prediction"
    result["evidence_origin"] = origin

    support_confidence = np.full(len(result), np.nan, dtype=np.float64)
    neuron_confidence = result["predicted_nt_confidence"].to_numpy(dtype=np.float64)
    celltype_confidence = result["celltype_predicted_nt_confidence"].to_numpy(
        dtype=np.float64
    )
    both = matches_neuron & matches_celltype
    both_values = np.vstack([neuron_confidence, celltype_confidence])
    conservative = np.fmin(both_values[0], both_values[1])
    support_confidence[both.to_numpy()] = conservative[both.to_numpy()]
    support_confidence[(matches_neuron & ~matches_celltype).to_numpy()] = neuron_confidence[
        (matches_neuron & ~matches_celltype).to_numpy()
    ]
    support_confidence[(~matches_neuron & matches_celltype).to_numpy()] = celltype_confidence[
        (~matches_neuron & matches_celltype).to_numpy()
    ]
    result["support_confidence"] = support_confidence

    unknown_labels = sorted(set(effective_label) - set(sign_rules))
    if unknown_labels:
        raise EvidenceCompilationError(f"Sign policy omits labels: {unknown_labels}")
    result["sign_code"] = effective_label.map(
        {label: int(rule["code"]) for label, rule in sign_rules.items()}
    ).astype(np.int8)
    result["sign_interpretation"] = effective_label.map(
        {label: str(rule["interpretation"]) for label, rule in sign_rules.items()}
    )
    result["sign_asserted"] = result["sign_code"].ne(0)

    ordered_columns = [
        "body_id",
        "runtime_node_index",
        "source_record_present",
        "cell_type",
        "total_nt_predictions",
        "predicted_nt",
        "predicted_nt_confidence",
        "ground_truth",
        "celltype_total_nt_predictions",
        "celltype_predicted_nt",
        "celltype_predicted_nt_confidence",
        "consensus_nt",
        "effective_transmitter",
        "evidence_origin",
        "support_confidence",
        "sign_code",
        "sign_interpretation",
        "sign_asserted",
    ]
    return result[ordered_columns].sort_values("runtime_node_index").reset_index(drop=True)


def _semantic_hash(frame: pd.DataFrame) -> str:
    semantic = frame.copy()
    for column in semantic.select_dtypes(include=["object", "string"]).columns:
        semantic[column] = semantic[column].fillna("(missing)").astype(str)
    values = pd.util.hash_pandas_object(semantic, index=False).to_numpy(dtype="uint64")
    return hashlib.sha256(values.astype("<u8", copy=False).tobytes()).hexdigest()


def _edge_accounting(
    weight_path: Path, body_ids: np.ndarray, sign_codes: np.ndarray
) -> dict[str, Any]:
    edge_counts: Counter[int] = Counter()
    synapse_weights: Counter[int] = Counter()
    runtime_edges = 0
    runtime_weight = 0
    with pa.memory_map(str(weight_path), "r") as mapped:
        reader = pa.ipc.open_file(mapped)
        for batch_index in range(reader.num_record_batches):
            batch = reader.get_batch(batch_index)
            pre = batch.column(0).to_numpy()
            post = batch.column(1).to_numpy()
            weights = batch.column(2).to_numpy().astype(np.int64, copy=False)
            pre_indices, pre_valid = _locate(body_ids, pre)
            _, post_valid = _locate(body_ids, post)
            selected = pre_valid & post_valid
            if selected.any():
                selected_codes = sign_codes[pre_indices[selected]]
                selected_weights = weights[selected]
                runtime_edges += int(selected.sum())
                runtime_weight += int(selected_weights.sum())
                for code in (-1, 0, 1):
                    mask = selected_codes == code
                    edge_counts[code] += int(mask.sum())
                    synapse_weights[code] += int(selected_weights[mask].sum())
            if (batch_index + 1) % 500 == 0 or batch_index + 1 == reader.num_record_batches:
                print(
                    f"[INFO] Edge accounting {batch_index + 1:,}/{reader.num_record_batches:,} batches; "
                    f"{runtime_edges:,} runtime edges",
                    flush=True,
                )
    labels = {-1: "inhibitory_prior", 0: "unknown_or_context_dependent", 1: "excitatory_prior"}
    return {
        "runtime_edges": runtime_edges,
        "runtime_synapse_weight": runtime_weight,
        "edge_counts_by_prior": {labels[code]: edge_counts[code] for code in (-1, 0, 1)},
        "synapse_weight_by_prior": {
            labels[code]: synapse_weights[code] for code in (-1, 0, 1)
        },
    }


def build_transmitter_sign_prior(
    recipe_path: Path = RECIPE_PATH,
    output_root: Path | None = None,
    *,
    account_edges: bool = True,
) -> dict[str, Any]:
    recipe = _load_recipe(recipe_path)
    annotation_path = _source_path(recipe, "annotations")
    transmitter_path = _source_path(recipe, "neurotransmitters")
    weight_path = _source_path(recipe, "connectome_weights")
    output_root = output_root or ROOT / recipe["outputs"]["root"]

    print("\n==> Source validation", flush=True)
    source_hashes: dict[str, str] = {}
    for key, path in (
        ("annotations", annotation_path),
        ("neurotransmitters", transmitter_path),
        ("connectome_weights", weight_path),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"Missing source: {path}")
        observed = _sha256_file(path)
        expected = recipe["sources"][key]["sha256"]
        if observed != expected:
            raise EvidenceCompilationError(
                f"{key} source hash mismatch: expected {expected}, got {observed}"
            )
        source_hashes[key] = observed
        print(f"[OK] {key}: {observed[:12]}...", flush=True)

    print("\n==> Canonical neuron evidence", flush=True)
    annotations = pd.read_feather(
        annotation_path, columns=["bodyId", "superclass", "status"]
    )
    transmitters = pd.read_feather(transmitter_path)
    frame = compile_neuron_priors(
        annotations, transmitters, recipe["typed_sign_prior"]["mappings"]
    )
    population = recipe["population"]
    matched = int(frame["source_record_present"].sum())
    if len(frame) != int(population["expected_canonical_neurons"]):
        raise EvidenceCompilationError(f"Unexpected canonical count: {len(frame)}")
    if matched != int(population["expected_transmitter_rows_in_scope"]):
        raise EvidenceCompilationError(f"Unexpected matched transmitter count: {matched}")
    if len(frame) - matched != int(population["expected_missing_records"]):
        raise EvidenceCompilationError("Unexpected missing transmitter-record count")
    print(
        f"[OK] {len(frame):,} canonical neurons; {matched:,} source records; "
        f"{len(frame) - matched:,} explicitly missing",
        flush=True,
    )

    edge_accounting: dict[str, Any] | None = None
    if account_edges:
        print("\n==> Runtime-edge sign-prior coverage", flush=True)
        edge_accounting = _edge_accounting(
            weight_path,
            frame["body_id"].to_numpy(dtype=np.int64),
            frame["sign_code"].to_numpy(dtype=np.int8),
        )
        if edge_accounting["runtime_edges"] != int(population["expected_runtime_edges"]):
            raise EvidenceCompilationError("Unexpected runtime edge count")
        if edge_accounting["runtime_synapse_weight"] != int(
            population["expected_runtime_synapse_weight"]
        ):
            raise EvidenceCompilationError("Unexpected runtime synapse weight")
        print(
            f"[OK] {edge_accounting['runtime_edges']:,} runtime edges exhaustively classified",
            flush=True,
        )

    print("\n==> Derived artifacts", flush=True)
    output_root.mkdir(parents=True, exist_ok=True)
    neuron_path = output_root / recipe["outputs"]["neuron_table"]
    arrays_path = output_root / recipe["outputs"]["runtime_arrays"]
    summary_path = output_root / recipe["outputs"]["summary"]
    frame.to_parquet(neuron_path, index=False, compression="zstd")
    np.savez_compressed(
        arrays_path,
        body_ids=frame["body_id"].to_numpy(dtype=np.int64),
        sign_codes=frame["sign_code"].to_numpy(dtype=np.int8),
        support_confidence=frame["support_confidence"].to_numpy(dtype=np.float32),
    )

    label_counts = {
        str(key): int(value)
        for key, value in frame["effective_transmitter"].value_counts().sort_index().items()
    }
    origin_counts = {
        str(key): int(value)
        for key, value in frame["evidence_origin"].value_counts().sort_index().items()
    }
    interpretation_counts = {
        str(key): int(value)
        for key, value in frame["sign_interpretation"].value_counts().sort_index().items()
    }
    for label, observed, expected in (
        ("label", label_counts, population["expected_label_counts"]),
        (
            "evidence origin",
            origin_counts,
            population["expected_evidence_origin_counts"],
        ),
        (
            "sign interpretation",
            interpretation_counts,
            population["expected_sign_interpretation_counts"],
        ),
    ):
        if observed != expected:
            raise EvidenceCompilationError(
                f"Unexpected {label} accounting: expected {expected}, got {observed}"
            )
    if edge_accounting is not None:
        if edge_accounting["edge_counts_by_prior"] != population[
            "expected_edge_counts_by_prior"
        ]:
            raise EvidenceCompilationError("Unexpected runtime edge prior distribution")
        if edge_accounting["synapse_weight_by_prior"] != population[
            "expected_synapse_weight_by_prior"
        ]:
            raise EvidenceCompilationError("Unexpected runtime synapse-weight distribution")
    summary: dict[str, Any] = {
        "schema_version": 1,
        "recipe_id": recipe["id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "claim_label": "EVIDENCE TRANSFER / TYPED PRIOR / NOT CALIBRATED DYNAMICS",
        "source_hashes": source_hashes,
        "recipe_sha256": _sha256_file(recipe_path),
        "semantic_prior_sha256": _semantic_hash(frame),
        "canonical_neurons": len(frame),
        "source_records_in_scope": matched,
        "missing_source_records": len(frame) - matched,
        "label_counts": label_counts,
        "evidence_origin_counts": origin_counts,
        "sign_interpretation_counts": interpretation_counts,
        "numeric_support_confidence_count": int(frame["support_confidence"].notna().sum()),
        "source_ground_truth_confidence_policy": "unquantified_preserved_as_null",
        "zero_sign_code_semantics": "no_sign_assertion_not_zero_synaptic_effect",
        "edge_accounting": edge_accounting,
        "outputs": {
            "neuron_table": str(neuron_path.relative_to(ROOT)).replace("\\", "/"),
            "neuron_table_sha256": _sha256_file(neuron_path),
            "runtime_arrays": str(arrays_path.relative_to(ROOT)).replace("\\", "/"),
            "runtime_arrays_sha256": _sha256_file(arrays_path),
        },
        "accepted_claims": recipe["accepted_claims"],
        "forbidden_claims": recipe["forbidden_claims"],
        "known_limitations": recipe["known_limitations"],
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[OK] {neuron_path}", flush=True)
    print(f"[OK] {arrays_path}", flush=True)
    print(f"[OK] {summary_path}", flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile MaleCNS transmitter evidence into typed sign priors"
    )
    parser.add_argument("--recipe", type=Path, default=RECIPE_PATH)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--skip-edge-accounting", action="store_true")
    args = parser.parse_args()
    try:
        summary = build_transmitter_sign_prior(
            args.recipe,
            args.output_root,
            account_edges=not args.skip_edge_accounting,
        )
    except Exception as exc:
        print(f"\nCALIBRATION_EVIDENCE_FAILED: {type(exc).__name__}: {exc}")
        return 1
    print(
        "\nCALIBRATION_EVIDENCE_OK: "
        f"{summary['canonical_neurons']:,} neurons, "
        f"semantic hash {summary['semantic_prior_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

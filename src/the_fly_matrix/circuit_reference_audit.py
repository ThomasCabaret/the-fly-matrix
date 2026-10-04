from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
import pyarrow.ipc as ipc
import yaml

from .central_graph import classify_population_scope
from .ledger import ROOT


RECIPE_PATH = (
    ROOT / "calibration" / "evidence" / "antennal-grooming-circuit-transferability-v0.yaml"
)
OUTPUT_ROOT = (
    ROOT / "data" / "derived" / "calibration" / "antennal-grooming-circuit-transferability-v0"
)
RESULT_PATH = (
    ROOT / "calibration" / "runner" / "antennal-grooming-circuit-transferability-result-v0.yaml"
)


class CircuitReferenceAuditError(ValueError):
    """Raised when the circuit reference cannot be audited deterministically."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_recipe(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise CircuitReferenceAuditError("Circuit reference recipe must be schema_version 1")
    if value.get("status") != "runnable_mapping_audit":
        raise CircuitReferenceAuditError("Circuit reference recipe is not runnable")
    return value


def _verify_inputs(recipe: Mapping[str, Any], root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for item in recipe["input_files"]:
        relative = str(item["path"])
        path = root / relative
        if not path.is_file():
            raise CircuitReferenceAuditError(
                f"Missing input {relative}; obtain it from {item['source_url']}"
            )
        actual = _sha256(path)
        if actual != str(item["sha256"]):
            raise CircuitReferenceAuditError(
                f"Input hash drift for {relative}: expected {item['sha256']}, got {actual}"
            )
        hashes[relative] = actual
    return hashes


def _workbook_identity_audit(
    workbook_path: Path, reference: Mapping[str, Any]
) -> dict[str, Any]:
    frame = pd.read_excel(workbook_path, sheet_name=str(reference["workbook_sheet"]))
    names = frame["Neuron Names"].fillna("").astype(str).str.strip()
    ids = frame["flyid"].astype("Int64")
    named_jon_count = int(names.str.startswith("JO_").sum())
    expected_jon_count = int(reference["expected_named_jon_rows_in_workbook"])
    if named_jon_count != expected_jon_count:
        raise CircuitReferenceAuditError(
            f"Workbook JON row drift: expected {expected_jon_count}, got {named_jon_count}"
        )
    named_cells: dict[str, int] = {}
    for name, expected_id in reference["expected_named_cells"].items():
        found = ids.loc[names.eq(str(name))].dropna().astype("int64").unique().tolist()
        if found != [int(expected_id)]:
            raise CircuitReferenceAuditError(
                f"Workbook identity mismatch for {name}: expected {expected_id}, got {found}"
            )
        named_cells[str(name)] = int(found[0])
    return {
        "named_jon_rows": named_jon_count,
        "paper_declared_jon_count": int(reference["paper_declared_jon_count"]),
        "declared_minus_named_rows": int(reference["paper_declared_jon_count"])
        - named_jon_count,
        "named_cells": named_cells,
    }


def _flywire_identity_audit(
    annotation_path: Path, reference: Mapping[str, Any]
) -> dict[str, Any]:
    frame = pd.read_csv(annotation_path, sep="\t", low_memory=False)
    rows_by_id = frame.set_index("root_id", drop=False)
    result: dict[str, Any] = {}
    for group, spec in reference["pinned_flywire_cells"].items():
        root_ids = [int(value) for value in spec["root_ids"]]
        expected_types = [str(value) for value in spec["expected_types"]]
        if len(root_ids) != len(expected_types):
            raise CircuitReferenceAuditError(f"{group}: root/type cardinality mismatch")
        observed_types: list[str] = []
        records: list[dict[str, Any]] = []
        for root_id in root_ids:
            if root_id not in rows_by_id.index:
                raise CircuitReferenceAuditError(f"FlyWire root {root_id} is absent")
            row = rows_by_id.loc[root_id]
            if isinstance(row, pd.DataFrame):
                raise CircuitReferenceAuditError(f"FlyWire root {root_id} is not unique")
            cell_type = str(row["cell_type"])
            observed_types.append(cell_type)
            records.append(
                {
                    "root_id": root_id,
                    "cell_type": cell_type,
                    "ito_lee_hemilineage": str(row["ito_lee_hemilineage"]),
                    "hartenstein_hemilineage": str(row["hartenstein_hemilineage"]),
                    "side": str(row["side"]),
                }
            )
        if observed_types != expected_types:
            raise CircuitReferenceAuditError(
                f"FlyWire type drift for {group}: expected {expected_types}, got {observed_types}"
            )
        result[str(group)] = {"records": records, "types": observed_types}
    return result


def _type_tokens(value: Any) -> set[str]:
    if pd.isna(value):
        return set()
    return {item.strip() for item in str(value).split(",") if item.strip()}


def _malecns_mapping_audit(
    annotation_path: Path,
    selection: Mapping[str, Any],
    flywire: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, set[int]]]:
    frame = classify_population_scope(pd.read_feather(annotation_path))
    canonical = frame.loc[frame["is_canonical_neuron"]].copy()
    canonical_ids = set(canonical["bodyId"].astype("int64"))
    prefixes = tuple(str(value) for value in selection["jon_type_prefixes"])
    jon = canonical.loc[canonical["type"].fillna("").astype(str).str.startswith(prefixes)]
    expected_jons = int(selection["expected_jon_count"])
    if len(jon) != expected_jons:
        raise CircuitReferenceAuditError(
            f"MaleCNS JON count drift: expected {expected_jons}, got {len(jon)}"
        )

    tokens = canonical["flywireType"].map(_type_tokens)
    expected_counts = {
        str(key): int(value) for key, value in selection["expected_type_match_counts"].items()
    }
    type_body_ids: dict[str, set[int]] = {}
    for cell_type, expected_count in expected_counts.items():
        mask = tokens.map(lambda values, target=cell_type: target in values) | canonical[
            "type"
        ].fillna("").astype(str).eq(cell_type)
        body_ids = set(canonical.loc[mask, "bodyId"].astype("int64"))
        if len(body_ids) != expected_count:
            raise CircuitReferenceAuditError(
                f"MaleCNS type count drift for {cell_type}: expected {expected_count}, got {len(body_ids)}"
            )
        type_body_ids[cell_type] = body_ids

    groups = {
        "jon": set(jon["bodyId"].astype("int64")),
        "aBN1": set().union(*(type_body_ids[t] for t in flywire["aBN1"]["types"])),
        "aBN2_resolved_subset": set().union(
            *(type_body_ids[t] for t in flywire["aBN2"]["types"] if type_body_ids[t])
        ),
        "aDN1": set().union(*(type_body_ids[t] for t in flywire["aDN1"]["types"])),
        "aDN2": set().union(*(type_body_ids[t] for t in flywire["aDN2"]["types"])),
    }
    expected_groups = {
        str(key): int(value) for key, value in selection["expected_unique_group_counts"].items()
    }
    for group, expected_count in expected_groups.items():
        if len(groups[group]) != expected_count:
            raise CircuitReferenceAuditError(
                f"MaleCNS group count drift for {group}: expected {expected_count}, got {len(groups[group])}"
            )
    if any(not values <= canonical_ids for values in groups.values()):
        raise CircuitReferenceAuditError("A selected circuit body is not a canonical neuron")

    aBN2_types = flywire["aBN2"]["types"]
    missing_aBN2_types = [value for value in aBN2_types if not type_body_ids[value]]
    result = {
        "canonical_neuron_count": int(len(canonical)),
        "jon_prefixes": list(prefixes),
        "type_match_counts": {key: len(value) for key, value in type_body_ids.items()},
        "group_counts": {key: len(value) for key, value in groups.items()},
        "group_body_ids": {key: sorted(value) for key, value in groups.items()},
        "missing_abn2_types": missing_aBN2_types,
        "abn2_source_type_coverage": {
            "resolved": len(aBN2_types) - len(missing_aBN2_types),
            "total": len(aBN2_types),
        },
    }
    return result, groups


def _scan_relations(edge_path: Path, groups: Mapping[str, set[int]]) -> dict[str, Any]:
    relations = {
        "jon_to_abn1": (groups["jon"], groups["aBN1"]),
        "jon_to_abn2_resolved_subset": (groups["jon"], groups["aBN2_resolved_subset"]),
        "abn1_to_adn": (groups["aBN1"], groups["aDN1"] | groups["aDN2"]),
        "abn2_resolved_subset_to_adn": (
            groups["aBN2_resolved_subset"],
            groups["aDN1"] | groups["aDN2"],
        ),
    }
    counts = {key: {"edges": 0, "synaptic_contacts": 0} for key in relations}
    reader = ipc.open_file(edge_path)
    for index in range(reader.num_record_batches):
        batch = reader.get_batch(index)
        pre = batch.column(batch.schema.get_field_index("body_pre")).to_numpy()
        post = batch.column(batch.schema.get_field_index("body_post")).to_numpy()
        weight = batch.column(batch.schema.get_field_index("weight")).to_numpy()
        for relation, (source_ids, target_ids) in relations.items():
            mask = np.isin(pre, list(source_ids)) & np.isin(post, list(target_ids))
            counts[relation]["edges"] += int(mask.sum())
            counts[relation]["synaptic_contacts"] += int(weight[mask].sum())
    return counts


def audit_circuit_reference(
    recipe_path: Path = RECIPE_PATH,
    output_root: Path = OUTPUT_ROOT,
    result_path: Path = RESULT_PATH,
    *,
    root: Path = ROOT,
    scan_connectivity: bool = True,
) -> dict[str, Any]:
    recipe = _load_recipe(recipe_path)
    print("[1/5] Vérification des quatre sources et de leurs hashes", flush=True)
    input_hashes = _verify_inputs(recipe, root)
    paths = {Path(item["path"]).name: root / item["path"] for item in recipe["input_files"]}

    print("[2/5] Contrôle des identités publiées dans FlyWire", flush=True)
    workbook = _workbook_identity_audit(
        paths["shiu-2024-supplementary-tables.xlsx"], recipe["source_reference"]
    )
    flywire = _flywire_identity_audit(
        paths["flywire-neuron-annotations-a83b277.tsv"], recipe["source_reference"]
    )
    print(
        f"      {workbook['named_jon_rows']} JON nommés dans la table "
        f"pour {workbook['paper_declared_jon_count']} annoncés dans l'article",
        flush=True,
    )

    print("[3/5] Projection des types sur les neurones canoniques MaleCNS", flush=True)
    malecns, groups = _malecns_mapping_audit(
        paths["body-annotations-male-cns-v1.0-minconf-0.5.feather"],
        recipe["malecns_selection"],
        flywire,
    )
    print(
        f"      aBN1={malecns['group_counts']['aBN1']}; "
        f"aBN2 résolus={malecns['group_counts']['aBN2_resolved_subset']}; "
        f"aDN={malecns['group_counts']['aDN1'] + malecns['group_counts']['aDN2']}",
        flush=True,
    )

    print("[4/5] Vérification des chemins structuraux MaleCNS", flush=True)
    relations: dict[str, Any] = {}
    if scan_connectivity:
        relations = _scan_relations(
            paths["connectome-weights-male-cns-v1.0-minconf-0.5.feather"], groups
        )
        for relation in recipe["acceptance"]["require_nonzero_structural_relations"]:
            if relations[str(relation)]["edges"] <= 0:
                raise CircuitReferenceAuditError(
                    f"Required structural relation is empty: {relation}"
                )
            print(
                f"      {relation}: {relations[str(relation)]['edges']} arêtes / "
                f"{relations[str(relation)]['synaptic_contacts']} contacts",
                flush=True,
            )
    else:
        print("      [SKIP] Scan des arêtes désactivé pour ce run", flush=True)

    status = "partial_mapping_abn2_unresolved"
    if status != recipe["acceptance"]["expected_transfer_status"]:
        raise CircuitReferenceAuditError("Unexpected transfer status")
    semantic_payload = {
        "recipe_id": recipe["id"],
        "input_hashes": input_hashes,
        "workbook": workbook,
        "flywire": flywire,
        "malecns": malecns,
        "relations": relations,
        "status": status,
    }
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "recipe_id": recipe["id"],
        "claim_label": recipe["claim_label"],
        "status": status,
        "semantic_result_sha256": _canonical_hash(semantic_payload),
        **semantic_payload,
        "accepted_claims": [
            "aBN1, aDN1 and aDN2 have exact systematic type matches in MaleCNS.",
            "Two of the three pinned aBN2 FlyWire types have a MaleCNS candidate subset.",
            "The mapped MaleCNS subsets participate in the required structural circuit relations."
            if scan_connectivity
            else "Identity transfer was checked without a connectivity claim.",
        ],
        "forbidden_claims": [
            "The independent circuit reference is ready to score.",
            "CB3129 is absent biologically rather than unresolved in cross-connectome annotation.",
            "The rate or LIF model class is scientifically accepted.",
            "Antennal grooming emerged or was reproduced.",
        ],
        "behavior_exposure": recipe["behavior_exposure"],
        "next_action": recipe["next_action"],
    }
    print("[5/5] Écriture du résultat compact et du cache d'audit", flush=True)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    compact = {
        "schema_version": 1,
        "id": "runner_result.antennal_grooming_circuit_transferability.v0",
        "status": status,
        "claim_label": recipe["claim_label"],
        "semantic_result_sha256": summary["semantic_result_sha256"],
        "workbook_identity": workbook,
        "malecns_mapping": {
            key: value for key, value in malecns.items() if key != "group_body_ids"
        },
        "structural_relations": relations,
        "scientific_circuit_protocol_locked": False,
        "behavior_exposure": recipe["behavior_exposure"],
        "next_action": recipe["next_action"],
    }
    result_path.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")
    print(f"[PARTIEL] Types aBN2 absents/non résolus: {malecns['missing_abn2_types']}", flush=True)
    print(f"[HASH] {summary['semantic_result_sha256']}", flush=True)
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit the transferability of an independent FlyWire circuit reference"
    )
    parser.add_argument("--no-connectivity", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    audit_circuit_reference(scan_connectivity=not args.no_connectivity)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

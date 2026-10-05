from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow.ipc as ipc
import yaml

from .central_graph import classify_population_scope
from .circuit_reference_audit import RECIPE_PATH as TRANSFER_RECIPE_PATH, _verify_inputs
from .ledger import ROOT


PROTOCOL_PATH = ROOT / "calibration" / "evidence" / "antennal-abn1-model-class-reference-v1.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "antennal-abn1-reference-lock-v1.yaml"
OUTPUT_ROOT = ROOT / "data" / "derived" / "calibration" / "antennal-abn1-reference-lock-v1"


class Abn1ReferenceLockError(RuntimeError):
    """Raised when the pre-output protocol lock no longer matches its sources."""


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _git_head(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=path, text=True, encoding="utf-8"
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Abn1ReferenceLockError(f"Cannot read source checkout commit: {exc}") from exc


def _select_groups(protocol: dict[str, Any], annotation_path: Path) -> tuple[dict[str, Any], dict[str, set[int]]]:
    frame = classify_population_scope(pd.read_feather(annotation_path))
    canonical = frame.loc[frame["is_canonical_neuron"]].copy()
    cell_type = canonical["type"].fillna("").astype(str)
    groups: dict[str, set[int]] = {}
    for key in ("JO_CE", "JO_F"):
        prefixes = tuple(protocol["scope"]["source_groups"][key]["malecns_type_prefixes"])
        selected = canonical.loc[cell_type.str.startswith(prefixes), "bodyId"].astype("int64")
        groups[key] = set(int(x) for x in selected)
        expected = int(protocol["scope"]["source_groups"][key]["expected_malecns_count"])
        if len(groups[key]) != expected:
            raise Abn1ReferenceLockError(f"{key} count drift: expected {expected}, got {len(groups[key])}")
    target_type = str(protocol["scope"]["target_group"]["systematic_type"])
    target = canonical.loc[cell_type.eq(target_type), "bodyId"].astype("int64")
    groups["aBN1"] = set(int(x) for x in target)
    expected_target = int(protocol["scope"]["target_group"]["expected_malecns_count"])
    if len(groups["aBN1"]) != expected_target:
        raise Abn1ReferenceLockError(
            f"aBN1 count drift: expected {expected_target}, got {len(groups['aBN1'])}"
        )
    expected_ids = set(int(x) for x in protocol["malecns_structural_lock"]["aBN1_body_ids"])
    if groups["aBN1"] != expected_ids:
        raise Abn1ReferenceLockError(
            f"aBN1 identity drift: expected {sorted(expected_ids)}, got {sorted(groups['aBN1'])}"
        )
    return {
        "canonical_neurons": int(len(canonical)),
        "group_counts": {key: len(value) for key, value in groups.items()},
        "aBN1_body_ids": sorted(groups["aBN1"]),
    }, groups


def _scan_relations(edge_path: Path, groups: dict[str, set[int]]) -> dict[str, Any]:
    result = {
        "JO_CE_to_aBN1": {"edges": 0, "synaptic_contacts": 0},
        "JO_F_to_aBN1": {"edges": 0, "synaptic_contacts": 0},
    }
    reader = ipc.open_file(edge_path)
    target = list(groups["aBN1"])
    for index in range(reader.num_record_batches):
        batch = reader.get_batch(index)
        pre = batch.column(batch.schema.get_field_index("body_pre")).to_numpy()
        post = batch.column(batch.schema.get_field_index("body_post")).to_numpy()
        weight = batch.column(batch.schema.get_field_index("weight")).to_numpy()
        target_mask = np.isin(post, target)
        for key, source_key in (("JO_CE_to_aBN1", "JO_CE"), ("JO_F_to_aBN1", "JO_F")):
            mask = target_mask & np.isin(pre, list(groups[source_key]))
            result[key]["edges"] += int(mask.sum())
            result[key]["synaptic_contacts"] += int(weight[mask].sum())
    return result


def audit_lock(
    scan_connectivity: bool = True,
    *,
    output_root: Path = OUTPUT_ROOT,
    result_path: Path = RESULT_PATH,
) -> dict[str, Any]:
    protocol = yaml.safe_load(PROTOCOL_PATH.read_text(encoding="utf-8"))
    transfer = yaml.safe_load(TRANSFER_RECIPE_PATH.read_text(encoding="utf-8"))
    if protocol.get("status") != "protocol_locked_execution_pending":
        raise Abn1ReferenceLockError("aBN1 protocol is not in its locked pre-execution state")
    if protocol.get("metrics_locked_before_candidate_execution") is None:
        raise Abn1ReferenceLockError("aBN1 metrics are not locked")
    print("[1/4] Vérification des sources MaleCNS et de leurs hashes...", flush=True)
    input_hashes = _verify_inputs(transfer, ROOT)
    paths = {Path(item["path"]).name: ROOT / item["path"] for item in transfer["input_files"]}
    print("[2/4] Vérification du commit source du protocole Figure 5g...", flush=True)
    checkout = ROOT / "runs" / "reference-source" / "Drosophila_brain_model"
    commit = _git_head(checkout)
    expected_commit = str(protocol["source_protocol_lock"]["commit"])
    if commit != expected_commit:
        raise Abn1ReferenceLockError(f"Source commit drift: expected {expected_commit}, got {commit}")
    print("[3/4] Reconstruction des groupes JO-CE, JO-F et aBN1...", flush=True)
    mapping, groups = _select_groups(
        protocol, paths["body-annotations-male-cns-v1.0-minconf-0.5.feather"]
    )
    relations: dict[str, Any] = {}
    if scan_connectivity:
        print("[4/4] Recalcul des relations directes vers aBN1...", flush=True)
        relations = _scan_relations(
            paths["connectome-weights-male-cns-v1.0-minconf-0.5.feather"], groups
        )
        for key, actual in relations.items():
            expected = protocol["malecns_structural_lock"][key]
            if actual != expected:
                raise Abn1ReferenceLockError(
                    f"Structural drift for {key}: expected {expected}, got {actual}"
                )
            print(
                f"      {key}: {actual['edges']} arêtes / {actual['synaptic_contacts']} contacts",
                flush=True,
            )
    else:
        print("[4/4] Scan de connectivité omis pour le test rapide.", flush=True)
    semantic = {
        "protocol_id": protocol["id"],
        "source_commit": commit,
        "input_hashes": input_hashes,
        "mapping": mapping,
        "relations": relations,
        "metrics": protocol["metrics_locked_before_candidate_execution"],
        "direction": protocol["decision_boundary"]["qualitative_required_direction"],
        "excluded": protocol["scope"]["explicitly_excluded"],
    }
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "protocol_locked_execution_pending",
        "claim_label": protocol["claim_label"],
        "semantic_result_sha256": _canonical_hash(semantic),
        **semantic,
        "scientific_model_class_gate_closed": False,
        "next_action": protocol["next_action"],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    compact = {key: value for key, value in summary.items() if key != "input_hashes"}
    compact["id"] = "runner_result.antennal_abn1_reference_lock.v1"
    result_path.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")
    print(f"[VERROUILLÉ] {result_path}", flush=True)
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit the locked aBN1 model-class reference")
    parser.add_argument("--no-connectivity", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    audit_lock(scan_connectivity=not args.no_connectivity)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

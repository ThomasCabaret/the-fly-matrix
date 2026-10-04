from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from .ledger import ROOT


RECIPE_PATH = ROOT / "calibration" / "evidence" / "basal-source-readiness-v0.yaml"
OUTPUT_ROOT = ROOT / "data" / "derived" / "calibration" / "basal-source-readiness-v0"


class BasalEvidenceError(ValueError):
    """Raised when basal evidence cannot be matched exhaustively and honestly."""


def _sha256_file(path: Path) -> str:
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


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BasalEvidenceError(f"{path} must contain a YAML mapping")
    return value


def _normalized(value: Any) -> str:
    if pd.isna(value):
        return "(unknown)"
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return "(unknown)"
    return text


def _is_unknown(value: str) -> bool:
    return value.strip().lower() in {"(unknown)", "unknown", "(missing)", "missing"}


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _verify_inputs(recipe: Mapping[str, Any], root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for item in recipe.get("input_files", []):
        relative = str(item["path"])
        path = root / relative
        if not path.is_file():
            raise BasalEvidenceError(f"Missing evidence input: {relative}")
        actual = _sha256_file(path)
        expected = str(item["sha256"])
        if actual != expected:
            raise BasalEvidenceError(
                f"Input hash drift for {relative}: expected {expected}, got {actual}"
            )
        hashes[relative] = actual
    return hashes


def _select(frame: pd.DataFrame, selector: Mapping[str, Any]) -> pd.DataFrame:
    field = str(selector["field"])
    if field not in frame.columns:
        raise BasalEvidenceError(f"Selector field {field!r} is absent")
    return frame.loc[frame[field].map(_normalized) == str(selector["value"])].copy()


def compile_basal_evidence(
    recipe_path: Path = RECIPE_PATH,
    output_root: Path = OUTPUT_ROOT,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    recipe = _load_yaml(recipe_path)
    if recipe.get("schema_version") != 1:
        raise BasalEvidenceError("Only basal evidence schema_version 1 is supported")
    if recipe.get("status") != "runnable":
        raise BasalEvidenceError("Basal evidence recipe must have status: runnable")

    print("[1/5] Verification des sources structurelles et de leurs hashes", flush=True)
    input_hashes = _verify_inputs(recipe, root)
    basal = pd.read_csv(root / "data/derived/wiring/basal-clamp-channels.csv")
    residual = pd.read_csv(root / "data/derived/wiring/unclassified-sensory-channels.csv")
    tables = {"basal_clamp": basal, "residual": residual}
    print(
        f"[OK] {len(basal):,} canaux clamps + {len(residual):,} canaux residuels",
        flush=True,
    )

    print("[2/5] Application des partitions de preuve versionnees", flush=True)
    source_ids = {str(item["id"]) for item in recipe.get("sources", [])}
    records: list[dict[str, Any]] = []
    family_summaries: list[dict[str, Any]] = []
    seen_channels: set[str] = set()
    for rule in recipe.get("family_rules", []):
        family_id = str(rule["family_id"])
        table_id = str(rule["table_id"])
        if table_id not in tables:
            raise BasalEvidenceError(f"{family_id}: unknown table_id {table_id}")
        frame = _select(tables[table_id], rule["selector"])
        partition_fields = [str(field) for field in rule["partition_fields"]]
        missing_fields = sorted(set(partition_fields) - set(frame.columns))
        if missing_fields:
            raise BasalEvidenceError(f"{family_id}: missing partition fields {missing_fields}")
        declared_sources = [str(value) for value in rule.get("source_ids", [])]
        unknown_sources = sorted(set(declared_sources) - source_ids)
        if unknown_sources:
            raise BasalEvidenceError(f"{family_id}: unknown evidence sources {unknown_sources}")

        expected = rule["expected"]
        channels = len(frame)
        terminals = int(frame["neuron_count"].sum()) if "neuron_count" in frame else channels
        partition_values: set[tuple[str, ...]] = set()
        family_statuses: Counter[str] = Counter()
        for _, row in frame.sort_values("channel_id").iterrows():
            channel_id = str(row["channel_id"])
            if channel_id in seen_channels:
                raise BasalEvidenceError(f"Channel assigned twice: {channel_id}")
            seen_channels.add(channel_id)
            values = tuple(_normalized(row[field]) for field in partition_fields)
            partition_values.add(values)
            status = str(rule["base_evidence_status"])
            condition = rule.get("partial_numeric_condition")
            if isinstance(condition, dict):
                observed = _normalized(row[str(condition["field"])])
                if observed == str(condition["value"]):
                    status = str(rule["partial_numeric_status"])
            if any(_is_unknown(value) for value in values):
                status = str(rule["unknown_key_status"])
            family_statuses[status] += 1
            records.append(
                {
                    "family_id": family_id,
                    "channel_id": channel_id,
                    "terminal_count": int(row.get("neuron_count", 1)),
                    "partition_key": "|".join(
                        f"{field}={value}" for field, value in zip(partition_fields, values)
                    ),
                    "evidence_status": status,
                    "evidence_source_ids": ";".join(declared_sources),
                    "numeric_transfer_status": str(rule["numeric_transfer_status"]),
                    "unit_bridge_status": str(
                        recipe["runtime_unit_contract"]["bridge_status"]
                    ),
                    "numeric_parameter_value_emitted": False,
                }
            )

        observed = {
            "channels": channels,
            "terminals": terminals,
            "partitions": len(partition_values),
        }
        for key, value in observed.items():
            if int(expected[key]) != value:
                raise BasalEvidenceError(
                    f"{family_id}: expected {key}={expected[key]}, observed {value}"
                )
        family_summaries.append(
            {
                "family_id": family_id,
                **observed,
                "partition_fields": partition_fields,
                "evidence_status_counts": dict(sorted(family_statuses.items())),
                "numeric_transfer_status": str(rule["numeric_transfer_status"]),
                "numeric_parameter_values_emitted": 0,
            }
        )
        print(
            f"  {family_id}: {channels:,} canaux, {terminals:,} terminaux, "
            f"{len(partition_values):,} partitions",
            flush=True,
        )

    print("[3/5] Controle d'exhaustivite et du refus de transfert numerique", flush=True)
    acceptance = recipe["acceptance"]
    status_counts = Counter(str(record["evidence_status"]) for record in records)
    numeric_ready = sum(
        record["numeric_transfer_status"] == "ready" for record in records
    )
    totals = {
        "families": len(family_summaries),
        "channels": len(records),
        "terminals": sum(int(record["terminal_count"]) for record in records),
        "partitions": sum(int(item["partitions"]) for item in family_summaries),
        "numeric_transfer_ready_channels": numeric_ready,
        "numeric_parameter_values_emitted": 0,
    }
    expected_totals = {
        "families": int(acceptance["expected_families"]),
        "channels": int(acceptance["expected_channels"]),
        "terminals": int(acceptance["expected_terminals"]),
        "numeric_transfer_ready_channels": int(
            acceptance["expected_numeric_transfer_ready_channels"]
        ),
        "numeric_parameter_values_emitted": int(
            acceptance["expected_parameter_values_emitted"]
        ),
    }
    for key, expected in expected_totals.items():
        if totals[key] != expected:
            raise BasalEvidenceError(
                f"Acceptance mismatch for {key}: expected {expected}, got {totals[key]}"
            )
    expected_all_channels = set(basal["channel_id"].astype(str)) | set(
        residual["channel_id"].astype(str)
    )
    if seen_channels != expected_all_channels:
        raise BasalEvidenceError(
            "Channel accounting mismatch: "
            f"missing={len(expected_all_channels - seen_channels)}, "
            f"unexpected={len(seen_channels - expected_all_channels)}"
        )

    semantic_payload = {
        "recipe_id": recipe["id"],
        "input_hashes": input_hashes,
        "unit_bridge_status": recipe["runtime_unit_contract"]["bridge_status"],
        "families": family_summaries,
        "totals": totals,
        "evidence_status_counts": dict(sorted(status_counts.items())),
        "channel_records": records,
    }
    semantic_hash = _canonical_hash(semantic_payload)
    summary = {
        "schema_version": 1,
        "recipe_id": recipe["id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "claim_label": recipe["claim_label"],
        "status": "accepted_evidence_accounting_numeric_transfer_blocked",
        "input_hashes": input_hashes,
        "recipe_sha256": _sha256_file(recipe_path),
        "semantic_result_sha256": semantic_hash,
        "runtime_unit_contract": recipe["runtime_unit_contract"],
        "families": family_summaries,
        "totals": totals,
        "evidence_status_counts": dict(sorted(status_counts.items())),
        "accepted_claims": [
            "Every declared basal and residual source channel is accounted exactly once.",
            "Current evidence supports heterogeneous annotation partitions for known modalities.",
            "No numerical basal parameter is ready for transfer into the current normalized runtime.",
        ],
        "forbidden_claims": [
            "Any basal rate, noise process or model-activity value has been calibrated.",
            "Residual sensory channels have acquired a biological modality or receptor identity.",
            "The current central ensemble has been ranked, reduced or behaviorally evaluated.",
        ],
        "next_action": recipe["next_action"],
    }

    print("[4/5] Ecriture des caches derives auditables", flush=True)
    output_root.mkdir(parents=True, exist_ok=True)
    coverage_path = output_root / "channel-evidence-coverage.csv"
    summary_path = output_root / "summary.json"
    pd.DataFrame.from_records(records).to_csv(coverage_path, index=False)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[OK] {_display_path(coverage_path, root)}", flush=True)
    print(f"[OK] {_display_path(summary_path, root)}", flush=True)
    print("[5/5] Resume", flush=True)
    print(
        f"[OK] {totals['channels']:,} canaux / {totals['terminals']:,} terminaux; "
        f"{totals['partitions']:,} partitions de preuve",
        flush=True,
    )
    print("[BLOCKED] 0 valeur numerique emise; pont spikes/s -> activite modele absent", flush=True)
    print(f"[HASH] {semantic_hash}", flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile exhaustive basal-source evidence coverage without selecting values"
    )
    parser.add_argument("--recipe", type=Path, default=RECIPE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    compile_basal_evidence(args.recipe, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

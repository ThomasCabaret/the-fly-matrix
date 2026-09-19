from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from neuprint import Client

from .config import NeuprintSettings
from .ledger import ROOT


OUTPUT = ROOT / "data" / "derived" / "inventory" / "roi-audit.json"
CSV_OUTPUT = ROOT / "data" / "derived" / "inventory" / "roi-signatures.csv"
DETAIL_OUTPUT = ROOT / "data" / "derived" / "inventory" / "roi-neuron-signatures.jsonl"

# Deliberately limited to the groups whose coarse anatomy is most useful for
# deciding the next wiring split. These predicates are factual annotation
# filters, not functional interpretations.
GROUP_QUERIES = (
    ("sensory.unknown", "n.class = 'unknown_sensory'"),
    ("sensory.central_brain", "n.superclass = 'cb_sensory'"),
    ("sensory.proprioceptive", "n.class = 'mechanosensory_proprioceptive'"),
    ("sensory.tactile", "n.class = 'mechanosensory_tactile'"),
    ("motor.vnc", "n.superclass = 'vnc_motor'"),
    ("motor.exit_nerve", "n.exitNerve IS NOT NULL"),
)


def section(title: str) -> None:
    print(f"\n==> {title}", flush=True)


def _parse_roi_info(value: Any) -> dict[str, dict[str, Any]]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _query_group(client: Client, predicate: str):
    query = f"""
    MATCH (n:Neuron)
    WHERE {predicate}
    RETURN n.bodyId AS bodyId,
           n.type AS type,
           n.instance AS instance,
           n.class AS neuronClass,
           n.subclass AS neuronSubclass,
           n.superclass AS neuronSuperclass,
           n.entryNerve AS entryNerve,
           n.exitNerve AS exitNerve,
           n.somaSide AS somaSide,
           n.rootSide AS rootSide,
           n.somaNeuromere AS somaNeuromere,
           n.roiInfo AS roiInfo
    ORDER BY n.bodyId
    """
    return client.fetch_custom(query, use_arrow=False)


def _top_roi(roi_rows: list[dict[str, Any]], field: str) -> dict[str, Any] | None:
    if not roi_rows:
        return None
    item = max(roi_rows, key=lambda row: (row[field], row["neurons"], row["roi"]))
    return {"roi": item["roi"], field: item[field], "neurons": item["neurons"]}


def audit_rois(
    output: Path = OUTPUT,
    csv_output: Path = CSV_OUTPUT,
    detail_output: Path = DETAIL_OUTPUT,
) -> dict[str, Any]:
    settings = NeuprintSettings.from_project_env()
    section("Connexion neuPrint pour les signatures anatomiques")
    print(f"Serveur : {settings.server}")
    print(f"Dataset : {settings.dataset}")
    print("Jeton   : chargé depuis .env (valeur masquée)")
    client = Client(
        settings.server,
        dataset=settings.dataset,
        token=settings.token,
        progress=False,
    )
    primary_rois = set(client.primary_rois)
    print(f"[OK] {len(primary_rois):,} ROI primaires disponibles")

    output.parent.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    csv_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []

    for index, (group_id, predicate) in enumerate(GROUP_QUERIES, start=1):
        section(f"Groupe {index}/{len(GROUP_QUERIES)} : {group_id}")
        frame = _query_group(client, predicate)
        aggregates: dict[str, dict[str, int]] = defaultdict(
            lambda: {"neurons": 0, "pre": 0, "post": 0}
        )
        neurons_with_primary_roi = 0

        for row in frame.itertuples(index=False):
            roi_info = _parse_roi_info(row.roiInfo)
            per_neuron: list[dict[str, Any]] = []
            for roi, counts in roi_info.items():
                if roi not in primary_rois or not isinstance(counts, dict):
                    continue
                pre = _integer(counts.get("pre"))
                post = _integer(counts.get("post"))
                if pre <= 0 and post <= 0:
                    continue
                aggregates[roi]["neurons"] += 1
                aggregates[roi]["pre"] += pre
                aggregates[roi]["post"] += post
                per_neuron.append({"roi": roi, "pre": pre, "post": post})

            if per_neuron:
                neurons_with_primary_roi += 1
            top_input = max(per_neuron, key=lambda item: (item["post"], item["roi"]), default=None)
            top_output = max(per_neuron, key=lambda item: (item["pre"], item["roi"]), default=None)
            detail_rows.append(
                {
                    "group_id": group_id,
                    "body_id": _integer(row.bodyId),
                    "type": row.type,
                    "instance": row.instance,
                    "class": row.neuronClass,
                    "subclass": row.neuronSubclass,
                    "superclass": row.neuronSuperclass,
                    "entry_nerve": row.entryNerve,
                    "exit_nerve": row.exitNerve,
                    "soma_side": row.somaSide,
                    "root_side": row.rootSide,
                    "soma_neuromere": row.somaNeuromere,
                    "primary_roi_count": len(per_neuron),
                    "top_input_roi": top_input["roi"] if top_input else None,
                    "top_input_post": top_input["post"] if top_input else 0,
                    "top_output_roi": top_output["roi"] if top_output else None,
                    "top_output_pre": top_output["pre"] if top_output else 0,
                }
            )

        neuron_count = len(frame.index)
        roi_rows = []
        for roi, counts in aggregates.items():
            roi_row = {
                "group_id": group_id,
                "roi": roi,
                "neurons": counts["neurons"],
                "coverage_percent": round(100 * counts["neurons"] / neuron_count, 2)
                if neuron_count
                else 0.0,
                "pre": counts["pre"],
                "post": counts["post"],
            }
            roi_rows.append(roi_row)
            csv_rows.append(roi_row)
        roi_rows.sort(key=lambda item: (item["neurons"], item["pre"] + item["post"]), reverse=True)
        top_input = _top_roi(roi_rows, "post")
        top_output = _top_roi(roi_rows, "pre")
        coverage = round(100 * neurons_with_primary_roi / neuron_count, 2) if neuron_count else 0.0
        summary = {
            "group_id": group_id,
            "query": predicate,
            "neurons": neuron_count,
            "neurons_with_primary_roi": neurons_with_primary_roi,
            "primary_roi_coverage_percent": coverage,
            "distinct_primary_rois": len(roi_rows),
            "top_input_roi": top_input,
            "top_output_roi": top_output,
            "top_rois_by_neuron_coverage": roi_rows[:15],
        }
        summaries.append(summary)
        print(
            f"[OK] {neuron_count:,} neurones; {coverage:.2f}% avec ROI primaire; "
            f"entrée dominante={top_input['roi'] if top_input else 'aucune'}; "
            f"sortie dominante={top_output['roi'] if top_output else 'aucune'}"
        )

    audit = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "server": settings.server,
        "dataset": settings.dataset,
        "method": {
            "scope": "coarse anatomical ROI signatures for selected interface groups",
            "input_measure": "post-synaptic count in each primary ROI",
            "output_measure": "pre-synaptic count in each primary ROI",
            "interpretation": "direct anatomical observation; no functional identity is inferred",
        },
        "groups": summaries,
        "credential_persisted": False,
    }
    output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("group_id", "roi", "neurons", "coverage_percent", "pre", "post"),
        )
        writer.writeheader()
        writer.writerows(sorted(csv_rows, key=lambda item: (item["group_id"], -item["neurons"], item["roi"])))
    with detail_output.open("w", encoding="utf-8", newline="\n") as stream:
        for row in detail_rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\n[OK] Synthèse : {output}")
    print(f"[OK] Table ROI : {csv_output}")
    print(f"[OK] Détail par neurone : {detail_output}")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit neuPrint des signatures ROI par groupe")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=CSV_OUTPUT)
    parser.add_argument("--detail-output", type=Path, default=DETAIL_OUTPUT)
    args = parser.parse_args()
    try:
        audit_rois(args.output, args.csv_output, args.detail_output)
    except Exception as exc:
        print(f"\nROI_AUDIT_FAILED: {type(exc).__name__}: {exc}")
        return 1
    print("\nROI_AUDIT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

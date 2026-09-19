from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from neuprint import Client

from .config import NeuprintSettings
from .inventory import OUTPUT as LOCAL_INVENTORY_PATH
from .ledger import ROOT


OUTPUT = ROOT / "data" / "derived" / "inventory" / "neuprint-audit.json"
GROUP_SPECS = (
    ("sensory.visual", "class", "visual"),
    ("sensory.olfactory", "class", "olfactory"),
    ("sensory.gustatory", "class", "gustatory"),
    ("sensory.tactile", "class", "mechanosensory_tactile"),
    ("sensory.mechanosensory_other", "class", "mechanosensory"),
    ("sensory.proprioceptive", "class", "mechanosensory_proprioceptive"),
    ("sensory.unknown", "class", "unknown_sensory"),
    ("sensory.optic_lobe", "superclass", "ol_sensory"),
    ("sensory.central_brain", "superclass", "cb_sensory"),
    ("sensory.vnc", "superclass", "vnc_sensory"),
    ("motor.vnc", "superclass", "vnc_motor"),
    ("projection.ascending", "superclass", "ascending_neuron"),
    ("projection.descending", "superclass", "descending_neuron"),
)


def section(title: str) -> None:
    print(f"\n==> {title}", flush=True)


def _safe_meta(meta: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "dataset",
        "uuid",
        "lastDatabaseEdit",
        "latestMutationId",
        "totalPreCount",
        "totalPostCount",
        "neuronProperties",
    )
    result = {key: meta[key] for key in keys if key in meta and key != "neuronProperties"}
    properties = meta.get("neuronProperties")
    if isinstance(properties, str):
        try:
            result["neuron_property_count"] = len(json.loads(properties))
        except (TypeError, ValueError):
            result["neuron_property_count"] = None
    return result


def _group_count_query() -> str:
    maps = ",\n".join(
        "{id: " + json.dumps(group_id) + ", property: " + json.dumps(prop)
        + ", value: " + json.dumps(value) + "}"
        for group_id, prop, value in GROUP_SPECS
    )
    return f"""
    WITH [{maps}] AS specs
    UNWIND specs AS spec
    MATCH (n:Neuron)
    WHERE n[spec.property] = spec.value
    RETURN spec.id AS group_id, count(n) AS neurons
    ORDER BY group_id
    """


def audit_neuprint(output: Path = OUTPUT) -> dict[str, Any]:
    settings = NeuprintSettings.from_project_env()
    section("Connexion neuPrint authentifiée")
    print(f"Serveur : {settings.server}")
    print(f"Dataset : {settings.dataset}")
    print("Jeton   : chargé depuis .env (valeur masquée)")
    client = Client(
        settings.server,
        dataset=settings.dataset,
        token=settings.token,
        progress=False,
    )
    version = client.fetch_version()
    datasets = client.fetch_datasets()
    print(f"[OK] neuPrintHTTP {version}; dataset sélectionné")

    section("Métadonnées et requête témoin")
    neuron_result = client.fetch_custom("MATCH (n:Neuron) RETURN count(n) AS neurons")
    neuron_count = int(neuron_result.iloc[0]["neurons"])
    meta = _safe_meta(client.meta)
    print(f"[OK] {neuron_count:,} nœuds :Neuron accessibles")
    print(f"[OK] {len(client.primary_rois):,} ROI primaires déclarées")

    section("Comparaison des groupes locaux et distants")
    remote_frame = client.fetch_custom(_group_count_query())
    remote_counts = {
        str(row.group_id): int(row.neurons) for row in remote_frame.itertuples(index=False)
    }
    exit_result = client.fetch_custom(
        "MATCH (n:Neuron) WHERE n.exitNerve IS NOT NULL "
        "RETURN count(n) AS neurons"
    )
    remote_counts["motor.exit_nerve"] = int(exit_result.iloc[0]["neurons"])
    local_counts: dict[str, int] = {}
    if LOCAL_INVENTORY_PATH.is_file():
        local_inventory = json.loads(LOCAL_INVENTORY_PATH.read_text(encoding="utf-8"))
        local_counts = {
            group["id"]: int(group["neurons"])
            for group in local_inventory.get("interface_groups", [])
        }
    comparisons = []
    comparison_ids = [group_id for group_id, _, _ in GROUP_SPECS]
    comparison_ids.insert(comparison_ids.index("projection.ascending"), "motor.exit_nerve")
    for group_id in comparison_ids:
        local = local_counts.get(group_id)
        remote = remote_counts.get(group_id, 0)
        match = local == remote if local is not None else None
        comparisons.append(
            {
                "group_id": group_id,
                "local_neurons": local,
                "remote_neurons": remote,
                "difference": remote - local if local is not None else None,
                "exact_match": match,
            }
        )
        marker = "OK" if match else "ECART"
        print(f"[{marker}] {group_id:32} local={local!s:>6} distant={remote:>6}")

    audit = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "server": settings.server,
        "dataset": settings.dataset,
        "server_version": version,
        "dataset_metadata": datasets.get(settings.dataset, {}),
        "meta": meta,
        "neuron_count": neuron_count,
        "primary_roi_count": len(client.primary_rois),
        "group_comparisons": comparisons,
        "credential_persisted": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] Audit non sensible écrit dans {output}")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit léger du dataset neuPrint distant")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    try:
        audit_neuprint(args.output)
    except Exception as exc:
        print(f"\nNEUPRINT_AUDIT_FAILED: {type(exc).__name__}: {exc}")
        return 1
    print("\nNEUPRINT_AUDIT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

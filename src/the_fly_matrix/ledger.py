from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
LEDGER_ROOT = ROOT / "ledger"

STATUS_SCORES: dict[str, dict[str, float]] = {
    "inventory": {"missing": 0.0, "partial": 0.5, "complete": 1.0},
    "routing": {
        "unknown": 0.0,
        "candidates_known": 0.25,
        "proposed": 0.5,
        "fixed": 0.8,
        "verified": 1.0,
    },
    "decomposition": {
        "unknown": 0.0,
        "proposed": 0.5,
        "fixed": 0.8,
        "verified": 1.0,
    },
    "implementation": {
        "not_started": 0.0,
        "stub": 0.25,
        "implemented": 0.7,
        "tested": 1.0,
    },
    "parameters": {
        "unknown": 0.0,
        "assumed": 0.2,
        "borrowed": 0.45,
        "measured": 0.7,
        "fitted": 0.85,
        "frozen": 1.0,
    },
    "validation": {
        "not_run": 0.0,
        "smoke": 0.25,
        "local_pass": 0.5,
        "integration_pass": 0.75,
        "held_out_pass": 1.0,
        "failed": 0.0,
    },
}

PARAMETER_SCORES = STATUS_SCORES["parameters"]
VALIDATION_SCORES = STATUS_SCORES["validation"]
WIRING_STATUS_SCORES: dict[str, dict[str, float]] = {
    "inventory": {"missing": 0.0, "partial": 0.5, "complete": 1.0},
    "routing": {
        "unknown": 0.0,
        "candidates_known": 0.15,
        "proposed": 0.35,
        "fixed": 0.75,
        "verified": 1.0,
    },
    "decomposition": {"unknown": 0.0, "proposed": 0.25, "fixed": 0.75, "verified": 1.0},
    "implementation": {"not_started": 0.0, "stub": 0.15, "implemented": 0.75, "tested": 1.0},
}
SECTOR_LABELS = {
    "physical_world": "Monde physique",
    "vision": "Vision",
    "mechanosensation": "Mécanosensation",
    "proprioception": "Proprioception",
    "basal_clamps": "Clamps basaux",
    "unclassified_sensory": "Entrées sensorielles non résolues",
    "central_nervous_system": "Système nerveux central",
    "motor_output": "Sortie motrice",
    "physical_body": "Corps physique",
    "evaluation": "Évaluation",
    "unknown": "Non classé",
}


class LedgerError(RuntimeError):
    pass


def _load_folder(folder: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise LedgerError(f"{path}: la racine YAML doit être un objet")
        data["_path"] = str(path.relative_to(ROOT)).replace("\\", "/")
        records.append(data)
    return records


def load_ledger(root: Path = LEDGER_ROOT) -> dict[str, list[dict[str, Any]]]:
    return {
        "boxes": _load_folder(root / "boxes"),
        "groups": _load_folder(root / "groups"),
        "wires": _load_folder(root / "wires"),
        "parameters": _load_folder(root / "parameter_families"),
        "validations": _load_folder(root / "validations"),
    }


def _index(records: list[dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id:
            raise LedgerError(f"{record.get('_path', kind)}: id manquant")
        if record_id in result:
            raise LedgerError(f"ID dupliqué {record_id!r} dans {kind}")
        result[record_id] = record
    return result


def _check_status(record: dict[str, Any], axes: tuple[str, ...]) -> None:
    status = record.get("status")
    if not isinstance(status, dict):
        raise LedgerError(f"{record['_path']}: bloc status manquant")
    for axis in axes:
        value = status.get(axis)
        if value not in STATUS_SCORES[axis]:
            allowed = ", ".join(STATUS_SCORES[axis])
            raise LedgerError(f"{record['_path']}: {axis}={value!r}; attendu {allowed}")


def validate_ledger(ledger: dict[str, list[dict[str, Any]]]) -> list[str]:
    boxes = _index(ledger["boxes"], "boxes")
    groups = _index(ledger["groups"], "groups")
    wires = _index(ledger["wires"], "wires")
    parameters = _index(ledger["parameters"], "parameters")
    validations = _index(ledger["validations"], "validations")

    for box in boxes.values():
        _check_status(box, ("inventory", "implementation", "parameters", "validation"))
        for parameter_id in box.get("parameter_family_ids", []):
            if parameter_id not in parameters:
                raise LedgerError(f"{box['_path']}: paramètre inconnu {parameter_id}")
        for validation_id in box.get("validation_ids", []):
            if validation_id not in validations:
                raise LedgerError(f"{box['_path']}: validation inconnue {validation_id}")
        parent_id = box.get("parent_id")
        if parent_id is not None and parent_id not in boxes:
            raise LedgerError(f"{box['_path']}: parent inconnu {parent_id}")

    for wire in wires.values():
        _check_status(wire, ("inventory", "routing", "implementation", "validation"))
        for endpoint_name in ("source", "target"):
            endpoint = wire.get(endpoint_name, {})
            box_id = endpoint.get("box_id")
            port = endpoint.get("port")
            if box_id not in boxes:
                raise LedgerError(f"{wire['_path']}: boîte {endpoint_name} inconnue {box_id}")
            port_kind = "outputs" if endpoint_name == "source" else "inputs"
            if port not in boxes[box_id].get("ports", {}).get(port_kind, []):
                raise LedgerError(
                    f"{wire['_path']}: port {endpoint_name} {box_id}.{port} absent de {port_kind}"
                )
        for validation_id in wire.get("validation_ids", []):
            if validation_id not in validations:
                raise LedgerError(f"{wire['_path']}: validation inconnue {validation_id}")

    for group in groups.values():
        _check_status(group, ("inventory", "decomposition", "routing", "validation"))
        parent_id = group.get("parent_id")
        if parent_id is not None and parent_id not in groups:
            raise LedgerError(f"{group['_path']}: groupe parent inconnu {parent_id}")
        for target_id in group.get("target_box_ids", []):
            if target_id not in boxes:
                raise LedgerError(f"{group['_path']}: boîte cible inconnue {target_id}")

    for parameter in parameters.values():
        owner_id = parameter.get("owner_id")
        if owner_id not in boxes:
            raise LedgerError(f"{parameter['_path']}: propriétaire inconnu {owner_id}")
        if parameter.get("status") not in PARAMETER_SCORES:
            raise LedgerError(f"{parameter['_path']}: statut de paramètre invalide")

    for validation in validations.values():
        if validation.get("status") not in VALIDATION_SCORES:
            raise LedgerError(f"{validation['_path']}: statut de validation invalide")
        valid_owners = set(boxes) | set(groups) | set(wires) | set(parameters)
        for owner_id in validation.get("owner_ids", []):
            if owner_id not in valid_owners:
                raise LedgerError(f"{validation['_path']}: propriétaire inconnu {owner_id}")

    return [
        f"{len(boxes)} boîtes avec IDs uniques",
        f"{len(groups)} groupes avec requêtes et cibles valides",
        f"{len(wires)} fils avec extrémités et ports valides",
        f"{len(parameters)} familles de paramètres avec propriétaires valides",
        f"{len(validations)} validations avec propriétaires multi-registres valides",
    ]


def status_score(status: dict[str, str], axes: tuple[str, ...]) -> float:
    return sum(STATUS_SCORES[axis][status[axis]] for axis in axes) / len(axes)


def record_progress(kind: str, record: dict[str, Any]) -> float:
    if kind == "boxes":
        return status_score(record["status"], ("inventory", "implementation", "parameters", "validation"))
    if kind == "wires":
        return status_score(record["status"], ("inventory", "routing", "implementation", "validation"))
    if kind == "groups":
        return status_score(record["status"], ("inventory", "decomposition", "routing", "validation"))
    if kind == "parameters":
        return PARAMETER_SCORES[record["status"]]
    if kind == "validations":
        return VALIDATION_SCORES[record["status"]]
    raise KeyError(kind)


def wiring_record_progress(kind: str, record: dict[str, Any]) -> float:
    """Readiness for a runnable graph with arbitrary injected parameters.

    Calibration, fitted values and held-out behavioral validation are deliberately
    excluded. Reaching 100% requires verified terminal groups and routes plus tested
    executable boxes and wires.
    """
    status = record["status"]
    if kind == "boxes":
        return (
            0.35 * WIRING_STATUS_SCORES["inventory"][status["inventory"]]
            + 0.65 * WIRING_STATUS_SCORES["implementation"][status["implementation"]]
        )
    if kind == "groups":
        return (
            0.55 * WIRING_STATUS_SCORES["decomposition"][status["decomposition"]]
            + 0.45 * WIRING_STATUS_SCORES["routing"][status["routing"]]
        )
    if kind == "wires":
        return (
            0.10 * WIRING_STATUS_SCORES["inventory"][status["inventory"]]
            + 0.45 * WIRING_STATUS_SCORES["routing"][status["routing"]]
            + 0.45 * WIRING_STATUS_SCORES["implementation"][status["implementation"]]
        )
    raise KeyError(kind)


def _axis_average(records: list[dict[str, Any]], axis: str) -> int:
    if not records:
        return 0
    return round(
        100
        * sum(WIRING_STATUS_SCORES[axis][record["status"][axis]] for record in records)
        / len(records)
    )


def build_summary(ledger: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    validate_ledger(ledger)
    enriched: dict[str, list[dict[str, Any]]] = {}
    all_scores: list[float] = []
    wiring_scores: list[float] = []
    for kind, records in ledger.items():
        enriched[kind] = []
        for original in records:
            record = dict(original)
            record["progress"] = round(record_progress(kind, record) * 100)
            if kind in {"boxes", "groups", "wires"}:
                record["wiring_progress"] = round(wiring_record_progress(kind, record) * 100)
                wiring_scores.append(wiring_record_progress(kind, record))
            enriched[kind].append(record)
            all_scores.append(record_progress(kind, record))

    sectors: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"boxes": [], "groups": [], "wires": [], "scores": [], "wiring_scores": []}
    )
    for kind in ("boxes", "groups", "wires"):
        for record in enriched[kind]:
            sector = record.get("sector", "unknown")
            sectors[sector][kind].append(record["id"])
            sectors[sector]["scores"].append(record["progress"])
            sectors[sector]["wiring_scores"].append(record["wiring_progress"])
    sector_rows = []
    for sector, data in sectors.items():
        scores = data.pop("scores")
        sector_wiring_scores = data.pop("wiring_scores")
        sector_rows.append(
            {
                "id": sector,
                "name": SECTOR_LABELS.get(sector, sector.replace("_", " ").title()),
                "progress": round(sum(scores) / len(scores)) if scores else 0,
                "wiring_progress": round(sum(sector_wiring_scores) / len(sector_wiring_scores))
                if sector_wiring_scores
                else 0,
                **data,
            }
        )
    sector_rows.sort(key=lambda row: (row["progress"], row["name"]))

    routing_counts = Counter(wire["status"]["routing"] for wire in enriched["wires"])
    validation_counts = Counter(item["status"] for item in enriched["validations"])
    next_actions = []
    for kind in ("boxes", "groups", "wires"):
        for record in enriched[kind]:
            action = record.get("next_action")
            if action and record["progress"] < 100:
                next_actions.append(
                    {
                        "kind": {"boxes": "box", "groups": "group", "wires": "wire"}[kind],
                        "id": record["id"],
                        "name": record["name"],
                        "sector": record.get("sector", "unknown"),
                        "progress": record["wiring_progress"],
                        "structural_progress": record["progress"],
                        "blocked_by": record.get("blocked_by", []),
                        "action": action,
                    }
                )
    next_actions.sort(key=lambda item: (bool(item["blocked_by"]), item["progress"], item["sector"]))

    return {
        "overall_progress": round(100 * sum(all_scores) / len(all_scores)) if all_scores else 0,
        "wiring_progress": round(100 * sum(wiring_scores) / len(wiring_scores))
        if wiring_scores
        else 0,
        "wiring_components": {
            "box_inventory": _axis_average(enriched["boxes"], "inventory"),
            "box_execution": _axis_average(enriched["boxes"], "implementation"),
            "group_decomposition": _axis_average(enriched["groups"], "decomposition"),
            "group_routing": _axis_average(enriched["groups"], "routing"),
            "wire_inventory": _axis_average(enriched["wires"], "inventory"),
            "wire_routing": _axis_average(enriched["wires"], "routing"),
            "wire_execution": _axis_average(enriched["wires"], "implementation"),
        },
        "counts": {kind: len(records) for kind, records in enriched.items()},
        "routing_counts": dict(routing_counts),
        "validation_counts": dict(validation_counts),
        "sectors": sector_rows,
        "next_actions": next_actions,
        **enriched,
    }

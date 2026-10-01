from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[2]
CALIBRATION_ROOT = ROOT / "calibration"


class CalibrationRegistryError(ValueError):
    """Raised when the versioned calibration inventory is inconsistent."""


@dataclass(frozen=True)
class CalibrationInventory:
    index: Mapping[str, Any]
    dag: Mapping[str, Any]
    families: Mapping[str, Mapping[str, Any]]
    topological_order: tuple[str, ...]

    @property
    def unresolved_family_ids(self) -> tuple[str, ...]:
        return tuple(
            family_id
            for family_id in self.topological_order
            if self.families[family_id].get("freeze", {}).get("status")
            not in {"frozen", "externally_frozen"}
        )


def _load_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise CalibrationRegistryError(f"Missing calibration registry file: {path}")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CalibrationRegistryError(f"{path} must contain a YAML mapping")
    return value


def _require_mapping(record: Mapping[str, Any], key: str, path: Path) -> Mapping[str, Any]:
    value = record.get(key)
    if not isinstance(value, dict):
        raise CalibrationRegistryError(f"{path}: {key} must be a mapping")
    return value


def _topological_order(node_ids: set[str], edges: list[Mapping[str, Any]]) -> tuple[str, ...]:
    incoming = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, list[str]] = defaultdict(list)
    seen_edges: set[tuple[str, str]] = set()
    for edge in edges:
        upstream = edge.get("upstream")
        downstream = edge.get("downstream")
        if upstream not in node_ids or downstream not in node_ids:
            raise CalibrationRegistryError(
                f"DAG edge references an unknown family: {upstream!r} -> {downstream!r}"
            )
        if upstream == downstream:
            raise CalibrationRegistryError(f"DAG self-loop on {upstream}")
        pair = (str(upstream), str(downstream))
        if pair in seen_edges:
            raise CalibrationRegistryError(f"Duplicate DAG edge: {upstream} -> {downstream}")
        seen_edges.add(pair)
        outgoing[str(upstream)].append(str(downstream))
        incoming[str(downstream)] += 1

    ready = deque(sorted(node_id for node_id, count in incoming.items() if count == 0))
    order: list[str] = []
    while ready:
        node_id = ready.popleft()
        order.append(node_id)
        for child_id in sorted(outgoing[node_id]):
            incoming[child_id] -= 1
            if incoming[child_id] == 0:
                ready.append(child_id)
    if len(order) != len(node_ids):
        cyclic = sorted(node_id for node_id, count in incoming.items() if count > 0)
        raise CalibrationRegistryError(f"Calibration dependency graph contains a cycle: {cyclic}")
    return tuple(order)


def load_calibration_inventory(root: Path = CALIBRATION_ROOT) -> CalibrationInventory:
    family_root = root / "parameter_families"
    index = _load_mapping(family_root / "index.yaml")
    dag = _load_mapping(root / "dependency-dag.yaml")

    families: dict[str, Mapping[str, Any]] = {}
    paths_by_id: dict[str, Path] = {}
    for path in sorted(family_root.glob("*.yaml")):
        if path.name == "index.yaml":
            continue
        record = _load_mapping(path)
        family_id = record.get("id")
        if not isinstance(family_id, str) or not family_id:
            raise CalibrationRegistryError(f"{path}: missing stable family id")
        if family_id in families:
            raise CalibrationRegistryError(
                f"Duplicate family id {family_id}: {paths_by_id[family_id]} and {path}"
            )
        families[family_id] = record
        paths_by_id[family_id] = path

    indexed_ids = index.get("family_ids")
    if not isinstance(indexed_ids, list) or not all(isinstance(item, str) for item in indexed_ids):
        raise CalibrationRegistryError("parameter_families/index.yaml: family_ids must be a string list")
    if len(indexed_ids) != len(set(indexed_ids)):
        raise CalibrationRegistryError("parameter_families/index.yaml contains duplicate family ids")
    if set(indexed_ids) != set(families):
        raise CalibrationRegistryError(
            "Inventory index and family files differ: "
            f"missing_files={sorted(set(indexed_ids) - set(families))}, "
            f"unindexed_files={sorted(set(families) - set(indexed_ids))}"
        )

    allowed_classes = {"evidence_transfer", "technical", "local_interface"}
    allowed_kinds = {
        "routing",
        "transfer",
        "basal",
        "neural_dynamics",
        "mechanical",
        "technical_nuisance",
    }
    allowed_roles = {"biological", "technical", "surrogate"}
    for family_id, record in families.items():
        path = paths_by_id[family_id]
        if record.get("primary_class") not in allowed_classes:
            raise CalibrationRegistryError(f"{path}: invalid primary_class")
        if record.get("parameter_kind") not in allowed_kinds:
            raise CalibrationRegistryError(f"{path}: invalid parameter_kind")
        if record.get("claim_role") not in allowed_roles:
            raise CalibrationRegistryError(f"{path}: invalid claim_role")
        for key in (
            "meaning",
            "scope",
            "sharing",
            "origin_policy",
            "identifiability",
            "dependencies",
            "uncertainty",
            "freeze",
        ):
            _require_mapping(record, key, path)
        if not record.get("next_action"):
            raise CalibrationRegistryError(f"{path}: next_action is required")
        dimension = _require_mapping(record["scope"], "dimension", path)
        if not dimension:
            raise CalibrationRegistryError(f"{path}: scope.dimension must be explicit")

    dag_node_ids = dag.get("node_ids")
    edges = dag.get("edges")
    if not isinstance(dag_node_ids, list) or not all(
        isinstance(item, str) for item in dag_node_ids
    ):
        raise CalibrationRegistryError("dependency-dag.yaml: node_ids must be a string list")
    if len(dag_node_ids) != len(set(dag_node_ids)):
        raise CalibrationRegistryError("dependency-dag.yaml contains duplicate node ids")
    if set(dag_node_ids) != set(families):
        raise CalibrationRegistryError("DAG nodes must exactly match the parameter-family inventory")
    if not isinstance(edges, list) or not all(isinstance(edge, dict) for edge in edges):
        raise CalibrationRegistryError("dependency-dag.yaml: edges must be a mapping list")

    node_ids = set(dag_node_ids)
    order = _topological_order(node_ids, edges)
    dag_upstream: dict[str, set[str]] = defaultdict(set)
    dag_downstream: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        upstream = str(edge["upstream"])
        downstream = str(edge["downstream"])
        dag_upstream[downstream].add(upstream)
        dag_downstream[upstream].add(downstream)
    for family_id, record in families.items():
        dependencies = record["dependencies"]
        declared_upstream = set(dependencies.get("upstream_family_ids", []))
        declared_downstream = set(dependencies.get("downstream_family_ids", []))
        if declared_upstream != dag_upstream[family_id]:
            raise CalibrationRegistryError(
                f"{family_id}: upstream declarations differ from dependency-dag.yaml"
            )
        if declared_downstream != dag_downstream[family_id]:
            raise CalibrationRegistryError(
                f"{family_id}: downstream declarations differ from dependency-dag.yaml"
            )

    accounting = _require_mapping(index, "accounting", family_root / "index.yaml")
    if accounting.get("total_families") != len(families):
        raise CalibrationRegistryError("Inventory accounting.total_families is stale")
    expected_by_kind = Counter(record["parameter_kind"] for record in families.values())
    if dict(accounting.get("by_kind", {})) != dict(expected_by_kind):
        raise CalibrationRegistryError("Inventory accounting.by_kind is stale")
    expected_by_role = Counter(record["claim_role"] for record in families.values())
    if dict(accounting.get("by_claim_role", {})) != dict(expected_by_role):
        raise CalibrationRegistryError("Inventory accounting.by_claim_role is stale")

    return CalibrationInventory(
        index=index,
        dag=dag,
        families=families,
        topological_order=order,
    )


def main() -> int:
    print("[1/3] Chargement de l'inventaire versionne...")
    inventory = load_calibration_inventory()
    print(f"[OK] {len(inventory.families)} familles, index exhaustif")
    print("[2/3] Validation du DAG et des declarations reciproques...")
    print(f"[OK] DAG acyclique, {len(inventory.dag['edges'])} dependances")
    print("[3/3] Resume de maturite...")
    status_counts = Counter(record["status"] for record in inventory.families.values())
    for status, count in sorted(status_counts.items()):
        print(f"  {status:38} {count:2}")
    print(f"Familles non gelees : {len(inventory.unresolved_family_ids)}")
    print(
        "Jeux de parametres acceptes : "
        f"{inventory.index['accounting']['accepted_parameter_sets']}"
    )
    print("Prochaine etape : compilateur routage/transfert et runner minimal.")
    print("IMPORTANT : inventaire complet ne signifie pas calibration terminee.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

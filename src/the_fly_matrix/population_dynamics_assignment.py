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


RECIPE_PATH = ROOT / "calibration" / "evidence" / "front-leg-population-dynamics-v0.yaml"
OUTPUT_ROOT = (
    ROOT / "data" / "derived" / "calibration" / "population-dynamics-front-leg-v0"
)


class PopulationDynamicsAssignmentError(ValueError):
    """Raised when a population assignment is incomplete or changes topology."""


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
        raise PopulationDynamicsAssignmentError(f"{path} must contain a YAML mapping")
    return value


def _normalized(value: Any) -> str:
    if pd.isna(value):
        return "(unknown)"
    return str(value).strip()


def _select(frame: pd.DataFrame, selector: Mapping[str, Any]) -> pd.DataFrame:
    conditions = selector.get("all")
    if not isinstance(conditions, list) or not conditions:
        raise PopulationDynamicsAssignmentError("Selector needs a non-empty all list")
    mask = pd.Series(True, index=frame.index)
    for condition in conditions:
        field = str(condition["field"])
        if field not in frame.columns:
            raise PopulationDynamicsAssignmentError(f"Missing selector field {field!r}")
        operation = str(condition["op"])
        if operation == "equals":
            mask &= frame[field].map(_normalized).eq(str(condition["value"]))
        elif operation == "in":
            allowed = {str(value) for value in condition["value"]}
            mask &= frame[field].map(_normalized).isin(allowed)
        else:
            raise PopulationDynamicsAssignmentError(
                f"Unsupported selector operation {operation!r}"
            )
    return frame.loc[mask].copy()


def _verify_inputs(recipe: Mapping[str, Any], root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for item in recipe.get("input_files", []):
        relative = str(item["path"])
        path = root / relative
        if not path.is_file():
            raise PopulationDynamicsAssignmentError(f"Missing input: {relative}")
        actual = _sha256_file(path)
        expected = str(item["sha256"])
        if actual != expected:
            raise PopulationDynamicsAssignmentError(
                f"Input hash drift for {relative}: expected {expected}, got {actual}"
            )
        hashes[relative] = actual
    return hashes


def _assert_expected(population_id: str, observed: Mapping[str, int], expected: Mapping[str, Any]) -> None:
    for key, expected_value in expected.items():
        actual = observed.get(str(key))
        if actual != int(expected_value):
            raise PopulationDynamicsAssignmentError(
                f"{population_id}: expected {key}={expected_value}, observed {actual}"
            )


def compile_population_dynamics_assignments(
    recipe_path: Path = RECIPE_PATH,
    output_root: Path = OUTPUT_ROOT,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    recipe = _load_yaml(recipe_path)
    if recipe.get("schema_version") != 1 or recipe.get("status") != "runnable":
        raise PopulationDynamicsAssignmentError("Recipe must be runnable schema_version 1")

    print("[1/5] Verification des sources et des hashes figes", flush=True)
    input_hashes = _verify_inputs(recipe, root)
    annotations = pd.read_feather(
        root / "data/raw/malecns/v1.0/body-annotations-male-cns-v1.0-minconf-0.5.feather"
    )
    node_scope = pd.read_parquet(
        root / "data/derived/analysis/cycle-topology/node-classification.parquet"
    ).set_index("body_id")
    proprio_routes = pd.read_parquet(
        root / "data/derived/wiring/proprioception-routes.parquet"
    )
    proprio_direct = pd.read_parquet(
        root / "data/derived/wiring/proprioception-input-candidates.parquet"
    )
    proprio_proxy = pd.read_parquet(
        root / "data/derived/wiring/proprioception-proxy-candidates.parquet"
    )
    motor_routes = pd.read_parquet(root / "data/derived/wiring/motor-routes.parquet")
    motor_candidates = pd.read_parquet(
        root / "data/derived/wiring/motor-actuator-candidates.parquet"
    )
    print(f"[OK] {len(input_hashes)} entrees immuables verifiees", flush=True)

    print("[2/5] Selection et controle du perimetre neuronal", flush=True)
    source_ids = {str(source["id"]) for source in recipe["sources"]}
    seen_body_ids: set[int] = set()
    member_records: list[dict[str, Any]] = []
    population_summaries: list[dict[str, Any]] = []
    assignment_counts: Counter[str] = Counter()

    for rule in recipe["population_rules"]:
        population_id = str(rule["id"])
        selected = _select(annotations, rule["selector"])
        body_ids = {int(value) for value in selected["bodyId"]}
        overlap = seen_body_ids & body_ids
        if overlap:
            raise PopulationDynamicsAssignmentError(
                f"Population overlap for {population_id}: {sorted(overlap)[:3]}"
            )
        seen_body_ids |= body_ids
        missing_scope = sorted(body_ids - set(node_scope.index.astype(int)))
        if missing_scope:
            raise PopulationDynamicsAssignmentError(
                f"Missing node-scope records for {population_id}: {missing_scope[:3]}"
            )
        scoped = node_scope.loc[sorted(body_ids)]
        canonical_count = int(
            (scoped["is_canonical_neuron"] & scoped["included_in_neural_runtime"]).sum()
        )
        if canonical_count != len(body_ids):
            raise PopulationDynamicsAssignmentError(
                f"{population_id}: selected non-canonical or runtime-excluded bodies"
            )

        declared_sources = {str(value) for value in rule.get("source_ids", [])}
        if not declared_sources or not declared_sources <= source_ids:
            raise PopulationDynamicsAssignmentError(
                f"{population_id}: missing or unknown assignment source"
            )
        if not rule.get("native_output_contract", {}).get("conversion_boundary"):
            raise PopulationDynamicsAssignmentError(
                f"{population_id}: missing conversion boundary"
            )

        assignment = str(rule["assignment"])
        if assignment not in {"event_required", "graded_required", "dual_unresolved", "excluded"}:
            raise PopulationDynamicsAssignmentError(
                f"{population_id}: invalid assignment {assignment}"
            )

        observed: dict[str, int] = {
            "neurons": len(body_ids),
            "canonical_runtime_neurons": canonical_count,
            "left_neurons": int((selected["rootSide" if rule["route_table"] == "proprioception" else "somaSide"] == "L").sum()),
            "right_neurons": int((selected["rootSide" if rule["route_table"] == "proprioception" else "somaSide"] == "R").sum()),
        }
        route_ids: dict[int, str] = {}
        if rule["route_table"] == "proprioception":
            routes = proprio_routes[proprio_routes["target_body_id"].isin(body_ids)].copy()
            channels = set(routes["channel_id"].astype(str))
            direct = proprio_direct[proprio_direct["target_channel_id"].isin(channels)]
            proxy = proprio_proxy[proprio_proxy["target_channel_id"].isin(channels)]
            observed.update(
                {
                    "route_rows": len(routes),
                    "terminal_channels": len(channels),
                    "named_types": int(selected["type"].nunique()),
                    "direct_candidate_edges": len(direct),
                    "proxy_candidate_edges": len(proxy),
                }
            )
            route_ids = {
                int(row.target_body_id): str(row.channel_id)
                for row in routes.itertuples(index=False)
            }
        elif rule["route_table"] == "motor":
            routes = motor_routes[motor_routes["source_body_id"].isin(body_ids)].copy()
            candidates = motor_candidates[
                motor_candidates["source_body_id"].isin(body_ids)
            ]
            observed.update(
                {
                    "route_rows": len(routes),
                    "motor_groups": int(routes["motor_group_id"].nunique()),
                    "actuator_candidate_edges": len(candidates),
                    "unique_actuators": int(candidates["target_actuator_id"].nunique()),
                }
            )
            route_ids = {
                int(row.source_body_id): str(row.channel_id)
                for row in routes.itertuples(index=False)
            }
        else:
            raise PopulationDynamicsAssignmentError(
                f"{population_id}: unknown route_table {rule['route_table']}"
            )

        _assert_expected(population_id, observed, rule["expected"])
        if set(route_ids) != body_ids:
            raise PopulationDynamicsAssignmentError(
                f"{population_id}: route membership differs from selected bodies"
            )

        assignment_counts[assignment] += len(body_ids)
        for row in selected.sort_values("bodyId").itertuples(index=False):
            body_id = int(row.bodyId)
            member_records.append(
                {
                    "population_id": population_id,
                    "body_id": body_id,
                    "route_channel_id": route_ids[body_id],
                    "annotation_type": _normalized(row.type),
                    "side": _normalized(
                        row.rootSide if rule["route_table"] == "proprioception" else row.somaSide
                    ),
                    "assignment": assignment,
                    "assignment_confidence": str(rule["assignment_confidence"]),
                    "source_ids": ";".join(sorted(declared_sources)),
                    "parameter_value_emitted": False,
                }
            )
        population_summaries.append(
            {
                "population_id": population_id,
                "role": str(rule["role"]),
                "assignment": assignment,
                "assignment_confidence": str(rule["assignment_confidence"]),
                "observed": observed,
                "native_input_contract": rule["native_input_contract"],
                "native_output_contract": rule["native_output_contract"],
                "delay_policy": str(rule["delay_policy"]),
                "source_ids": sorted(declared_sources),
            }
        )
        print(
            f"  {population_id}: {len(body_ids)} neurones -> {assignment}",
            flush=True,
        )

    print("[3/5] Controle exhaustif des issues et de l'absence de valeurs", flush=True)
    acceptance = recipe["acceptance"]
    totals = {
        "populations": len(population_summaries),
        "neurons": len(member_records),
        "event_required_neurons": assignment_counts["event_required"],
        "dual_unresolved_neurons": assignment_counts["dual_unresolved"],
        "graded_required_neurons": assignment_counts["graded_required"],
        "excluded_neurons": assignment_counts["excluded"],
        "parameter_values_emitted": 0,
        "unmatched_neurons": 0,
    }
    expected_totals = {
        "populations": int(acceptance["expected_populations"]),
        "neurons": int(acceptance["expected_neurons"]),
        "event_required_neurons": int(acceptance["expected_event_required_neurons"]),
        "dual_unresolved_neurons": int(acceptance["expected_dual_unresolved_neurons"]),
        "graded_required_neurons": int(acceptance["expected_graded_required_neurons"]),
        "excluded_neurons": int(acceptance["expected_excluded_neurons"]),
        "parameter_values_emitted": int(acceptance["expected_parameter_values_emitted"]),
        "unmatched_neurons": int(acceptance["expected_unmatched_neurons"]),
    }
    for key, expected in expected_totals.items():
        if totals[key] != expected:
            raise PopulationDynamicsAssignmentError(
                f"Acceptance mismatch for {key}: expected {expected}, got {totals[key]}"
            )

    semantic_payload = {
        "recipe_id": recipe["id"],
        "input_hashes": input_hashes,
        "populations": population_summaries,
        "totals": totals,
        "members": member_records,
    }
    semantic_hash = _canonical_hash(semantic_payload)
    summary = {
        "schema_version": 1,
        "recipe_id": recipe["id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "claim_label": recipe["claim_label"],
        "status": "accepted_partial_assignment_motor_event_sensory_dual_unresolved",
        "input_hashes": input_hashes,
        "recipe_sha256": _sha256_file(recipe_path),
        "semantic_result_sha256": semantic_hash,
        "populations": population_summaries,
        "totals": totals,
        "behavior_exposure": recipe["behavior_exposure"],
        "accepted_claims": [
            "All 46 scoped canonical neurons and their accepted terminal routes are accounted.",
            "The T1 tibia-flexor motor pool requires an event-capable representation at class level.",
            "The selected FeCO population remains dual-unresolved because available local evidence does not identify native event versus graded dynamics.",
        ],
        "forbidden_claims": [
            "Any neuron or interface parameter value has been calibrated.",
            "Every MaleCNS motor or sensory population has the same dynamics class.",
            "The exact experimental motor neurons are individually crosswalked to all selected bodyIds.",
            "A leg behavior or actuator trajectory has been reproduced or inspected.",
        ],
        "next_action": recipe["next_action"],
    }

    print("[4/5] Ecriture des artefacts derives auditables", flush=True)
    output_root.mkdir(parents=True, exist_ok=True)
    member_path = output_root / "population-members.csv"
    summary_path = output_root / "summary.json"
    pd.DataFrame.from_records(member_records).to_csv(member_path, index=False)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[OK] {member_path}", flush=True)
    print(f"[OK] {summary_path}", flush=True)

    print("[5/5] Resume", flush=True)
    print(
        f"[OK] {totals['neurons']} neurones: "
        f"{totals['event_required_neurons']} event_required, "
        f"{totals['dual_unresolved_neurons']} dual_unresolved",
        flush=True,
    )
    print("[OK] 0 exception, 0 valeur de parametre, 0 comportement", flush=True)
    print(f"[HASH] {semantic_hash}", flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Account front-leg population dynamics assignments without fitting values"
    )
    parser.add_argument("--recipe", type=Path, default=RECIPE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    compile_population_dynamics_assignments(args.recipe, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

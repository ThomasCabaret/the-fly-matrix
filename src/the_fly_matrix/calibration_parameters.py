from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml

from .ledger import ROOT


CONTRACT_PATH = ROOT / "calibration" / "compilers" / "peripheral-routing-transfer-v0.yaml"


class ParameterCompilationError(ValueError):
    """Raised when logical parameters do not satisfy a frozen compiler contract."""


@dataclass(frozen=True)
class CompiledParameterVector:
    family_id: str
    parameter_ids: tuple[str, ...]
    values: np.ndarray


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _route_keys(frame: pd.DataFrame, columns: Sequence[str]) -> pd.Series:
    if not columns:
        raise ParameterCompilationError("route_key_columns cannot be empty")
    values = frame[list(columns)].fillna("").astype(str)
    if len(columns) == 1:
        return values.iloc[:, 0]
    return values.apply(
        lambda row: json.dumps(row.tolist(), ensure_ascii=True, separators=(",", ":")),
        axis=1,
    )


def load_compiler_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("families"), dict):
        raise ParameterCompilationError(f"Invalid compiler contract: {path}")
    return value


def load_candidate_frame(spec: Mapping[str, Any], root: Path = ROOT) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for source in spec["candidate_sources"]:
        path = root / source["path"]
        if not path.is_file():
            raise ParameterCompilationError(f"Missing candidate source: {path}")
        observed = _sha256_file(path)
        if observed != source["sha256"]:
            raise ParameterCompilationError(
                f"Candidate source drift for {path}: expected {source['sha256']}, got {observed}"
            )
        frames.append(pd.read_parquet(path))
    if not frames:
        raise ParameterCompilationError("A compiler family must declare candidate sources")
    frame = pd.concat(frames, ignore_index=True)
    sort_columns = list(spec["runtime_sort_columns"])
    missing = set(sort_columns) - set(frame)
    if missing:
        raise ParameterCompilationError(f"Candidate manifest misses sort columns: {sorted(missing)}")
    return frame.sort_values(sort_columns).reset_index(drop=True)


def validate_family_boundary(
    family_id: str, spec: Mapping[str, Any], root: Path = ROOT
) -> None:
    path = root / str(spec["parameter_family_record"])
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or record.get("id") != family_id:
        raise ParameterCompilationError(f"Compiler family record mismatch: {path}")
    observed = record.get("scope", {}).get("topology_snapshot", {}).get(
        "semantic_topology_sha256"
    )
    expected = spec.get("topology_semantic_sha256")
    if observed != expected:
        raise ParameterCompilationError(
            f"Topology boundary mismatch for {family_id}: expected {expected}, got {observed}"
        )


def validate_candidate_contract(frame: pd.DataFrame, spec: Mapping[str, Any]) -> dict[str, int]:
    runtime_id = str(spec["runtime_parameter_id_column"])
    group_column = str(spec["route_group_column"])
    route_columns = list(spec["route_key_columns"])
    required = {runtime_id, group_column, *route_columns}
    if missing := required - set(frame):
        raise ParameterCompilationError(f"Candidate manifest misses columns: {sorted(missing)}")
    runtime_ids = frame[runtime_id].astype(str)
    if runtime_ids.duplicated().any():
        raise ParameterCompilationError("Runtime parameter IDs must be unique")
    route_keys = _route_keys(frame, route_columns)
    route_groups = frame[group_column].astype(str)
    group_per_route = pd.DataFrame({"route": route_keys, "group": route_groups}).drop_duplicates()
    if group_per_route["route"].duplicated().any():
        raise ParameterCompilationError("A logical route belongs to more than one route group")
    observed = {
        "runtime_coefficients": len(frame),
        "logical_routes": int(route_keys.nunique()),
        "route_groups": int(route_groups.nunique()),
    }
    expected = {key: int(value) for key, value in spec["expected_counts"].items()}
    if observed != expected:
        raise ParameterCompilationError(
            f"Candidate accounting drift: expected {expected}, got {observed}"
        )
    return observed


def compile_factorized_parameters(
    *,
    family_id: str,
    candidates: pd.DataFrame,
    spec: Mapping[str, Any],
    routing_weights: Mapping[str, float],
    transfer_assignment: Mapping[str, str],
    transfer_values: Mapping[str, float],
    simplex_tolerance: float = 1e-9,
) -> CompiledParameterVector:
    """Compile separate route and transfer parameters into the current runtime vector.

    Routing is normalized once per logical route group. A logical route may expand
    to several runtime coefficients (the motor case). Transfer sharing is explicit
    through ``transfer_assignment`` and is never inferred by this function.
    """
    validate_candidate_contract(candidates, spec)
    runtime_id = str(spec["runtime_parameter_id_column"])
    group_column = str(spec["route_group_column"])
    route_keys = _route_keys(candidates, list(spec["route_key_columns"]))
    runtime_ids = tuple(candidates[runtime_id].astype(str))
    logical_routes = set(route_keys)
    supplied_routes = set(routing_weights)
    if logical_routes != supplied_routes:
        raise ParameterCompilationError(
            "Routing key mismatch: "
            f"missing={len(logical_routes - supplied_routes)}, "
            f"extra={len(supplied_routes - logical_routes)}"
        )
    route_values = pd.Series(
        [routing_weights[key] for key in route_keys], dtype=np.float64
    )
    if not np.isfinite(route_values).all() or (route_values < 0.0).any():
        raise ParameterCompilationError("Routing weights must be finite and non-negative")
    route_table = pd.DataFrame(
        {
            "route": route_keys,
            "group": candidates[group_column].astype(str),
            "weight": route_values,
        }
    ).drop_duplicates(subset=["route"])
    group_sums = route_table.groupby("group", sort=True)["weight"].sum()
    bad_groups = group_sums.index[~np.isclose(group_sums, 1.0, atol=simplex_tolerance, rtol=0.0)]
    if len(bad_groups):
        raise ParameterCompilationError(
            f"Routing simplex violation in {len(bad_groups)} groups; first={bad_groups[0]}"
        )

    assignment_ids = set(transfer_assignment)
    runtime_id_set = set(runtime_ids)
    if assignment_ids != runtime_id_set:
        raise ParameterCompilationError(
            "Transfer-assignment key mismatch: "
            f"missing={len(runtime_id_set - assignment_ids)}, "
            f"extra={len(assignment_ids - runtime_id_set)}"
        )
    transfer_keys = [str(transfer_assignment[item]) for item in runtime_ids]
    if any(not key for key in transfer_keys):
        raise ParameterCompilationError("Transfer keys must be non-empty")
    required_transfers = set(transfer_keys)
    supplied_transfers = set(transfer_values)
    if required_transfers != supplied_transfers:
        raise ParameterCompilationError(
            "Transfer-value key mismatch: "
            f"missing={len(required_transfers - supplied_transfers)}, "
            f"extra={len(supplied_transfers - required_transfers)}"
        )
    gains = np.asarray([transfer_values[key] for key in transfer_keys], dtype=np.float64)
    if not np.isfinite(gains).all():
        raise ParameterCompilationError("Transfer values must be finite")
    values = route_values.to_numpy(dtype=np.float64) * gains
    values.setflags(write=False)
    return CompiledParameterVector(family_id, runtime_ids, values)


def _synthetic_structure_inputs(
    frame: pd.DataFrame, spec: Mapping[str, Any]
) -> tuple[dict[str, float], dict[str, str], dict[str, float]]:
    """Create non-persistent unit/simplex values for compiler structure tests only."""
    route_keys = _route_keys(frame, list(spec["route_key_columns"]))
    groups = frame[str(spec["route_group_column"])].astype(str)
    route_table = pd.DataFrame({"route": route_keys, "group": groups}).drop_duplicates()
    counts = route_table.groupby("group")["route"].transform("count")
    routing = dict(zip(route_table["route"], 1.0 / counts.to_numpy(dtype=np.float64)))
    runtime_ids = frame[str(spec["runtime_parameter_id_column"])].astype(str)
    assignment = dict(zip(runtime_ids, groups.map(lambda item: f"test-only::{item}")))
    transfer = {key: 1.0 for key in assignment.values()}
    return routing, assignment, transfer


def validate_all_contracts(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    contract = load_compiler_contract(path)
    results: dict[str, Any] = {}
    for family_id, spec in contract["families"].items():
        validate_family_boundary(family_id, spec)
        frame = load_candidate_frame(spec)
        counts = validate_candidate_contract(frame, spec)
        routing, assignment, transfer = _synthetic_structure_inputs(frame, spec)
        first = compile_factorized_parameters(
            family_id=family_id,
            candidates=frame,
            spec=spec,
            routing_weights=routing,
            transfer_assignment=assignment,
            transfer_values=transfer,
        )
        second = compile_factorized_parameters(
            family_id=family_id,
            candidates=frame,
            spec=spec,
            routing_weights=routing,
            transfer_assignment=assignment,
            transfer_values=transfer,
        )
        if first.parameter_ids != second.parameter_ids or not np.array_equal(
            first.values, second.values
        ):
            raise ParameterCompilationError(f"Non-deterministic compilation for {family_id}")
        results[family_id] = {
            **counts,
            "synthetic_test_transfer_keys": len(transfer),
            "deterministic": True,
        }
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate routing/transfer parameter compiler contracts"
    )
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    args = parser.parse_args()
    print("PARAMETER COMPILER STRUCTURE TEST ONLY / NOT CALIBRATION")
    print("[1/3] Verifying frozen candidate manifests and topology boundaries...")
    try:
        results = validate_all_contracts(args.contract)
    except Exception as exc:
        print(f"PARAMETER_COMPILER_FAILED: {type(exc).__name__}: {exc}")
        return 1
    print("[2/3] Compiling explicit synthetic simplexes and unit transfers twice...")
    for family_id, result in results.items():
        print(
            f"[OK] {family_id}: {result['route_groups']:,} groups, "
            f"{result['logical_routes']:,} logical routes -> "
            f"{result['runtime_coefficients']:,} runtime coefficients"
        )
    print("[3/3] Checking deterministic order and exact parameter accounting...")
    print("PARAMETER_COMPILER_OK: structure verified; no value fitted or persisted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

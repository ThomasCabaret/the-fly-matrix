from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .ledger import ROOT
from .wiring_revalidation import apply_rules, match_frame


DEFAULT_RULESET = ROOT / "wiring" / "revalidation" / "motor-output-v1.yaml"
DEFAULT_EXCEPTIONS = ROOT / "wiring" / "revalidation" / "motor-output-exceptions-v1.yaml"
DEFAULT_CURRENT_CANDIDATES = ROOT / "data" / "derived" / "wiring" / "motor-actuator-candidates.parquet"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_id(prefix: str, payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}.{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:16]}"


def _clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return "(unknown)"
    return str(value)


def _actuator_side(name: str) -> str:
    for pattern, side in (
        (r"(?:^|-)l(?:f|m|h)_", "L"),
        (r"(?:^|-)r(?:f|m|h)_", "R"),
        (r"-l_(?:wing|haltere|antenna|labrum)-", "L"),
        (r"-r_(?:wing|haltere|antenna|labrum)-", "R"),
    ):
        if re.search(pattern, name):
            return side
    return "neutral"


def _leg_position(name: str) -> str | None:
    match = re.search(r"(?:^|-)(?:l|r)([fmh])_", name)
    if match is None:
        return None
    return {"f": "front", "m": "middle", "h": "hind"}[match.group(1)]


def _select_actuators(
    actuators: pd.DataFrame, selector: dict[str, Any] | None, side: str
) -> pd.DataFrame:
    if selector is None:
        return actuators.iloc[0:0].copy()
    selected = actuators.loc[actuators["body_group"].eq(selector["body_group"])].copy()
    if "leg_position" in selector:
        selected = selected.loc[
            selected["actuator_name"].map(_leg_position).eq(selector["leg_position"])
        ]
    policy = str(selector.get("side_policy", "neutral"))
    actuator_sides = selected["actuator_name"].map(_actuator_side)
    if policy == "same":
        selected = selected.loc[actuator_sides.eq(side)]
    elif policy == "neutral":
        selected = selected.loc[actuator_sides.eq("neutral")]
    elif policy == "neutral_or_same":
        selected = selected.loc[actuator_sides.isin(["neutral", side])]
    else:
        raise RuntimeError(f"Unsupported side policy: {policy}")
    return selected.sort_values(["control_address", "actuator_id"]).reset_index(drop=True)


def _motor_groups(annotations: pd.DataFrame, scope_selector: dict[str, Any]) -> list[dict[str, Any]]:
    selected = annotations.loc[match_frame(annotations, scope_selector)].copy()
    selected["grouping_type"] = selected["type"].fillna("(unknown)").astype(str)
    unknown = selected["grouping_type"].eq("(unknown)")
    selected.loc[unknown, "grouping_type"] = selected.loc[unknown, "bodyId"].map(
        lambda body_id: f"(unknown bodyId={int(body_id)})"
    )
    groups: list[dict[str, Any]] = []
    for (subclass, grouping_type, side), members in selected.groupby(
        ["subclass", "grouping_type", "somaSide"], dropna=False, sort=True
    ):
        body_ids = tuple(sorted(members["bodyId"].astype(int)))
        record = {
            "independent_group_id": _stable_id(
                "review.motor.group", [str(subclass), str(grouping_type), str(side), body_ids]
            ),
            "subclass": _clean(subclass),
            "grouping_type": _clean(grouping_type),
            "type": _clean(members["type"].iloc[0]),
            "somaSide": _clean(side),
            "member_body_ids": body_ids,
            "member_count": len(body_ids),
        }
        for field in ("superclass", "exitNerve", "mancType", "somaNeuromere"):
            values = sorted(set(members[field].map(_clean)))
            record[field] = values[0] if len(values) == 1 else " | ".join(values)
        groups.append(record)
    return groups


def _semantic_hash(decisions: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
    payload = {
        "groups": sorted(
            (
                tuple(item["member_body_ids"]),
                item["terminal_disposition"],
                item["rule_id"],
            )
            for item in decisions
        ),
        "edges": sorted(
            (
                tuple(item["source_body_ids"]),
                int(item["actuator_id"]),
                item["actuator_name"],
                item["rule_id"],
            )
            for item in edges
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _quantiles(values: list[int]) -> dict[str, float]:
    series = pd.Series(values, dtype="float64")
    return {
        "mean": float(series.mean()),
        "p50": float(series.quantile(0.50)),
        "p90": float(series.quantile(0.90)),
        "p95": float(series.quantile(0.95)),
        "max": float(series.max()),
    }


def build_motor_output_envelope(
    output_dir: Path,
    ruleset_path: Path = DEFAULT_RULESET,
    exceptions_path: Path = DEFAULT_EXCEPTIONS,
) -> dict[str, Any]:
    """Build motor output topology without opening the executable prewiring."""
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RuntimeError(f"Clean-build destination is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    ruleset = yaml.safe_load(ruleset_path.read_text(encoding="utf-8"))
    exceptions = yaml.safe_load(exceptions_path.read_text(encoding="utf-8"))
    if int(ruleset.get("schema_version", 0)) != 1:
        raise RuntimeError("Unsupported motor-output ruleset schema")
    if int(exceptions.get("schema_version", 0)) != 1:
        raise RuntimeError("Unsupported motor-output exception schema")
    if exceptions.get("entries"):
        raise RuntimeError("motor-output exception application is not implemented; refusing fallback")

    source_paths = {
        name: ROOT / source["path"] for name, source in ruleset["sources"].items()
    }
    for name, path in source_paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"Missing motor-output source {name}: {path}")

    annotations = pd.read_feather(source_paths["annotations"])
    population = pd.read_parquet(source_paths["population_scope"])
    actuators = pd.read_csv(source_paths["actuators"])
    canonical_ids = set(
        population.loc[population["is_canonical_neuron"], "body_id"].astype(int)
    )
    if len(canonical_ids) != 166_700:
        raise RuntimeError(f"Expected 166700 canonical neurons, found {len(canonical_ids)}")
    if len(actuators) != 102 or actuators["actuator_id"].duplicated().any():
        raise RuntimeError("FlyBody actuator inventory must contain 102 unique actuator IDs")

    groups = _motor_groups(annotations, ruleset["scope"])
    terminal_ids = {body_id for group in groups for body_id in group["member_body_ids"]}
    if len(terminal_ids) != 815:
        raise RuntimeError(f"Expected 815 motor terminals, found {len(terminal_ids)}")
    if terminal_ids - canonical_ids:
        raise RuntimeError("Motor scope contains noncanonical annotated bodies")
    if sum(group["member_count"] for group in groups) != len(terminal_ids):
        raise RuntimeError("Motor grouping is not lossless and disjoint")

    decisions: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    rule_counts: Counter[str] = Counter()
    relation_counts: Counter[str] = Counter()
    disposition_counts: Counter[str] = Counter()
    unexpected: list[dict[str, Any]] = []

    for group in groups:
        rule, matched, error = apply_rules(group, ruleset["rules"])
        if error is not None or rule is None:
            unexpected.append(
                {
                    "group_id": group["independent_group_id"],
                    "code": error or "no_rule_matched",
                    "matched_rule_ids": matched,
                }
            )
            continue
        candidate_actuators = _select_actuators(
            actuators, rule.get("actuator_selector"), str(group["somaSide"])
        )
        disposition = str(rule["terminal_disposition"])
        if disposition == "parameterized" and candidate_actuators.empty:
            unexpected.append(
                {
                    "group_id": group["independent_group_id"],
                    "code": "empty_parameterized_candidate_set",
                    "matched_rule_ids": matched,
                }
            )
            continue
        if disposition == "sink" and not candidate_actuators.empty:
            unexpected.append(
                {
                    "group_id": group["independent_group_id"],
                    "code": "sink_has_candidates",
                    "matched_rule_ids": matched,
                }
            )
            continue

        decision = dict(group)
        decision.update(
            {
                "rule_id": str(rule["id"]),
                "matched_rule_ids": tuple(matched),
                "outcome": str(rule["outcome"]),
                "relation_class": str(rule["relation_class"]),
                "terminal_disposition": disposition,
                "provenance_kind": str(rule["provenance_kind"]),
                "source_references": tuple(map(str, rule.get("source_references", []))),
                "used_claim": str(rule["used_claim"]),
                "candidate_count": len(candidate_actuators),
            }
        )
        decisions.append(decision)
        rule_counts[str(rule["id"])] += 1
        relation_counts[str(rule["relation_class"])] += 1
        disposition_counts[disposition] += 1

        for actuator in candidate_actuators.itertuples(index=False):
            edge_key = [group["member_body_ids"], int(actuator.actuator_id)]
            edges.append(
                {
                    "independent_edge_id": _stable_id("review.motor.edge", edge_key),
                    "independent_group_id": group["independent_group_id"],
                    "source_body_ids": group["member_body_ids"],
                    "source_member_count": group["member_count"],
                    "subclass": group["subclass"],
                    "grouping_type": group["grouping_type"],
                    "soma_side": group["somaSide"],
                    "actuator_id": int(actuator.actuator_id),
                    "actuator_name": str(actuator.actuator_name),
                    "control_address": int(actuator.control_address),
                    "target_joint_name": str(actuator.target_joint_name),
                    "actuator_body_group": str(actuator.body_group),
                    "rule_id": str(rule["id"]),
                    "relation_class": str(rule["relation_class"]),
                    "routing_parameter_id": _stable_id("route.motor", edge_key),
                    "transfer_parameter_count": int(group["member_count"]),
                }
            )

    if unexpected:
        (output_dir / "unexpected-exceptions.json").write_text(
            json.dumps(unexpected, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        raise RuntimeError(f"Motor-output reconstruction has {len(unexpected)} exceptions")

    edges_by_group = Counter(item["independent_group_id"] for item in edges)
    topography_violations: list[str] = []
    for decision in decisions:
        if edges_by_group[decision["independent_group_id"]] != decision["candidate_count"]:
            topography_violations.append(decision["independent_group_id"])

    mirror: dict[tuple[str, str], dict[str, int]] = {}
    for decision in decisions:
        side = str(decision["somaSide"])
        if side not in {"L", "R"}:
            continue
        mirror.setdefault((decision["subclass"], decision["grouping_type"]), {})[side] = int(
            decision["candidate_count"]
        )
    symmetry_violations = [
        {"subclass": key[0], "grouping_type": key[1], "candidate_counts": sides}
        for key, sides in sorted(mirror.items())
        if set(sides) == {"L", "R"} and sides["L"] != sides["R"]
    ]
    covered_actuators = {int(item["actuator_id"]) for item in edges}
    uncovered_actuators = sorted(set(actuators["actuator_id"].astype(int)) - covered_actuators)
    if topography_violations or symmetry_violations or uncovered_actuators:
        raise RuntimeError(
            "Motor-output negative constraints failed: "
            f"topography={len(topography_violations)}, symmetry={len(symmetry_violations)}, "
            f"uncovered_actuators={len(uncovered_actuators)}"
        )

    semantic_hash = _semantic_hash(decisions, edges)
    parameterized_sizes = [
        int(item["candidate_count"])
        for item in decisions
        if item["terminal_disposition"] == "parameterized"
    ]
    expanded_terminal_actuator_relations = sum(
        int(item["member_count"]) * int(item["candidate_count"])
        for item in decisions
        if item["terminal_disposition"] == "parameterized"
    )
    summary = {
        "schema_version": 1,
        "ruleset_id": str(ruleset["id"]),
        "ruleset_sha256": _sha256_file(ruleset_path),
        "exceptions_id": str(exceptions["id"]),
        "exceptions_sha256": _sha256_file(exceptions_path),
        "source_hashes": {
            name: {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": _sha256_file(path)}
            for name, path in source_paths.items()
        },
        "claim": str(ruleset["claim"]),
        "status": "independently_reconstructed_not_yet_compared",
        "semantic_topology_sha256": semantic_hash,
        "terminal_count": len(terminal_ids),
        "group_count": len(decisions),
        "candidate_edge_count": len(edges),
        "covered_actuator_count": len(covered_actuators),
        "sink_group_count": disposition_counts["sink"],
        "parameterized_group_count": disposition_counts["parameterized"],
        "rule_counts": dict(rule_counts),
        "relation_class_counts": dict(relation_counts),
        "disposition_counts": dict(disposition_counts),
        "candidate_set_statistics": _quantiles(parameterized_sizes),
        "degrees_of_freedom": {
            "candidate_membership_bits": len(edges),
            "routing_simplex_dimensions": sum(max(size - 1, 0) for size in parameterized_sizes),
            "continuous_transfer_parameters": expanded_terminal_actuator_relations,
        },
        "negative_constraints": {
            "topography_violations": topography_violations,
            "uncovered_actuator_ids": uncovered_actuators,
            "pass": not topography_violations and not uncovered_actuators,
        },
        "symmetry": {
            "paired_group_keys_checked": sum(set(sides) == {"L", "R"} for sides in mirror.values()),
            "violations": symmetry_violations,
            "pass": not symmetry_violations,
        },
        "singular_exception_count": len(exceptions.get("entries", [])),
        "masked_gold_standard": ruleset["gold_standard"],
        "accepted_for_calibration": False,
        "next_action": (
            "Compare this finalized hash and relation set against executable prewiring, classify "
            "every difference, repeat the clean build, and compile the accepted topology into runtime."
        ),
    }

    decision_frame = pd.DataFrame(decisions).copy()
    decision_frame["member_body_ids"] = decision_frame["member_body_ids"].map(
        lambda values: ",".join(map(str, values))
    )
    decision_frame["matched_rule_ids"] = decision_frame["matched_rule_ids"].map(
        lambda values: ",".join(values)
    )
    decision_frame["source_references"] = decision_frame["source_references"].map(
        lambda values: ",".join(values)
    )
    edge_frame = pd.DataFrame(edges).copy()
    edge_frame["source_body_ids"] = edge_frame["source_body_ids"].map(
        lambda values: ",".join(map(str, values))
    )
    decision_frame.sort_values("independent_group_id").to_parquet(
        output_dir / "group-decisions.parquet", index=False
    )
    edge_frame.sort_values(["independent_group_id", "actuator_id"]).to_parquet(
        output_dir / "candidate-edges.parquet", index=False
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def compare_motor_output_with_prewiring(
    output_dir: Path,
    current_path: Path = DEFAULT_CURRENT_CANDIDATES,
    ruleset_path: Path = DEFAULT_RULESET,
    exceptions_path: Path = DEFAULT_EXCEPTIONS,
) -> dict[str, Any]:
    """Compare only after a clean result and its semantic hash exist on disk."""
    output_dir = output_dir.resolve()
    summary_path = output_dir / "summary.json"
    candidate_path = output_dir / "candidate-edges.parquet"
    if not summary_path.is_file() or not candidate_path.is_file():
        raise RuntimeError("Independent motor output and semantic hash must exist before comparison")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    finalized_hash = str(summary["semantic_topology_sha256"])

    with tempfile.TemporaryDirectory(prefix="flymatrix-motor-repeat-") as temporary:
        repeated = build_motor_output_envelope(
            Path(temporary), ruleset_path=ruleset_path, exceptions_path=exceptions_path
        )
    repeat_hash = str(repeated["semantic_topology_sha256"])
    repeat_pass = repeat_hash == finalized_hash

    # This is deliberately the first point at which the executable candidate
    # matrix is opened. It cannot influence the independent builder above.
    independent = pd.read_parquet(candidate_path)
    current = pd.read_parquet(current_path)
    required = {"source_body_id", "target_actuator_id"}
    if not required.issubset(current.columns):
        raise RuntimeError(f"Current motor candidates miss columns: {sorted(required - set(current.columns))}")

    independent_relations: set[tuple[int, int]] = set()
    for row in independent.itertuples(index=False):
        for body_id in str(row.source_body_ids).split(","):
            independent_relations.add((int(body_id), int(row.actuator_id)))
    current_pairs = [
        (int(row.source_body_id), int(row.target_actuator_id))
        for row in current.itertuples(index=False)
    ]
    current_relations = set(current_pairs)
    duplicate_current_relations = len(current_pairs) - len(current_relations)
    missing_from_current = sorted(independent_relations - current_relations)
    extra_in_current = sorted(current_relations - independent_relations)
    confirmed = sorted(independent_relations & current_relations)

    difference_rows = [
        {"source_body_id": body_id, "target_actuator_id": actuator_id, "classification": "add_to_current"}
        for body_id, actuator_id in missing_from_current
    ] + [
        {"source_body_id": body_id, "target_actuator_id": actuator_id, "classification": "remove_from_current"}
        for body_id, actuator_id in extra_in_current
    ]
    pd.DataFrame(
        difference_rows,
        columns=["source_body_id", "target_actuator_id", "classification"],
    ).to_parquet(output_dir / "relation-differences.parquet", index=False)

    relation_pass = (
        not missing_from_current
        and not extra_in_current
        and duplicate_current_relations == 0
    )
    independently_validated = (
        repeat_pass
        and relation_pass
        and bool(summary["negative_constraints"]["pass"])
        and bool(summary["symmetry"]["pass"])
        and int(summary["singular_exception_count"]) == 0
    )
    comparison = {
        "current_path": str(current_path.relative_to(ROOT)).replace("\\", "/"),
        "current_sha256": _sha256_file(current_path),
        "independent_terminal_actuator_relations": len(independent_relations),
        "current_terminal_actuator_relations": len(current_relations),
        "confirmed_relations": len(confirmed),
        "missing_from_current": len(missing_from_current),
        "extra_in_current": len(extra_in_current),
        "duplicate_current_relations": duplicate_current_relations,
        "representative_missing": missing_from_current[:20],
        "representative_extra": extra_in_current[:20],
        "pass": relation_pass,
    }
    summary.update(
        {
            "status": "independently_validated" if independently_validated else "comparison_failed",
            "clean_rebuild_repeat": {
                "first_semantic_topology_sha256": finalized_hash,
                "second_semantic_topology_sha256": repeat_hash,
                "pass": repeat_pass,
            },
            "prewiring_comparison": comparison,
            "topology_independently_validated": independently_validated,
            "accepted_for_calibration": False,
            "calibration_blocker": (
                "The global scientific_wiring_revalidation remains open for other interface "
                "families; transfer parameters also remain uncalibrated."
            ),
            "next_action": (
                "Keep this motor topology frozen by semantic hash while independently rebuilding "
                "the remaining input candidate families."
                if independently_validated
                else "Classify and resolve every motor prewiring relation difference."
            ),
        }
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "prewiring-comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary

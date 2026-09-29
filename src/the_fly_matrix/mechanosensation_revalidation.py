from __future__ import annotations

import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .ledger import ROOT
from .wiring_revalidation import apply_rules, match_frame


DEFAULT_RULESET = ROOT / "wiring" / "revalidation" / "mechanosensation-v1.yaml"
DEFAULT_EXCEPTIONS = (
    ROOT / "wiring" / "revalidation" / "mechanosensation-exceptions-v1.yaml"
)
DEFAULT_CURRENT_CANDIDATES = (
    ROOT / "data" / "derived" / "wiring" / "mechanosensation-input-candidates.parquet"
)
DEFAULT_CURRENT_ROUTES = (
    ROOT / "data" / "derived" / "wiring" / "mechanosensation-routes.parquet"
)

LEG_COMPONENTS = (
    "found",
    "force_contact_x",
    "force_contact_y",
    "force_contact_z",
    "torque_contact_x",
    "torque_contact_y",
    "torque_contact_z",
)
LOCAL_CONTACT_COMPONENTS = ("force_world_x", "force_world_y", "force_world_z")


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
    if value is None or pd.isna(value) or str(value) == "":
        return "(unknown)"
    return str(value)


def _family(neuron_class: str) -> str:
    return {
        "mechanosensory_tactile": "sensory.tactile",
        "mechanosensory": "sensory.mechanosensory_other",
    }[neuron_class]


def _groups(annotations: pd.DataFrame, selector: dict[str, Any]) -> list[dict[str, Any]]:
    selected = annotations.loc[match_frame(annotations, selector)].copy()
    selected["family"] = selected["class"].map(_family)
    fields = ["family", "entryNerve", "subclass", "mancType", "type", "rootSide"]
    for field in fields:
        selected[field] = selected[field].map(_clean)

    groups: list[dict[str, Any]] = []
    for key, members in selected.groupby(fields, dropna=False, sort=True):
        body_ids = tuple(sorted(members["bodyId"].astype(int)))
        record = dict(zip(fields, map(str, key), strict=True))
        record.update(
            {
                "independent_group_id": _stable_id(
                    "review.mechanosensation.group", [*map(str, key), body_ids]
                ),
                "class": _clean(members["class"].iloc[0]),
                "member_body_ids": body_ids,
                "member_count": len(body_ids),
            }
        )
        groups.append(record)
    return groups


def _side_token(side: str) -> str:
    if side not in {"L", "R"}:
        raise RuntimeError(f"Unsupported root side: {side}")
    return side.lower()


def _leg_code(position: str, side: str) -> str:
    return _side_token(side) + {"front": "f", "middle": "m", "hind": "h"}[position]


def _joint_side(name: str) -> str:
    if any(token in name for token in ("-lf_", "-lm_", "-lh_", "-l_wing", "-l_haltere", "-l_antenna", "-l_labrum")):
        return "L"
    if any(token in name for token in ("-rf_", "-rm_", "-rh_", "-r_wing", "-r_haltere", "-r_antenna", "-r_labrum")):
        return "R"
    return "neutral"


def _physical_observables(
    leg_contacts: pd.DataFrame,
    local_contacts: pd.DataFrame,
    joint_state: pd.DataFrame,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for row in leg_contacts.itertuples(index=False):
        for component in LEG_COMPONENTS:
            records.append(
                {
                    "observable_id": f"{row.channel_id}.{component}",
                    "kind": "leg_contact",
                    "body_group": "legs",
                    "side": str(row.leg)[0].upper(),
                    "leg": str(row.leg),
                    "segment_name": "",
                    "joint_id": -1,
                    "joint_name": "",
                    "component": component,
                    "source_channel_id": str(row.channel_id),
                }
            )
    for row in local_contacts.itertuples(index=False):
        for component in LOCAL_CONTACT_COMPONENTS:
            records.append(
                {
                    "observable_id": f"{row.channel_id}.{component}",
                    "kind": "local_contact",
                    "body_group": str(row.body_group),
                    "side": "neutral",
                    "leg": "",
                    "segment_name": str(row.segment_name),
                    "joint_id": -1,
                    "joint_name": "",
                    "component": component,
                    "source_channel_id": str(row.channel_id),
                }
            )
    for row in joint_state.itertuples(index=False):
        for component in ("position", "velocity"):
            records.append(
                {
                    "observable_id": f"{row.channel_id}.{component}",
                    "kind": "joint_state",
                    "body_group": str(row.body_group),
                    "side": _joint_side(str(row.joint_name)),
                    "leg": "",
                    "segment_name": "",
                    "joint_id": int(row.joint_id),
                    "joint_name": str(row.joint_name),
                    "component": component,
                    "source_channel_id": str(row.channel_id),
                }
            )
    frame = pd.DataFrame(records)
    if frame["observable_id"].duplicated().any():
        raise RuntimeError("Physical observable IDs are not unique")
    return frame.sort_values("observable_id").reset_index(drop=True)


def _select_observables(
    observables: pd.DataFrame, selector: dict[str, Any], side: str
) -> pd.DataFrame:
    selected = observables.loc[observables["kind"].eq(str(selector["kind"]))].copy()
    if "body_group" in selector:
        selected = selected.loc[selected["body_group"].eq(str(selector["body_group"]))]
    if "segment_name" in selector:
        selected = selected.loc[selected["segment_name"].eq(str(selector["segment_name"]))]
    if "leg_position" in selector:
        selected = selected.loc[selected["leg"].eq(_leg_code(str(selector["leg_position"]), side))]
    side_policy = str(selector.get("side_policy", "neutral"))
    if side_policy == "same":
        selected = selected.loc[selected["side"].eq(side)]
    elif side_policy == "neutral":
        selected = selected.loc[selected["side"].eq("neutral")]
    elif side_policy == "neutral_or_same":
        selected = selected.loc[selected["side"].isin(["neutral", side])]
    else:
        raise RuntimeError(f"Unsupported side policy: {side_policy}")
    return selected.sort_values("observable_id").reset_index(drop=True)


def _semantic_hash(decisions: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
    payload = {
        "groups": sorted(
            (tuple(item["member_body_ids"]), item["terminal_disposition"], item["rule_id"])
            for item in decisions
        ),
        "edges": sorted(
            (
                tuple(item["target_body_ids"]),
                item["observable_id"],
                item["rule_id"],
                item["relation_class"],
            )
            for item in edges
        ),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _quantiles(values: list[int]) -> dict[str, float]:
    series = pd.Series(values, dtype="float64")
    return {
        "mean": float(series.mean()),
        "p50": float(series.quantile(0.50)),
        "p90": float(series.quantile(0.90)),
        "p95": float(series.quantile(0.95)),
        "max": float(series.max()),
    }


def build_mechanosensation_envelope(
    output_dir: Path,
    ruleset_path: Path = DEFAULT_RULESET,
    exceptions_path: Path = DEFAULT_EXCEPTIONS,
) -> dict[str, Any]:
    """Clean-build mechanosensory candidates without opening executable prewiring."""
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RuntimeError(f"Clean-build destination is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    ruleset = yaml.safe_load(ruleset_path.read_text(encoding="utf-8"))
    exceptions = yaml.safe_load(exceptions_path.read_text(encoding="utf-8"))
    if int(ruleset.get("schema_version", 0)) != 1:
        raise RuntimeError("Unsupported mechanosensation ruleset schema")
    if int(exceptions.get("schema_version", 0)) != 1:
        raise RuntimeError("Unsupported mechanosensation exception schema")
    if exceptions.get("entries"):
        raise RuntimeError("Mechanosensation exceptions are not implemented; refusing fallback")

    source_paths = {name: ROOT / item["path"] for name, item in ruleset["sources"].items()}
    for name, path in source_paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"Missing mechanosensation source {name}: {path}")

    annotations = pd.read_feather(source_paths["annotations"])
    population = pd.read_parquet(source_paths["population_scope"])
    leg_contacts = pd.read_csv(source_paths["leg_contacts"])
    local_contacts = pd.read_csv(source_paths["local_contacts"])
    joint_state = pd.read_csv(source_paths["joint_state"])
    canonical_ids = set(population.loc[population["is_canonical_neuron"], "body_id"].astype(int))
    if len(canonical_ids) != 166_700:
        raise RuntimeError(f"Expected 166700 canonical neurons, found {len(canonical_ids)}")

    groups = _groups(annotations, ruleset["scope"])
    terminal_ids = {body_id for group in groups for body_id in group["member_body_ids"]}
    if len(terminal_ids) != 4_291:
        raise RuntimeError(f"Expected 4291 mechanosensory terminals, found {len(terminal_ids)}")
    if len(groups) != 323:
        raise RuntimeError(f"Expected 323 mechanosensory groups, found {len(groups)}")
    if terminal_ids - canonical_ids:
        raise RuntimeError("Mechanosensation scope contains noncanonical annotated bodies")
    if sum(group["member_count"] for group in groups) != len(terminal_ids):
        raise RuntimeError("Mechanosensation grouping is not lossless and disjoint")

    observables = _physical_observables(leg_contacts, local_contacts, joint_state)
    decisions: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    unexpected: list[dict[str, Any]] = []
    rule_counts: Counter[str] = Counter()
    relation_counts: Counter[str] = Counter()

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
        candidates = _select_observables(
            observables, rule["observable_selector"], str(group["rootSide"])
        )
        expected = int(rule["expected_candidate_count"])
        if len(candidates) != expected:
            unexpected.append(
                {
                    "group_id": group["independent_group_id"],
                    "code": "candidate_count_mismatch",
                    "expected": expected,
                    "actual": len(candidates),
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
                "terminal_disposition": str(rule["terminal_disposition"]),
                "provenance_kind": str(rule["provenance_kind"]),
                "source_references": tuple(map(str, rule.get("source_references", []))),
                "used_claim": str(rule["used_claim"]),
                "candidate_count": len(candidates),
            }
        )
        decisions.append(decision)
        rule_counts[str(rule["id"])] += 1
        relation_counts[str(rule["relation_class"])] += 1
        for observable in candidates.itertuples(index=False):
            edge_key = [group["member_body_ids"], str(observable.observable_id)]
            edges.append(
                {
                    "independent_edge_id": _stable_id("review.mechanosensation.edge", edge_key),
                    "independent_group_id": group["independent_group_id"],
                    "target_body_ids": group["member_body_ids"],
                    "target_member_count": group["member_count"],
                    "family": group["family"],
                    "entry_nerve": group["entryNerve"],
                    "subclass": group["subclass"],
                    "root_side": group["rootSide"],
                    "observable_id": str(observable.observable_id),
                    "observable_kind": str(observable.kind),
                    "observable_side": str(observable.side),
                    "observable_leg": str(observable.leg),
                    "observable_segment": str(observable.segment_name),
                    "observable_joint_name": str(observable.joint_name),
                    "observable_component": str(observable.component),
                    "source_channel_id": str(observable.source_channel_id),
                    "rule_id": str(rule["id"]),
                    "relation_class": str(rule["relation_class"]),
                    "routing_parameter_id": _stable_id("route.mechanosensation", edge_key),
                    "transfer_parameter_count": int(group["member_count"]),
                }
            )

    if unexpected:
        (output_dir / "unexpected-exceptions.json").write_text(
            json.dumps(unexpected, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        raise RuntimeError(f"Mechanosensation reconstruction has {len(unexpected)} exceptions")

    edges_by_group = Counter(item["independent_group_id"] for item in edges)
    topography_violations = [
        item["independent_group_id"]
        for item in decisions
        if edges_by_group[item["independent_group_id"]] != int(item["candidate_count"])
    ]
    side_violations = [
        item["independent_edge_id"]
        for item in edges
        if item["observable_side"] not in {"neutral", item["root_side"]}
    ]

    mirror: dict[tuple[str, str, str, str, str], dict[str, int]] = {}
    for decision in decisions:
        side = str(decision["rootSide"])
        if side not in {"L", "R"}:
            continue
        key = (
            str(decision["family"]),
            str(decision["entryNerve"]),
            str(decision["subclass"]),
            str(decision["mancType"]),
            str(decision["type"]),
        )
        mirror.setdefault(key, {})[side] = int(decision["candidate_count"])
    symmetry_violations = [
        {"group_key": list(key), "candidate_counts": sides}
        for key, sides in sorted(mirror.items())
        if set(sides) == {"L", "R"} and sides["L"] != sides["R"]
    ]
    if topography_violations or side_violations or symmetry_violations:
        raise RuntimeError(
            "Mechanosensation negative constraints failed: "
            f"topography={len(topography_violations)}, side={len(side_violations)}, "
            f"symmetry={len(symmetry_violations)}"
        )

    semantic_hash = _semantic_hash(decisions, edges)
    candidate_sizes = [int(item["candidate_count"]) for item in decisions]
    expanded_relations = sum(
        int(item["member_count"]) * int(item["candidate_count"]) for item in decisions
    )
    summary = {
        "schema_version": 1,
        "ruleset_id": str(ruleset["id"]),
        "ruleset_sha256": _sha256_file(ruleset_path),
        "exceptions_id": str(exceptions["id"]),
        "exceptions_sha256": _sha256_file(exceptions_path),
        "source_hashes": {
            name: {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": _sha256_file(path),
            }
            for name, path in source_paths.items()
        },
        "claim": str(ruleset["claim"]),
        "status": "independently_reconstructed_not_yet_compared",
        "semantic_topology_sha256": semantic_hash,
        "terminal_count": len(terminal_ids),
        "group_count": len(decisions),
        "candidate_edge_count": len(edges),
        "expanded_terminal_observable_relations": expanded_relations,
        "represented_observable_count": len({item["observable_id"] for item in edges}),
        "rule_counts": dict(rule_counts),
        "relation_class_counts": dict(relation_counts),
        "disposition_counts": {"parameterized": len(decisions)},
        "candidate_set_statistics": _quantiles(candidate_sizes),
        "degrees_of_freedom": {
            "candidate_membership_bits": len(edges),
            "routing_simplex_dimensions": sum(max(size - 1, 0) for size in candidate_sizes),
            "continuous_transfer_parameters": expanded_relations,
        },
        "negative_constraints": {
            "topography_violations": topography_violations,
            "side_violations": side_violations,
            "pass": not topography_violations and not side_violations,
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
            "Compare this finalized semantic hash and relation set against executable "
            "prewiring, classify every difference, and repeat the clean build."
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
    edge_frame["target_body_ids"] = edge_frame["target_body_ids"].map(
        lambda values: ",".join(map(str, values))
    )
    decision_frame.sort_values("independent_group_id").to_parquet(
        output_dir / "group-decisions.parquet", index=False
    )
    edge_frame.sort_values(["independent_group_id", "observable_id"]).to_parquet(
        output_dir / "candidate-edges.parquet", index=False
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def _current_observable_id(row: Any) -> str:
    component = str(row.source_observable)
    if str(row.source_kind) == "contact_load":
        component = {
            "contact_found": "found",
            "force_x": "force_contact_x",
            "force_y": "force_contact_y",
            "force_z": "force_contact_z",
            "torque_x": "torque_contact_x",
            "torque_y": "torque_contact_y",
            "torque_z": "torque_contact_z",
        }.get(component, "")
    elif str(row.source_kind) == "body_contact":
        component = {
            "force_x": "force_world_x",
            "force_y": "force_world_y",
            "force_z": "force_world_z",
        }.get(component, "")
    elif str(row.source_kind) != "joint_state" or component not in {"position", "velocity"}:
        component = ""
    if not component:
        raise RuntimeError(
            "Unsupported current mechanosensation observable: "
            f"kind={row.source_kind!r}, observable={row.source_observable!r}"
        )
    return f"{row.source_channel_id}.{component}"


def compare_mechanosensation_with_prewiring(
    output_dir: Path,
    current_candidates_path: Path = DEFAULT_CURRENT_CANDIDATES,
    current_routes_path: Path = DEFAULT_CURRENT_ROUTES,
    ruleset_path: Path = DEFAULT_RULESET,
    exceptions_path: Path = DEFAULT_EXCEPTIONS,
) -> dict[str, Any]:
    """Compare only after the independent semantic hash exists on disk."""
    output_dir = output_dir.resolve()
    summary_path = output_dir / "summary.json"
    candidate_path = output_dir / "candidate-edges.parquet"
    if not summary_path.is_file() or not candidate_path.is_file():
        raise RuntimeError(
            "Independent mechanosensation candidates and semantic hash must exist before comparison"
        )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    finalized_hash = str(summary["semantic_topology_sha256"])

    with tempfile.TemporaryDirectory(prefix="flymatrix-mechanosensation-repeat-") as temporary:
        repeated = build_mechanosensation_envelope(
            Path(temporary), ruleset_path=ruleset_path, exceptions_path=exceptions_path
        )
    repeat_hash = str(repeated["semantic_topology_sha256"])
    repeat_pass = repeat_hash == finalized_hash

    # The executable candidate matrix is deliberately opened only after the
    # first semantic hash is finalized and an independent repeat is complete.
    independent = pd.read_parquet(candidate_path)
    current = pd.read_parquet(current_candidates_path)
    routes = pd.read_parquet(current_routes_path)
    required_candidates = {
        "source_kind",
        "source_channel_id",
        "source_observable",
        "target_channel_id",
    }
    required_routes = {"channel_id", "target_body_id"}
    if not required_candidates.issubset(current.columns):
        raise RuntimeError(
            "Current mechanosensation candidates miss columns: "
            f"{sorted(required_candidates - set(current.columns))}"
        )
    if not required_routes.issubset(routes.columns):
        raise RuntimeError(
            f"Current mechanosensation routes miss columns: {sorted(required_routes - set(routes.columns))}"
        )

    bodies_by_channel = {
        str(channel_id): tuple(sorted(rows["target_body_id"].astype(int)))
        for channel_id, rows in routes.groupby("channel_id", sort=True)
    }
    if len(bodies_by_channel) != 323 or sum(map(len, bodies_by_channel.values())) != 4_291:
        raise RuntimeError("Current mechanosensation route inventory is not 323 groups / 4291 terminals")
    missing_channels = set(current["target_channel_id"].astype(str)) - set(bodies_by_channel)
    if missing_channels:
        raise RuntimeError(
            f"Current mechanosensation candidates reference {len(missing_channels)} unknown channels"
        )

    independent_group_pairs = [
        (tuple(map(int, str(row.target_body_ids).split(","))), str(row.observable_id))
        for row in independent.itertuples(index=False)
    ]
    current_group_pairs = [
        (bodies_by_channel[str(row.target_channel_id)], _current_observable_id(row))
        for row in current.itertuples(index=False)
    ]
    independent_group_relations = set(independent_group_pairs)
    current_group_relations = set(current_group_pairs)
    duplicate_independent_group_relations = len(independent_group_pairs) - len(
        independent_group_relations
    )
    duplicate_current_group_relations = len(current_group_pairs) - len(current_group_relations)
    missing_group_relations = sorted(independent_group_relations - current_group_relations)
    extra_group_relations = sorted(current_group_relations - independent_group_relations)

    independent_terminal_relations = {
        (body_id, observable_id)
        for body_ids, observable_id in independent_group_relations
        for body_id in body_ids
    }
    current_terminal_relations = {
        (body_id, observable_id)
        for body_ids, observable_id in current_group_relations
        for body_id in body_ids
    }
    missing_terminal_relations = sorted(
        independent_terminal_relations - current_terminal_relations
    )
    extra_terminal_relations = sorted(current_terminal_relations - independent_terminal_relations)
    confirmed_terminal_relations = independent_terminal_relations & current_terminal_relations

    difference_rows = [
        {
            "target_body_ids": ",".join(map(str, body_ids)),
            "observable_id": observable_id,
            "classification": "add_to_current",
        }
        for body_ids, observable_id in missing_group_relations
    ] + [
        {
            "target_body_ids": ",".join(map(str, body_ids)),
            "observable_id": observable_id,
            "classification": "remove_from_current",
        }
        for body_ids, observable_id in extra_group_relations
    ]
    pd.DataFrame(
        difference_rows,
        columns=["target_body_ids", "observable_id", "classification"],
    ).to_parquet(output_dir / "relation-differences.parquet", index=False)

    relation_pass = (
        not missing_group_relations
        and not extra_group_relations
        and not missing_terminal_relations
        and not extra_terminal_relations
        and duplicate_independent_group_relations == 0
        and duplicate_current_group_relations == 0
    )
    independently_validated = (
        repeat_pass
        and relation_pass
        and bool(summary["negative_constraints"]["pass"])
        and bool(summary["symmetry"]["pass"])
        and int(summary["singular_exception_count"]) == 0
    )
    comparison = {
        "current_candidate_path": str(current_candidates_path.relative_to(ROOT)).replace("\\", "/"),
        "current_candidate_sha256": _sha256_file(current_candidates_path),
        "current_routes_path": str(current_routes_path.relative_to(ROOT)).replace("\\", "/"),
        "current_routes_sha256": _sha256_file(current_routes_path),
        "independent_group_observable_relations": len(independent_group_relations),
        "current_group_observable_relations": len(current_group_relations),
        "independent_terminal_observable_relations": len(independent_terminal_relations),
        "current_terminal_observable_relations": len(current_terminal_relations),
        "confirmed_relations": len(confirmed_terminal_relations),
        "missing_group_relations_from_current": len(missing_group_relations),
        "extra_group_relations_in_current": len(extra_group_relations),
        "missing_terminal_relations_from_current": len(missing_terminal_relations),
        "extra_terminal_relations_in_current": len(extra_terminal_relations),
        "duplicate_independent_group_relations": duplicate_independent_group_relations,
        "duplicate_current_group_relations": duplicate_current_group_relations,
        "representative_missing_groups": [
            [list(body_ids), observable_id]
            for body_ids, observable_id in missing_group_relations[:20]
        ],
        "representative_extra_groups": [
            [list(body_ids), observable_id]
            for body_ids, observable_id in extra_group_relations[:20]
        ],
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
                "The global scientific_wiring_revalidation remains open for vision and "
                "proprioception; mechanosensory transfer values also remain uncalibrated."
            ),
            "next_action": (
                "Freeze this mechanosensation topology by semantic hash while independently "
                "rebuilding vision and proprioception."
                if independently_validated
                else "Classify and resolve every mechanosensation prewiring difference."
            ),
        }
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "prewiring-comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary

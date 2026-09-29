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
from .wiring_revalidation import match_frame


DEFAULT_RULESET = ROOT / "wiring" / "revalidation" / "vision-v1.yaml"
DEFAULT_EXCEPTIONS = ROOT / "wiring" / "revalidation" / "vision-exceptions-v1.yaml"
DEFAULT_CURRENT_COLUMNS = ROOT / "data" / "derived" / "wiring" / "vision-optic-columns.csv"
DEFAULT_CURRENT_ASSIGNMENTS = ROOT / "data" / "derived" / "wiring" / "vision-column-photoreceptors.parquet"
DEFAULT_CURRENT_REMAINDER = ROOT / "data" / "derived" / "wiring" / "vision-remainder-transduction.parquet"
DEFAULT_CURRENT_ROUTES = ROOT / "data" / "derived" / "wiring" / "vision-routes.parquet"
DEFAULT_CURRENT_PHYSICAL = ROOT / "data" / "derived" / "wiring" / "flybody-vision-channels.csv"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, payload: Any) -> str:
    return f"{prefix}.{_stable_hash(payload)[:16]}"


def _clean(value: Any) -> str:
    if value is None or pd.isna(value) or str(value) == "":
        return "(unknown)"
    return str(value)


def _load_published_columns(path: Path) -> pd.DataFrame:
    pattern = re.compile(r"^ME_([LR])_col_(\d+)_(\d+)$")
    records: list[dict[str, Any]] = []
    for sheet_name, expected_side in (("Right OL", "R"), ("Left OL", "L")):
        sheet = pd.read_excel(path, sheet_name=sheet_name)
        for row in sheet.itertuples(index=False):
            column_id = str(row.column)
            match = pattern.fullmatch(column_id)
            if match is None or match.group(1) != expected_side:
                raise RuntimeError(f"Unexpected optic-column identifier: {column_id}")
            receptors = []
            for receptor_class in ("R7", "R8"):
                body_id = int(getattr(row, receptor_class))
                if body_id == -99:
                    continue
                receptors.append(
                    {
                        "body_id": body_id,
                        "receptor_class": receptor_class,
                        "receptor_type": str(getattr(row, f"{receptor_class}_type")),
                    }
                )
            if not receptors:
                continue
            for receptor in receptors:
                records.append(
                    {
                        "column_id": column_id,
                        "side": expected_side,
                        "column_type": str(row.column_type),
                        **receptor,
                    }
                )
    frame = pd.DataFrame(records).sort_values(["column_id", "receptor_class"]).reset_index(
        drop=True
    )
    if frame["body_id"].duplicated().any():
        raise RuntimeError("The optic supplement assigns one body to several columns")
    return frame


def _physical_source_sets(channels: pd.DataFrame) -> tuple[pd.DataFrame, dict[tuple[str, str], dict[str, Any]]]:
    required = {"channel_id", "eye", "ommatidium_id", "ommatidium_type"}
    if not required.issubset(channels.columns):
        raise RuntimeError(f"Physical retina misses columns: {sorted(required - set(channels.columns))}")
    side_by_eye = {"left": "L", "right": "R"}
    channels = channels.copy()
    channels["side"] = channels["eye"].map(side_by_eye)
    if channels["side"].isna().any():
        raise RuntimeError("Physical retina contains an unknown eye label")
    if channels["channel_id"].duplicated().any():
        raise RuntimeError("Physical retina channel IDs are not unique")
    if channels.duplicated(["side", "ommatidium_id"]).any():
        raise RuntimeError("Physical retina repeats an eye/ommatidium pair")

    records: list[dict[str, Any]] = []
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for side in ("L", "R"):
        side_frame = channels.loc[channels["side"].eq(side)]
        for palette in ("any", "pale", "yellow"):
            selected = side_frame if palette == "any" else side_frame.loc[
                side_frame["ommatidium_type"].eq(palette)
            ]
            channel_ids = tuple(sorted(selected["channel_id"].astype(str)))
            record = {
                "source_set_id": f"vision.sources.{side.lower()}.{palette}",
                "side": side,
                "palette": palette,
                "source_count": len(channel_ids),
                "source_channel_ids": channel_ids,
                "source_set_sha256": _stable_hash(channel_ids),
            }
            records.append(record)
            lookup[(side, palette)] = record
    return pd.DataFrame(records), lookup


def _semantic_hash(
    terminals: list[dict[str, Any]],
    envelopes: list[dict[str, Any]],
    source_sets: pd.DataFrame,
) -> str:
    payload = {
        "terminals": sorted(
            (
                int(item["body_id"]),
                item["partition"],
                item["terminal_disposition"],
                item["registration_unit_id"],
                item["rule_id"],
            )
            for item in terminals
        ),
        "envelopes": sorted(
            (
                item["registration_unit_id"],
                tuple(item["member_body_ids"]),
                item["source_set_id"],
                item["source_set_sha256"],
                item["registration_policy"],
                item["terminal_disposition"],
            )
            for item in envelopes
        ),
        "source_sets": sorted(
            (
                str(row.source_set_id),
                int(row.source_count),
                str(row.source_set_sha256),
            )
            for row in source_sets.itertuples(index=False)
        ),
    }
    return _stable_hash(payload)


def _quantiles(values: list[int]) -> dict[str, float]:
    series = pd.Series(values, dtype="float64")
    return {
        "mean": float(series.mean()),
        "p50": float(series.quantile(0.50)),
        "p90": float(series.quantile(0.90)),
        "p95": float(series.quantile(0.95)),
        "max": float(series.max()),
    }


def build_vision_envelope(
    output_dir: Path,
    ruleset_path: Path = DEFAULT_RULESET,
    exceptions_path: Path = DEFAULT_EXCEPTIONS,
) -> dict[str, Any]:
    """Clean-build visual registration envelopes without opening executable prewiring."""
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RuntimeError(f"Clean-build destination is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    ruleset = yaml.safe_load(ruleset_path.read_text(encoding="utf-8"))
    exceptions = yaml.safe_load(exceptions_path.read_text(encoding="utf-8"))
    if int(ruleset.get("schema_version", 0)) != 1:
        raise RuntimeError("Unsupported vision ruleset schema")
    if int(exceptions.get("schema_version", 0)) != 1:
        raise RuntimeError("Unsupported vision exception schema")
    if exceptions.get("entries"):
        raise RuntimeError("Vision exceptions are not implemented; refusing fallback")

    source_paths = {name: ROOT / item["path"] for name, item in ruleset["sources"].items()}
    for name, path in source_paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"Missing vision source {name}: {path}")

    annotations = pd.read_feather(source_paths["annotations"])
    population = pd.read_parquet(source_paths["population_scope"])
    physical = pd.read_csv(source_paths["physical_retina"])
    published = _load_published_columns(source_paths["optic_columns"])
    canonical_ids = set(population.loc[population["is_canonical_neuron"], "body_id"].astype(int))
    if len(canonical_ids) != 166_700:
        raise RuntimeError(f"Expected 166700 canonical neurons, found {len(canonical_ids)}")

    selected = annotations.loc[match_frame(annotations, ruleset["scope"])].copy()
    selected["body_id"] = selected["bodyId"].astype(int)
    if len(selected) != 6_098 or selected["body_id"].nunique() != 6_098:
        raise RuntimeError("Expected 6098 unique visual terminals")
    terminal_ids = set(selected["body_id"])
    if terminal_ids - canonical_ids:
        raise RuntimeError("Vision scope contains noncanonical annotated bodies")
    annotations_by_body = selected.set_index("body_id")
    if not annotations_by_body.index.is_unique:
        raise RuntimeError("Visual annotation body IDs are not unique")

    if len(published) != 2_628 or published["column_id"].nunique() != 1_332:
        raise RuntimeError("Expected 2628 published R7/R8 bodies in 1332 columns")
    published_ids = set(published["body_id"].astype(int))
    if published_ids - terminal_ids:
        raise RuntimeError("Published optic bodies are absent from the visual terminal scope")
    for row in published.itertuples(index=False):
        annotation = annotations_by_body.loc[int(row.body_id)]
        if _clean(annotation["type"]) != str(row.receptor_type):
            raise RuntimeError(f"Published receptor type mismatch for body {row.body_id}")
        if _clean(annotation["rootSide"]) != str(row.side):
            raise RuntimeError(f"Published receptor side mismatch for body {row.body_id}")

    source_sets, source_lookup = _physical_source_sets(physical)
    expected_source_counts = {("L", "any"): 721, ("R", "any"): 721,
                              ("L", "pale"): 216, ("R", "pale"): 216,
                              ("L", "yellow"): 505, ("R", "yellow"): 505}
    actual_source_counts = {
        (str(row.side), str(row.palette)): int(row.source_count)
        for row in source_sets.itertuples(index=False)
    }
    if actual_source_counts != expected_source_counts:
        raise RuntimeError(f"Unexpected physical retina palette counts: {actual_source_counts}")

    policies = ruleset["policies"]
    palette_map = policies["published_columns"]["column_palette"]
    terminals: list[dict[str, Any]] = []
    envelopes: list[dict[str, Any]] = []
    disposition_counts: Counter[str] = Counter()
    partition_counts: Counter[str] = Counter()

    for column_id, members in published.groupby("column_id", sort=True):
        side_values = set(members["side"].astype(str))
        type_values = set(members["column_type"].astype(str))
        if len(side_values) != 1 or len(type_values) != 1:
            raise RuntimeError(f"Inconsistent published column {column_id}")
        side = next(iter(side_values))
        column_type = next(iter(type_values))
        if column_type not in palette_map:
            raise RuntimeError(f"No physical palette rule for column type {column_type}")
        palette = str(palette_map[column_type])
        source_set = source_lookup[(side, palette)]
        body_ids = tuple(sorted(members["body_id"].astype(int)))
        envelopes.append(
            {
                "registration_unit_id": str(column_id),
                "partition": "published_column",
                "member_body_ids": body_ids,
                "member_count": len(body_ids),
                "side": side,
                "biological_column_id": str(column_id),
                "column_type": column_type,
                "physical_palette": palette,
                "source_set_id": source_set["source_set_id"],
                "source_set_sha256": source_set["source_set_sha256"],
                "candidate_source_count": source_set["source_count"],
                "registration_policy": str(policies["published_columns"]["registration_policy"]),
                "terminal_disposition": str(policies["published_columns"]["terminal_disposition"]),
                "relation_class": str(policies["published_columns"]["relation_class"]),
                "rule_id": str(policies["published_columns"]["rule_id"]),
            }
        )
        for row in members.itertuples(index=False):
            terminals.append(
                {
                    "body_id": int(row.body_id),
                    "partition": "published_column",
                    "annotation_type": _clean(annotations_by_body.loc[int(row.body_id), "type"]),
                    "side": side,
                    "receptor_class": str(row.receptor_class),
                    "receptor_type": str(row.receptor_type),
                    "biological_column_id": str(column_id),
                    "column_type": column_type,
                    "registration_unit_id": str(column_id),
                    "terminal_disposition": str(policies["published_columns"]["terminal_disposition"]),
                    "relation_class": str(policies["published_columns"]["relation_class"]),
                    "rule_id": str(policies["published_columns"]["rule_id"]),
                }
            )
            disposition_counts[str(policies["published_columns"]["terminal_disposition"])] += 1
            partition_counts["published_column"] += 1

    remainder = selected.loc[~selected["body_id"].isin(published_ids)].copy()
    hbeyelet = remainder.loc[remainder["type"].eq("HBeyelet")].copy()
    unregistered = remainder.loc[~remainder["type"].eq("HBeyelet")].copy()
    if len(unregistered) != 3_463 or len(hbeyelet) != 7:
        raise RuntimeError(
            f"Expected 3463 unregistered photoreceptors and 7 HBeyelet, found "
            f"{len(unregistered)} and {len(hbeyelet)}"
        )
    if not unregistered["class"].eq("visual").all():
        raise RuntimeError("Unregistered non-HBeyelet terminals are not all class visual")

    for row in unregistered.sort_values("body_id").itertuples(index=False):
        side = _clean(row.rootSide)
        if side not in {"L", "R"}:
            raise RuntimeError(f"Unregistered photoreceptor {row.body_id} lacks visual side")
        policy = policies["unregistered_photoreceptors"]
        source_set = source_lookup[(side, str(policy["physical_palette"]))]
        unit_id = f"terminal.{int(row.body_id)}"
        envelopes.append(
            {
                "registration_unit_id": unit_id,
                "partition": "unregistered_photoreceptor",
                "member_body_ids": (int(row.body_id),),
                "member_count": 1,
                "side": side,
                "biological_column_id": "",
                "column_type": "",
                "physical_palette": str(policy["physical_palette"]),
                "source_set_id": source_set["source_set_id"],
                "source_set_sha256": source_set["source_set_sha256"],
                "candidate_source_count": source_set["source_count"],
                "registration_policy": str(policy["registration_policy"]),
                "terminal_disposition": str(policy["terminal_disposition"]),
                "relation_class": str(policy["relation_class"]),
                "rule_id": str(policy["rule_id"]),
            }
        )
        terminals.append(
            {
                "body_id": int(row.body_id),
                "partition": "unregistered_photoreceptor",
                "annotation_type": _clean(row.type),
                "side": side,
                "receptor_class": "unregistered",
                "receptor_type": _clean(row.type),
                "biological_column_id": "",
                "column_type": "",
                "registration_unit_id": unit_id,
                "terminal_disposition": str(policy["terminal_disposition"]),
                "relation_class": str(policy["relation_class"]),
                "rule_id": str(policy["rule_id"]),
            }
        )
        disposition_counts[str(policy["terminal_disposition"])] += 1
        partition_counts["unregistered_photoreceptor"] += 1

    for row in hbeyelet.sort_values("body_id").itertuples(index=False):
        match = re.fullmatch(r"HBeyelet_([LR])", _clean(row.instance))
        if match is None:
            raise RuntimeError(f"HBeyelet {row.body_id} lacks a sided instance")
        side = match.group(1)
        policy = policies["hbeyelet_proxy"]
        source_set = source_lookup[(side, str(policy["physical_palette"]))]
        unit_id = f"terminal.{int(row.body_id)}"
        envelopes.append(
            {
                "registration_unit_id": unit_id,
                "partition": "hbeyelet_proxy",
                "member_body_ids": (int(row.body_id),),
                "member_count": 1,
                "side": side,
                "biological_column_id": "",
                "column_type": "",
                "physical_palette": str(policy["physical_palette"]),
                "source_set_id": source_set["source_set_id"],
                "source_set_sha256": source_set["source_set_sha256"],
                "candidate_source_count": source_set["source_count"],
                "registration_policy": str(policy["registration_policy"]),
                "terminal_disposition": str(policy["terminal_disposition"]),
                "relation_class": str(policy["relation_class"]),
                "rule_id": str(policy["rule_id"]),
            }
        )
        terminals.append(
            {
                "body_id": int(row.body_id),
                "partition": "hbeyelet_proxy",
                "annotation_type": "HBeyelet",
                "side": side,
                "receptor_class": "HBeyelet",
                "receptor_type": "HBeyelet",
                "biological_column_id": "",
                "column_type": "",
                "registration_unit_id": unit_id,
                "terminal_disposition": str(policy["terminal_disposition"]),
                "relation_class": str(policy["relation_class"]),
                "rule_id": str(policy["rule_id"]),
            }
        )
        disposition_counts[str(policy["terminal_disposition"])] += 1
        partition_counts["hbeyelet_proxy"] += 1

    decision_ids = {int(item["body_id"]) for item in terminals}
    partition_pass = len(terminals) == len(decision_ids) == 6_098 and decision_ids == terminal_ids
    cross_eye_violations = [
        item["registration_unit_id"]
        for item in envelopes
        if not item["source_set_id"].startswith(f"vision.sources.{item['side'].lower()}.")
    ]
    palette_violations = [
        item["registration_unit_id"]
        for item in envelopes
        if item["partition"] == "published_column"
        and item["physical_palette"] != str(palette_map[item["column_type"]])
    ]
    published_units_by_side = Counter(
        item["side"] for item in envelopes if item["partition"] == "published_column"
    )
    injectivity_feasible = all(
        count <= source_lookup[(side, "any")]["source_count"]
        for side, count in published_units_by_side.items()
    )
    symmetry_violations = [
        palette
        for palette in ("any", "pale", "yellow")
        if source_lookup[("L", palette)]["source_count"]
        != source_lookup[("R", palette)]["source_count"]
    ]
    if (
        not partition_pass
        or cross_eye_violations
        or palette_violations
        or not injectivity_feasible
        or symmetry_violations
    ):
        raise RuntimeError(
            "Vision negative constraints failed: "
            f"partition={partition_pass}, cross_eye={len(cross_eye_violations)}, "
            f"palette={len(palette_violations)}, injectivity={injectivity_feasible}, "
            f"symmetry={len(symmetry_violations)}"
        )

    semantic_hash = _semantic_hash(terminals, envelopes, source_sets)
    candidate_sizes = [int(item["candidate_source_count"]) for item in envelopes]
    candidate_relations = sum(candidate_sizes)
    expanded_relations = sum(
        int(item["member_count"]) * int(item["candidate_source_count"])
        for item in envelopes
    )
    discrete_envelopes = [
        item for item in envelopes if item["registration_policy"] != "same_eye_mean"
    ]
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
        "terminal_count": len(terminals),
        "registration_unit_count": len(envelopes),
        "published_column_count": int(partition_counts["published_column"] and published["column_id"].nunique()),
        "candidate_edge_count": candidate_relations,
        "expanded_terminal_observable_relations": expanded_relations,
        "represented_observable_count": len(physical),
        "partition_counts": dict(partition_counts),
        "disposition_counts": dict(disposition_counts),
        "candidate_set_statistics": _quantiles(candidate_sizes),
        "degrees_of_freedom": {
            "discrete_registration_parameters": len(discrete_envelopes),
            "routing_simplex_dimensions": sum(
                int(item["candidate_source_count"]) - 1 for item in discrete_envelopes
            ),
            "continuous_transfer_parameters": len(terminals),
            "published_injectivity_constraints": int(published["column_id"].nunique()),
        },
        "negative_constraints": {
            "partition_pass": partition_pass,
            "cross_eye_violations": cross_eye_violations,
            "palette_violations": palette_violations,
            "published_injectivity_feasible": injectivity_feasible,
            "pass": partition_pass and not cross_eye_violations and not palette_violations and injectivity_feasible,
        },
        "symmetry": {
            "physical_palette_capacities_checked": 3,
            "violations": symmetry_violations,
            "pass": not symmetry_violations,
        },
        "singular_exception_count": len(exceptions.get("entries", [])),
        "masked_gold_standard": ruleset["gold_standard"],
        "accepted_for_calibration": False,
        "next_action": (
            "Compare this finalized semantic hash and normalized registration envelope "
            "against executable prewiring, classify every difference, and repeat the clean build."
        ),
    }

    terminal_frame = pd.DataFrame(terminals).sort_values("body_id")
    envelope_frame = pd.DataFrame(envelopes).copy()
    envelope_frame["member_body_ids"] = envelope_frame["member_body_ids"].map(
        lambda values: ",".join(map(str, values))
    )
    source_frame = source_sets.copy()
    source_frame["source_channel_ids"] = source_frame["source_channel_ids"].map(
        lambda values: ",".join(values)
    )
    terminal_frame.to_parquet(output_dir / "terminal-decisions.parquet", index=False)
    envelope_frame.sort_values("registration_unit_id").to_parquet(
        output_dir / "registration-envelopes.parquet", index=False
    )
    source_frame.sort_values("source_set_id").to_parquet(
        output_dir / "allowed-source-sets.parquet", index=False
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def _current_normalized_records(
    columns: pd.DataFrame,
    assignments: pd.DataFrame,
    remainder: pd.DataFrame,
    routes: pd.DataFrame,
    physical: pd.DataFrame,
) -> tuple[set[tuple[Any, ...]], set[tuple[Any, ...]], dict[str, Any]]:
    required_columns = {
        "column_id", "side", "column_type", "expected_flybody_sample_type",
        "r7_body_id", "r8_body_id",
    }
    required_assignments = {
        "column_id", "side", "column_type", "expected_flybody_sample_type",
        "receptor_class", "receptor_type", "target_body_id",
    }
    required_remainder = {
        "target_body_id", "target_type", "target_instance", "side", "source_policy",
        "candidate_source_count", "terminal_disposition",
    }
    required_routes = {"target_body_id", "channel_id"}
    for label, frame, required in (
        ("columns", columns, required_columns),
        ("assignments", assignments, required_assignments),
        ("remainder", remainder, required_remainder),
        ("routes", routes, required_routes),
    ):
        if not required.issubset(frame.columns):
            raise RuntimeError(f"Current vision {label} misses {sorted(required - set(frame.columns))}")
    if len(routes) != 6_098 or routes["target_body_id"].nunique() != 6_098:
        raise RuntimeError("Current vision routes are not 6098 unique bodyIds")

    source_sets, source_lookup = _physical_source_sets(physical)
    terminal_keys: list[tuple[Any, ...]] = []
    envelope_keys: list[tuple[Any, ...]] = []
    assignment_bodies = set(assignments["target_body_id"].astype(int))
    remainder_bodies = set(remainder["target_body_id"].astype(int))
    route_bodies = set(routes["target_body_id"].astype(int))
    if assignment_bodies & remainder_bodies or assignment_bodies | remainder_bodies != route_bodies:
        raise RuntimeError("Current vision assignments do not partition routed bodyIds")

    assignments_by_column = {
        str(column_id): rows for column_id, rows in assignments.groupby("column_id", sort=True)
    }
    for row in columns.itertuples(index=False):
        column_id = str(row.column_id)
        members = assignments_by_column.get(column_id)
        if members is None:
            raise RuntimeError(f"Current column {column_id} has no receptor assignment")
        side = str(row.side)
        palette = str(row.expected_flybody_sample_type)
        source_set = source_lookup[(side, palette)]
        body_ids = tuple(sorted(members["target_body_id"].astype(int)))
        envelope_keys.append(
            (
                column_id,
                body_ids,
                side,
                str(row.column_type),
                palette,
                str(source_set["source_set_sha256"]),
                int(source_set["source_count"]),
                "injective_within_eye",
                "parameterized",
            )
        )
        for assignment in members.itertuples(index=False):
            terminal_keys.append(
                (
                    int(assignment.target_body_id),
                    "published_column",
                    side,
                    column_id,
                    str(assignment.receptor_type),
                    "parameterized",
                )
            )

    for row in remainder.itertuples(index=False):
        body_id = int(row.target_body_id)
        side = str(row.side)
        source_set = source_lookup[(side, "any")]
        is_proxy = str(row.source_policy) == "same_eye_mean_retinal_proxy"
        partition = "hbeyelet_proxy" if is_proxy else "unregistered_photoreceptor"
        policy = "same_eye_mean" if is_proxy else "independent_choice_within_eye"
        unit_id = f"terminal.{body_id}"
        terminal_keys.append(
            (
                body_id,
                partition,
                side,
                "",
                str(row.target_type),
                str(row.terminal_disposition),
            )
        )
        envelope_keys.append(
            (
                unit_id,
                (body_id,),
                side,
                "",
                "any",
                str(source_set["source_set_sha256"]),
                int(row.candidate_source_count),
                policy,
                str(row.terminal_disposition),
            )
        )

    diagnostics = {
        "duplicate_terminal_records": len(terminal_keys) - len(set(terminal_keys)),
        "duplicate_envelope_records": len(envelope_keys) - len(set(envelope_keys)),
        "source_set_count": len(source_sets),
    }
    return set(terminal_keys), set(envelope_keys), diagnostics


def compare_vision_with_prewiring(
    output_dir: Path,
    current_columns_path: Path = DEFAULT_CURRENT_COLUMNS,
    current_assignments_path: Path = DEFAULT_CURRENT_ASSIGNMENTS,
    current_remainder_path: Path = DEFAULT_CURRENT_REMAINDER,
    current_routes_path: Path = DEFAULT_CURRENT_ROUTES,
    current_physical_path: Path = DEFAULT_CURRENT_PHYSICAL,
    ruleset_path: Path = DEFAULT_RULESET,
    exceptions_path: Path = DEFAULT_EXCEPTIONS,
) -> dict[str, Any]:
    """Compare only after the independent semantic hash exists on disk."""
    output_dir = output_dir.resolve()
    summary_path = output_dir / "summary.json"
    terminal_path = output_dir / "terminal-decisions.parquet"
    envelope_path = output_dir / "registration-envelopes.parquet"
    if not all(path.is_file() for path in (summary_path, terminal_path, envelope_path)):
        raise RuntimeError("Independent vision envelope and semantic hash must exist before comparison")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    finalized_hash = str(summary["semantic_topology_sha256"])

    with tempfile.TemporaryDirectory(prefix="flymatrix-vision-repeat-") as temporary:
        repeated = build_vision_envelope(
            Path(temporary), ruleset_path=ruleset_path, exceptions_path=exceptions_path
        )
    repeat_hash = str(repeated["semantic_topology_sha256"])
    repeat_pass = repeat_hash == finalized_hash

    independent_terminals = pd.read_parquet(terminal_path)
    independent_envelopes = pd.read_parquet(envelope_path)
    current_columns = pd.read_csv(current_columns_path)
    current_assignments = pd.read_parquet(current_assignments_path)
    current_remainder = pd.read_parquet(current_remainder_path)
    current_routes = pd.read_parquet(current_routes_path)
    current_physical = pd.read_csv(current_physical_path)

    independent_terminal_keys = {
        (
            int(row.body_id),
            str(row.partition),
            str(row.side),
            str(row.biological_column_id),
            str(row.receptor_type),
            str(row.terminal_disposition),
        )
        for row in independent_terminals.itertuples(index=False)
    }
    independent_envelope_keys = {
        (
            str(row.registration_unit_id),
            tuple(map(int, str(row.member_body_ids).split(","))),
            str(row.side),
            str(row.column_type),
            str(row.physical_palette),
            str(row.source_set_sha256),
            int(row.candidate_source_count),
            str(row.registration_policy),
            str(row.terminal_disposition),
        )
        for row in independent_envelopes.itertuples(index=False)
    }
    current_terminal_keys, current_envelope_keys, diagnostics = _current_normalized_records(
        current_columns,
        current_assignments,
        current_remainder,
        current_routes,
        current_physical,
    )

    missing_terminals = sorted(independent_terminal_keys - current_terminal_keys)
    extra_terminals = sorted(current_terminal_keys - independent_terminal_keys)
    missing_envelopes = sorted(independent_envelope_keys - current_envelope_keys)
    extra_envelopes = sorted(current_envelope_keys - independent_envelope_keys)
    relation_pass = (
        not missing_terminals
        and not extra_terminals
        and not missing_envelopes
        and not extra_envelopes
        and diagnostics["duplicate_terminal_records"] == 0
        and diagnostics["duplicate_envelope_records"] == 0
    )
    independently_validated = (
        repeat_pass
        and relation_pass
        and bool(summary["negative_constraints"]["pass"])
        and bool(summary["symmetry"]["pass"])
        and int(summary["singular_exception_count"]) == 0
    )
    comparison = {
        "current_columns_path": str(current_columns_path.relative_to(ROOT)).replace("\\", "/"),
        "current_columns_sha256": _sha256_file(current_columns_path),
        "current_assignments_path": str(current_assignments_path.relative_to(ROOT)).replace("\\", "/"),
        "current_assignments_sha256": _sha256_file(current_assignments_path),
        "current_remainder_path": str(current_remainder_path.relative_to(ROOT)).replace("\\", "/"),
        "current_remainder_sha256": _sha256_file(current_remainder_path),
        "current_routes_path": str(current_routes_path.relative_to(ROOT)).replace("\\", "/"),
        "current_routes_sha256": _sha256_file(current_routes_path),
        "independent_terminal_records": len(independent_terminal_keys),
        "current_terminal_records": len(current_terminal_keys),
        "confirmed_terminal_records": len(independent_terminal_keys & current_terminal_keys),
        "independent_registration_envelopes": len(independent_envelope_keys),
        "current_registration_envelopes": len(current_envelope_keys),
        "confirmed_registration_envelopes": len(independent_envelope_keys & current_envelope_keys),
        "normalized_candidate_relations": int(summary["candidate_edge_count"]),
        "expanded_terminal_observable_relations": int(summary["expanded_terminal_observable_relations"]),
        "independent_terminal_observable_relations": int(summary["expanded_terminal_observable_relations"]),
        "current_terminal_observable_relations": int(summary["expanded_terminal_observable_relations"]),
        "confirmed_relations": int(summary["expanded_terminal_observable_relations"]) if relation_pass else 0,
        "missing_terminal_records_from_current": len(missing_terminals),
        "extra_terminal_records_in_current": len(extra_terminals),
        "missing_registration_envelopes_from_current": len(missing_envelopes),
        "extra_registration_envelopes_in_current": len(extra_envelopes),
        **diagnostics,
        "representative_missing_terminals": [list(item) for item in missing_terminals[:20]],
        "representative_extra_terminals": [list(item) for item in extra_terminals[:20]],
        "representative_missing_envelopes": [list(item) for item in missing_envelopes[:20]],
        "representative_extra_envelopes": [list(item) for item in extra_envelopes[:20]],
        "pass": relation_pass,
    }
    pd.DataFrame(
        [
            {"kind": "terminal", "classification": "add_to_current", "record": json.dumps(item)}
            for item in missing_terminals
        ]
        + [
            {"kind": "terminal", "classification": "remove_from_current", "record": json.dumps(item)}
            for item in extra_terminals
        ]
        + [
            {"kind": "envelope", "classification": "add_to_current", "record": json.dumps(item)}
            for item in missing_envelopes
        ]
        + [
            {"kind": "envelope", "classification": "remove_from_current", "record": json.dumps(item)}
            for item in extra_envelopes
        ],
        columns=["kind", "classification", "record"],
    ).to_parquet(output_dir / "relation-differences.parquet", index=False)

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
                "No scientific wiring blocker remains if the global four-family run passes; "
                "retinal registrations, gains and transfer dynamics remain uncalibrated."
                if independently_validated
                else "Vision prewiring differences must be resolved before calibration."
            ),
            "next_action": (
                "Rerun the global four-family review and close scientific wiring revalidation."
                if independently_validated
                else "Classify and resolve every vision prewiring difference."
            ),
        }
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "prewiring-comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary

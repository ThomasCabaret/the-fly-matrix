from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import webbrowser
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .ledger import ROOT


DEFAULT_RULESET = ROOT / "wiring" / "revalidation" / "rules-v1.yaml"
OUTPUT_ROOT = ROOT / "data" / "derived" / "wiring-revalidation"
REPORT_PATH = ROOT / "reports" / "generated" / "wiring-revalidation.html"


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean(value: Any) -> Any:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return "(unknown)"
    if isinstance(value, bool):
        return value
    return str(value)


def matches(record: dict[str, Any], selector: dict[str, Any]) -> bool:
    """Evaluate the deliberately small selector language used by rule files."""
    if "all" in selector:
        return all(matches(record, item) for item in selector["all"])
    if "any" in selector:
        return any(matches(record, item) for item in selector["any"])
    if "not" in selector:
        return not matches(record, selector["not"])

    field = str(selector["field"])
    op = str(selector["op"])
    actual = record.get(field, "(unknown)")
    expected = selector.get("value")
    if op == "equals":
        return actual == expected or str(actual) == str(expected)
    if op == "in":
        return any(actual == item or str(actual) == str(item) for item in expected)
    if op == "contains":
        return str(expected) in str(actual)
    if op == "regex":
        return re.search(str(expected), str(actual)) is not None
    if op == "is_unknown":
        return str(actual).strip().lower() in {"", "(unknown)", "unknown", "nan", "none"}
    raise ValueError(f"Unsupported selector operation: {op}")


def match_frame(frame: pd.DataFrame, selector: dict[str, Any]) -> pd.Series:
    """Vectorized counterpart of :func:`matches` for raw-table selection."""
    if "all" in selector:
        result = pd.Series(True, index=frame.index)
        for item in selector["all"]:
            result &= match_frame(frame, item)
        return result
    if "any" in selector:
        result = pd.Series(False, index=frame.index)
        for item in selector["any"]:
            result |= match_frame(frame, item)
        return result
    if "not" in selector:
        return ~match_frame(frame, selector["not"])

    field = str(selector["field"])
    op = str(selector["op"])
    values = frame[field]
    expected = selector.get("value")
    if op == "equals":
        return values.eq(expected)
    if op == "in":
        return values.isin(expected)
    if op == "contains":
        return values.fillna("").astype(str).str.contains(str(expected), regex=False)
    if op == "regex":
        return values.fillna("").astype(str).str.contains(str(expected), regex=True)
    if op == "is_unknown":
        return values.fillna("").astype(str).str.strip().str.lower().isin(
            {"", "(unknown)", "unknown", "nan", "none"}
        )
    raise ValueError(f"Unsupported selector operation: {op}")


def apply_rules(
    record: dict[str, Any], rules: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, list[str], str | None]:
    matched = [rule for rule in rules if matches(record, rule["selector"])]
    if not matched:
        return None, [], "no_rule_matched"
    top_priority = max(int(rule.get("priority", 0)) for rule in matched)
    top = [rule for rule in matched if int(rule.get("priority", 0)) == top_priority]
    signatures = {
        (
            str(rule["outcome"]),
            str(rule["relation_class"]),
            str(rule["terminal_disposition"]),
        )
        for rule in top
    }
    if len(signatures) != 1:
        return None, [str(rule["id"]) for rule in top], "conflicting_top_priority_rules"
    selected = sorted(top, key=lambda item: str(item["id"]))[0]
    return selected, [str(rule["id"]) for rule in matched], None


def validate_ruleset(ruleset: dict[str, Any]) -> None:
    """Reject YAML scalar coercions and incomplete scientific rule records."""
    if int(ruleset.get("schema_version", 0)) != 1:
        raise RuntimeError("Unsupported wiring-revalidation ruleset schema")

    def visit_selector(selector: dict[str, Any], rule_id: str) -> None:
        for key in ("all", "any"):
            for child in selector.get(key, []):
                visit_selector(child, rule_id)
        if "not" in selector:
            visit_selector(selector["not"], rule_id)
        if "field" not in selector:
            return
        field = str(selector["field"])
        value = selector.get("value")
        values = value if isinstance(value, list) else [value]
        if field != "published_optic_column" and any(isinstance(item, bool) for item in values):
            raise RuntimeError(
                f"Rule {rule_id} contains a boolean selector value for string field {field}; "
                "quote YAML tokens such as ON/OFF/YES/NO"
            )

    for workstream, spec in ruleset.get("workstreams", {}).items():
        visit_selector(spec["selector"], f"{workstream}.scope")
        for rule in spec.get("rules", []):
            required = {
                "id",
                "selector",
                "outcome",
                "relation_class",
                "terminal_disposition",
                "provenance_kind",
                "source_references",
                "used_claim",
            }
            missing = required - set(rule)
            if missing:
                raise RuntimeError(f"Rule {rule.get('id', '<unknown>')} misses {sorted(missing)}")
            visit_selector(rule["selector"], str(rule["id"]))


def _git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def _load_optic_assignments(path: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    pattern = re.compile(r"^ME_([LR])_col_(\d+)_(\d+)$")
    for sheet_name, expected_side in (("Right OL", "R"), ("Left OL", "L")):
        sheet = pd.read_excel(path, sheet_name=sheet_name)
        for row in sheet.itertuples(index=False):
            column_id = str(row.column)
            match = pattern.fullmatch(column_id)
            if match is None or match.group(1) != expected_side:
                raise RuntimeError(f"Unexpected optic-column identifier: {column_id}")
            for receptor_class in ("R7", "R8"):
                body_id = int(getattr(row, receptor_class))
                if body_id == -99:
                    continue
                rows.append(
                    {
                        "body_id": body_id,
                        "column_id": column_id,
                        "side": expected_side,
                        "receptor_class": receptor_class,
                        "receptor_type": str(getattr(row, f"{receptor_class}_type")).strip(),
                    }
                )
    result = pd.DataFrame(rows).sort_values(["body_id", "column_id"]).reset_index(drop=True)
    if result["body_id"].duplicated().any():
        raise RuntimeError("The optic supplement assigns one body to several columns")
    return result


def _family_values(frame: pd.DataFrame, spec: dict[str, Any]) -> pd.Series:
    if "constant" in spec:
        return pd.Series(str(spec["constant"]), index=frame.index, dtype="object")
    mapping = spec["field_map"]
    values = frame[str(mapping["field"])].map(mapping["values"])
    if values.isna().any():
        missing = sorted(set(frame.loc[values.isna(), str(mapping["field"])].astype(str)))
        raise RuntimeError(f"No family mapping for values: {missing}")
    return values.astype(str)


def _independent_groups(
    workstream: str,
    selected: pd.DataFrame,
    spec: dict[str, Any],
    published_bodies: set[int],
) -> list[dict[str, Any]]:
    selected = selected.copy()
    selected["family"] = _family_values(selected, spec["family"])
    selected["published_optic_column"] = selected["bodyId"].astype(int).isin(published_bodies)
    selected["grouping_type"] = selected["type"].fillna("(unknown)").astype(str)
    unknown_type = selected["grouping_type"].eq("(unknown)")
    selected.loc[unknown_type, "grouping_type"] = selected.loc[unknown_type, "bodyId"].map(
        lambda body_id: f"(unknown bodyId={int(body_id)})"
    )
    axes = list(spec["group_by"])
    for axis in axes:
        selected[axis] = selected[axis].map(_clean)

    groups: list[dict[str, Any]] = []
    for values, members in selected.groupby(axes, dropna=False, sort=True):
        if len(axes) == 1:
            values = (values,)
        body_ids = tuple(sorted(members["bodyId"].astype(int)))
        key = json.dumps([workstream, *values], ensure_ascii=False, separators=(",", ":"))
        record: dict[str, Any] = {
            "independent_group_id": "review.group."
            + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16],
            "workstream": workstream,
            "direction": str(spec["direction"]),
            "member_body_ids": body_ids,
            "member_count": len(body_ids),
            "synonyms": " | ".join(
                sorted(set(members["synonyms"].dropna().astype(str)))
            ),
            "published_optic_column": bool(members["published_optic_column"].all()),
        }
        record.update({axis: _clean(value) for axis, value in zip(axes, values)})
        for field in (
            "family",
            "superclass",
            "class",
            "subclass",
            "type",
            "instance",
            "entryNerve",
            "exitNerve",
            "rootSide",
            "somaSide",
            "somaNeuromere",
            "mancType",
            "grouping_type",
        ):
            if field not in record and field in members:
                unique = sorted(set(members[field].map(_clean)), key=str)
                record[field] = unique[0] if len(unique) == 1 else " | ".join(map(str, unique))
        groups.append(record)
    return groups


def _current_group_index(spec: dict[str, Any]) -> tuple[dict[frozenset[int], str], set[int]]:
    current = spec["current"]
    path = ROOT / current["route_path"]
    routes = pd.read_parquet(path)
    body_column = str(current["body_column"])
    group_column = str(current["group_column"])
    grouped: dict[frozenset[int], str] = {}
    for group_id, members in routes.groupby(group_column, sort=True):
        body_ids = frozenset(members[body_column].astype(int))
        if body_ids in grouped:
            raise RuntimeError(f"Duplicate current group membership in {path}")
        grouped[body_ids] = str(group_id)
    return grouped, set(routes[body_column].astype(int))


def _current_dispositions(workstream: str, current_group_ids: set[str]) -> dict[str, str]:
    root = ROOT / "data" / "derived" / "wiring"
    if workstream == "vision":
        routes = pd.read_parquet(root / "vision-routes.parquet")
        body_to_group = dict(zip(routes["target_body_id"].astype(int), routes["channel_id"].astype(str)))
        published = pd.read_parquet(root / "vision-column-photoreceptors.parquet")
        result = {
            body_to_group[int(body_id)]: "parameterized"
            for body_id in published["target_body_id"]
        }
        remainder = pd.read_parquet(root / "vision-remainder-transduction.parquet")
        for row in remainder.itertuples(index=False):
            result[body_to_group[int(row.target_body_id)]] = str(row.terminal_disposition)
        return result
    if workstream == "proprioception":
        direct = pd.read_parquet(root / "proprioception-input-candidates.parquet")
        proxy = pd.read_parquet(root / "proprioception-proxy-candidates.parquet")
        result = {str(value): "parameterized" for value in direct["target_channel_id"].unique()}
        result.update({str(value): "proxy" for value in proxy["target_channel_id"].unique()})
        return result
    if workstream == "mechanosensation":
        candidates = pd.read_parquet(root / "mechanosensation-input-candidates.parquet")
        return {
            str(value): "parameterized" for value in candidates["target_channel_id"].unique()
        }
    if workstream == "motor_output":
        candidates = pd.read_parquet(root / "motor-actuator-candidates.parquet")
        parameterized = set(candidates["motor_group_id"].astype(str))
        return {
            group_id: "parameterized" if group_id in parameterized else "sink"
            for group_id in current_group_ids
        }
    raise ValueError(workstream)


def _compare_optic_assignments(independent: pd.DataFrame) -> dict[str, Any]:
    current_path = ROOT / "data" / "derived" / "wiring" / "vision-column-photoreceptors.parquet"
    current = pd.read_parquet(current_path)
    independent_keys = {
        (
            int(row.body_id),
            str(row.column_id),
            str(row.receptor_class),
            str(row.receptor_type),
            str(row.side),
        )
        for row in independent.itertuples(index=False)
    }
    current_keys = {
        (
            int(row.target_body_id),
            str(row.column_id),
            str(row.receptor_class),
            str(row.receptor_type),
            str(row.side),
        )
        for row in current.itertuples(index=False)
    }
    missing = sorted(independent_keys - current_keys)
    extra = sorted(current_keys - independent_keys)
    return {
        "independent_relations": len(independent_keys),
        "current_relations": len(current_keys),
        "missing_from_current": len(missing),
        "extra_in_current": len(extra),
        "representative_missing": missing[:10],
        "representative_extra": extra[:10],
        "pass": not missing and not extra,
    }


def _render_html(summary: dict[str, Any], output: Path) -> None:
    workstream_rows = []
    for name, item in summary["workstreams"].items():
        workstream_rows.append(
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td>{html.escape(item['direction'])}</td>"
            f"<td>{item['independent_terminals']:,}</td>"
            f"<td>{item['independent_groups']:,}</td>"
            f"<td>{item['applied_groups']:,}</td>"
            f"<td>{item['blocked_relation_families']:,}</td>"
            f"<td>{item['unexpected_exceptions']:,}</td>"
            f"<td>{html.escape(item['status'])}</td>"
            "</tr>"
        )
    blocked_rows = "".join(
        "<li><strong>"
        + html.escape(item["workstream"])
        + ":</strong> "
        + html.escape(item["reason"])
        + " — "
        + html.escape(item["next_action"])
        + "</li>"
        for item in summary["blocked"]
    )
    exception_rows = "".join(
        "<li><code>"
        + html.escape(item["code"])
        + "</code> "
        + html.escape(item["message"])
        + "</li>"
        for item in summary["exceptions"][:50]
    ) or "<li>None.</li>"
    status_class = "ok" if summary["unexpected_exception_count"] == 0 else "bad"
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>The Fly Matrix — wiring revalidation</title>
<style>
body{{font:15px/1.45 system-ui,sans-serif;background:#10141b;color:#e9eef7;margin:0}}main{{max-width:1200px;margin:auto;padding:28px}}
h1,h2{{margin:.3em 0}}.muted{{color:#9cabc0}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:18px 0}}
.card,section{{background:#18202b;border:1px solid #2d3b4e;border-radius:10px;padding:16px}}.card strong{{display:block;font-size:28px}}table{{width:100%;border-collapse:collapse}}
th,td{{padding:9px;border-bottom:1px solid #2d3b4e;text-align:left}}.ok{{color:#7fe0a3}}.bad{{color:#ff8b8b}}code{{color:#9fd3ff}}li{{margin:.45em 0}}
</style></head><body><main>
<h1>Independent wiring revalidation</h1><p class="muted">Run {html.escape(summary['run_id'])} · rules {html.escape(summary['ruleset_id'])} · no calibration</p>
<div class="cards"><div class="card"><strong>{summary['totals']['terminals']:,}</strong>raw terminals</div><div class="card"><strong>{summary['totals']['groups']:,}</strong>independent groups</div><div class="card"><strong>{summary['totals']['applied']:,}</strong>rule-applied groups</div><div class="card"><strong class="{status_class}">{summary['unexpected_exception_count']:,}</strong>unexpected exceptions</div></div>
<section><h2>Meaning of this run</h2><p>{html.escape(summary['claim'])}</p><p><strong>Scientific review:</strong> {html.escape(summary['scientific_review_status'])}. A green accounting run does not accept candidate matrices that were not independently regenerated.</p></section>
<section><h2>Workstreams</h2><table><thead><tr><th>Workstream</th><th>Direction</th><th>Terminals</th><th>Groups</th><th>Applied</th><th>Blocked families</th><th>Exceptions</th><th>Status</th></tr></thead><tbody>{''.join(workstream_rows)}</tbody></table></section>
<section><h2>Expected blockers</h2><ul>{blocked_rows}</ul></section>
<section><h2>Unexpected exceptions</h2><ul>{exception_rows}</ul></section>
<section><h2>Published vision subgraph</h2><pre>{html.escape(json.dumps(summary['optic_assignment_comparison'], indent=2))}</pre></section>
</main></body></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")


def run_revalidation(
    ruleset_path: Path = DEFAULT_RULESET,
    direction: str = "all",
    output_root: Path = OUTPUT_ROOT,
    report_path: Path = REPORT_PATH,
) -> dict[str, Any]:
    ruleset_path = ruleset_path.resolve()
    ruleset = yaml.safe_load(ruleset_path.read_text(encoding="utf-8"))
    validate_ruleset(ruleset)

    source_paths = {
        name: ROOT / source["path"] for name, source in ruleset["sources"].items()
    }
    for name, path in source_paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"Missing {name} source: {path}")

    print("[1/6] Loading raw MaleCNS annotations and canonical population flags...", flush=True)
    annotations = pd.read_feather(source_paths["annotations"])
    scope = pd.read_parquet(source_paths["population_scope"])
    canonical_ids = set(
        scope.loc[scope["is_canonical_neuron"], "body_id"].astype(int)
    )
    if len(canonical_ids) != 166_700:
        raise RuntimeError(f"Expected 166700 canonical neurons, found {len(canonical_ids)}")

    print("[2/6] Reconstructing the published R7/R8 optic-column subgraph...", flush=True)
    optic = _load_optic_assignments(source_paths["optic_columns"])
    published_bodies = set(optic["body_id"].astype(int))
    optic_comparison = _compare_optic_assignments(optic)

    selected_workstreams = {
        name: spec
        for name, spec in ruleset["workstreams"].items()
        if direction == "all" or str(spec["direction"]) == direction
    }
    if not selected_workstreams:
        raise RuntimeError(f"No workstream selected for direction={direction}")

    now = datetime.now(UTC)
    run_id = "wiring-revalidation-" + now.strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    fine_family_results: dict[str, Any] = {}
    if "motor_output" in selected_workstreams:
        from .motor_output_revalidation import (
            build_motor_output_envelope,
            compare_motor_output_with_prewiring,
        )

        print(
            "[2b/6] Clean-building the motor-output candidate envelope before comparison...",
            flush=True,
        )
        motor_dir = run_dir / "motor-output"
        build_motor_output_envelope(motor_dir)
        fine_family_results["motor_output"] = compare_motor_output_with_prewiring(motor_dir)
        motor_comparison = fine_family_results["motor_output"]["prewiring_comparison"]
        print(
            "  [motor_output] "
            f"{motor_comparison['confirmed_relations']:,}/"
            f"{motor_comparison['independent_terminal_actuator_relations']:,} "
            "terminal-actuator relations independently confirmed",
            flush=True,
        )

    if "mechanosensation" in selected_workstreams:
        from .mechanosensation_revalidation import (
            build_mechanosensation_envelope,
            compare_mechanosensation_with_prewiring,
        )

        print(
            "[2c/6] Clean-building the mechanosensation candidate envelope before comparison...",
            flush=True,
        )
        mechanosensation_dir = run_dir / "mechanosensation"
        build_mechanosensation_envelope(mechanosensation_dir)
        fine_family_results["mechanosensation"] = (
            compare_mechanosensation_with_prewiring(mechanosensation_dir)
        )
        mechanosensation_comparison = fine_family_results["mechanosensation"][
            "prewiring_comparison"
        ]
        print(
            "  [mechanosensation] "
            f"{mechanosensation_comparison['confirmed_relations']:,}/"
            f"{mechanosensation_comparison['independent_terminal_observable_relations']:,} "
            "terminal-observable relations independently confirmed",
            flush=True,
        )

    if "proprioception" in selected_workstreams:
        from .proprioception_revalidation import (
            build_proprioception_envelope,
            compare_proprioception_with_prewiring,
        )

        print(
            "[2d/6] Clean-building the proprioception candidate envelope before comparison...",
            flush=True,
        )
        proprioception_dir = run_dir / "proprioception"
        build_proprioception_envelope(proprioception_dir)
        fine_family_results["proprioception"] = compare_proprioception_with_prewiring(
            proprioception_dir
        )
        proprioception_comparison = fine_family_results["proprioception"][
            "prewiring_comparison"
        ]
        print(
            "  [proprioception] "
            f"{proprioception_comparison['confirmed_relations']:,}/"
            f"{proprioception_comparison['independent_terminal_observable_relations']:,} "
            "terminal-observable relations independently confirmed",
            flush=True,
        )

    decisions: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    workstream_summaries: dict[str, Any] = {}
    all_terminal_ids: set[int] = set()

    print("[3/6] Reconstructing terminal scopes and annotation-backed groups...", flush=True)
    for name, spec in selected_workstreams.items():
        selected = annotations.loc[match_frame(annotations, spec["selector"])].copy()
        terminal_ids = set(selected["bodyId"].astype(int))
        all_terminal_ids |= terminal_ids
        noncanonical = terminal_ids - canonical_ids
        current_groups, current_terminal_ids = _current_group_index(spec)
        current_group_ids = set(current_groups.values())
        current_dispositions = _current_dispositions(name, current_group_ids)
        groups = _independent_groups(name, selected, spec, published_bodies)

        missing_current = terminal_ids - current_terminal_ids
        extra_current = current_terminal_ids - terminal_ids
        independent_memberships = {frozenset(group["member_body_ids"]): group for group in groups}
        missing_groups = set(independent_memberships) - set(current_groups)
        extra_groups = set(current_groups) - set(independent_memberships)
        for code, values, message in (
            ("noncanonical_terminal", noncanonical, "Raw selector included noncanonical bodies"),
            ("terminal_missing_from_current", missing_current, "Independent terminals are absent from prewiring"),
            ("terminal_extra_in_current", extra_current, "Prewiring contains terminals absent from independent selection"),
            ("group_missing_from_current", missing_groups, "Independent group membership is absent from prewiring"),
            ("group_extra_in_current", extra_groups, "Prewiring group membership is absent from independent reconstruction"),
        ):
            if values:
                exceptions.append(
                    {
                        "workstream": name,
                        "code": code,
                        "message": f"{message}: {len(values)}",
                        "count": len(values),
                        "examples": [str(value) for value in list(values)[:10]],
                    }
                )

        local_exception_count = 0
        applied_count = 0
        disposition_counts: Counter[str] = Counter()
        relation_counts: Counter[str] = Counter()
        for group in groups:
            selected_rule, matched_rule_ids, error = apply_rules(group, spec["rules"])
            membership = frozenset(group["member_body_ids"])
            current_group_id = current_groups.get(membership)
            decision = dict(group)
            decision["member_body_ids"] = ",".join(map(str, group["member_body_ids"]))
            decision["current_group_id"] = current_group_id or ""
            decision["matched_rule_ids"] = ",".join(matched_rule_ids)
            if error is not None:
                decision.update(
                    {
                        "outcome": "exception",
                        "rule_id": "",
                        "relation_class": "",
                        "terminal_disposition": "",
                        "current_terminal_disposition": current_dispositions.get(
                            current_group_id or "", "missing"
                        ),
                        "exception_code": error,
                    }
                )
                local_exception_count += 1
                exceptions.append(
                    {
                        "workstream": name,
                        "code": error,
                        "message": f"Group {group['independent_group_id']} was not classified uniquely",
                        "count": 1,
                        "examples": [group["independent_group_id"]],
                    }
                )
            else:
                expected = str(selected_rule["terminal_disposition"])
                current_value = current_dispositions.get(current_group_id or "", "missing")
                mismatch = expected != current_value
                decision.update(
                    {
                        "outcome": str(selected_rule["outcome"]),
                        "rule_id": str(selected_rule["id"]),
                        "relation_class": str(selected_rule["relation_class"]),
                        "terminal_disposition": expected,
                        "current_terminal_disposition": current_value,
                        "provenance_kind": str(selected_rule["provenance_kind"]),
                        "source_references": ",".join(
                            map(str, selected_rule.get("source_references", []))
                        ),
                        "used_claim": str(selected_rule["used_claim"]),
                        "exception_code": "disposition_mismatch" if mismatch else "",
                    }
                )
                if mismatch:
                    local_exception_count += 1
                    exceptions.append(
                        {
                            "workstream": name,
                            "code": "disposition_mismatch",
                            "message": (
                                f"{group['independent_group_id']}: independent={expected}, "
                                f"current={current_value}"
                            ),
                            "count": 1,
                            "examples": [group["independent_group_id"]],
                        }
                    )
                else:
                    applied_count += 1
                disposition_counts[expected] += 1
                relation_counts[str(selected_rule["relation_class"])] += 1
            decisions.append(decision)

        fine_result = fine_family_results.get(name)
        fine_validated = bool(
            fine_result and fine_result.get("topology_independently_validated")
        )
        relation_block = {
            "workstream": name,
            "scope": "candidate_edge_reconstruction",
            "outcome": "blocked",
            "reason": (
                "Terminal populations, annotation groups and dispositions are reconstructed, "
                "but the complete fine candidate-edge set is not independently regenerated by rules-v1."
            ),
            "next_action": (
                "Add a source-backed independent candidate builder, compare every relation, "
                "then classify additions, removals and unsupported edges."
            ),
        }
        if name == "vision" and optic_comparison["pass"]:
            relation_block["reason"] += " The 2628 published R7/R8 column relations already match exactly."
        if not fine_validated:
            blocked.append(relation_block)
        initial_exception_count = sum(
            1 for item in exceptions if item["workstream"] == name
        )
        workstream_summaries[name] = {
            "direction": str(spec["direction"]),
            "independent_terminals": len(terminal_ids),
            "current_terminals": len(current_terminal_ids),
            "independent_groups": len(groups),
            "current_groups": len(current_groups),
            "applied_groups": applied_count,
            "disposition_counts": dict(disposition_counts),
            "relation_class_counts": dict(relation_counts),
            "blocked_relation_families": 0 if fine_validated else 1,
            "unexpected_exceptions": initial_exception_count,
            "status": (
                "independently_validated"
                if fine_validated and initial_exception_count == 0
                else "partial_pass"
                if initial_exception_count == 0
                else "exceptions_present"
            ),
        }
        if fine_result is not None:
            expanded_relation_key = (
                "independent_terminal_actuator_relations"
                if name == "motor_output"
                else "independent_terminal_observable_relations"
            )
            workstream_summaries[name]["fine_candidate_envelope"] = {
                "semantic_topology_sha256": fine_result["semantic_topology_sha256"],
                "candidate_edge_count": fine_result["candidate_edge_count"],
                "expanded_terminal_relations": fine_result["prewiring_comparison"][
                    expanded_relation_key
                ],
                "current_relation_match": fine_result["prewiring_comparison"]["pass"],
                "clean_rebuild_repeat_pass": fine_result["clean_rebuild_repeat"]["pass"],
                "topology_independently_validated": fine_result[
                    "topology_independently_validated"
                ],
            }
        print(
            f"  [{name}] {len(terminal_ids):,} terminals, {len(groups):,} groups, "
            f"{applied_count:,} applied, {initial_exception_count:,} unexpected exceptions",
            flush=True,
        )

    if "vision" in selected_workstreams and not optic_comparison["pass"]:
        exceptions.append(
            {
                "workstream": "vision",
                "code": "published_optic_relation_diff",
                "message": "Independent optic-column relations differ from prewiring",
                "count": optic_comparison["missing_from_current"]
                + optic_comparison["extra_in_current"],
                "examples": optic_comparison["representative_missing"]
                + optic_comparison["representative_extra"],
            }
        )

    print("[4/6] Writing exhaustive decisions and exception packets...", flush=True)
    stable_decisions = sorted(
        decisions, key=lambda item: (str(item["workstream"]), str(item["independent_group_id"]))
    )
    decision_digest = hashlib.sha256(
        json.dumps(stable_decisions, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    pd.DataFrame(stable_decisions).to_parquet(run_dir / "group-decisions.parquet", index=False)
    (run_dir / "exceptions.json").write_text(
        json.dumps(exceptions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "blocked-review-packets.json").write_text(
        json.dumps(blocked, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    source_hashes = {
        name: {"path": _relative(path), "sha256": _sha256_file(path)}
        for name, path in source_paths.items()
    }
    total_groups = len(decisions)
    total_applied = sum(item.get("outcome") == "applied" for item in decisions)
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": now.isoformat(),
        "git_commit": _git_commit(),
        "ruleset_id": str(ruleset["id"]),
        "ruleset_path": _relative(ruleset_path),
        "ruleset_sha256": _sha256_file(ruleset_path),
        "direction": direction,
        "claim": (
            "Independent raw-data reconstruction of terminal scopes, annotation-backed groups "
            "and group dispositions; registered family-specific builders independently "
            "reconstruct and compare their fine candidate matrices."
        ),
        "scientific_review_status": "in_progress",
        "source_hashes": source_hashes,
        "decision_sha256": decision_digest,
        "totals": {
            "terminals": len(all_terminal_ids),
            "groups": total_groups,
            "applied": int(total_applied),
            "blocked_relation_families": len(blocked),
        },
        "workstreams": workstream_summaries,
        "fine_family_results": {
            name: {
                "status": item["status"],
                "semantic_topology_sha256": item["semantic_topology_sha256"],
                "candidate_edge_count": item["candidate_edge_count"],
                "prewiring_comparison": item["prewiring_comparison"],
                "clean_rebuild_repeat": item["clean_rebuild_repeat"],
                "degrees_of_freedom": item["degrees_of_freedom"],
                "candidate_set_statistics": item["candidate_set_statistics"],
                "masked_gold_standard": item["masked_gold_standard"],
            }
            for name, item in fine_family_results.items()
        },
        "optic_assignment_comparison": optic_comparison,
        "unexpected_exception_count": len(exceptions),
        "exceptions": exceptions,
        "blocked": blocked,
        "acceptance": {
            "terminal_and_group_accounting_pass": len(exceptions) == 0,
            "published_vision_subgraph_pass": optic_comparison["pass"],
            "fine_candidate_matrices_independently_reconstructed": len(blocked) == 0,
            "global_scientific_revalidation_pass": False,
        },
        "next_action": (
            "Implement the independent candidate-edge builder for unregistered vision, "
            "and rerun until every current relation is "
            "classified as confirmed, added, removed, unsupported or explicitly blocked."
        ),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "latest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "summary": _relative(run_dir / "summary.json"),
                "decision_sha256": decision_digest,
                "unexpected_exception_count": len(exceptions),
                "scientific_review_status": "in_progress",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("[5/6] Rendering the human-readable report...", flush=True)
    _render_html(summary, report_path)
    print("[6/6] Revalidation accounting complete.", flush=True)
    print(f"[RESULT] {total_applied:,}/{total_groups:,} groups classified by rules")
    print(f"[RESULT] {len(exceptions):,} unexpected exceptions")
    print(f"[BLOCKED] {len(blocked):,} fine candidate relation families still require independent builders")
    print(f"[REPORT] {_relative(report_path)}")
    print(f"[DATA] {_relative(run_dir / 'summary.json')}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Independently reconstruct and compare MaleCNS interface wiring rules"
    )
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULESET)
    parser.add_argument("--direction", choices=("all", "input", "output"), default="all")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    try:
        summary = run_revalidation(args.rules, args.direction)
    except Exception as exc:
        print(f"WIRING_REVALIDATION_FAILED: {type(exc).__name__}: {exc}", flush=True)
        return 1
    if not args.no_open:
        webbrowser.open(REPORT_PATH.resolve().as_uri())
    return 0 if summary["unexpected_exception_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

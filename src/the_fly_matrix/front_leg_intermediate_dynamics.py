from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from .ledger import ROOT


CAMPAIGN_PATH = (
    ROOT
    / "calibration"
    / "campaigns"
    / "front-leg-intermediate-dynamics-accounting-v0.yaml"
)
RESULT_PATH = (
    ROOT / "calibration" / "runner" / "front-leg-intermediate-dynamics-accounting-v0.yaml"
)
OUTPUT_ROOT = (
    ROOT
    / "data"
    / "derived"
    / "calibration"
    / "front-leg-intermediate-dynamics-accounting-v0"
)


class IntermediateDynamicsError(RuntimeError):
    """Raised when the bounded population assignment contract is violated."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise IntermediateDynamicsError(f"{path} must contain a YAML mapping")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_missing(value: Any) -> bool:
    return bool(pd.isna(value)) or str(value).strip() == ""


def _matches(row: Mapping[str, Any], selector: Mapping[str, Any]) -> bool:
    clauses = selector.get("all", [])
    if not clauses:
        raise IntermediateDynamicsError("every assignment rule needs a nonempty all selector")
    for clause in clauses:
        field = str(clause["field"])
        operation = str(clause["op"])
        value = row.get(field)
        if operation == "equals":
            passed = not _is_missing(value) and str(value) == str(clause["value"])
        elif operation == "is_missing":
            passed = _is_missing(value)
        elif operation == "not_missing":
            passed = not _is_missing(value)
        elif operation == "in":
            passed = not _is_missing(value) and value in clause["value"]
        else:
            raise IntermediateDynamicsError(f"unsupported selector operation: {operation}")
        if not passed:
            return False
    return True


def classify_intermediates(
    inventory: pd.DataFrame,
    paths: pd.DataFrame,
    transmitter_prior: pd.DataFrame,
    rules_record: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any], list[dict[str, Any]]]:
    """Apply ordered evidence rules and exhaustively account the frozen scope."""

    required_inventory = {
        "body_id",
        "superclass",
        "subclass",
        "type",
        "somaSide",
        "chain_assignment",
        "parameter_values_emitted",
    }
    if missing := required_inventory - set(inventory):
        raise IntermediateDynamicsError(f"intermediate inventory misses {sorted(missing)}")
    if inventory["body_id"].duplicated().any():
        raise IntermediateDynamicsError("intermediate inventory contains duplicate bodies")
    if set(inventory["chain_assignment"].astype(str)) != {"dual_unresolved"}:
        raise IntermediateDynamicsError("upstream intermediate assignments drifted")
    if inventory["parameter_values_emitted"].astype(bool).any():
        raise IntermediateDynamicsError("upstream chain emitted parameter values")

    prior_columns = [
        "body_id",
        "effective_transmitter",
        "sign_code",
        "sign_interpretation",
    ]
    if missing := set(prior_columns) - set(transmitter_prior):
        raise IntermediateDynamicsError(f"transmitter prior misses {sorted(missing)}")
    prior = transmitter_prior[prior_columns].copy()
    if prior["body_id"].duplicated().any():
        raise IntermediateDynamicsError("transmitter prior contains duplicate body IDs")

    frame = inventory.copy()
    frame["body_id"] = frame["body_id"].astype(np.int64)
    frame = frame.merge(prior, on="body_id", how="left", validate="one_to_one")
    if frame["effective_transmitter"].isna().any():
        missing_bodies = frame.loc[frame["effective_transmitter"].isna(), "body_id"].tolist()
        raise IntermediateDynamicsError(
            f"scoped bodies absent from frozen transmitter prior: {missing_bodies}"
        )

    scoped_ids = set(frame["body_id"].tolist())
    path_rows = paths.loc[paths["intermediate_body_id"].isin(scoped_ids)].copy()
    path_rows["intermediate_body_id"] = path_rows["intermediate_body_id"].astype(np.int64)
    participation = (
        path_rows.groupby("intermediate_body_id")
        .agg(
            path_count=("intermediate_body_id", "size"),
            unique_source_count=("source_body_id", "nunique"),
            unique_target_count=("target_body_id", "nunique"),
            first_edge_weight_sum=("first_edge_weight", "sum"),
            second_edge_weight_sum=("second_edge_weight", "sum"),
        )
        .reset_index()
        .rename(columns={"intermediate_body_id": "body_id"})
    )
    frame = frame.merge(participation, on="body_id", how="left", validate="one_to_one")
    if frame["path_count"].isna().any():
        missing_bodies = frame.loc[frame["path_count"].isna(), "body_id"].tolist()
        raise IntermediateDynamicsError(
            f"scoped bodies absent from frozen path inventory: {missing_bodies}"
        )

    rules = list(rules_record.get("rules", []))
    if not rules:
        raise IntermediateDynamicsError("assignment rules are empty")
    assignments: list[dict[str, Any]] = []
    rule_counts = {str(rule["id"]): 0 for rule in rules}
    for row in frame.to_dict(orient="records"):
        matches = [rule for rule in rules if _matches(row, rule["selector"])]
        if not matches:
            raise IntermediateDynamicsError(f"body {row['body_id']} has no assignment rule")
        highest = max(int(rule["priority"]) for rule in matches)
        winners = [rule for rule in matches if int(rule["priority"]) == highest]
        if len(winners) != 1:
            raise IntermediateDynamicsError(
                f"body {row['body_id']} has conflicting highest-priority rules"
            )
        winner = winners[0]
        rule_id = str(winner["id"])
        rule_counts[rule_id] += 1
        assignments.append(
            {
                "body_id": int(row["body_id"]),
                "assignment": str(winner["assignment"]),
                "assignment_confidence": str(winner["assignment_confidence"]),
                "assignment_rule_id": rule_id,
                "evidence_ids": ";".join(str(value) for value in winner["evidence_ids"]),
                "rationale": str(winner["rationale"]),
                "lower_priority_matches": ";".join(
                    str(rule["id"]) for rule in matches if rule is not winner
                ),
            }
        )
    frame = frame.merge(pd.DataFrame(assignments), on="body_id", validate="one_to_one")
    frame["parameter_values_emitted"] = False

    for rule in rules:
        observed = rule_counts[str(rule["id"])]
        expected = int(rule["expected_count"])
        if observed != expected:
            raise IntermediateDynamicsError(
                f"rule {rule['id']} count drift: observed {observed}, expected {expected}"
            )

    exceptions = [
        {
            "id": "exception.native_dynamics_evidence_missing",
            "status": "open_propagate_dual_unresolved",
            "count": int(frame["assignment"].eq("dual_unresolved").sum()),
            "meaning": "Identity/sign evidence exists but native event-versus-graded evidence does not.",
        },
        {
            "id": "exception.annotation_type_missing",
            "status": "open_low_identity_resolution",
            "count": int(frame["type"].map(_is_missing).sum()),
            "body_ids": [
                int(value) for value in frame.loc[frame["type"].map(_is_missing), "body_id"]
            ],
        },
        {
            "id": "exception.motor_types_without_direct_dynamics_transfer",
            "status": "open_keep_dual_unresolved",
            "count": int(
                (
                    frame["superclass"].eq("vnc_motor")
                    & frame["assignment"].eq("dual_unresolved")
                ).sum()
            ),
            "body_ids": [
                int(value)
                for value in frame.loc[
                    frame["superclass"].eq("vnc_motor")
                    & frame["assignment"].eq("dual_unresolved"),
                    "body_id",
                ]
            ],
        },
    ]
    assignment_counts = {
        str(key): int(value) for key, value in frame["assignment"].value_counts().items()
    }
    summary = {
        "scoped_bodies": len(frame),
        "assignment_counts": assignment_counts,
        "rule_counts": rule_counts,
        "missing_type_annotations": int(frame["type"].map(_is_missing).sum()),
        "superclass_counts": {
            str(key): int(value)
            for key, value in frame["superclass"].fillna("(missing)").value_counts().items()
        },
        "transmitter_counts": {
            str(key): int(value)
            for key, value in frame["effective_transmitter"].value_counts().items()
        },
        "accounted_two_hop_paths": len(path_rows),
        "unique_sources_in_accounted_paths": int(path_rows["source_body_id"].nunique()),
        "unique_targets_in_accounted_paths": int(path_rows["target_body_id"].nunique()),
        "path_count_min": int(frame["path_count"].min()),
        "path_count_median": float(frame["path_count"].median()),
        "path_count_max": int(frame["path_count"].max()),
        "parameter_values_emitted": 0,
        "topology_changes": 0,
        "behavior_targets_exposed": 0,
    }
    return frame.sort_values("body_id"), summary, exceptions


def _validate_acceptance(summary: Mapping[str, Any], campaign: Mapping[str, Any]) -> None:
    acceptance = campaign["acceptance"]
    observed = {
        "expected_bodies": summary["scoped_bodies"],
        "expected_event_required": summary["assignment_counts"].get("event_required", 0),
        "expected_dual_unresolved": summary["assignment_counts"].get("dual_unresolved", 0),
        "expected_graded_required": summary["assignment_counts"].get("graded_required", 0),
        "expected_missing_type": summary["missing_type_annotations"],
        "expected_rules_applied": len(summary["rule_counts"]),
        "expected_accounted_two_hop_paths": summary["accounted_two_hop_paths"],
        "expected_unique_sources_in_accounted_paths": summary[
            "unique_sources_in_accounted_paths"
        ],
        "expected_unique_targets_in_accounted_paths": summary[
            "unique_targets_in_accounted_paths"
        ],
        "expected_parameter_values_emitted": summary["parameter_values_emitted"],
    }
    for key, value in observed.items():
        if int(acceptance[key]) != int(value):
            raise IntermediateDynamicsError(
                f"acceptance drift for {key}: observed {value}, expected {acceptance[key]}"
            )
    if campaign.get("behavior_targets"):
        raise IntermediateDynamicsError("intermediate accounting cannot expose behavior")
    if campaign.get("topology_changes_allowed") is not False:
        raise IntermediateDynamicsError("intermediate accounting cannot change topology")


def run_intermediate_dynamics_accounting(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    campaign = _load_yaml(campaign_path)
    frozen = campaign["frozen_inputs"]
    paths = {
        key: ROOT / str(value)
        for key, value in frozen.items()
        if key not in {"upstream_semantic_result_sha256", "transmitter_semantic_values_sha256"}
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise IntermediateDynamicsError(f"missing frozen inputs: {missing}")

    print("[1/6] Verification de la chaine amont et du prior neurotransmetteur", flush=True)
    upstream = _load_yaml(paths["prior_chain_result"])
    if upstream["semantic_result_sha256"] != frozen["upstream_semantic_result_sha256"]:
        raise IntermediateDynamicsError("upstream chain semantic result drift")
    parameter_set = _load_yaml(paths["transmitter_parameter_set"])
    observed_prior_hash = parameter_set["parameter_families"][0]["semantic_values_sha256"]
    if observed_prior_hash != frozen["transmitter_semantic_values_sha256"]:
        raise IntermediateDynamicsError("transmitter semantic prior drift")

    print("[2/6] Chargement des 150 corps et de leurs chemins locaux", flush=True)
    inventory = pd.read_csv(paths["intermediate_inventory"])
    central_paths = pd.read_csv(paths["central_paths"])
    transmitter_prior = pd.read_parquet(paths["transmitter_prior"])
    rules_record = _load_yaml(paths["rules"])

    print("[3/6] Application des regles ordonnees et detection des exceptions", flush=True)
    classified, summary, exceptions = classify_intermediates(
        inventory, central_paths, transmitter_prior, rules_record
    )
    _validate_acceptance(summary, campaign)

    print("[4/6] Construction de la priorite d'acquisition sans selection fonctionnelle", flush=True)
    priority = classified.loc[classified["assignment"].eq("dual_unresolved")].copy()
    priority = priority.sort_values(["path_count", "body_id"], ascending=[False, True])
    priority["priority_basis"] = "frozen_local_path_participation_only"
    priority["selection_allowed"] = False

    print("[5/6] Ecriture des artefacts derives et du resultat compact", flush=True)
    output_root.mkdir(parents=True, exist_ok=True)
    classified_path = output_root / "classified-intermediates.csv"
    priority_path = output_root / "unresolved-evidence-priority.csv"
    exceptions_path = output_root / "exceptions.yaml"
    classified.to_csv(classified_path, index=False)
    priority.to_csv(priority_path, index=False)
    exceptions_path.write_text(
        yaml.safe_dump({"schema_version": 1, "exceptions": exceptions}, sort_keys=False),
        encoding="utf-8",
    )
    input_hashes = {key: _sha256(path) for key, path in paths.items()}
    artifact = {
        "schema_version": 1,
        "campaign_id": campaign["id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "pass_exhaustive_accounting_two_event_required_148_dual_unresolved",
        "claim_label": campaign["claim_label"],
        "input_hashes": input_hashes,
        "summary": summary,
        "exceptions": exceptions,
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "artifact_refs": [
            str(classified_path.relative_to(ROOT)).replace("\\", "/"),
            str(priority_path.relative_to(ROOT)).replace("\\", "/"),
            str(exceptions_path.relative_to(ROOT)).replace("\\", "/"),
        ],
        "next_action": campaign["next_action"],
    }
    artifact["semantic_result_sha256"] = _canonical_hash(
        {key: value for key, value in artifact.items() if key != "generated_at"}
    )
    summary_path = output_root / "summary.json"
    summary_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    compact = {
        "schema_version": 1,
        "id": "runner_result.front_leg_intermediate_dynamics_accounting.v0",
        "campaign_id": campaign["id"],
        "target_id": campaign["target_id"],
        "status": artifact["status"],
        "claim_label": campaign["claim_label"],
        "command": "front_leg_intermediate_dynamics.bat",
        "behavior_targets": [],
        "campaign_sha256": _sha256(campaign_path),
        "rules_sha256": input_hashes["rules"],
        "upstream_semantic_result_sha256": upstream["semantic_result_sha256"],
        "semantic_result_sha256": artifact["semantic_result_sha256"],
        "summary": summary,
        "exceptions": exceptions,
        "artifact_ref": str(summary_path.relative_to(ROOT)).replace("\\", "/"),
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    result_path.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")

    print("[6/6] Resume", flush=True)
    print(
        f"[SCOPE] {summary['scoped_bodies']}/{summary['scoped_bodies']} corps comptes; "
        f"{summary['accounted_two_hop_paths']} chemins locaux attribues",
        flush=True,
    )
    print(
        f"[ASSIGNMENTS] {summary['assignment_counts'].get('event_required', 0)} event_required; "
        f"{summary['assignment_counts'].get('dual_unresolved', 0)} dual_unresolved",
        flush=True,
    )
    print(
        f"[EXCEPTIONS] type absent={summary['missing_type_annotations']}; "
        "chaque exception conserve une raison et une prochaine action",
        flush=True,
    )
    print("[BOUNDARY] 0 valeur, 0 topologie, 0 comportement, 0 selection de chemin", flush=True)
    print(f"[HASH] {artifact['semantic_result_sha256']}", flush=True)
    return compact


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply evidence rules to the bounded front-leg CNS intermediates"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    run_intermediate_dynamics_accounting(args.campaign, output_root=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

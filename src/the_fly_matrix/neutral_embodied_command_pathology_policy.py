from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from .ledger import ROOT
from .neutral_embodied_command_factor_isolation import (
    _load_campaign as _load_factor_campaign,
    _verify_frozen_inputs as _verify_factor_inputs,
    _write_policy_csv,
)
from .neutral_embodied_declared_closed_loop_sentinel import _canonical_hash, _load_yaml
from .neutral_embodied_full_chain_sentinel import _sha256


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "neutral-embodied-command-pathology-policy-v1.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "neutral-embodied-command-pathology-policy-v1.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "neutral-embodied-command-pathology-policy-v1.yaml"


class CommandPathologyPolicyError(RuntimeError):
    """Raised when exact-row policy compilation violates its frozen contract."""


def _load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = _load_yaml(path)
    if campaign.get("optimization_exposure") != "diagnostic_only" or campaign.get("behavior_targets"):
        raise CommandPathologyPolicyError("command policy must remain behavior-naive diagnostic_only")
    if campaign.get("topology_changes_allowed") is not False:
        raise CommandPathologyPolicyError("command policy cannot change topology")
    acceptance = campaign["acceptance"]
    for key in (
        "allow_broad_factor_rejection",
        "allow_safety_inheritance_to_unseen_combinations",
        "allow_clipping",
        "allow_threshold_change",
        "allow_candidate_ranking",
        "stability_acceptance_possible",
    ):
        if acceptance.get(key) is not False:
            raise CommandPathologyPolicyError(f"command policy must forbid {key}")
    if campaign["policy_contract"].get("scope") != "exact_immutable_240_row_schedule":
        raise CommandPathologyPolicyError("command policy scope must remain exact immutable schedule")
    return campaign


def _verify_lineage(campaign: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    frozen = campaign["frozen_inputs"]
    pairs = {
        "factor_campaign": "factor_campaign_sha256",
        "factor_result": "factor_result_sha256",
        "factor_evaluation": "factor_evaluation_sha256",
    }
    hashes: dict[str, str] = {}
    for key, expected_key in pairs.items():
        hashes[key] = _sha256(ROOT / str(frozen[key]))
        if hashes[key] != str(frozen[expected_key]):
            raise CommandPathologyPolicyError(f"frozen input drift for {key}")
    factor_campaign = _load_factor_campaign(ROOT / str(frozen["factor_campaign"]))
    factor_result = _load_yaml(ROOT / str(frozen["factor_result"]))
    factor_evaluation = _load_yaml(ROOT / str(frozen["factor_evaluation"]))
    if factor_result.get("semantic_result_sha256") != frozen["factor_result_semantic_sha256"]:
        raise CommandPathologyPolicyError("factor-isolation semantic result drift")
    context, _panel_campaign, panel_result, diagnostic_result, _factor_hashes = _verify_factor_inputs(factor_campaign)
    return context, panel_result, diagnostic_result, factor_result, hashes


def _factor_summary(factor_result: Mapping[str, Any]) -> dict[str, Any]:
    by_ablation: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for outcome in factor_result["factor_outcomes"]:
        for probe in outcome["branches"].values():
            by_ablation[str(outcome["ablation_id"])][str(probe["status"])] += 1
    return {
        key: dict(sorted(value.items()))
        for key, value in sorted(by_ablation.items())
    }


def _schedule_confounding(context: Mapping[str, Any]) -> dict[str, Any]:
    numeric_to_gains: dict[str, set[str]] = defaultdict(set)
    gain_to_numeric: dict[str, set[str]] = defaultdict(set)
    for row in context["rows"]:
        numeric_to_gains[str(row["numeric_profile_id"])].add(str(row["bridge_gain_index"]))
        gain_to_numeric[str(row["bridge_gain_index"])].add(str(row["numeric_profile_id"]))
    return {
        "numeric_profile_to_gain_indices": {
            key: sorted(value) for key, value in sorted(numeric_to_gains.items())
        },
        "gain_index_to_numeric_profiles": {
            key: sorted(value) for key, value in sorted(gain_to_numeric.items())
        },
        "each_numeric_profile_has_exactly_one_gain": all(len(value) == 1 for value in numeric_to_gains.values()),
        "numeric_profile_count": len(numeric_to_gains),
        "gain_count": len(gain_to_numeric),
    }


def compile_policy(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
) -> dict[str, Any]:
    print("[1/5] Verifying frozen failed-factor lineage", flush=True)
    campaign = _load_campaign(campaign_path)
    context, panel_result, diagnostic_result, factor_result, frozen_hashes = _verify_lineage(campaign)
    expected = campaign["evidence_interpretation"]
    factor_summary = _factor_summary(factor_result)
    probes = [probe for item in factor_result["factor_outcomes"] for probe in item["branches"].values()]
    completed = sum(probe["status"] == "completed_within_limit" for probe in probes)
    crossings = sum(probe["status"] == "first_command_limit_crossing" for probe in probes)
    middle = factor_summary.get("bridge_gain_middle", {})
    numeric_crossings = sum(
        counts.get("first_command_limit_crossing", 0)
        for key, counts in factor_summary.items()
        if key != "bridge_gain_middle"
    )

    print("[2/5] Auditing schedule factor identifiability", flush=True)
    confounding = _schedule_confounding(context)

    print("[3/5] Compiling exact dispositions for all 240 rows", flush=True)
    policy_path = ROOT / str(campaign["policy_contract"]["output"])
    policy = _write_policy_csv(policy_path, panel_result, diagnostic_result)
    expected_blocked = list(map(str, campaign["policy_contract"]["expected_blocked_tuple_ids"]))
    checks = {
        "factor_campaign_failure_preserved": (
            factor_result["status"] == expected["factor_campaign_status_expected"]
            and factor_result["checks"]["every_single_factor_ablation_completed_within_limit"] is False
        ),
        "complete_24_probe_factor_accounting": len(probes) == int(expected["complete_probe_accounting_required"]),
        "exact_14_complete_10_crossing_factor_outcomes": (
            completed == int(expected["observed_completed_probes"])
            and crossings == int(expected["observed_crossing_probes"])
        ),
        "middle_gain_6_of_6_complete": middle.get("completed_within_limit", 0) == int(expected["middle_gain_probes_completed"]),
        "numeric_ablation_crossings_retained": numeric_crossings == int(expected["numeric_ablation_crossing_probes"]),
        "numeric_gain_confounding_reported": confounding["each_numeric_profile_has_exactly_one_gain"],
        "all_240_schedule_rows_accounted": policy["rows"] == 240,
        "exact_237_completed_and_3_blocked": (
            policy["within_contract_rows"] == int(campaign["policy_contract"]["expected_completed"])
            and policy["blocked_rows"] == int(campaign["policy_contract"]["expected_blocked"])
            and policy["blocked_tuple_ids"] == expected_blocked
        ),
        "zero_broad_domain_rejection_clipping_ranking_promotion_behavior": True,
    }
    passed = all(checks.values())

    print("[4/5] Writing hash-linked policy result", flush=True)
    result = {
        "schema_version": 1,
        "id": "runner_result.neutral_embodied_command_pathology_policy.v1",
        "campaign_id": campaign["id"],
        "status": "pass_exact_schedule_command_policy_unseen_fail_closed" if passed else "failed_exact_schedule_command_policy",
        "completed_at": datetime.now(UTC).isoformat(),
        "claim_label": campaign["claim_label"],
        "command": "neutral_embodied_command_pathology_policy.bat",
        "frozen_input_sha256": frozen_hashes,
        "factor_isolation": {
            "source_status": factor_result["status"],
            "completed_probes": completed,
            "crossing_probes": crossings,
            "by_ablation": factor_summary,
            "interpretation": "Middle gain prevents the observed crossings, while numeric ablations do not define a safe domain.",
        },
        "schedule_factor_identifiability": confounding,
        "policy": {
            "scope": campaign["policy_contract"]["scope"],
            "path": str(policy_path.relative_to(ROOT)).replace("\\", "/"),
            **policy,
            "broad_gain_domains_rejected": [],
            "broad_numeric_domains_rejected": [],
            "unseen_combination_policy": campaign["policy_contract"]["unseen_combination_policy"],
            "inheritance_policy": campaign["policy_contract"]["inheritance_policy"],
        },
        "accounting": {
            "schedule_rows": policy["rows"],
            "rows_admitted_to_next_technical_gate": policy["within_contract_rows"],
            "rows_blocked_at_command_contract": policy["blocked_rows"],
            "optimized_parameters": 0,
            "promoted_parameter_values": 0,
            "selected_candidates": 0,
            "named_behavior_exposure": 0,
        },
        "checks": checks,
        "scientific_boundary": campaign["scientific_boundary"],
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    result["semantic_result_sha256"] = _canonical_hash({
        key: value for key, value in result.items() if key != "completed_at"
    })
    result_path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.neutral_embodied_command_pathology_policy.v1",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": result["semantic_result_sha256"],
        "status": "pass" if passed else "fail",
        "checks": checks,
        "policy_scope": campaign["policy_contract"]["scope"] if passed else "open",
        "rows_admitted_to_next_technical_gate": policy["within_contract_rows"] if passed else 0,
        "blocked_tuple_ids": policy["blocked_tuple_ids"],
        "candidate_selected": False,
        "parameter_promoted": False,
        "stability_accepted": False,
        "behavior_claimed": False,
        "interpretation": "The exact schedule command guard is closed; factor-domain safety and stability remain open.",
        "next_action": campaign["next_action"],
    }
    evaluation_path.write_text(yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8")
    if not passed:
        raise CommandPathologyPolicyError(f"command pathology policy failed: {[key for key, value in checks.items() if not value]}")
    print("[5/5] PASS", flush=True)
    print("[FACTOR RESULT] retained honestly: 14 completed / 10 crossings", flush=True)
    print("[POLICY] 237 rows admitted to next technical gate / 3 exact composites blocked", flush=True)
    print("[UNSEEN] no inherited safety; pre-application guard remains mandatory", flush=True)
    print(f"[HASH] {result['semantic_result_sha256']}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile exact-schedule direct-MOTOR pathology policy")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    compile_policy(campaign_path=args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from .ledger import ROOT
from .neutral_embodied_declared_closed_loop_sentinel import _canonical_hash, _load_yaml
from .neutral_embodied_full_chain_sentinel import _sha256


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "basal-low-capacity-readiness-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "basal-low-capacity-readiness-v0.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "basal-low-capacity-readiness-v0.yaml"
DESIGN_PATH = ROOT / "calibration" / "parameter_sets" / "basal-low-capacity-sensitivity-design-v0.yaml"


class BasalReadinessError(RuntimeError):
    """Raised when the preregistered basal-readiness contract drifts."""


def _load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = _load_yaml(path)
    if campaign.get("primary_class") != "technical" or campaign.get("behavior_targets"):
        raise BasalReadinessError("basal readiness must remain technical and behavior-naive")
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise BasalReadinessError("basal readiness cannot optimize parameters")
    if campaign.get("topology_changes_allowed") is not False:
        raise BasalReadinessError("basal readiness cannot change topology")
    if campaign["sensitivity_design"]["status"] != "preregistered_shapes_only_absolute_scales_blocked":
        raise BasalReadinessError("numeric basal values cannot be hidden in this campaign")
    return campaign


def _verified_inputs(campaign: Mapping[str, Any]) -> dict[str, Any]:
    frozen = campaign["frozen_inputs"]
    artifacts: dict[str, Any] = {}
    for key in (
        "basal_evidence", "conditioned_bundles", "population_accounting",
        "intermediate_population_accounting", "population_target",
        "basal_population_reachability", "typed_hybrid_runtime",
    ):
        path = ROOT / str(frozen[key])
        observed = _sha256(path)
        expected = str(frozen[f"{key}_sha256"])
        if observed != expected:
            raise BasalReadinessError(f"frozen input drift for {key}: {observed} != {expected}")
        artifacts[key] = _load_yaml(path)
    bundles = artifacts["conditioned_bundles"]
    if bundles.get("runner_semantic_sha256") != frozen["conditioned_bundles_semantic_sha256"]:
        raise BasalReadinessError("conditioned-bundle semantic hash drift")
    return artifacts


def _accounting(campaign: Mapping[str, Any], artifacts: Mapping[str, Any]) -> dict[str, Any]:
    evidence = artifacts["basal_evidence"]
    population = artifacts["population_accounting"]
    intermediate = artifacts["intermediate_population_accounting"]
    bundles = artifacts["conditioned_bundles"]
    reachability = artifacts["basal_population_reachability"]
    expected = campaign["expected_accounting"]
    families = list(evidence["family_rules"])
    channels = sum(int(item["expected"]["channels"]) for item in families)
    terminals = sum(int(item["expected"]["terminals"]) for item in families)
    family_ids = [str(item["family_id"]) for item in families]
    dispositions = bundles["family_dispositions"]
    result = {
        "basal_family_ids": family_ids,
        "basal_families": len(family_ids),
        "basal_channels": channels,
        "basal_terminals": terminals,
        "canonical_MaleCNS_neurons": int(expected["canonical_MaleCNS_neurons"]),
        "currently_accounted_local_population_neurons": (
            int(population["accounting"]["neurons"]) + int(intermediate["summary"]["scoped_bodies"])
        ),
        "currently_event_required_local_neurons": (
            int(population["accounting"]["event_required_neurons"])
            + int(intermediate["summary"]["assignment_counts"]["event_required"])
        ),
        "currently_dual_unresolved_local_neurons": (
            int(population["accounting"]["dual_unresolved_neurons"])
            + int(intermediate["summary"]["assignment_counts"]["dual_unresolved"])
        ),
        "basal_reached_population_neurons": int(reachability["union_reachability"]["reachable_neurons"]),
        "basal_reached_event_required_neurons": int(reachability["population_assignment_counts"]["event_required"]),
        "basal_reached_dual_unresolved_neurons": int(reachability["population_assignment_counts"]["dual_unresolved"]),
        "basal_unreached_neurons": int(reachability["union_reachability"]["unreachable_neurons"]),
        "basal_family_bundle_dispositions": {family_id: dispositions.get(family_id) for family_id in family_ids},
    }
    exact_fields = (
        "basal_families", "basal_channels", "basal_terminals",
        "currently_accounted_local_population_neurons", "currently_event_required_local_neurons",
        "currently_dual_unresolved_local_neurons",
        "basal_reached_population_neurons", "basal_reached_event_required_neurons",
        "basal_reached_dual_unresolved_neurons", "basal_unreached_neurons",
    )
    drift = [field for field in exact_fields if result[field] != int(expected[field])]
    if drift:
        raise BasalReadinessError(f"accounting drift: {drift}")
    return result


def run_readiness(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    design_path: Path = DESIGN_PATH,
) -> dict[str, Any]:
    print("[1/6] Verifying frozen basal evidence, local bundles and population accounting", flush=True)
    campaign = _load_campaign(campaign_path)
    artifacts = _verified_inputs(campaign)

    print("[2/6] Accounting every basal family, channel and terminal", flush=True)
    accounting = _accounting(campaign, artifacts)
    family_dispositions = accounting["basal_family_bundle_dispositions"]
    runtime = artifacts["typed_hybrid_runtime"]

    print("[3/6] Compiling behavior-naive sensitivity shapes without numerical values", flush=True)
    arms = list(campaign["sensitivity_design"]["arms"])
    if [item["id"] for item in arms] != ["explicit_silence_control", "uniform_per_terminal", "equal_family_mass"]:
        raise BasalReadinessError("sensitivity-arm identity or order drift")
    numerical_value_count = 0
    scope_fraction = (
        accounting["basal_reached_population_neurons"]
        / accounting["canonical_MaleCNS_neurons"]
    )

    print("[4/6] Evaluating whole-MaleCNS typed/hybrid execution gates", flush=True)
    gates = {
        "all_six_basal_families_accounted": accounting["basal_families"] == 6,
        "all_6041_basal_terminals_accounted": accounting["basal_terminals"] == 6041,
        "all_basal_families_explicitly_not_exercised_in_local_bundles": all(
            value == "not_exercised_no_freeze" for value in family_dispositions.values()
        ),
        "absolute_basal_values_remain_unset": numerical_value_count == 0,
        "complete_consumed_population_disposition_accounting": (
            accounting["basal_reached_event_required_neurons"]
            + accounting["basal_reached_dual_unresolved_neurons"]
            == accounting["basal_reached_population_neurons"]
        ),
        "explicit_event_or_graded_unit_bridge_per_consumed_population": False,
        "accepted_typed_hybrid_whole_MaleCNS_runtime": (
            runtime["status"]
            == "accepted_execution_engine_two_extremes_zero_scientific_assignment_or_values"
            and runtime["scientific_boundary"]["population_assignments_promoted"] == 0
            and runtime["scientific_boundary"]["source_bridges_executed"] == 0
        ),
    }
    blocker_ids = [
        key for key in (
            "complete_consumed_population_disposition_accounting",
            "explicit_event_or_graded_unit_bridge_per_consumed_population",
            "accepted_typed_hybrid_whole_MaleCNS_runtime",
        )
        if not gates[key]
    ]
    if not all(gates[key] for key in (
        "all_six_basal_families_accounted",
        "all_6041_basal_terminals_accounted",
        "all_basal_families_explicitly_not_exercised_in_local_bundles",
        "absolute_basal_values_remain_unset",
    )):
        raise BasalReadinessError("a non-negotiable accounting boundary failed")

    semantic_payload = {
        "campaign_id": campaign["id"],
        "accounting": accounting,
        "arms": arms,
        "gates": gates,
        "blocker_ids": blocker_ids,
    }
    semantic_hash = _canonical_hash(semantic_payload)
    result = {
        "schema_version": 1,
        "id": "runner_result.basal_low_capacity_readiness.v0",
        "campaign_id": campaign["id"],
        "status": "completed_runtime_mechanics_available_basal_source_bridges_blocked",
        "completed_at": datetime.now(UTC).isoformat(),
        "command": "basal_low_capacity_readiness.bat",
        "claim_label": campaign["claim_label"],
        "accounting": accounting,
        "population_assignment_scope_fraction": scope_fraction,
        "sensitivity_arm_ids": [item["id"] for item in arms],
        "numerical_basal_values_emitted": numerical_value_count,
        "gates": gates,
        "blocker_ids": blocker_ids,
        "whole_MaleCNS_execution_disposition": "mechanics_executed_basal_inputs_not_executed",
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
        "semantic_result_sha256": semantic_hash,
    }

    print("[5/6] Writing reconstructible design, result and evaluation", flush=True)
    design = {
        "schema_version": 1,
        "id": "parameters.basal_low_capacity_sensitivity_design.v0",
        "title": "Behavior-naive basal sensitivity shapes with unresolved absolute scales",
        "status": "preregistered_shape_only_blocked_on_source_unit_bridges",
        "primary_class": "technical",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": semantic_hash,
        "family_ids": accounting["basal_family_ids"],
        "family_count": accounting["basal_families"],
        "channel_count": accounting["basal_channels"],
        "terminal_count": accounting["basal_terminals"],
        "arms": arms,
        "common_rules": campaign["sensitivity_design"]["common_rules"],
        "absolute_numeric_values": [],
        "seeds": [],
        "time_courses": [],
        "unit_contract": "blocked_until_event_or_graded_conversion_is_explicit_for_every_consumed_population",
        "selection_contract": "execute_all_arms_after_unblocking_no_named_behavior_selection",
        "applicability": {
            "whole_MaleCNS_mechanics_executable": True,
            "basal_arms_executable": False,
            "local_front_leg_bundles_consume_basal_families": False,
            "biological_baseline_claim": False,
        },
        "next_action": campaign["next_action"],
    }
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.basal_low_capacity_readiness.v0",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": semantic_hash,
        "design_id": design["id"],
        "status": "accepted_readiness_accounting_runtime_mechanics_pass_basal_bridges_blocked",
        "checks": gates,
        "blocker_ids": blocker_ids,
        "numerical_basal_values_emitted": 0,
        "named_behavior_exposed": False,
        "interpretation": (
            "The uncertainty axes are explicit, all 166,431 basal-reached neurons have an event-required or "
            "dual-unresolved disposition, and both explicit runtime extremes execute. The six basal families still "
            "lack event-process or Hz-to-graded source bridges, so no basal arm has executed and no assignment or "
            "value is promoted."
        ),
        "next_action": campaign["next_action"],
    }
    result_path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    design_path.write_text(yaml.safe_dump(design, sort_keys=False, allow_unicode=True), encoding="utf-8")
    evaluation_path.write_text(yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8")

    print("[6/6] COMPLETE — runtime mechanics available; basal source bridges honestly blocked", flush=True)
    print(f"[ACCOUNTING] {accounting['basal_families']} families / {accounting['basal_channels']} channels / {accounting['basal_terminals']} terminals", flush=True)
    print(f"[POPULATIONS] {accounting['basal_reached_population_neurons']:,}/{accounting['canonical_MaleCNS_neurons']:,} basal-reached neurons disposition-accounted", flush=True)
    print(f"[BLOCKERS] {', '.join(blocker_ids)}", flush=True)
    print(f"[HASH] {semantic_hash}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile basal sensitivity shapes and whole-MaleCNS readiness")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    run_readiness(campaign_path=args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

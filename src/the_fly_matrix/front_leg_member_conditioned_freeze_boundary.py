from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from .ledger import ROOT
from .neutral_embodied_declared_closed_loop_sentinel import _canonical_hash, _load_yaml
from .neutral_embodied_full_chain_sentinel import _sha256


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "front-leg-member-conditioned-freeze-boundary-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "front-leg-member-conditioned-freeze-boundary-v0.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "front-leg-member-conditioned-freeze-boundary-v0.yaml"
PARAMETER_SET_PATH = ROOT / "calibration" / "parameter_sets" / "front-leg-member-conditioned-bundles-v0.yaml"


class MemberConditionedFreezeBoundaryError(RuntimeError):
    """Raised when the exact-member compilation contract is violated."""


def _load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = _load_yaml(path)
    if campaign.get("primary_class") != "technical" or campaign.get("behavior_targets"):
        raise MemberConditionedFreezeBoundaryError("compilation must remain technical and behavior-naive")
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise MemberConditionedFreezeBoundaryError("compilation cannot optimize parameters")
    if campaign.get("topology_changes_allowed") is not False:
        raise MemberConditionedFreezeBoundaryError("compilation cannot change topology")
    if int(campaign["acceptance"]["independent_family_freezes_expected"]) != 0:
        raise MemberConditionedFreezeBoundaryError("exact composites cannot imply independent family freezes")
    return campaign


def _verify_frozen_inputs(campaign: Mapping[str, Any]) -> dict[str, Any]:
    frozen = campaign["frozen_inputs"]
    artifacts: dict[str, Any] = {}
    for key in ("accepted_ensemble", "parent_result", "exact_schedule"):
        path = ROOT / str(frozen[key])
        observed = _sha256(path)
        expected = str(frozen[f"{key}_sha256"])
        if observed != expected:
            raise MemberConditionedFreezeBoundaryError(f"frozen input drift for {key}: {observed} != {expected}")
        artifacts[key] = path

    ensemble = _load_yaml(artifacts["accepted_ensemble"])
    parent = _load_yaml(artifacts["parent_result"])
    if parent.get("semantic_result_sha256") != frozen["parent_semantic_sha256"]:
        raise MemberConditionedFreezeBoundaryError("parent semantic result drift")
    expected_ids = list(map(str, campaign["expected_parent_state"]["exact_member_ids"]))
    if list(map(str, ensemble["ensemble"]["member_tuple_ids"])) != expected_ids:
        raise MemberConditionedFreezeBoundaryError("accepted ensemble member order or identity drift")
    accepted_from_parent = [
        str(item["tuple_id"])
        for item in parent["outcomes"]
        if item.get("classification") == "accepted_local_nonamplifying"
    ]
    if accepted_from_parent != expected_ids:
        raise MemberConditionedFreezeBoundaryError("parent accepted-member classification drift")
    artifacts.update({"ensemble": ensemble, "parent": parent, "expected_ids": expected_ids})
    return artifacts


def _typed_value(field: str, raw: str) -> Any:
    if field in {"feco_source_path_index", "motor_assignment_index", "route_body_id", "route_target_actuator_id", "bridge_gain_index"}:
        return int(raw)
    if field in {
        "bridge_gain_command_per_uN",
        "graded_membrane_tau_s",
        "dimensionless_input_scale",
        "unresolved_event_intensity_ceiling_hz",
    }:
        return float(raw)
    return raw


def _schedule_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _compile_bundles(campaign: Mapping[str, Any], artifacts: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = _schedule_rows(artifacts["exact_schedule"])
    by_id: dict[str, dict[str, str]] = {}
    for row in rows:
        tuple_id = str(row["tuple_id"])
        if tuple_id in by_id:
            raise MemberConditionedFreezeBoundaryError(f"duplicate exact schedule row: {tuple_id}")
        by_id[tuple_id] = row

    bundles: list[dict[str, Any]] = []
    partition = campaign["factor_partition"]
    for tuple_id in artifacts["expected_ids"]:
        if tuple_id not in by_id:
            raise MemberConditionedFreezeBoundaryError(f"missing exact schedule row: {tuple_id}")
        row = by_id[tuple_id]
        factors: dict[str, dict[str, Any]] = {}
        all_fields: dict[str, Any] = {}
        for factor_name in ("sensory", "central", "motor"):
            values: dict[str, Any] = {}
            for field in partition[factor_name]["schedule_fields"]:
                raw = row.get(str(field), "")
                if raw == "":
                    raise MemberConditionedFreezeBoundaryError(f"missing {field} for {tuple_id}")
                values[str(field)] = _typed_value(str(field), raw)
            factors[factor_name] = {
                "family_ids": list(map(str, partition[factor_name]["family_ids"])),
                "values": values,
                "semantic_sha256": _canonical_hash(values),
                "freeze_disposition": "member_conditioned_only_not_independently_frozen",
            }
            all_fields.update(values)
        bundles.append(
            {
                "member_id": tuple_id,
                "factors": factors,
                "coupling_contract": "sensory_central_motor_values_are_an_indivisible_exact_composite",
                "bundle_semantic_sha256": _canonical_hash({"member_id": tuple_id, "values": all_fields}),
            }
        )
    return bundles


def run_member_conditioned_compilation(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    parameter_set_path: Path = PARAMETER_SET_PATH,
) -> dict[str, Any]:
    print("[1/6] Verifying frozen local ensemble, parent classifications and exact schedule", flush=True)
    campaign = _load_campaign(campaign_path)
    artifacts = _verify_frozen_inputs(campaign)

    print("[2/6] Reconstructing every accepted exact composite", flush=True)
    bundles = _compile_bundles(campaign, artifacts)
    basal_ids = list(map(str, campaign["factor_partition"]["basal"]["family_ids"]))
    family_dispositions = {
        str(family_id): "member_conditioned_only_not_independently_frozen"
        for name in ("sensory", "central", "motor")
        for family_id in campaign["factor_partition"][name]["family_ids"]
    }
    family_dispositions.update({family_id: "not_exercised_no_freeze" for family_id in basal_ids})

    print("[3/6] Enforcing the no-marginal-promotion and no-basal-default boundaries", flush=True)
    checks = {
        "all_expected_members_accounted": len(bundles) == int(campaign["expected_parent_state"]["exact_member_count"]),
        "exact_member_order_preserved": [item["member_id"] for item in bundles] == artifacts["expected_ids"],
        "all_factor_fields_present": all(
            factor["values"]
            for bundle in bundles
            for factor in bundle["factors"].values()
        ),
        "independent_family_freezes_zero": not any(value == "frozen" for value in family_dispositions.values()),
        "all_basal_families_accounted_not_exercised": len(basal_ids) == 6
        and all(family_dispositions[item] == "not_exercised_no_freeze" for item in basal_ids),
        "no_member_ranking_or_reference_selection": True,
        "zero_numeric_optimization_zero_behavior_exposure": True,
        "human_checkpoint_required_before_post_global_visual_tuning": bool(
            campaign["human_checkpoint"]["required_before_post_global_visual_tuning"]
        ),
    }
    if not all(checks.values()):
        raise MemberConditionedFreezeBoundaryError(f"compilation checks failed: {[k for k, v in checks.items() if not v]}")

    semantic_payload = {
        "campaign_id": campaign["id"],
        "bundles": bundles,
        "family_dispositions": family_dispositions,
        "checks": checks,
    }
    semantic_hash = _canonical_hash(semantic_payload)
    result = {
        "schema_version": 1,
        "id": "runner_result.front_leg_member_conditioned_freeze_boundary.v0",
        "campaign_id": campaign["id"],
        "status": "completed_member_conditioned_compilation",
        "completed_at": datetime.now(UTC).isoformat(),
        "command": "front_leg_member_conditioned_freeze_boundary.bat",
        "claim_label": campaign["claim_label"],
        "accounting": {
            "expected_members": len(artifacts["expected_ids"]),
            "compiled_bundles": len(bundles),
            "independent_family_freezes": 0,
            "basal_families_not_exercised": len(basal_ids),
            "numeric_optimization_steps": 0,
            "named_behavior_exposures": 0,
        },
        "bundles": bundles,
        "family_dispositions": family_dispositions,
        "checks": checks,
        "human_checkpoint": campaign["human_checkpoint"],
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
        "semantic_result_sha256": semantic_hash,
    }

    print("[4/6] Writing compact result and reconstructible conditioned parameter set", flush=True)
    parameter_set = {
        "schema_version": 1,
        "id": "parameters.front_leg_member_conditioned_bundles.v0",
        "title": "Reconstructible front-leg sensory-central-motor bundles conditioned by exact member",
        "status": "accepted_reconstructible_conditioned_bundles_not_family_freeze",
        "scope_ids": campaign["scope_ids"],
        "primary_class": "technical",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": semantic_hash,
        "selection_exposure": {
            "technical_local_trajectory_used_by_parent": True,
            "named_behavior_used": False,
            "ranking_used": False,
            "held_out_protocol_used": False,
        },
        "ensemble": {
            "representation": "finite_exact_member_conditioned_bundles",
            "member_count": len(bundles),
            "member_ids": artifacts["expected_ids"],
            "members_ranked": False,
            "selected_reference_member_id": None,
            "bundles": bundles,
        },
        "family_dispositions": family_dispositions,
        "independent_family_freezes": [],
        "topology_boundaries": campaign["frozen_inputs"]["topology_boundaries"],
        "human_checkpoint": campaign["human_checkpoint"],
        "applicability": {
            "local_front_leg_chain_only": True,
            "whole_body_stability": False,
            "complete_recurrent_MaleCNS": False,
            "biological_behavior": False,
        },
        "reopening_policy": "new_campaign_required_no_silent_decoupling_ranking_or_default",
        "next_action": campaign["next_action"],
    }
    result_path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    parameter_set_path.write_text(yaml.safe_dump(parameter_set, sort_keys=False, allow_unicode=True), encoding="utf-8")

    print("[5/6] Writing evaluation with explicit unresolved basal boundary", flush=True)
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.front_leg_member_conditioned_freeze_boundary.v0",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": semantic_hash,
        "parameter_set_id": parameter_set["id"],
        "status": "accepted_reconstructible_compilation",
        "checks": checks,
        "compiled_member_ids": artifacts["expected_ids"],
        "independent_family_freezes": 0,
        "basal_family_disposition": "not_exercised_no_freeze",
        "whole_body_stability_accepted": False,
        "population_assignment_accepted": False,
        "named_behavior_exposed": False,
        "interpretation": (
            "The three exact local composites are reconstructible and may be propagated without ranking. "
            "Their sensory, central and motor factors remain confounded; basal families remain unexercised."
        ),
        "human_checkpoint": campaign["human_checkpoint"],
        "next_action": campaign["next_action"],
    }
    evaluation_path.write_text(yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8")

    print("[6/6] COMPLETE", flush=True)
    print(f"[BUNDLES] {len(bundles)} exact composites; unranked and member-conditioned", flush=True)
    print("[FREEZE] 0 independent families; 6 basal families explicitly not exercised", flush=True)
    print("[CHECKPOINT] user visual review required after first whole-body technical preview", flush=True)
    print(f"[HASH] {semantic_hash}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile exact local survivors into member-conditioned bundles")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    run_member_conditioned_compilation(campaign_path=args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

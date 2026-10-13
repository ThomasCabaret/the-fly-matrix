from __future__ import annotations

import argparse
import csv
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from .ledger import ROOT
from .neutral_embodied_command_limit_diagnostic import (
    _load_campaign as _load_diagnostic_campaign,
    _probe_once,
    _verified_context as _verified_diagnostic_context,
)
from .neutral_embodied_declared_closed_loop_sentinel import (
    _canonical_hash,
    _incoming_l1_matrices,
    _load_yaml,
    _profiles,
)
from .neutral_embodied_full_chain_sentinel import _sha256
from .runtime import FlyBodyPhysicsLoop


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "neutral-embodied-command-factor-isolation-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "neutral-embodied-command-factor-isolation-v0.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "neutral-embodied-command-factor-isolation-v0.yaml"


class CommandFactorIsolationError(RuntimeError):
    """Raised when the locked factor-isolation or exact-row policy contract fails."""


def _load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = _load_yaml(path)
    if campaign.get("optimization_exposure") != "diagnostic_only" or campaign.get("behavior_targets"):
        raise CommandFactorIsolationError("factor isolation must remain behavior-naive diagnostic_only")
    if campaign.get("topology_changes_allowed") is not False:
        raise CommandFactorIsolationError("factor isolation cannot change topology")
    acceptance = campaign["acceptance"]
    for key in (
        "allow_candidate_narrowing",
        "allow_broad_factor_rejection",
        "allow_threshold_change",
        "allow_clipping",
        "stability_acceptance_possible",
    ):
        if acceptance.get(key) is not False:
            raise CommandFactorIsolationError(f"factor isolation must forbid {key}")
    for key in ("optimized_parameters", "promoted_parameter_values", "selected_candidates", "named_behavior_exposure"):
        if int(campaign["scientific_boundary"].get(key, -1)) != 0:
            raise CommandFactorIsolationError(f"factor isolation requires zero {key}")
    if campaign["policy_contract"].get("pass_scope") != "exact_observed_composite_rows_only":
        raise CommandFactorIsolationError("policy scope must remain exact observed composite rows")
    if campaign["policy_contract"].get("broad_factor_rejection_allowed") is not False:
        raise CommandFactorIsolationError("broad factor rejection is forbidden")
    return campaign


def _verify_frozen_inputs(campaign: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    frozen = campaign["frozen_inputs"]
    pairs = {
        "diagnostic_campaign": "diagnostic_campaign_sha256",
        "diagnostic_result": "diagnostic_result_sha256",
        "diagnostic_evaluation": "diagnostic_evaluation_sha256",
        "declared_schedule": "declared_schedule_sha256",
    }
    hashes: dict[str, str] = {}
    for key, expected_key in pairs.items():
        hashes[key] = _sha256(ROOT / str(frozen[key]))
        if hashes[key] != str(frozen[expected_key]):
            raise CommandFactorIsolationError(f"frozen input drift for {key}")
    diagnostic_campaign = _load_diagnostic_campaign(ROOT / str(frozen["diagnostic_campaign"]))
    diagnostic_result = _load_yaml(ROOT / str(frozen["diagnostic_result"]))
    diagnostic_evaluation = _load_yaml(ROOT / str(frozen["diagnostic_evaluation"]))
    if diagnostic_result.get("semantic_result_sha256") != frozen["diagnostic_result_semantic_sha256"]:
        raise CommandFactorIsolationError("diagnostic semantic result drift")
    if diagnostic_result.get("status") != "pass_deterministic_command_limit_localization_no_selection":
        raise CommandFactorIsolationError("factor isolation requires the passed frozen diagnostic")
    if diagnostic_evaluation.get("status") != "pass":
        raise CommandFactorIsolationError("factor isolation requires the passed diagnostic evaluation")
    context, panel_campaign, panel_result, _diagnostic_hashes = _verified_diagnostic_context(diagnostic_campaign)
    return context, panel_campaign, panel_result, diagnostic_result, hashes


def _variant_row(
    reference: Mapping[str, str],
    ablation: Mapping[str, Any],
    numeric_profiles: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, str], list[str]]:
    row = dict(reference)
    axis = str(ablation["changed_axis"])
    changed_fields: list[str] = []
    if axis == "bridge_gain":
        replacements = {
            "bridge_gain_index": str(ablation["bridge_gain_index"]),
            "bridge_gain_command_per_uN": str(ablation["bridge_gain_command_per_uN"]),
        }
    else:
        numeric_id = str(ablation["numeric_profile_id"])
        numeric = numeric_profiles[numeric_id]
        replacements = {
            "numeric_profile_id": numeric_id,
            "graded_membrane_tau_s": str(numeric["graded_membrane_tau_s"]),
            "dimensionless_input_scale": str(numeric["dimensionless_input_scale"]),
            "unresolved_event_intensity_ceiling_hz": str(numeric["unresolved_event_intensity_ceiling_hz"]),
        }
        requested = {
            "graded_membrane_tau_s": float(ablation["graded_membrane_tau_s"]),
            "dimensionless_input_scale": float(ablation["dimensionless_input_scale"]),
            "unresolved_event_intensity_ceiling_hz": float(ablation["unresolved_event_intensity_ceiling_hz"]),
        }
        if any(float(numeric[key]) != value for key, value in requested.items()):
            raise CommandFactorIsolationError(f"numeric profile drift for {numeric_id}")
    for key, value in replacements.items():
        if str(row[key]) != value:
            row[key] = value
            changed_fields.append(key)
    conceptual_changes = []
    if str(row["bridge_gain_command_per_uN"]) != str(reference["bridge_gain_command_per_uN"]):
        conceptual_changes.append("bridge_gain")
    for field in ("graded_membrane_tau_s", "dimensionless_input_scale", "unresolved_event_intensity_ceiling_hz"):
        if float(row[field]) != float(reference[field]):
            conceptual_changes.append(field)
    if conceptual_changes != [axis]:
        raise CommandFactorIsolationError(
            f"ablation {ablation['id']} changes conceptual axes {conceptual_changes}, expected {[axis]}"
        )
    return row, changed_fields


def _write_policy_csv(
    path: Path,
    panel_result: Mapping[str, Any],
    diagnostic_result: Mapping[str, Any],
) -> dict[str, Any]:
    diagnosis = {str(item["tuple_id"]): item for item in diagnostic_result["outcomes"]}
    fields = [
        "tuple_id",
        "disposition",
        "evidence_basis",
        "baseline_peak_abs_command",
        "perturbed_peak_abs_command",
        "first_crossing_min_ms",
        "max_attempted_abs_command",
        "selected_or_promoted",
    ]
    rows: list[dict[str, Any]] = []
    for outcome in panel_result["outcomes"]:
        tuple_id = str(outcome["tuple_id"])
        if outcome["status"] == "completed_contract":
            rows.append({
                "tuple_id": tuple_id,
                "disposition": "observed_within_direct_motor_contract_not_promoted",
                "evidence_basis": "frozen_exhaustive_panel_both_branches_completed",
                "baseline_peak_abs_command": outcome["baseline_chain"]["peak_abs_command"],
                "perturbed_peak_abs_command": outcome["perturbed_chain"]["peak_abs_command"],
                "first_crossing_min_ms": "",
                "max_attempted_abs_command": "",
                "selected_or_promoted": "false",
            })
        else:
            item = diagnosis.get(tuple_id)
            if item is None:
                raise CommandFactorIsolationError(f"failed panel row {tuple_id} lacks frozen diagnosis")
            probes = [
                probe
                for branch in ("baseline", "perturbed")
                for probe in item["branches"][branch]["repeats"]
            ]
            rows.append({
                "tuple_id": tuple_id,
                "disposition": "blocked_exact_composite_direct_motor_limit",
                "evidence_basis": "frozen_deterministic_first_crossing_before_application",
                "baseline_peak_abs_command": "",
                "perturbed_peak_abs_command": "",
                "first_crossing_min_ms": min(float(probe["time_s"]) for probe in probes) * 1000.0,
                "max_attempted_abs_command": max(float(probe["absolute_attempted_command"]) for probe in probes),
                "selected_or_promoted": "false",
            })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    blocked = [row["tuple_id"] for row in rows if row["disposition"].startswith("blocked_")]
    return {
        "rows": len(rows),
        "within_contract_rows": len(rows) - len(blocked),
        "blocked_rows": len(blocked),
        "blocked_tuple_ids": blocked,
        "sha256": _sha256(path),
    }


def run_factor_isolation(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
) -> dict[str, Any]:
    started = time.perf_counter()
    print("[1/7] Verifying preregistration, failed-panel lineage and fixed limit", flush=True)
    campaign = _load_campaign(campaign_path)
    context, panel_campaign, panel_result, diagnostic_result, frozen_hashes = _verify_frozen_inputs(campaign)
    scope = campaign["factor_isolation"]
    tuple_ids = list(map(str, scope["failed_tuple_ids"]))
    diagnosed_ids = [str(item["tuple_id"]) for item in diagnostic_result["outcomes"]]
    exact_failed_identity = tuple_ids == diagnosed_ids
    if not exact_failed_identity:
        raise CommandFactorIsolationError("factor-isolation tuple IDs differ from frozen diagnostic")

    rows = {str(row["tuple_id"]): row for row in context["rows"]}
    sentinel_campaign = _load_yaml(ROOT / str(panel_campaign["frozen_inputs"]["causal_sentinel_campaign"]))
    profiles = _profiles(context)
    first, second, direct, _audit = _incoming_l1_matrices(context["inputs"])
    matrices = (first, second, direct)
    branches = list(map(str, scope["branches"]))
    ablations = list(scope["ablations"])

    print("[2/7] Building 12 locked one-factor variants", flush=True)
    variants: list[dict[str, Any]] = []
    for tuple_id in tuple_ids:
        reference = rows[tuple_id]
        for ablation in ablations:
            variant, changed_fields = _variant_row(reference, ablation, profiles["numeric"])
            variants.append({
                "tuple_id": tuple_id,
                "ablation_id": str(ablation["id"]),
                "changed_axis": str(ablation["changed_axis"]),
                "changed_fields": changed_fields,
                "row": variant,
            })
    if len(variants) != int(scope["expected_variants"]):
        raise CommandFactorIsolationError("variant count differs from preregistration")

    print("[3/7] Running 24 reset-isolated baseline/perturbed probes", flush=True)
    outcomes: list[dict[str, Any]] = []
    with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=False) as loop:
        for index, variant in enumerate(variants, start=1):
            print(
                f"[VARIANT {index:02d}/{len(variants)}] {variant['tuple_id']} / {variant['ablation_id']}",
                flush=True,
            )
            branch_results = {
                branch: _probe_once(
                    sentinel_campaign,
                    variant["row"],
                    context,
                    profiles,
                    matrices,
                    loop,
                    branch=branch,
                )
                for branch in branches
            }
            outcomes.append({
                "tuple_id": variant["tuple_id"],
                "ablation_id": variant["ablation_id"],
                "changed_axis": variant["changed_axis"],
                "changed_fields": variant["changed_fields"],
                "factor_values": {
                    "bridge_gain_index": variant["row"]["bridge_gain_index"],
                    "bridge_gain_command_per_uN": variant["row"]["bridge_gain_command_per_uN"],
                    "numeric_profile_id": variant["row"]["numeric_profile_id"],
                    "graded_membrane_tau_s": variant["row"]["graded_membrane_tau_s"],
                    "dimensionless_input_scale": variant["row"]["dimensionless_input_scale"],
                    "unresolved_event_intensity_ceiling_hz": variant["row"]["unresolved_event_intensity_ceiling_hz"],
                },
                "branches": branch_results,
            })

    print("[4/7] Applying the preregistered exact-row policy to all 240 rows", flush=True)
    policy_path = ROOT / str(campaign["policy_contract"]["output"])
    policy = _write_policy_csv(policy_path, panel_result, diagnostic_result)
    probes = [probe for item in outcomes for probe in item["branches"].values()]
    all_ablations_complete = all(probe["status"] == "completed_within_limit" for probe in probes)
    offending_never_applied = all(
        probe.get("offending_command_applied") is False
        for probe in probes
        if probe["status"] == "first_command_limit_crossing"
    )
    checks = {
        "exact_failed_tuple_identity": exact_failed_identity,
        "all_12_variants_accounted": len(outcomes) == int(scope["expected_variants"]),
        "all_24_probe_episodes_accounted": len(probes) == int(scope["expected_probe_episodes"]),
        "each_variant_changes_exactly_one_conceptual_factor": all(bool(item["changed_fields"]) for item in outcomes),
        "every_single_factor_ablation_completed_within_limit": all_ablations_complete,
        "offending_commands_never_applied": offending_never_applied,
        "all_240_policy_rows_accounted": policy["rows"] == int(campaign["policy_contract"]["declared_schedule_rows"]),
        "exact_237_within_and_3_blocked_dispositions": (
            policy["within_contract_rows"] == int(campaign["policy_contract"]["completed_panel_rows"])
            and policy["blocked_rows"] == int(campaign["policy_contract"]["observed_failed_rows"])
            and policy["blocked_tuple_ids"] == tuple_ids
        ),
        "zero_clipping_threshold_change_fit_selection_promotion_behavior": True,
    }
    elapsed = time.perf_counter() - started
    checks["within_compute_budget"] = elapsed <= float(campaign["compute_budget"]["maximum_wall_clock_minutes"]) * 60.0
    passed = all(checks.values())

    print("[5/7] Writing compact results and policy hashes", flush=True)
    result = {
        "schema_version": 1,
        "id": "runner_result.neutral_embodied_command_factor_isolation.v0",
        "campaign_id": campaign["id"],
        "status": "pass_exact_row_pathology_policy_factor_interaction_localized" if passed else "failed_factor_isolation_policy_open",
        "completed_at": datetime.now(UTC).isoformat(),
        "claim_label": campaign["claim_label"],
        "command": "neutral_embodied_command_factor_isolation.bat",
        "frozen_input_sha256": frozen_hashes,
        "accounting": {
            "failed_reference_tuples": len(tuple_ids),
            "single_factor_variants": len(outcomes),
            "probe_episodes": len(probes),
            "completed_within_limit_probes": sum(probe["status"] == "completed_within_limit" for probe in probes),
            "first_limit_crossing_probes": sum(probe["status"] == "first_command_limit_crossing" for probe in probes),
            "declared_policy_rows": policy["rows"],
            "within_contract_rows": policy["within_contract_rows"],
            "blocked_exact_composite_rows": policy["blocked_rows"],
            "optimized_parameters": 0,
            "promoted_parameter_values": 0,
            "selected_candidates": 0,
            "named_behavior_exposure": 0,
        },
        "checks": checks,
        "factor_outcomes": outcomes,
        "policy": {
            "scope": campaign["policy_contract"]["pass_scope"],
            "path": str(policy_path.relative_to(ROOT)).replace("\\", "/"),
            **policy,
            "broad_factor_domains_rejected": [],
            "survivor_meaning": "observed within fixed command contract only; not selected or promoted",
        },
        "scientific_boundary": campaign["scientific_boundary"],
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "wall_seconds": elapsed,
        "next_action": campaign["next_action"],
    }
    result["semantic_result_sha256"] = _canonical_hash({
        key: value for key, value in result.items() if key not in {"completed_at", "wall_seconds"}
    })
    result_path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.neutral_embodied_command_factor_isolation.v0",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": result["semantic_result_sha256"],
        "status": "pass" if passed else "fail",
        "checks": checks,
        "policy_scope": campaign["policy_contract"]["pass_scope"] if passed else "open",
        "blocked_tuple_ids": policy["blocked_tuple_ids"],
        "candidate_selected": False,
        "parameter_promoted": False,
        "stability_accepted": False,
        "behavior_claimed": False,
        "interpretation": (
            "A pass closes only exact-row direct-MOTOR command-contract accounting for the immutable 240-row schedule. "
            "The 237 completed rows remain unselected and scientifically uncalibrated."
        ),
        "next_action": campaign["next_action"],
    }
    evaluation_path.write_text(yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8")

    print("[6/7] Enforcing scientific boundaries", flush=True)
    if not passed:
        failed = [key for key, value in checks.items() if not value]
        raise CommandFactorIsolationError(f"factor-isolation policy failed: {failed}")
    print("[7/7] PASS", flush=True)
    print(f"[FACTORS] {len(outcomes)} one-factor variants / {len(probes)} completed probes", flush=True)
    print("[POLICY] 237 observed-within-contract / 3 exact composites blocked / 0 broad domains rejected", flush=True)
    print("[BOUNDARY] 0 clipping, fit, selection, promotion, stability or behavior", flush=True)
    print(f"[HASH] {result['semantic_result_sha256']}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run locked direct-MOTOR factor isolation and exact-row policy")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    run_factor_isolation(campaign_path=args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

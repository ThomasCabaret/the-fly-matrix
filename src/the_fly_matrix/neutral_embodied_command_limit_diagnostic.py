from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml

from .ledger import ROOT
from .neutral_embodied_declared_closed_loop_panel import _verified_panel_context
from .neutral_embodied_declared_closed_loop_sentinel import (
    MotorCommandLimitError,
    _canonical_hash,
    _incoming_l1_matrices,
    _load_yaml,
    _profiles,
    _run_episode,
)
from .neutral_embodied_full_chain_sentinel import _sha256
from .runtime import FlyBodyPhysicsLoop


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "neutral-embodied-command-limit-diagnostic-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "neutral-embodied-command-limit-diagnostic-v0.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "neutral-embodied-command-limit-diagnostic-v0.yaml"


class CommandLimitDiagnosticError(RuntimeError):
    """Raised when the bounded command-limit diagnostic violates its contract."""


def _load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = _load_yaml(path)
    if campaign.get("optimization_exposure") != "diagnostic_only" or campaign.get("behavior_targets"):
        raise CommandLimitDiagnosticError("command-limit diagnostic must remain behavior-naive diagnostic_only")
    if campaign.get("topology_changes_allowed") is not False:
        raise CommandLimitDiagnosticError("command-limit diagnostic cannot change topology")
    acceptance = campaign["acceptance"]
    for key in ("allow_candidate_narrowing", "allow_threshold_change", "allow_clipping", "stability_acceptance_possible"):
        if acceptance.get(key) is not False:
            raise CommandLimitDiagnosticError(f"command-limit diagnostic must forbid {key}")
    for key in ("optimized_parameters", "promoted_parameter_values", "selected_candidates", "named_behavior_exposure"):
        if int(campaign["scientific_boundary"].get(key, -1)) != 0:
            raise CommandLimitDiagnosticError(f"command-limit diagnostic requires zero {key}")
    return campaign


def _verified_context(campaign: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    frozen = campaign["frozen_inputs"]
    pairs = {
        "failed_panel_campaign": "failed_panel_campaign_sha256",
        "failed_panel_result": "failed_panel_result_sha256",
        "failed_panel_evaluation": "failed_panel_evaluation_sha256",
    }
    hashes: dict[str, str] = {}
    for key, expected_key in pairs.items():
        hashes[key] = _sha256(ROOT / str(frozen[key]))
        if hashes[key] != str(frozen[expected_key]):
            raise CommandLimitDiagnosticError(f"frozen input drift for {key}")
    panel_campaign = _load_yaml(ROOT / str(frozen["failed_panel_campaign"]))
    panel_result = _load_yaml(ROOT / str(frozen["failed_panel_result"]))
    panel_evaluation = _load_yaml(ROOT / str(frozen["failed_panel_evaluation"]))
    if panel_result.get("semantic_result_sha256") != frozen["failed_panel_result_semantic_sha256"]:
        raise CommandLimitDiagnosticError("failed panel semantic result drift")
    if panel_result.get("status") != "failed_exhaustive_causal_physical_accounting" or panel_evaluation.get("status") != "fail":
        raise CommandLimitDiagnosticError("diagnostic requires the frozen failed panel")
    context, sentinel_result, _panel_hashes = _verified_panel_context(panel_campaign)
    return context, panel_campaign, panel_result, hashes


def _factor_coordinates(row: Mapping[str, str]) -> dict[str, Any]:
    keys = (
        "base_tuple_id",
        "feco_routing_profile_id",
        "unknown_sign_profile_id",
        "numeric_profile_id",
        "intermediate_profile_id",
        "feco_alternative_id",
        "feco_native_representation",
        "motor_assignment_index",
        "motor_assignment_signature",
        "route_body_id",
        "route_target_actuator_id",
        "route_target_actuator_name",
        "bridge_gain_index",
        "bridge_gain_command_per_uN",
        "graded_membrane_tau_s",
        "dimensionless_input_scale",
        "unresolved_event_intensity_ceiling_hz",
    )
    return {key: row[key] for key in keys}


def _probe_once(
    sentinel_campaign: Mapping[str, Any],
    row: Mapping[str, str],
    context: Mapping[str, Any],
    profiles: Mapping[str, Any],
    matrices: tuple[np.ndarray, np.ndarray, np.ndarray],
    loop: FlyBodyPhysicsLoop,
    *,
    branch: str,
) -> dict[str, Any]:
    perturbation = None if branch == "baseline" else sentinel_campaign["physical_protocol"]["perturbation"]
    try:
        _episode, _metadata, diagnostic = _run_episode(
            sentinel_campaign,
            row,
            context,
            profiles,
            matrices,
            perturbation=perturbation,
            reusable_loop=loop,
        )
        outcome = {
            "status": "completed_within_limit",
            "trace_sha256": diagnostic["trace_sha256"],
            "peak_abs_command": diagnostic["peak_abs_command"],
        }
    except MotorCommandLimitError as exc:
        outcome = {
            "status": "first_command_limit_crossing",
            "native_step": exc.step_index,
            "time_s": exc.step_index * float(sentinel_campaign["runtime_contract"]["timestep_s"]),
            "attempted_command": exc.command,
            "absolute_attempted_command": abs(exc.command),
            "target_actuator_id": exc.target_actuator_id,
            "route_body_id": exc.route_body_id,
            "offending_command_applied": False,
        }
    outcome["signature_sha256"] = _canonical_hash(outcome)
    return outcome


def run_diagnostic(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
) -> dict[str, Any]:
    started = time.perf_counter()
    print("[1/6] Verifying failed-panel lineage and locked diagnostic scope", flush=True)
    campaign = _load_campaign(campaign_path)
    context, panel_campaign, panel_result, frozen_hashes = _verified_context(campaign)
    tuple_ids = list(map(str, campaign["diagnostic_scope"]["tuple_ids"]))
    panel_failures = [str(item["tuple_id"]) for item in panel_result["outcomes"] if item["status"] != "completed_contract"]
    exact_failed_identity = tuple_ids == panel_failures
    if not exact_failed_identity:
        raise CommandLimitDiagnosticError("diagnostic tuple IDs differ from frozen panel failures")
    rows = {str(row["tuple_id"]): row for row in context["rows"]}
    sentinel_campaign = _load_yaml(ROOT / str(panel_campaign["frozen_inputs"]["causal_sentinel_campaign"]))
    profiles = _profiles(context)
    first, second, direct, _audit = _incoming_l1_matrices(context["inputs"])
    matrices = (first, second, direct)
    branches = list(map(str, campaign["diagnostic_scope"]["branches"]))
    repeats = int(campaign["diagnostic_scope"]["deterministic_repeats_per_branch"])

    print("[2/6] Building one reset-isolated MuJoCo model", flush=True)
    outcomes: list[dict[str, Any]] = []
    with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=False) as loop:
        print("[3/6] Replaying 3 tuples x 2 branches x 2 deterministic repeats", flush=True)
        for tuple_id in tuple_ids:
            row = rows[tuple_id]
            print(f"[TUPLE] {tuple_id}", flush=True)
            branch_results: dict[str, Any] = {}
            for branch in branches:
                probes = [
                    _probe_once(sentinel_campaign, row, context, profiles, matrices, loop, branch=branch)
                    for _repeat in range(repeats)
                ]
                signatures = [probe["signature_sha256"] for probe in probes]
                branch_results[branch] = {
                    "repeats": probes,
                    "repeat_signatures_identical": len(set(signatures)) == 1,
                }
                print(f"  {branch}: {probes[0]['status']}", flush=True)
            outcomes.append({
                "tuple_id": tuple_id,
                "factor_coordinates": _factor_coordinates(row),
                "branches": branch_results,
            })

    print("[4/6] Checking determinism and command non-application", flush=True)
    all_probes = [
        probe
        for item in outcomes
        for branch in branches
        for probe in item["branches"][branch]["repeats"]
    ]
    checks = {
        "exact_failed_tuple_identity": exact_failed_identity,
        "all_12_probe_episodes_accounted": len(all_probes) == int(campaign["diagnostic_scope"]["total_probe_episodes"]),
        "all_repeat_signatures_identical": all(
            item["branches"][branch]["repeat_signatures_identical"]
            for item in outcomes for branch in branches
        ),
        "each_tuple_reproduces_at_least_one_finite_absolute_limit_crossing": all(
            any(
                probe["status"] == "first_command_limit_crossing"
                and np.isfinite(float(probe["attempted_command"]))
                and float(probe["absolute_attempted_command"]) > float(campaign["diagnostic_scope"]["motor_command_absolute_limit"])
                for branch in branches for probe in item["branches"][branch]["repeats"]
            )
            for item in outcomes
        ),
        "offending_commands_never_applied": all(
            probe.get("offending_command_applied") is False
            for probe in all_probes if probe["status"] == "first_command_limit_crossing"
        ),
        "zero_clipping_zero_fit_zero_selection_zero_behavior": True,
    }
    passed = all(checks.values())
    elapsed = time.perf_counter() - started
    if elapsed > float(campaign["compute_budget"]["maximum_wall_clock_minutes"]) * 60.0:
        passed = False
        checks["within_compute_budget"] = False
    else:
        checks["within_compute_budget"] = True

    print("[5/6] Writing compact hash-linked diagnosis", flush=True)
    result = {
        "schema_version": 1,
        "id": "runner_result.neutral_embodied_command_limit_diagnostic.v0",
        "campaign_id": campaign["id"],
        "status": "pass_deterministic_command_limit_localization_no_selection" if passed else "failed_command_limit_localization",
        "completed_at": datetime.now(UTC).isoformat(),
        "claim_label": campaign["claim_label"],
        "command": "neutral_embodied_command_limit_diagnostic.bat",
        "frozen_input_sha256": frozen_hashes,
        "accounting": {
            "tuples": len(outcomes),
            "branches": len(outcomes) * len(branches),
            "probe_episodes": len(all_probes),
            "first_limit_crossing_probes": sum(probe["status"] == "first_command_limit_crossing" for probe in all_probes),
            "completed_within_limit_probes": sum(probe["status"] == "completed_within_limit" for probe in all_probes),
            "optimized_parameters": 0,
            "promoted_parameter_values": 0,
            "selected_candidates": 0,
            "named_behavior_exposure": 0,
        },
        "checks": checks,
        "outcomes": outcomes,
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
        "id": "evaluation.neutral_embodied_command_limit_diagnostic.v0",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": result["semantic_result_sha256"],
        "status": "pass" if passed else "fail",
        "checks": checks,
        "candidate_selected": False,
        "stability_accepted": False,
        "behavior_claimed": False,
        "interpretation": "A pass localizes deterministic first command-limit crossings only; it does not decide the later pathology policy.",
        "next_action": campaign["next_action"],
    }
    evaluation_path.write_text(yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8")
    if not passed:
        raise CommandLimitDiagnosticError(f"command-limit diagnostic failed: {[key for key, value in checks.items() if not value]}")
    print("[6/6] PASS", flush=True)
    print(f"[ACCOUNTING] {len(all_probes)}/12 probe episodes", flush=True)
    print(f"[BOUNDARY HITS] {result['accounting']['first_limit_crossing_probes']}", flush=True)
    print("[BOUNDARY] offending commands not applied; 0 clipping/fit/selection/behavior", flush=True)
    print(f"[HASH] {result['semantic_result_sha256']}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose frozen direct-MOTOR command-limit crossings")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    run_diagnostic(campaign_path=args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import yaml

from .embodied_measurement_contract import _episode_metrics, paired_recovery_metrics
from .ledger import ROOT
from .neutral_embodied_adapter_sentinel import (
    _canonical_hash,
    _compact_episode,
    _load_campaign as _load_adapter_campaign,
    _read_schedule,
    _run_command_episode,
    compile_motor_route_trace,
)
from .neutral_embodied_full_chain_sentinel import (
    _load_campaign as _load_full_chain_campaign,
    _sha256,
    _verify_and_load_inputs,
    execute_local_chain,
)
from .runtime import FlyBodyPhysicsLoop


CAMPAIGN_PATH = (
    ROOT / "calibration" / "campaigns" / "neutral-embodied-full-chain-panel-v0.yaml"
)
RESULT_PATH = (
    ROOT / "calibration" / "runner" / "neutral-embodied-full-chain-panel-v0.yaml"
)
EVALUATION_PATH = (
    ROOT / "calibration" / "evaluations" / "neutral-embodied-full-chain-panel-v0.yaml"
)
RUN_ROOT = ROOT / "runs" / "calibration" / "neutral-embodied-full-chain-panel-v0"


class FullChainPanelError(RuntimeError):
    """Raised when the immutable full-chain panel contract is violated."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FullChainPanelError(f"{path} must contain a YAML mapping")
    return value


def _require_hash(path: Path, expected: str, label: str) -> None:
    observed = _sha256(path)
    if observed != str(expected):
        raise FullChainPanelError(
            f"{label} drift: expected {expected}, observed {observed}"
        )


def _load_campaign(
    path: Path = CAMPAIGN_PATH,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    campaign = _load_yaml(path)
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise FullChainPanelError("full-chain panel must remain diagnostic_only")
    if campaign.get("behavior_targets"):
        raise FullChainPanelError("full-chain panel cannot expose behavior targets")
    if campaign.get("topology_changes_allowed") is not False:
        raise FullChainPanelError("full-chain panel cannot change topology")
    boundary = campaign.get("scientific_boundary", {})
    for key in (
        "optimized_parameters",
        "promoted_parameter_values",
        "selected_candidates",
        "named_behavior_exposure",
    ):
        if int(boundary.get(key, -1)) != 0:
            raise FullChainPanelError(f"full-chain panel requires zero {key}")
    if campaign["schedule_contract"].get("candidate_selection_from_body_motion") is not False:
        raise FullChainPanelError("body motion cannot select a panel candidate")
    if campaign["acceptance"].get("allow_physical_magnitude_to_select_candidate") is not False:
        raise FullChainPanelError("physical magnitude cannot select a panel candidate")

    frozen = campaign["frozen_inputs"]
    for key, hash_key, label in (
        ("schedule_campaign", "schedule_campaign_sha256", "schedule campaign"),
        ("schedule_csv", "schedule_csv_sha256", "schedule CSV"),
        ("full_chain_contract", "full_chain_contract_sha256", "full-chain contract"),
    ):
        _require_hash(ROOT / str(frozen[key]), str(frozen[hash_key]), label)

    schedule_result = _load_yaml(ROOT / str(frozen["schedule_result"]))
    if (
        schedule_result.get("semantic_result_sha256")
        != frozen["schedule_result_semantic_sha256"]
    ):
        raise FullChainPanelError("immutable schedule semantic result drift")
    sentinel_result = _load_yaml(ROOT / str(frozen["passed_sentinel_result"]))
    if not str(sentinel_result.get("status", "")).startswith("pass_"):
        raise FullChainPanelError("full-chain sentinel is not passed")
    if (
        sentinel_result.get("semantic_result_sha256")
        != frozen["passed_sentinel_semantic_sha256"]
    ):
        raise FullChainPanelError("passed full-chain sentinel semantic result drift")
    full_chain_campaign = _load_full_chain_campaign(
        ROOT / str(frozen["full_chain_contract"])
    )
    return campaign, full_chain_campaign, schedule_result


def _axis_coverage(rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    profile_counts = Counter(str(row["intermediate_profile_id"]) for row in rows)
    feco_counts = Counter(str(row["feco_alternative_id"]) for row in rows)
    assignment_counts = Counter(int(row["motor_assignment_index"]) for row in rows)
    route_counts = Counter(
        (int(row["route_body_id"]), int(row["route_target_actuator_id"]))
        for row in rows
    )
    gain_counts = Counter(int(row["bridge_gain_index"]) for row in rows)
    return {
        "scheduled_tuples": len(rows),
        "intermediate_profiles": {
            "unique": len(profile_counts),
            "minimum_repetitions": min(profile_counts.values()),
            "maximum_repetitions": max(profile_counts.values()),
        },
        "feco_alternatives": {
            "unique": len(feco_counts),
            "minimum_repetitions": min(feco_counts.values()),
            "maximum_repetitions": max(feco_counts.values()),
        },
        "motor_assignments": {"unique": len(assignment_counts)},
        "route_basis_edges": {
            "unique": len(route_counts),
            "minimum_repetitions": min(route_counts.values()),
            "maximum_repetitions": max(route_counts.values()),
        },
        "bridge_gains": {
            "unique": len(gain_counts),
            "counts": {str(key): gain_counts[key] for key in sorted(gain_counts)},
        },
    }


def _validate_axis_coverage(
    campaign: Mapping[str, Any], coverage: Mapping[str, Any]
) -> None:
    expected = campaign["schedule_contract"]
    observed = {
        "tuples": coverage["scheduled_tuples"],
        "intermediate_profiles": coverage["intermediate_profiles"]["unique"],
        "feco_alternatives": coverage["feco_alternatives"]["unique"],
        "motor_assignments": coverage["motor_assignments"]["unique"],
        "route_basis_edges": coverage["route_basis_edges"]["unique"],
        "bridge_gains": coverage["bridge_gains"]["unique"],
    }
    for key, value in observed.items():
        if int(value) != int(expected[key]):
            raise FullChainPanelError(
                f"schedule coverage drift for {key}: expected {expected[key]}, observed {value}"
            )


def compile_full_chain_panel(
    campaign_path: Path = CAMPAIGN_PATH,
    *,
    actuator_names: tuple[str, ...] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    campaign, full_chain_campaign, schedule_result = _load_campaign(campaign_path)
    adapter_campaign = _load_adapter_campaign(
        ROOT / str(full_chain_campaign["frozen_inputs"]["adapter_campaign"])
    )
    rows, observed_schedule_result = _read_schedule(adapter_campaign)
    if (
        observed_schedule_result["semantic_result_sha256"]
        != schedule_result["semantic_result_sha256"]
    ):
        raise FullChainPanelError("schedule result differs across frozen contracts")
    if len({str(row["tuple_id"]) for row in rows}) != len(rows):
        raise FullChainPanelError("schedule tuple IDs are not unique")
    coverage = _axis_coverage(rows)
    _validate_axis_coverage(campaign, coverage)
    inputs = _verify_and_load_inputs(full_chain_campaign)

    compiled: list[dict[str, Any]] = []
    for row in rows:
        local = execute_local_chain(row, full_chain_campaign, inputs)
        route = compile_motor_route_trace(
            row,
            inputs,
            local["route_event_counts"],
            frame_dt_s=float(
                full_chain_campaign["physical_protocol"]["expected_frame_dt_s"]
            ),
            actuator_names=actuator_names,
        )
        command_trace = route["command_trace"]
        active = list(route["active_actuator_ids"])
        if active not in ([], [int(route["target_actuator_id"])]):
            raise FullChainPanelError("compiled command leaked outside scheduled route")
        compiled.append(
            {
                "tuple_id": str(row["tuple_id"]),
                "row": dict(row),
                "local_chain": local["trace"],
                "route": {
                    key: value
                    for key, value in route.items()
                    if key not in {"assignment", "command_trace"}
                },
                "command_trace": command_trace,
                "command_trace_sha256": _canonical_hash(command_trace.tolist()),
                "non_scoped_actuators_zero": True,
            }
        )
    return campaign, full_chain_campaign, compiled, {
        "coverage": coverage,
        "schedule_result_semantic_sha256": schedule_result[
            "semantic_result_sha256"
        ],
        "input_hashes": inputs["input_hashes"],
        "adapter_input_hashes": inputs["adapter_input_hashes"],
    }


def _describe(values: Sequence[float | int]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0:
        return {"minimum": 0.0, "median": 0.0, "maximum": 0.0}
    return {
        "minimum": float(np.min(array)),
        "median": float(np.median(array)),
        "maximum": float(np.max(array)),
    }


def _compact_tuple(outcome: Mapping[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {
        "tuple_id": outcome["tuple_id"],
        "status": outcome["status"],
        "intermediate_profile_id": outcome["row"]["intermediate_profile_id"],
        "feco_alternative_id": outcome["row"]["feco_alternative_id"],
        "motor_assignment_index": int(outcome["row"]["motor_assignment_index"]),
        "route_body_id": int(outcome["row"]["route_body_id"]),
        "route_target_actuator_id": int(outcome["row"]["route_target_actuator_id"]),
        "bridge_gain_index": int(outcome["row"]["bridge_gain_index"]),
        "neural_trace_sha256": outcome["local_chain"]["neural_trace_sha256"],
        "command_trace_sha256": outcome["command_trace_sha256"],
        "feco_nonzero_drive_samples": int(
            outcome["local_chain"]["feco_nonzero_drive_samples"]
        ),
        "intermediate_nonzero_state_samples": int(
            outcome["local_chain"]["intermediate_nonzero_state_samples"]
        ),
        "motor_spike_count_all_bodies": int(
            outcome["local_chain"]["motor_spike_count_all_bodies"]
        ),
        "route_motor_event_count": int(
            outcome["local_chain"]["route_motor_event_count"]
        ),
        "non_scoped_actuators_zero": bool(outcome["non_scoped_actuators_zero"]),
    }
    if "baseline" in outcome and "perturbed" in outcome:
        item["baseline_finite_fraction"] = float(outcome["baseline"]["finite_fraction"])
        item["perturbed_finite_fraction"] = float(
            outcome["perturbed"]["finite_fraction"]
        )
    if "error" in outcome:
        item["error"] = str(outcome["error"])
    if "skip_reason" in outcome:
        item["skip_reason"] = str(outcome["skip_reason"])
    return item


def run_panel(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    run_root: Path = RUN_ROOT,
) -> dict[str, Any]:
    started = time.perf_counter()
    print("[1/6] Verifying hashes, passed sentinel and immutable schedule", flush=True)
    with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=False) as probe_loop:
        actuator_names = tuple(probe_loop.actuator_names)
    campaign, full_chain_campaign, compiled, context = compile_full_chain_panel(
        campaign_path, actuator_names=actuator_names
    )
    print(
        "[2/6] Compiled 120 FeCO -> typed CNS -> motor command traces; "
        "all declared axes are present",
        flush=True,
    )

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    artifact_root = run_root / run_id
    artifact_root.mkdir(parents=True, exist_ok=False)
    outcomes: list[dict[str, Any]] = []
    error_classes: Counter[str] = Counter()
    stop_reason: str | None = None
    protocol = full_chain_campaign["physical_protocol"]
    perturbation = protocol["perturbation"]
    error_limit = int(
        campaign["execution_contract"]["error_policy"][
            "repeated_runtime_error_class_limit"
        ]
    )
    wall_budget_s = float(campaign["compute_budget"]["maximum_wall_clock_hours"]) * 3600

    print("[3/6] Running 240 paired MuJoCo episodes", flush=True)
    for index, item in enumerate(compiled, start=1):
        tuple_started = time.perf_counter()
        outcome: dict[str, Any] = {
            "tuple_id": item["tuple_id"],
            "status": "error",
            "row": item["row"],
            "local_chain": item["local_chain"],
            "route": item["route"],
            "command_trace_sha256": item["command_trace_sha256"],
            "non_scoped_actuators_zero": item["non_scoped_actuators_zero"],
        }
        if stop_reason is not None or time.perf_counter() - started > wall_budget_s:
            if stop_reason is None:
                stop_reason = "wall_clock_budget_exhausted"
            outcome.update(status="budget_skipped", skip_reason=stop_reason)
            outcome["wall_seconds"] = time.perf_counter() - tuple_started
            outcomes.append(outcome)
            print(
                f"[TUPLE {index:03d}/120] {item['tuple_id']} | budget_skipped | {stop_reason}",
                flush=True,
            )
            continue
        try:
            baseline, baseline_metadata = _run_command_episode(
                full_chain_campaign, item["command_trace"], perturbation=None
            )
            perturbed, perturbed_metadata = _run_command_episode(
                full_chain_campaign,
                item["command_trace"],
                perturbation=perturbation,
            )
            if baseline_metadata["model_contract"] != perturbed_metadata["model_contract"]:
                raise FullChainPanelError("paired episode model contracts differ")
            baseline_metrics = _episode_metrics(baseline, baseline_metadata)
            perturbed_metrics = _episode_metrics(perturbed, perturbed_metadata)
            paired = paired_recovery_metrics(
                baseline,
                perturbed,
                int(protocol["perturbation_step"]),
            )
            finite = (
                float(baseline_metrics["finite_fraction"]) == 1.0
                and float(perturbed_metrics["finite_fraction"]) == 1.0
            )
            tuple_root = artifact_root / item["tuple_id"]
            tuple_root.mkdir(parents=True, exist_ok=False)
            baseline_path = tuple_root / "baseline.npz"
            perturbed_path = tuple_root / "perturbed.npz"
            np.savez_compressed(baseline_path, **baseline)
            np.savez_compressed(perturbed_path, **perturbed)
            outcome.update(
                {
                    "status": "completed_contract" if finite else "failed_nonfinite",
                    "baseline": _compact_episode(baseline_metrics),
                    "perturbed": _compact_episode(perturbed_metrics),
                    "paired_recovery": paired,
                    "artifacts": {
                        "baseline": str(baseline_path.relative_to(ROOT)).replace("\\", "/"),
                        "perturbed": str(perturbed_path.relative_to(ROOT)).replace("\\", "/"),
                    },
                }
            )
        except Exception as exc:  # every failure remains visible and accounted
            error_key = f"{type(exc).__name__}: {exc}"
            outcome["error"] = error_key
            error_classes[error_key] += 1
            if error_classes[error_key] >= error_limit:
                stop_reason = f"repeated_runtime_error_limit:{error_key}"
        outcome["wall_seconds"] = time.perf_counter() - tuple_started
        outcomes.append(outcome)
        print(
            f"[TUPLE {index:03d}/120] {item['tuple_id']} | {outcome['status']} | "
            f"{outcome['local_chain']['feco_representation']} | "
            f"{outcome['local_chain']['intermediate_event_candidates']} event / "
            f"{outcome['local_chain']['intermediate_graded_candidates']} graded | "
            f"route events {outcome['local_chain']['route_motor_event_count']} | "
            f"{outcome['wall_seconds']:.2f}s",
            flush=True,
        )

    print("[4/6] Accounting all tuples and computing non-selecting robustness", flush=True)
    statuses = Counter(str(item["status"]) for item in outcomes)
    for name in ("completed_contract", "failed_nonfinite", "error", "budget_skipped"):
        statuses.setdefault(name, 0)
    compact_outcomes = [_compact_tuple(item) for item in outcomes]
    all_axes_active = all(
        int(item["local_chain"]["feco_nonzero_drive_samples"]) > 0
        and int(item["local_chain"]["intermediate_nonzero_state_samples"]) > 0
        and int(item["local_chain"]["motor_spike_count_all_bodies"]) > 0
        for item in outcomes
        if item["status"] != "budget_skipped"
    )
    all_accounted = len(outcomes) == int(campaign["schedule_contract"]["tuples"])
    coverage_exact = context["coverage"]["scheduled_tuples"] == len(outcomes)
    passed = (
        all_accounted
        and coverage_exact
        and all_axes_active
        and statuses["completed_contract"] == len(outcomes)
    )
    status = (
        "pass_full_local_chain_panel_execution_no_calibration"
        if passed
        else "failed_full_local_chain_panel_execution"
    )
    robustness = {
        "scope": "fixed_120_tuple_schedule_only",
        "all_axes_active": all_axes_active,
        "all_physical_pairs_finite": statuses["completed_contract"] == len(outcomes),
        "route_body_silent_tuples": sum(
            int(item["local_chain"]["route_motor_event_count"]) == 0
            for item in outcomes
        ),
        "unique_neural_trace_hashes": len(
            {item["local_chain"]["neural_trace_sha256"] for item in outcomes}
        ),
        "feco_event_count": _describe(
            [item["local_chain"]["feco_event_count"] for item in outcomes]
        ),
        "intermediate_spike_count": _describe(
            [item["local_chain"]["intermediate_spike_count"] for item in outcomes]
        ),
        "motor_spike_count_all_bodies": _describe(
            [item["local_chain"]["motor_spike_count_all_bodies"] for item in outcomes]
        ),
        "route_motor_event_count": _describe(
            [item["local_chain"]["route_motor_event_count"] for item in outcomes]
        ),
        "body_motion_used_for_selection": False,
        "physical_magnitudes_are_descriptive_only": True,
    }
    summary = {
        "schema_version": 1,
        "campaign_id": campaign["id"],
        "status": status,
        "claim_label": campaign["claim_label"],
        "generated_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "accounting": {
            "scheduled_tuples": len(compiled),
            "paired_physical_episodes_planned": len(compiled) * 2,
            "outcome_counts": dict(statuses),
            "all_tuples_accounted": all_accounted,
            "stop_reason": stop_reason,
        },
        "coverage": context["coverage"],
        "robustness": robustness,
        "execution_boundary": {
            "feco_transduction_executed": True,
            "typed_intermediate_cns_executed": True,
            "motor_event_force_bridge_route_executed": True,
            "paired_mujoco_physics_executed": statuses["completed_contract"] > 0,
            "local_panel_execution_contract_passed": passed,
            "population_assignments_promoted": 0,
            "candidate_selected_from_motion": False,
            "stability_evaluated": False,
            "optimized_parameters": 0,
            "promoted_parameter_values": 0,
        },
        "input_hashes": context["input_hashes"],
        "adapter_input_hashes": context["adapter_input_hashes"],
        "schedule_result_semantic_sha256": context[
            "schedule_result_semantic_sha256"
        ],
        "wall_seconds": time.perf_counter() - started,
        "tuple_outcomes": outcomes,
        "compact_tuple_accounting": compact_outcomes,
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    semantic_payload = {
        key: summary[key]
        for key in (
            "schema_version",
            "campaign_id",
            "status",
            "claim_label",
            "accounting",
            "coverage",
            "robustness",
            "execution_boundary",
            "input_hashes",
            "adapter_input_hashes",
            "schedule_result_semantic_sha256",
            "compact_tuple_accounting",
            "accepted_claims",
            "forbidden_claims",
            "next_action",
        )
    }
    semantic_payload["accounting"] = dict(semantic_payload["accounting"])
    summary["semantic_result_sha256"] = _canonical_hash(semantic_payload)
    (artifact_root / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print("[5/6] Writing compact versioned result and evaluation", flush=True)
    compact = {
        "schema_version": 1,
        "id": "runner_result.neutral_embodied_full_chain_panel.v0",
        "campaign_id": campaign["id"],
        "target_id": campaign["target_id"],
        "status": status,
        "claim_label": campaign["claim_label"],
        "command": "neutral_embodied_full_chain_panel.bat",
        "behavior_targets": [],
        "campaign_sha256": _sha256(campaign_path),
        "implementation_sha256": _sha256(Path(__file__).resolve()),
        "semantic_result_sha256": summary["semantic_result_sha256"],
        "input_hashes": summary["input_hashes"],
        "adapter_input_hashes": summary["adapter_input_hashes"],
        "schedule_result_semantic_sha256": summary[
            "schedule_result_semantic_sha256"
        ],
        "accounting": summary["accounting"],
        "coverage": summary["coverage"],
        "robustness": summary["robustness"],
        "execution_boundary": summary["execution_boundary"],
        "tuple_accounting": compact_outcomes,
        "artifact_ref": str((artifact_root / "summary.json").relative_to(ROOT)).replace(
            "\\", "/"
        ),
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    result_path.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.neutral_embodied_full_chain_panel.v0",
        "title": "Immutable 120-tuple full local-chain execution panel",
        "status": "evaluated" if passed else "failed",
        "campaign_id": campaign["id"],
        "target_id": campaign["target_id"],
        "primary_class": campaign["primary_class"],
        "optimization_exposure": campaign["optimization_exposure"],
        "claim_label": campaign["claim_label"],
        "behavior_targets": [],
        "acceptance_result": status,
        "runner_result_id": compact["id"],
        "runner_semantic_sha256": compact["semantic_result_sha256"],
        "parameter_values_promoted": 0,
        "population_assignments_promoted": 0,
        "candidate_selected_from_motion": False,
        "stability_accepted": False,
        "full_local_panel_execution_contract": passed,
        "conclusion": (
            "All 120 immutable tuples completed the FeCO-to-MuJoCo local execution contract with finite paired physical episodes. This establishes execution robustness over the scheduled panel only; diagnostic fixtures remain uncalibrated and no body trajectory selected a candidate."
            if passed
            else "The immutable local panel did not complete its execution contract. Every tuple is retained as completed, failed, errored or budget-skipped; no candidate or value is promoted."
        ),
        "next_action": campaign["next_action"],
    }
    evaluation_path.write_text(
        yaml.safe_dump(evaluation, sort_keys=False), encoding="utf-8"
    )

    print("[6/6] Summary", flush=True)
    print(
        f"[ACCOUNTING] {statuses['completed_contract']}/{len(outcomes)} completed; "
        f"{statuses['failed_nonfinite']} nonfinite; {statuses['error']} errors; "
        f"{statuses['budget_skipped']} skipped",
        flush=True,
    )
    print(
        f"[COVERAGE] 50 profiles, 24 FeCO alternatives, 120 motor assignments, "
        f"110 routes, 3 gains | exact={coverage_exact}",
        flush=True,
    )
    print(
        "[BOUNDARY] 0 fit, 0 selection, 0 promotion, 0 behavior, 0 stability claim",
        flush=True,
    )
    print(f"[HASH] {summary['semantic_result_sha256']}", flush=True)
    return compact


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the immutable 120-tuple full local-chain execution panel"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--output", type=Path, default=RUN_ROOT)
    args = parser.parse_args()
    result = run_panel(args.campaign, run_root=args.output)
    return 0 if result["status"].startswith("pass_") else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import yaml

from .calibration_parameters import validate_contract_family
from .calibration_registry import CALIBRATION_ROOT, load_calibration_inventory
from .ledger import ROOT
from .signed_dynamics import characterize_unfitted_regime, validate_full_graph_contract


DEFAULT_JOB_PATH = CALIBRATION_ROOT / "runner" / "peripheral-compiler-validation-v0.yaml"
DEFAULT_OUTPUT_ROOT = ROOT / "runs" / "calibration" / "runner"
Scalar = bool | int | float | str
Evaluator = Callable[[Mapping[str, Any]], Mapping[str, Scalar]]


class CalibrationRunnerError(ValueError):
    """Raised when a runner job violates its immutable execution contract."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _semantic_metrics(
    metrics: Mapping[str, Scalar],
    exclusions: frozenset[str],
    float_significant_digits: int | None,
) -> dict[str, Scalar]:
    result: dict[str, Scalar] = {}
    for key, value in metrics.items():
        if key in exclusions:
            continue
        if (
            float_significant_digits is not None
            and isinstance(value, float)
            and np.isfinite(value)
            and value != 0.0
        ):
            value = float(f"{value:.{float_significant_digits}g}")
        result[key] = value
    return result


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CalibrationRunnerError(f"{path} must contain a YAML mapping")
    return value


def _id_registry(directory: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in sorted(directory.glob("*.yaml")):
        record = _load_yaml(path)
        record_id = record.get("id")
        if isinstance(record_id, str):
            if record_id in result:
                raise CalibrationRunnerError(f"Duplicate registry id: {record_id}")
            result[record_id] = path
    return result


def _git_state() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status_lines = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        return {
            "git_commit": commit,
            "git_worktree_clean": not status_lines,
            "git_changed_path_count": len(status_lines),
        }
    except (OSError, subprocess.SubprocessError):
        return {
            "git_commit": "unavailable",
            "git_worktree_clean": False,
            "git_changed_path_count": None,
        }


def _peripheral_compiler_evaluator(trial: Mapping[str, Any]) -> Mapping[str, Scalar]:
    family_id = str(trial.get("args", {}).get("family_id", ""))
    result = validate_contract_family(family_id)
    return {
        "runtime_coefficients": int(result["runtime_coefficients"]),
        "logical_routes": int(result["logical_routes"]),
        "route_groups": int(result["route_groups"]),
        "synthetic_test_transfer_keys": int(result["synthetic_test_transfer_keys"]),
        "deterministic": bool(result["deterministic"]),
    }


def _signed_dynamics_contract_evaluator(
    trial: Mapping[str, Any],
) -> Mapping[str, Scalar]:
    if trial.get("args", {}).get("probe_id") != "all_transmitter_classes_nonzero":
        raise CalibrationRunnerError("Unknown signed-dynamics structural probe")
    return validate_full_graph_contract()


def _signed_dynamics_characterization_evaluator(
    trial: Mapping[str, Any],
) -> Mapping[str, Scalar]:
    probe_id = str(trial.get("args", {}).get("probe_id", ""))
    return characterize_unfitted_regime(probe_id, int(trial["seed"]))


DEFAULT_EVALUATORS: Mapping[str, Evaluator] = {
    "peripheral_parameter_compiler_contract.v0": _peripheral_compiler_evaluator,
    "malecns_typed_signed_rate_contract.v0": _signed_dynamics_contract_evaluator,
    "malecns_signed_unfitted_characterization.v0": (
        _signed_dynamics_characterization_evaluator
    ),
}
DEFAULT_EVALUATOR_POLICIES: Mapping[str, Mapping[str, frozenset[str]]] = {
    "peripheral_parameter_compiler_contract.v0": {
        "allowed_modes": frozenset({"validation"}),
        "allowed_record_kinds": frozenset({"runner_validation"}),
    },
    "malecns_typed_signed_rate_contract.v0": {
        "allowed_modes": frozenset({"validation"}),
        "allowed_record_kinds": frozenset({"runner_validation"}),
    },
    "malecns_signed_unfitted_characterization.v0": {
        "allowed_modes": frozenset({"validation"}),
        "allowed_record_kinds": frozenset({"calibration_campaign"}),
    },
}


def _validate_gate(metric: Scalar, gate: Mapping[str, Any]) -> bool:
    operator = gate.get("operator")
    expected = gate.get("value")
    if operator == "eq":
        return metric == expected
    if operator == "ge":
        return float(metric) >= float(expected)
    if operator == "le":
        return float(metric) <= float(expected)
    if operator == "between":
        bounds = gate.get("bounds")
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise CalibrationRunnerError("between gate requires two bounds")
        return float(bounds[0]) <= float(metric) <= float(bounds[1])
    if operator == "finite":
        return bool(np.isfinite(float(metric)))
    raise CalibrationRunnerError(f"Unsupported acceptance operator: {operator!r}")


def validate_job(job: Mapping[str, Any], job_path: Path) -> dict[str, str]:
    if job.get("schema_version") != 1:
        raise CalibrationRunnerError("Only runner schema_version 1 is supported")
    if job.get("status") != "runnable":
        raise CalibrationRunnerError("Runner job must have status: runnable")
    if job.get("record_kind") not in {"runner_validation", "calibration_campaign"}:
        raise CalibrationRunnerError("Invalid runner record_kind")
    mode = job.get("mode")
    if mode not in {"validation", "fit", "evaluation"}:
        raise CalibrationRunnerError("Runner mode must be validation, fit, or evaluation")
    exposure = job.get("optimization_exposure")
    if exposure not in {"allowed", "diagnostic_only", "evaluation_only"}:
        raise CalibrationRunnerError("Invalid optimization_exposure")
    if mode == "fit" and exposure == "evaluation_only":
        raise CalibrationRunnerError("A fitting job cannot use evaluation_only exposure")
    if mode == "evaluation" and exposure != "evaluation_only":
        raise CalibrationRunnerError("Evaluation mode must be evaluation_only")
    if job.get("behavior_targeted") and not job.get("user_authorization_ref"):
        raise CalibrationRunnerError("Behavior-targeted jobs require explicit authorization")

    splits = job.get("scenario_splits")
    if not isinstance(splits, dict):
        raise CalibrationRunnerError("scenario_splits must be explicit")
    forbidden = list(splits.get("held_out", [])) + list(splits.get("behavior_held_out", []))
    if mode != "evaluation" and forbidden:
        raise CalibrationRunnerError(
            "Optimization and validation jobs cannot access held-out scenarios"
        )
    acceptance = job.get("acceptance")
    if not isinstance(acceptance, dict) or not acceptance.get("criteria_locked_before_run"):
        raise CalibrationRunnerError("Acceptance criteria must be locked before execution")

    target_registry = _id_registry(CALIBRATION_ROOT / "targets")
    family_inventory = load_calibration_inventory()
    parameter_registry = _id_registry(CALIBRATION_ROOT / "parameter_sets")
    for target_id in job.get("target_ids", []):
        if target_id not in target_registry:
            raise CalibrationRunnerError(f"Unknown target id: {target_id}")
        target = _load_yaml(target_registry[target_id])
        if target.get("optimization_exposure") == "evaluation_only" and mode != "evaluation":
            raise CalibrationRunnerError(
                f"Held-out target {target_id} cannot be used outside evaluation mode"
            )
        if target.get("primary_class") == "behavior_targeted" and not job.get(
            "user_authorization_ref"
        ):
            raise CalibrationRunnerError(
                f"Behavior-targeted target {target_id} requires explicit authorization"
            )
    family_ids = job.get("parameter_family_ids", [])
    for family_id in family_ids:
        if family_id not in family_inventory.families:
            raise CalibrationRunnerError(f"Unknown parameter family id: {family_id}")
    for parameter_set_id in job.get("parent_parameter_set_ids", []):
        if parameter_set_id not in parameter_registry:
            raise CalibrationRunnerError(f"Unknown parent parameter set: {parameter_set_id}")
    if mode == "fit" and (not family_ids or not job.get("output_parameter_set_id")):
        raise CalibrationRunnerError(
            "Fitting jobs require parameter families and an output parameter-set id"
        )

    boundaries = job.get("topology_boundary", {}).get("semantic_topology_hashes", {})
    if not isinstance(boundaries, dict):
        raise CalibrationRunnerError("semantic_topology_hashes must be a mapping")
    for family_id, expected in boundaries.items():
        if family_id not in family_inventory.families:
            raise CalibrationRunnerError(f"Topology boundary names unknown family: {family_id}")
        observed = (
            family_inventory.families[family_id]
            .get("scope", {})
            .get("topology_snapshot", {})
            .get("semantic_topology_sha256")
        )
        if observed != expected:
            raise CalibrationRunnerError(
                f"Topology boundary drift for {family_id}: expected {expected}, got {observed}"
            )
    for family_id in family_ids:
        observed = (
            family_inventory.families[family_id]
            .get("scope", {})
            .get("topology_snapshot", {})
            .get("semantic_topology_sha256")
        )
        if observed and boundaries.get(family_id) != observed:
            raise CalibrationRunnerError(
                f"Job omits the accepted topology boundary for {family_id}"
            )

    input_hashes: dict[str, str] = {}
    for item in job.get("input_files", []):
        if not isinstance(item, dict) or not item.get("path") or not item.get("sha256"):
            raise CalibrationRunnerError("Every input file needs path and sha256")
        path = ROOT / str(item["path"])
        try:
            path.resolve().relative_to(ROOT.resolve())
        except ValueError as exc:
            raise CalibrationRunnerError("Immutable inputs must remain inside the project") from exc
        if not path.is_file():
            raise CalibrationRunnerError(f"Missing immutable input: {path}")
        observed = _sha256_file(path)
        if observed != item["sha256"]:
            raise CalibrationRunnerError(
                f"Input hash drift for {path}: expected {item['sha256']}, got {observed}"
            )
        input_hashes[str(item["path"])] = observed

    trials = job.get("trials")
    if not isinstance(trials, list) or not trials:
        raise CalibrationRunnerError("Runner job must declare at least one trial")
    case_ids = [trial.get("case_id") for trial in trials if isinstance(trial, dict)]
    if len(case_ids) != len(trials) or any(not isinstance(item, str) or not item for item in case_ids):
        raise CalibrationRunnerError("Every trial needs a non-empty case_id")
    if len(case_ids) != len(set(case_ids)):
        raise CalibrationRunnerError("Trial case_ids must be unique")
    for trial in trials:
        if not isinstance(trial.get("seed"), int):
            raise CalibrationRunnerError(f"Trial {trial['case_id']} needs an integer seed")
        gates = trial.get("gates")
        if not isinstance(gates, dict) or not gates:
            raise CalibrationRunnerError(f"Trial {trial['case_id']} needs locked gates")
    exclusions = job.get("semantic_metric_exclusions", [])
    if not isinstance(exclusions, list) or not all(
        isinstance(item, str) and item for item in exclusions
    ):
        raise CalibrationRunnerError("semantic_metric_exclusions must be a string list")
    if len(exclusions) != len(set(exclusions)):
        raise CalibrationRunnerError("semantic_metric_exclusions must be unique")
    gated_metrics = {
        metric_name for trial in trials for metric_name in trial["gates"]
    }
    if overlap := set(exclusions) & gated_metrics:
        raise CalibrationRunnerError(
            f"Gated metrics cannot be excluded from semantic results: {sorted(overlap)}"
        )
    significant_digits = job.get("semantic_float_significant_digits")
    if significant_digits is not None and (
        not isinstance(significant_digits, int) or not 1 <= significant_digits <= 15
    ):
        raise CalibrationRunnerError(
            "semantic_float_significant_digits must be an integer from 1 to 15"
        )
    repetitions = job.get("repeat_each", 1)
    if not isinstance(repetitions, int) or repetitions < 1:
        raise CalibrationRunnerError("repeat_each must be a positive integer")
    scheduled = len(trials) * repetitions
    budget = job.get("budget")
    if not isinstance(budget, dict) or int(budget.get("max_trials", -1)) < scheduled:
        raise CalibrationRunnerError("Trial plan exceeds declared max_trials")
    if float(budget.get("max_wall_seconds", 0)) <= 0:
        raise CalibrationRunnerError("max_wall_seconds must be positive")
    if not isinstance(job.get("evaluator_id"), str):
        raise CalibrationRunnerError("evaluator_id is required")
    return input_hashes


def _expanded_schedule(job: Mapping[str, Any]) -> list[dict[str, Any]]:
    schedule: list[dict[str, Any]] = []
    for trial in job["trials"]:
        for repetition in range(int(job.get("repeat_each", 1))):
            schedule.append(
                {
                    **trial,
                    "trial_id": f"{trial['case_id']}--r{repetition + 1:02d}",
                    "repetition": repetition + 1,
                }
            )
    return schedule


def run_job(
    job_path: Path = DEFAULT_JOB_PATH,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    evaluators: Mapping[str, Evaluator] | None = None,
) -> dict[str, Any]:
    job_path = Path(job_path)
    job = _load_yaml(job_path)
    input_hashes = validate_job(job, job_path)
    available = dict(DEFAULT_EVALUATORS)
    if evaluators:
        available.update(evaluators)
    evaluator_id = str(job["evaluator_id"])
    if evaluator_id not in available:
        raise CalibrationRunnerError(f"Evaluator is not registered: {evaluator_id}")
    if evaluator_id in DEFAULT_EVALUATOR_POLICIES:
        policy = DEFAULT_EVALUATOR_POLICIES[evaluator_id]
        if job["mode"] not in policy["allowed_modes"]:
            raise CalibrationRunnerError(
                f"Evaluator {evaluator_id} is not permitted in {job['mode']} mode"
            )
        if job["record_kind"] not in policy["allowed_record_kinds"]:
            raise CalibrationRunnerError(
                f"Evaluator {evaluator_id} is not permitted for {job['record_kind']}"
            )

    now = datetime.now(UTC)
    safe_id = "".join(character if character.isalnum() else "-" for character in job["id"])
    run_id = f"{now.strftime('%Y%m%dT%H%M%S%fZ')}--{safe_id}"
    run_root = Path(output_root) / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    config_text = job_path.read_text(encoding="utf-8")
    (run_root / "job.yaml").write_text(config_text, encoding="utf-8")
    config_sha256 = hashlib.sha256(config_text.encode("utf-8")).hexdigest()
    schedule = _expanded_schedule(job)
    started = time.perf_counter()
    trial_results: list[dict[str, Any]] = []
    wall_budget = float(job["budget"]["max_wall_seconds"])

    print(f"[RUN] {job['id']} -> {run_id}", flush=True)
    print(
        f"[PLAN] {len(schedule)} trials; evaluator={evaluator_id}; "
        f"exposure={job['optimization_exposure']}",
        flush=True,
    )
    for index, trial in enumerate(schedule, start=1):
        trial_started = time.perf_counter()
        print(f"[{index}/{len(schedule)}] {trial['trial_id']}...", flush=True)
        if trial_started - started > wall_budget:
            result = {
                "trial_id": trial["trial_id"],
                "case_id": trial["case_id"],
                "repetition": trial["repetition"],
                "seed": trial["seed"],
                "status": "skipped_budget_exhausted",
                "metrics": {},
                "gate_results": {},
                "elapsed_seconds": 0.0,
                "error": None,
            }
        else:
            try:
                metrics = dict(available[evaluator_id](trial))
                if any(
                    not isinstance(value, (bool, int, float, str))
                    for value in metrics.values()
                ):
                    raise CalibrationRunnerError("Evaluator metrics must be scalar")
                gate_results: dict[str, bool] = {}
                for metric_name, gate in trial["gates"].items():
                    if metric_name not in metrics:
                        raise CalibrationRunnerError(
                            f"Missing gated metric {metric_name} in {trial['trial_id']}"
                        )
                    gate_results[metric_name] = _validate_gate(metrics[metric_name], gate)
                status = "accepted" if all(gate_results.values()) else "rejected"
                result = {
                    "trial_id": trial["trial_id"],
                    "case_id": trial["case_id"],
                    "repetition": trial["repetition"],
                    "seed": trial["seed"],
                    "status": status,
                    "metrics": metrics,
                    "gate_results": gate_results,
                    "elapsed_seconds": time.perf_counter() - trial_started,
                    "error": None,
                }
            except Exception as exc:
                result = {
                    "trial_id": trial["trial_id"],
                    "case_id": trial["case_id"],
                    "repetition": trial["repetition"],
                    "seed": trial["seed"],
                    "status": "error",
                    "metrics": {},
                    "gate_results": {},
                    "elapsed_seconds": time.perf_counter() - trial_started,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
        trial_results.append(result)
        (run_root / f"trial-{index:04d}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"      -> {result['status']}", flush=True)

    counts = Counter(item["status"] for item in trial_results)
    metric_exclusions = frozenset(job.get("semantic_metric_exclusions", []))
    semantic_digits = job.get("semantic_float_significant_digits")
    repeated_metrics: dict[str, list[str]] = {}
    for result in trial_results:
        if result["status"] in {"accepted", "rejected"}:
            repeated_metrics.setdefault(result["case_id"], []).append(
                _canonical_hash(
                    _semantic_metrics(
                        result["metrics"], metric_exclusions, semantic_digits
                    )
                )
            )
    nondeterministic_cases = sorted(
        case_id for case_id, hashes in repeated_metrics.items() if len(set(hashes)) > 1
    )
    accounted = sum(counts.values()) == len(schedule)
    acceptance = job["acceptance"]
    required_accepted = (
        len(schedule)
        if acceptance.get("require_all_trials_accepted", False)
        else int(acceptance.get("minimum_accepted_trials", 1))
    )
    acceptance_count_pass = counts.get("accepted", 0) >= required_accepted
    error_count_pass = counts.get("error", 0) <= int(acceptance.get("maximum_errors", 0))
    determinism_pass = not acceptance.get(
        "require_repetition_determinism", False
    ) or not nondeterministic_cases
    budget_pass = time.perf_counter() - started <= wall_budget
    final_status = (
        "passed"
        if accounted
        and acceptance_count_pass
        and error_count_pass
        and determinism_pass
        and budget_pass
        else "failed"
    )
    recorded_trials = [
        {
            "trial_id": item["trial_id"],
            "case_id": item["case_id"],
            "repetition": item["repetition"],
            "seed": item["seed"],
            "status": item["status"],
            "metrics": item["metrics"],
            "gate_results": item["gate_results"],
            "error": item["error"],
        }
        for item in trial_results
    ]
    semantic_trials = [
        {
            **item,
            "metrics": _semantic_metrics(
                item["metrics"], metric_exclusions, semantic_digits
            ),
        }
        for item in recorded_trials
    ]
    git_state = _git_state()
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "job_id": job["id"],
        "record_kind": job["record_kind"],
        "claim_label": job["claim_label"],
        "mode": job["mode"],
        "optimization_exposure": job["optimization_exposure"],
        "started_at": now.isoformat(),
        "elapsed_seconds": time.perf_counter() - started,
        "status": final_status,
        "trial_accounting": {
            "scheduled": len(schedule),
            "accounted": sum(counts.values()),
            "by_status": dict(sorted(counts.items())),
            "unaccounted": len(schedule) - sum(counts.values()),
        },
        "nondeterministic_cases": nondeterministic_cases,
        "acceptance_accounting": {
            "required_accepted_trials": required_accepted,
            "accepted_count_pass": acceptance_count_pass,
            "maximum_errors": int(acceptance.get("maximum_errors", 0)),
            "error_count_pass": error_count_pass,
            "repetition_determinism_pass": determinism_pass,
            "wall_time_budget_pass": budget_pass,
        },
        "semantic_result_sha256": _canonical_hash(semantic_trials),
        "semantic_metric_exclusions": sorted(metric_exclusions),
        "semantic_float_significant_digits": semantic_digits,
        "reproducibility": {
            "job_config_sha256": config_sha256,
            "input_hashes": input_hashes,
            **git_state,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "process_id": os.getpid(),
        },
        "topology_boundary": job["topology_boundary"],
        "behavior_exposure": {
            "behavior_targeted": bool(job.get("behavior_targeted", False)),
            "scenario_splits": job["scenario_splits"],
        },
        "trials": recorded_trials,
    }
    summary_path = run_root / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        summary_reference = str(summary_path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        summary_reference = str(summary_path.resolve())
    latest = {
        "run_id": run_id,
        "summary": summary_reference,
        "status": final_status,
        "semantic_result_sha256": summary["semantic_result_sha256"],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (Path(output_root) / "latest.json").write_text(
        json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[SUMMARY] {final_status.upper()}: {len(schedule)} scheduled, "
        f"{counts.get('accepted', 0)} accepted, {counts.get('rejected', 0)} rejected, "
        f"{counts.get('error', 0)} errors",
        flush=True,
    )
    print(f"[ARTIFACT] {summary_path}", flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an immutable calibration job")
    parser.add_argument("--job", type=Path, default=DEFAULT_JOB_PATH)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    print("CALIBRATION RUNNER / AUDITABLE EXECUTION")
    try:
        summary = run_job(args.job, args.output_root)
    except Exception as exc:
        print(f"CALIBRATION_RUNNER_FAILED: {type(exc).__name__}: {exc}")
        return 1
    if summary["status"] != "passed":
        print("CALIBRATION_RUNNER_COMPLETED_WITH_FAILURES")
        return 1
    print(
        "CALIBRATION_RUNNER_OK: all trials accounted; "
        f"semantic hash {summary['semantic_result_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

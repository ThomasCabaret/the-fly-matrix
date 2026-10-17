from __future__ import annotations

import argparse
import hashlib
import json
import math
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import yaml

from .ledger import ROOT
from .motor_spike_force_parser import (
    PARSER_CONTRACT,
    _load_member,
    _sha256,
    _spike_indices,
    _trial_members,
    make_frame_time,
    make_input_time,
    matlab_smooth,
)


CAMPAIGN_PATH = (
    ROOT / "calibration" / "campaigns" / "motor-slow-tonic-envelope-v0.yaml"
)
RUNNER_PATH = (
    ROOT / "calibration" / "runner" / "motor-slow-tonic-envelope-v0.yaml"
)
OUTPUT_ROOT = (
    ROOT / "data" / "derived" / "calibration" / "motor-slow-tonic-envelope-v0"
)


class MotorSlowTonicEnvelopeError(RuntimeError):
    pass


@dataclass(frozen=True)
class SlowTrial:
    trial: int
    step_pA: float
    frame_time_s: np.ndarray
    force_delta_uN: np.ndarray
    spike_time_s: np.ndarray
    rest_rate_hz: float
    fit_mask: np.ndarray


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def first_order_event_rate(
    sample_time_s: np.ndarray,
    spike_time_s: np.ndarray,
    *,
    tau_s: float,
    delay_s: float,
    initial_rate_hz: float,
) -> np.ndarray:
    """Causal exponential filtering of events, in equivalent spikes/second."""

    sample_time = np.asarray(sample_time_s, dtype=np.float64)
    spikes = np.asarray(spike_time_s, dtype=np.float64) + float(delay_s)
    tau = float(tau_s)
    delay = float(delay_s)
    initial_rate = float(initial_rate_hz)
    if sample_time.ndim != 1 or len(sample_time) == 0:
        raise MotorSlowTonicEnvelopeError("sample_time_s must be a non-empty vector")
    if np.any(np.diff(sample_time) <= 0.0):
        raise MotorSlowTonicEnvelopeError("sample times must be strictly increasing")
    if not math.isfinite(tau) or tau <= 0.0:
        raise MotorSlowTonicEnvelopeError("tau_s must be finite and positive")
    if not math.isfinite(delay) or delay < 0.0:
        raise MotorSlowTonicEnvelopeError("delay_s must be finite and nonnegative")
    if not math.isfinite(initial_rate) or initial_rate < 0.0:
        raise MotorSlowTonicEnvelopeError(
            "initial_rate_hz must be finite and nonnegative"
        )

    start = float(sample_time[0])
    result = initial_rate * np.exp(-(sample_time - start) / tau)
    admitted = spikes[(spikes >= start) & (spikes <= float(sample_time[-1]))]
    if admitted.size:
        age = sample_time[:, None] - admitted[None, :]
        causal = age >= 0.0
        result += np.sum(
            np.where(causal, np.exp(-np.maximum(age, 0.0) / tau) / tau, 0.0),
            axis=1,
        )
    return result


def stratified_trial_folds(
    trial_steps: Mapping[int, float], fold_count: int
) -> list[list[int]]:
    if fold_count < 2:
        raise MotorSlowTonicEnvelopeError("at least two folds are required")
    by_step: dict[float, list[int]] = {}
    for trial, step in trial_steps.items():
        by_step.setdefault(float(step), []).append(int(trial))
    if not by_step or min(len(values) for values in by_step.values()) < fold_count:
        raise MotorSlowTonicEnvelopeError(
            "every current-step stratum must contain at least fold_count trials"
        )
    folds = [[] for _ in range(fold_count)]
    for step in sorted(by_step):
        for index, trial in enumerate(sorted(by_step[step])):
            folds[index % fold_count].append(trial)
    return [sorted(fold) for fold in folds]


def _extract_slow_trials(
    archive_path: Path,
    spec: Mapping[str, Any],
    selection: Mapping[str, Any],
) -> tuple[list[SlowTrial], dict[str, Any]]:
    stem = f"{spec['protocol']}_Raw_{spec['cell_id']}_"
    baseline_lo, baseline_hi = (float(value) for value in selection["baseline_window_s"])
    rest_lo, rest_hi = (float(value) for value in selection["rest_rate_window_s"])
    fit_lo, fit_hi = (float(value) for value in selection["fit_window_s"])
    spring = float(selection["spring_constant_uN_per_source_displacement"])
    smoothing_window = int(selection["force_smoothing_frames"])
    allowed_steps = {float(value) for value in selection["allowed_current_steps_pA"]}
    dispositions = {
        "declared": 0,
        "source_excluded": 0,
        "unexpected_current_step": 0,
        "missing_baseline": 0,
        "missing_fit_window": 0,
        "selected": 0,
    }
    rows: list[SlowTrial] = []
    with zipfile.ZipFile(archive_path) as archive:
        members = _trial_members(archive, stem)
        for trial_number in range(int(spec["trial_first"]), int(spec["trial_last"]) + 1):
            dispositions["declared"] += 1
            if trial_number not in members:
                raise MotorSlowTonicEnvelopeError(
                    f"missing declared trial {trial_number} in {archive_path.name}"
                )
            trial = _load_member(archive, members[trial_number])
            if bool(trial.get("excluded", False)):
                dispositions["source_excluded"] += 1
                continue
            step = float(trial["params"]["step"])
            if step not in allowed_steps:
                dispositions["unexpected_current_step"] += 1
                continue
            frame_time = make_frame_time(trial)
            force = np.asarray(
                trial["forceProbeStuff"]["CoM"], dtype=np.float64
            ).reshape(-1)
            force = matlab_smooth(force, smoothing_window) * spring
            finite = np.isfinite(force)
            baseline = (
                (frame_time >= baseline_lo)
                & (frame_time < baseline_hi)
                & finite
            )
            if not baseline.any():
                dispositions["missing_baseline"] += 1
                continue
            force = force - float(np.mean(force[baseline]))
            fit_mask = (
                (frame_time >= fit_lo) & (frame_time <= fit_hi) & np.isfinite(force)
            )
            if not fit_mask.any():
                dispositions["missing_fit_window"] += 1
                continue
            input_time = make_input_time(trial["params"])
            spike_indices = _spike_indices(trial)
            if len(spike_indices) and int(spike_indices.max()) >= len(input_time):
                raise MotorSlowTonicEnvelopeError("spike index exceeds input time")
            spike_time = input_time[spike_indices]
            rest_count = int(np.sum((spike_time >= rest_lo) & (spike_time < rest_hi)))
            rest_rate = rest_count / (rest_hi - rest_lo)
            rows.append(
                SlowTrial(
                    trial=trial_number,
                    step_pA=step,
                    frame_time_s=frame_time,
                    force_delta_uN=force,
                    spike_time_s=spike_time,
                    rest_rate_hz=float(rest_rate),
                    fit_mask=fit_mask,
                )
            )
            dispositions["selected"] += 1
    accounted = sum(value for key, value in dispositions.items() if key != "declared")
    if accounted != dispositions["declared"] or dispositions["selected"] != len(rows):
        raise MotorSlowTonicEnvelopeError("slow trial dispositions are not exhaustive")
    step_counts: dict[str, int] = {}
    for row in rows:
        step_counts[str(row.step_pA)] = step_counts.get(str(row.step_pA), 0) + 1
    return rows, {**dispositions, "selected_by_current_step_pA": step_counts}


def _candidate_grid(campaign: Mapping[str, Any]) -> list[tuple[float, float]]:
    grid = campaign["fit"]["candidate_grid"]
    taus = np.geomspace(
        float(grid["tau_s"]["minimum"]),
        float(grid["tau_s"]["maximum"]),
        int(grid["tau_s"]["count"]),
    )
    delays = np.linspace(
        float(grid["delay_s"]["minimum"]),
        float(grid["delay_s"]["maximum"]),
        int(grid["delay_s"]["count"]),
    )
    return [(float(tau), float(delay)) for tau in taus for delay in delays]


def _candidate_predictors(
    rows: Sequence[SlowTrial], candidate: tuple[float, float], baseline_window_s: Sequence[float]
) -> dict[int, np.ndarray]:
    lo, hi = (float(value) for value in baseline_window_s)
    result: dict[int, np.ndarray] = {}
    for row in rows:
        trace = first_order_event_rate(
            row.frame_time_s,
            row.spike_time_s,
            tau_s=candidate[0],
            delay_s=candidate[1],
            initial_rate_hz=row.rest_rate_hz,
        )
        baseline = (row.frame_time_s >= lo) & (row.frame_time_s < hi)
        trace = trace - float(np.mean(trace[baseline]))
        result[row.trial] = trace
    return result


def _fit_gain_and_score(
    rows: Sequence[SlowTrial], predictors: Mapping[int, np.ndarray]
) -> tuple[float, float, float, int]:
    numerator = 0.0
    denominator = 0.0
    for row in rows:
        x = predictors[row.trial][row.fit_mask]
        y = row.force_delta_uN[row.fit_mask]
        numerator += float(np.dot(x, y))
        denominator += float(np.dot(x, x))
    gain = max(0.0, numerator / denominator) if denominator > 0.0 else 0.0
    sse = 0.0
    energy = 0.0
    samples = 0
    for row in rows:
        x = predictors[row.trial][row.fit_mask]
        y = row.force_delta_uN[row.fit_mask]
        residual = y - gain * x
        sse += float(np.dot(residual, residual))
        energy += float(np.dot(y, y))
        samples += len(y)
    return gain, sse, energy, samples


def fit_slow_tonic_envelope(
    rows: Sequence[SlowTrial],
    candidates: Sequence[tuple[float, float]],
    *,
    fold_count: int,
    baseline_window_s: Sequence[float],
    near_optimal_relative_rmse: float,
) -> dict[str, Any]:
    if not rows:
        raise MotorSlowTonicEnvelopeError("no slow trials")
    trial_steps = {row.trial: row.step_pA for row in rows}
    folds = stratified_trial_folds(trial_steps, fold_count)
    predictor_cache = {
        candidate: _candidate_predictors(rows, candidate, baseline_window_s)
        for candidate in candidates
    }
    fold_results: list[dict[str, Any]] = []
    held_sse = 0.0
    held_energy = 0.0
    held_samples = 0
    for index, held_trials in enumerate(folds):
        held = set(held_trials)
        training = [row for row in rows if row.trial not in held]
        validation = [row for row in rows if row.trial in held]
        scored: list[tuple[float, float, float, tuple[float, float]]] = []
        for candidate in candidates:
            gain, sse, _, samples = _fit_gain_and_score(
                training, predictor_cache[candidate]
            )
            scored.append((math.sqrt(sse / samples), candidate[0], candidate[1], candidate))
        _, _, _, best = min(scored)
        train_gain, _, _, _ = _fit_gain_and_score(training, predictor_cache[best])
        sse = 0.0
        energy = 0.0
        samples = 0
        for row in validation:
            x = predictor_cache[best][row.trial][row.fit_mask]
            y = row.force_delta_uN[row.fit_mask]
            residual = y - train_gain * x
            sse += float(np.dot(residual, residual))
            energy += float(np.dot(y, y))
            samples += len(y)
        held_sse += sse
        held_energy += energy
        held_samples += samples
        fold_results.append(
            {
                "fold": index,
                "held_out_trials": held_trials,
                "tau_s": best[0],
                "delay_s": best[1],
                "training_gain_uN_per_hz": train_gain,
                "held_out_rmse_uN": math.sqrt(sse / samples),
                "held_out_energy_fraction_explained": 1.0 - sse / energy,
            }
        )

    all_scores: list[tuple[float, tuple[float, float], float, float]] = []
    for candidate in candidates:
        gain, sse, energy, samples = _fit_gain_and_score(
            rows, predictor_cache[candidate]
        )
        all_scores.append((math.sqrt(sse / samples), candidate, gain, energy))
    best_rmse, best, best_gain, _ = min(
        all_scores, key=lambda item: (item[0], item[1][0], item[1][1])
    )
    near = [
        (index, candidate, gain, rmse)
        for index, (rmse, candidate, gain, _) in enumerate(all_scores)
        if rmse <= best_rmse * (1.0 + float(near_optimal_relative_rmse))
    ]
    tau_values = [candidate[0] for _, candidate, _, _ in near]
    delay_values = [candidate[1] for _, candidate, _, _ in near]
    gain_values = [gain for _, _, gain, _ in near]
    return {
        "selected_trial_count": len(rows),
        "selected_trial_ids": sorted(trial_steps),
        "current_step_counts_pA": {
            str(step): sum(1 for value in trial_steps.values() if value == step)
            for step in sorted(set(trial_steps.values()))
        },
        "fold_count": fold_count,
        "candidate_count": len(candidates),
        "held_out_rmse_uN": math.sqrt(held_sse / held_samples),
        "held_out_energy_fraction_explained": 1.0 - held_sse / held_energy,
        "fold_results": fold_results,
        "all_data_best_candidate": {
            "tau_s": best[0],
            "delay_s": best[1],
            "gain_uN_per_hz": best_gain,
            "rmse_uN": best_rmse,
        },
        "near_optimal_envelope": {
            "relative_rmse_tolerance": near_optimal_relative_rmse,
            "candidate_count": len(near),
            "tau_s": [min(tau_values), max(tau_values)],
            "delay_s": [min(delay_values), max(delay_values)],
            "gain_uN_per_hz": [min(gain_values), max(gain_values)],
            "retained_candidates": [
                {
                    "grid_index": index,
                    "tau_s": candidate[0],
                    "delay_s": candidate[1],
                    "gain_uN_per_hz": gain,
                    "rmse_uN": rmse,
                }
                for index, candidate, gain, rmse in near
            ],
        },
        "grid_boundary_contact": {
            "tau_minimum": min(tau_values) == min(value[0] for value in candidates),
            "tau_maximum": max(tau_values) == max(value[0] for value in candidates),
            "delay_minimum": min(delay_values) == min(value[1] for value in candidates),
            "delay_maximum": max(delay_values) == max(value[1] for value in candidates),
        },
    }


def run(
    campaign_path: Path = CAMPAIGN_PATH,
    parser_contract_path: Path = PARSER_CONTRACT,
    output_root: Path = OUTPUT_ROOT,
    runner_path: Path = RUNNER_PATH,
) -> dict[str, Any]:
    campaign = yaml.safe_load(campaign_path.read_text(encoding="utf-8"))
    parser_contract = yaml.safe_load(parser_contract_path.read_text(encoding="utf-8"))
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise MotorSlowTonicEnvelopeError("slow campaign must remain diagnostic_only")
    if campaign.get("behavior_targets") != [] or campaign.get("topology_changes_allowed") is not False:
        raise MotorSlowTonicEnvelopeError("slow campaign cannot expose behavior or topology")
    selection = campaign["selection_policy"]
    if selection["promote_values"] or selection["choose_body_class_assignment"]:
        raise MotorSlowTonicEnvelopeError("slow campaign cannot promote or choose body classes")

    source = campaign["inputs"]["source_archive"]
    archive_path = ROOT / source["path"]
    print("[1/4] Verifying the exact slow-cell archive and scientific boundary", flush=True)
    if not archive_path.is_file() or archive_path.stat().st_size != int(source["expected_bytes"]):
        raise MotorSlowTonicEnvelopeError(f"missing or size-drifted archive: {archive_path}")
    digest = _sha256(archive_path)
    if digest != source["sha256"]:
        raise MotorSlowTonicEnvelopeError(f"archive hash drift: {archive_path}")

    spec = parser_contract["class_specs"]["slow_35C09"]
    print("[2/4] Extracting baseline-aware tonic spike/force trials", flush=True)
    rows, dispositions = _extract_slow_trials(
        archive_path, spec, campaign["trace_selection"]
    )
    print(
        f"      selected {len(rows)} / {dispositions['declared']} declared trials; "
        f"steps={dispositions['selected_by_current_step_pA']}",
        flush=True,
    )

    print("[3/4] Fitting a shared causal tonic envelope with stratified held-out trials", flush=True)
    candidates = _candidate_grid(campaign)
    result = fit_slow_tonic_envelope(
        rows,
        candidates,
        fold_count=int(campaign["fit"]["fold_count"]),
        baseline_window_s=campaign["trace_selection"]["baseline_window_s"],
        near_optimal_relative_rmse=float(campaign["fit"]["near_optimal_relative_rmse"]),
    )
    boundary = result["grid_boundary_contact"]
    status = (
        "completed_finite_diagnostic_envelope_boundary_contact_zero_promoted"
        if any(boundary.values())
        else "completed_finite_diagnostic_envelope_zero_promoted"
    )
    summary = {
        "schema_version": 1,
        "campaign_id": campaign["id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "claim_label": campaign["claim_label"],
        "campaign_sha256": _sha256(campaign_path),
        "parser_contract_sha256": _sha256(parser_contract_path),
        "archive_sha256": digest,
        "trial_dispositions": dispositions,
        "slow_result": result,
        "accounting": {
            "promoted_parameter_values": 0,
            "selected_body_class_assignments": 0,
            "behavior_targets_exposed": 0,
            "topology_changes": 0,
        },
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    summary["semantic_result_sha256"] = _canonical_hash(
        {key: value for key, value in summary.items() if key != "generated_at"}
    )
    output_root.mkdir(parents=True, exist_ok=True)
    artifact_path = output_root / "summary.json"
    artifact_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    compact = {
        "schema_version": 1,
        "id": "runner_result.motor_slow_tonic_envelope.v0",
        "campaign_id": campaign["id"],
        "target_id": campaign["target_id"],
        "status": status,
        "claim_label": campaign["claim_label"],
        "command": "fit_motor_slow_tonic_envelope.bat",
        "campaign_sha256": summary["campaign_sha256"],
        "semantic_result_sha256": summary["semantic_result_sha256"],
        "artifact_ref": str(artifact_path.relative_to(ROOT)).replace("\\", "/"),
        "trial_dispositions": dispositions,
        "slow_result": result,
        "accounting": summary["accounting"],
        "accepted_claims": summary["accepted_claims"],
        "forbidden_claims": summary["forbidden_claims"],
        "next_action": summary["next_action"],
    }
    runner_path.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")
    print("[4/4] Summary", flush=True)
    best = result["all_data_best_candidate"]
    envelope = result["near_optimal_envelope"]
    print(
        f"[DIAGNOSTIC] held-out R2={result['held_out_energy_fraction_explained']:.4f}; "
        f"best tau={best['tau_s']:.6f}s delay={best['delay_s']:.6f}s",
        flush=True,
    )
    print(
        f"[ENVELOPE] {envelope['candidate_count']} candidates; "
        f"tau={envelope['tau_s']} delay={envelope['delay_s']}",
        flush=True,
    )
    print("[BOUNDARY] 0 values promoted; 0 body assignments; 0 behavior targets", flush=True)
    print(f"[HASH] {summary['semantic_result_sha256']}", flush=True)
    return compact


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fit the slow motor-unit tonic response envelope without promotion"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    run(campaign_path=args.campaign, output_root=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
    _position_from_tags,
    _sha256,
    _spike_indices,
    _trial_members,
    make_frame_time,
    make_input_time,
)


CAMPAIGN_PATH = (
    ROOT / "calibration" / "campaigns" / "motor-twitch-temporal-diagnostic-v0.yaml"
)
RUNNER_PATH = (
    ROOT / "calibration" / "runner" / "motor-twitch-temporal-diagnostic-v0.yaml"
)
OUTPUT_ROOT = (
    ROOT / "data" / "derived" / "calibration" / "motor-twitch-temporal-diagnostic-v0"
)


class MotorTwitchTemporalError(RuntimeError):
    pass


@dataclass(frozen=True)
class NormalizedTwitch:
    trial: int
    time_s: np.ndarray
    normalized_force: np.ndarray
    peak_force_uN: float
    observed_time_to_peak_s: float


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def peak_normalized_biexponential(
    time_s: np.ndarray, rise_time_s: float, decay_time_s: float
) -> np.ndarray:
    """Evaluate the same causal, peak-normalized kernel used by local_conversion."""

    time = np.asarray(time_s, dtype=np.float64)
    rise = float(rise_time_s)
    decay = float(decay_time_s)
    if not math.isfinite(rise) or not math.isfinite(decay) or not 0 < rise < decay:
        raise MotorTwitchTemporalError("kernel requires 0 < rise_time_s < decay_time_s")
    peak_time = rise * decay / (decay - rise) * math.log(decay / rise)
    peak = math.exp(-peak_time / decay) - math.exp(-peak_time / rise)
    result = np.zeros_like(time, dtype=np.float64)
    causal = time > 0.0
    result[causal] = (
        np.exp(-time[causal] / decay) - np.exp(-time[causal] / rise)
    ) / peak
    return result


def _kernel_peak_time(rise_time_s: float, decay_time_s: float) -> float:
    return float(
        rise_time_s
        * decay_time_s
        / (decay_time_s - rise_time_s)
        * math.log(decay_time_s / rise_time_s)
    )


def deterministic_folds(trial_numbers: Sequence[int], fold_count: int) -> list[list[int]]:
    if fold_count < 2:
        raise MotorTwitchTemporalError("at least two folds are required")
    ordered = sorted(int(value) for value in trial_numbers)
    if len(ordered) < fold_count:
        raise MotorTwitchTemporalError("fewer selected trials than folds")
    folds = [[] for _ in range(fold_count)]
    for index, trial in enumerate(ordered):
        folds[index % fold_count].append(trial)
    return folds


def _extract_isolated_twitches(
    archive_path: Path,
    spec: Mapping[str, Any],
    rules: Mapping[str, Any],
) -> tuple[list[NormalizedTwitch], dict[str, int]]:
    stem = f"{spec['protocol']}_Raw_{spec['cell_id']}_"
    allowed_positions = {float(value) for value in spec["positions"]}
    dispositions = {
        "declared": 0,
        "source_excluded": 0,
        "not_single_spike": 0,
        "non_neutral_probe_position": 0,
        "missing_pre_spike_baseline": 0,
        "no_finite_fit_window": 0,
        "nonpositive_peak": 0,
        "source_fast_small_peak": 0,
        "selected": 0,
    }
    selected: list[NormalizedTwitch] = []
    with zipfile.ZipFile(archive_path) as archive:
        members = _trial_members(archive, stem)
        for trial_number in range(int(spec["trial_first"]), int(spec["trial_last"]) + 1):
            dispositions["declared"] += 1
            if trial_number not in members:
                raise MotorTwitchTemporalError(
                    f"missing declared trial {trial_number} in {archive_path.name}"
                )
            trial = _load_member(archive, members[trial_number])
            if bool(trial.get("excluded", False)):
                dispositions["source_excluded"] += 1
                continue
            spikes = _spike_indices(trial)
            if len(spikes) != 1:
                dispositions["not_single_spike"] += 1
                continue
            position = _position_from_tags(trial.get("tags"), allowed_positions)
            if not math.isfinite(position) or position != float(rules["probe_position"]):
                dispositions["non_neutral_probe_position"] += 1
                continue
            input_time = make_input_time(trial["params"])
            spike_index = int(spikes[0])
            if spike_index >= len(input_time):
                raise MotorTwitchTemporalError("spike index exceeds input time")
            relative_time = make_frame_time(trial) - input_time[spike_index]
            displacement = np.asarray(
                trial["forceProbeStuff"]["CoM"], dtype=np.float64
            ).reshape(-1)
            before = np.flatnonzero(relative_time < 0.0)
            if not len(before) or not math.isfinite(float(displacement[before[-1]])):
                dispositions["missing_pre_spike_baseline"] += 1
                continue
            displacement = displacement - displacement[before[-1]]
            fit_window = (
                (relative_time > float(rules["fit_window_s"][0]))
                & (relative_time < float(rules["fit_window_s"][1]))
                & np.isfinite(displacement)
            )
            if not fit_window.any():
                dispositions["no_finite_fit_window"] += 1
                continue
            peak_displacement = float(np.max(displacement[fit_window]))
            if peak_displacement <= 0.0:
                dispositions["nonpositive_peak"] += 1
                continue
            if (
                str(spec["functional_class"]) == "fast_81A07"
                and peak_displacement < float(rules["fast_minimum_peak_source_unit"])
            ):
                dispositions["source_fast_small_peak"] += 1
                continue
            force = displacement[fit_window] * float(rules["spring_constant_N_per_m"])
            peak_force = peak_displacement * float(rules["spring_constant_N_per_m"])
            normalized = force / peak_force
            local_time = relative_time[fit_window]
            selected.append(
                NormalizedTwitch(
                    trial=trial_number,
                    time_s=local_time,
                    normalized_force=normalized,
                    peak_force_uN=peak_force,
                    observed_time_to_peak_s=float(local_time[int(np.argmax(normalized))]),
                )
            )
            dispositions["selected"] += 1
    accounted = sum(value for key, value in dispositions.items() if key != "declared")
    if accounted != dispositions["declared"] or dispositions["selected"] != len(selected):
        raise MotorTwitchTemporalError("trial dispositions are not exhaustive")
    return selected, dispositions


def _grid(campaign: Mapping[str, Any]) -> list[tuple[float, float]]:
    grid = campaign["fit"]["candidate_grid"]
    rise = np.geomspace(
        float(grid["rise_time_s"]["minimum"]),
        float(grid["rise_time_s"]["maximum"]),
        int(grid["rise_time_s"]["count"]),
    )
    decay = np.geomspace(
        float(grid["decay_time_s"]["minimum"]),
        float(grid["decay_time_s"]["maximum"]),
        int(grid["decay_time_s"]["count"]),
    )
    result = [(float(r), float(d)) for r in rise for d in decay if d > r]
    if not result:
        raise MotorTwitchTemporalError("candidate grid contains no valid kernel")
    return result


def _sum_squared_error(
    rows: Sequence[NormalizedTwitch], candidate: tuple[float, float]
) -> tuple[float, float, int]:
    squared_error = 0.0
    observed_energy = 0.0
    sample_count = 0
    for row in rows:
        predicted = peak_normalized_biexponential(row.time_s, *candidate)
        residual = row.normalized_force - predicted
        squared_error += float(np.sum(residual * residual))
        observed_energy += float(np.sum(row.normalized_force * row.normalized_force))
        sample_count += len(row.time_s)
    return squared_error, observed_energy, sample_count


def fit_temporal_shape(
    rows: Sequence[NormalizedTwitch],
    candidates: Sequence[tuple[float, float]],
    *,
    fold_count: int,
    near_optimal_relative_rmse: float,
) -> dict[str, Any]:
    if not rows:
        raise MotorTwitchTemporalError("no isolated twitch rows")
    by_trial = {row.trial: row for row in rows}
    folds = deterministic_folds(list(by_trial), fold_count)
    fold_results: list[dict[str, Any]] = []
    held_out_sse = 0.0
    held_out_energy = 0.0
    held_out_samples = 0
    for index, held_trials in enumerate(folds):
        held = set(held_trials)
        training_rows = [row for row in rows if row.trial not in held]
        validation_rows = [row for row in rows if row.trial in held]
        scored = [(_sum_squared_error(training_rows, candidate)[0], candidate) for candidate in candidates]
        _, best = min(scored, key=lambda item: (item[0], item[1][0], item[1][1]))
        sse, energy, samples = _sum_squared_error(validation_rows, best)
        held_out_sse += sse
        held_out_energy += energy
        held_out_samples += samples
        fold_results.append(
            {
                "fold": index,
                "held_out_trials": held_trials,
                "rise_time_s": best[0],
                "decay_time_s": best[1],
                "peak_time_s": _kernel_peak_time(*best),
                "held_out_rmse_peak_normalized": math.sqrt(sse / samples),
                "held_out_energy_fraction_explained": 1.0 - sse / energy,
            }
        )

    all_scores: list[tuple[float, tuple[float, float]]] = []
    for candidate in candidates:
        sse, _, samples = _sum_squared_error(rows, candidate)
        all_scores.append((math.sqrt(sse / samples), candidate))
    best_rmse, best = min(all_scores, key=lambda item: (item[0], item[1][0], item[1][1]))
    near = [
        candidate
        for rmse, candidate in all_scores
        if rmse <= best_rmse * (1.0 + float(near_optimal_relative_rmse))
    ]
    peaks = np.asarray([row.peak_force_uN for row in rows], dtype=np.float64)
    times = np.asarray([row.observed_time_to_peak_s for row in rows], dtype=np.float64)
    return {
        "selected_trial_count": len(rows),
        "selected_trial_ids": sorted(by_trial),
        "fold_count": fold_count,
        "candidate_count": len(candidates),
        "held_out_rmse_peak_normalized": math.sqrt(held_out_sse / held_out_samples),
        "held_out_energy_fraction_explained": 1.0 - held_out_sse / held_out_energy,
        "fold_results": fold_results,
        "all_data_best_candidate": {
            "rise_time_s": best[0],
            "decay_time_s": best[1],
            "peak_time_s": _kernel_peak_time(*best),
            "rmse_peak_normalized": best_rmse,
        },
        "near_optimal_envelope": {
            "relative_rmse_tolerance": near_optimal_relative_rmse,
            "candidate_count": len(near),
            "rise_time_s": [min(value[0] for value in near), max(value[0] for value in near)],
            "decay_time_s": [min(value[1] for value in near), max(value[1] for value in near)],
            "peak_time_s": [
                min(_kernel_peak_time(*value) for value in near),
                max(_kernel_peak_time(*value) for value in near),
            ],
        },
        "observed_single_spike_summary": {
            "peak_force_uN_median": float(np.median(peaks)),
            "peak_force_uN_iqr": [float(np.quantile(peaks, 0.25)), float(np.quantile(peaks, 0.75))],
            "time_to_peak_s_median": float(np.median(times)),
            "time_to_peak_s_iqr": [float(np.quantile(times, 0.25)), float(np.quantile(times, 0.75))],
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
        raise MotorTwitchTemporalError("temporal pilot must remain diagnostic_only")
    if campaign.get("behavior_targets") != [] or campaign.get("topology_changes_allowed") is not False:
        raise MotorTwitchTemporalError("temporal pilot cannot expose behavior or topology changes")
    if campaign["selection_policy"]["promote_values"] is not False:
        raise MotorTwitchTemporalError("temporal pilot cannot promote values")

    source_by_class = {item["functional_class"]: item for item in campaign["inputs"]["source_archives"]}
    candidates = _grid(campaign)
    rules = campaign["trace_selection"]
    results: dict[str, Any] = {}
    dispositions: dict[str, Any] = {}
    archive_hashes: dict[str, str] = {}

    print("[1/4] Verifying exact archives and diagnostic-only campaign boundary", flush=True)
    for functional_class in campaign["fit"]["fitted_classes"]:
        spec = parser_contract["class_specs"][functional_class]
        source = source_by_class[functional_class]
        archive_path = ROOT / source["path"]
        if not archive_path.is_file() or archive_path.stat().st_size != int(source["expected_bytes"]):
            raise MotorTwitchTemporalError(f"missing or size-drifted archive: {archive_path}")
        digest = _sha256(archive_path)
        if digest != source["sha256"]:
            raise MotorTwitchTemporalError(f"archive hash drift: {archive_path}")
        archive_hashes[functional_class] = digest

    print("[2/4] Extracting source-filtered, neutral-position, single-spike traces", flush=True)
    for functional_class in campaign["fit"]["fitted_classes"]:
        spec = parser_contract["class_specs"][functional_class]
        archive_path = ROOT / source_by_class[functional_class]["path"]
        rows, local_dispositions = _extract_isolated_twitches(archive_path, spec, rules)
        dispositions[functional_class] = local_dispositions
        print(
            f"      {functional_class}: {len(rows)} selected / {local_dispositions['declared']} declared",
            flush=True,
        )
        results[functional_class] = fit_temporal_shape(
            rows,
            candidates,
            fold_count=int(campaign["fit"]["fold_count"]),
            near_optimal_relative_rmse=float(
                campaign["fit"]["near_optimal_relative_rmse"]
            ),
        )

    print("[3/4] Accounting for the slow class without forcing an unsupported fit", flush=True)
    slow_class = str(campaign["fit"]["unfitted_class"])
    slow_spec = parser_contract["class_specs"][slow_class]
    slow_archive = ROOT / source_by_class[slow_class]["path"]
    if not slow_archive.is_file() or slow_archive.stat().st_size != int(source_by_class[slow_class]["expected_bytes"]):
        raise MotorTwitchTemporalError(f"missing or size-drifted archive: {slow_archive}")
    slow_digest = _sha256(slow_archive)
    if slow_digest != source_by_class[slow_class]["sha256"]:
        raise MotorTwitchTemporalError(f"archive hash drift: {slow_archive}")
    archive_hashes[slow_class] = slow_digest
    _, slow_dispositions = _extract_isolated_twitches(slow_archive, slow_spec, rules)
    dispositions[slow_class] = slow_dispositions
    results[slow_class] = {
        "status": "not_fit_no_isolated_single_spike_trials",
        "selected_trial_count": slow_dispositions["selected"],
        "reason": campaign["fit"]["unfitted_class_reason"],
    }

    summary = {
        "schema_version": 1,
        "campaign_id": campaign["id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "completed_diagnostic_fast_intermediate_slow_unidentified_zero_promoted",
        "claim_label": campaign["claim_label"],
        "campaign_sha256": _sha256(campaign_path),
        "parser_contract_sha256": _sha256(parser_contract_path),
        "archive_hashes": archive_hashes,
        "trial_dispositions": dispositions,
        "class_results": results,
        "accounting": {
            "fitted_classes": 2,
            "unfitted_classes": 1,
            "selected_single_spike_trials": sum(
                dispositions[name]["selected"] for name in campaign["fit"]["fitted_classes"]
            ),
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
    artifact_ref = str(artifact_path.relative_to(ROOT)).replace("\\", "/")
    compact = {
        "schema_version": 1,
        "id": "runner_result.motor_twitch_temporal_diagnostic.v0",
        "campaign_id": campaign["id"],
        "target_id": campaign["target_id"],
        "status": summary["status"],
        "claim_label": campaign["claim_label"],
        "command": "fit_motor_twitch_temporal_pilot.bat",
        "campaign_sha256": summary["campaign_sha256"],
        "semantic_result_sha256": summary["semantic_result_sha256"],
        "artifact_ref": artifact_ref,
        "accounting": summary["accounting"],
        "class_results": results,
        "accepted_claims": summary["accepted_claims"],
        "forbidden_claims": summary["forbidden_claims"],
        "next_action": summary["next_action"],
    }
    runner_path.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")
    print("[4/4] Summary", flush=True)
    for name in campaign["fit"]["fitted_classes"]:
        item = results[name]
        best = item["all_data_best_candidate"]
        print(
            f"[DIAGNOSTIC] {name}: held-out R2={item['held_out_energy_fraction_explained']:.4f}; "
            f"rise={best['rise_time_s']:.6f}s decay={best['decay_time_s']:.6f}s",
            flush=True,
        )
    print("[UNRESOLVED] slow_35C09: no isolated single-spike trial; no kernel fit", flush=True)
    print("[BOUNDARY] 0 values promoted; 0 body assignments; 0 behavior targets", flush=True)
    print(f"[HASH] {summary['semantic_result_sha256']}", flush=True)
    return compact


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fit diagnostic within-cell motor twitch shapes without promotion"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    run(campaign_path=args.campaign, output_root=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

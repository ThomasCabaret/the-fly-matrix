from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml
from scipy.signal import fftconvolve

from .feco_observation import gcamp_kernel, predict_calcium
from .ledger import ROOT


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "feco-calcium-held-out-fit-v0.yaml"
RUNNER_PATH = ROOT / "calibration" / "runner" / "feco-calcium-held-out-fit-v0.yaml"
OUTPUT_ROOT = ROOT / "runs" / "calibration" / "feco-calcium-held-out-fit-v0"


class FeCOCalciumFitError(ValueError):
    """Raised when the preregistered fit cannot be executed honestly."""


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    fit_kind: str
    model_type: str
    sampling_policy: str = "source_ceil_second_time_sample"
    grouping_policy: str = "per_animal_trial_roi"
    threshold_deg_s: float | None = None
    claw_center_deg: float = 80.0
    pad_first_sample: int = 0


@dataclass(frozen=True)
class PreparedData:
    frame: pd.DataFrame
    accounting: Mapping[str, int]


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FeCOCalciumFitError(f"{path} must contain a YAML mapping")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = _load_yaml(path)
    if campaign.get("primary_class") != "local_interface":
        raise FeCOCalciumFitError("FeCO fitting must remain a local_interface campaign")
    if campaign.get("optimization_exposure") != "allowed":
        raise FeCOCalciumFitError("the local fit must declare optimization exposure")
    if campaign.get("behavior_targets") != []:
        raise FeCOCalciumFitError("FeCO fitting cannot expose behavior targets")
    if campaign.get("topology_changes_allowed") is not False:
        raise FeCOCalciumFitError("FeCO fitting cannot change topology")
    if campaign.get("selection_policy", {}).get("choose_winner") is not False:
        raise FeCOCalciumFitError("v0 must report the candidate ensemble, not choose a winner")
    if campaign.get("fit", {}).get("maximum_parameters_per_fold_candidate") != 5:
        raise FeCOCalciumFitError("v0 must expose the five-parameter claw fitting path")
    return campaign


def candidates_for(dataset: Mapping[str, Any]) -> list[Candidate]:
    result: list[Candidate] = []
    for item in dataset["candidates"]:
        result.append(
            Candidate(
                candidate_id=str(item["id"]),
                fit_kind=str(item["fit_kind"]),
                model_type=str(item["model_type"]),
                sampling_policy=str(item.get("sampling_policy", "not_applicable")),
                grouping_policy=str(item.get("grouping_policy", "per_animal_trial_roi")),
                threshold_deg_s=(
                    None if item.get("threshold_deg_s") is None else float(item["threshold_deg_s"])
                ),
                claw_center_deg=float(item.get("claw_center_deg", 80.0)),
                pad_first_sample=int(item.get("pad_first_sample", 0)),
            )
        )
    if len(result) != len({item.candidate_id for item in result}):
        raise FeCOCalciumFitError("candidate identifiers must be unique within a dataset")
    return result


def prepare_frame(frame: pd.DataFrame, dataset: Mapping[str, Any]) -> PreparedData:
    required = ("animal_id", "trial", "roi", "analyze", "time", "calcium", "L1C_flex")
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise FeCOCalciumFitError(f"missing required columns: {missing}")

    rows_total = int(len(frame))
    analyze = pd.to_numeric(frame["analyze"], errors="coerce").eq(1)
    roi = frame["roi"].astype("string").str.contains(
        str(dataset["roi_contains"]), regex=False, na=False
    )
    working = frame.copy()
    working["_source_order"] = np.arange(len(working), dtype=np.int64)
    selected = working.loc[analyze & roi, [*required, "_source_order"]].copy()
    selected["time"] = pd.to_numeric(selected["time"], errors="coerce")
    selected["calcium"] = pd.to_numeric(selected["calcium"], errors="coerce")
    selected["L1C_flex"] = pd.to_numeric(selected["L1C_flex"], errors="coerce")
    finite = np.isfinite(selected[["time", "calcium", "L1C_flex"]].to_numpy()).all(axis=1)
    invalid_numeric = int((~finite).sum())
    selected = selected.loc[finite].copy()
    selected["animal_id"] = selected["animal_id"].astype("string")
    selected["trial"] = selected["trial"].astype("string")
    selected["roi"] = selected["roi"].astype("string")
    missing_keys = selected[["animal_id", "trial", "roi"]].isna().any(axis=1)
    invalid_keys = int(missing_keys.sum())
    selected = selected.loc[~missing_keys].copy()
    selected.sort_values(["animal_id", "trial", "roi", "time"], kind="stable", inplace=True)
    selected.reset_index(drop=True, inplace=True)

    if selected.empty:
        raise FeCOCalciumFitError("no finite analyze=1 rows match the preregistered ROI")
    duplicated_time = selected.duplicated(["animal_id", "trial", "roi", "time"]).sum()
    if duplicated_time:
        raise FeCOCalciumFitError(f"{duplicated_time} duplicate sample times inside trial groups")
    animals = int(selected["animal_id"].nunique())
    if animals < 2:
        raise FeCOCalciumFitError("leave-one-animal-out fitting requires at least two animals")
    accounting = {
        "rows_total": rows_total,
        "rows_analyze_roi_selected_before_numeric_check": int((analyze & roi).sum()),
        "rows_excluded_analyze_or_roi": int(rows_total - int((analyze & roi).sum())),
        "rows_excluded_nonfinite_numeric": invalid_numeric,
        "rows_excluded_missing_group_key": invalid_keys,
        "rows_retained": int(len(selected)),
        "animals_retained": animals,
        "trials_retained": int(selected[["animal_id", "trial", "roi"]].drop_duplicates().shape[0]),
    }
    if sum(
        accounting[key]
        for key in (
            "rows_excluded_analyze_or_roi",
            "rows_excluded_nonfinite_numeric",
            "rows_excluded_missing_group_key",
            "rows_retained",
        )
    ) != rows_total:
        raise FeCOCalciumFitError("row accounting is not exhaustive")
    return PreparedData(frame=selected, accounting=accounting)


def _sampling_hz(group: pd.DataFrame, policy: str) -> float:
    time = group["time"].to_numpy(dtype=np.float64)
    if len(time) < 2:
        raise FeCOCalciumFitError("each trial/ROI group needs at least two time samples")
    delta = np.diff(time)
    if not np.isfinite(delta).all() or np.any(delta <= 0):
        raise FeCOCalciumFitError("time must be finite and strictly increasing per trial/ROI")
    median = float(np.median(delta))
    if float(np.max(np.abs(delta - median))) > max(1e-9, 0.02 * median):
        raise FeCOCalciumFitError("sampling intervals vary by more than 2% inside a trial")
    if policy == "source_ceil_second_time_sample":
        if abs(float(time[0])) > max(1e-9, 0.02 * median):
            raise FeCOCalciumFitError(
                "source sampling rule requires each trial time vector to start at zero"
            )
        return float(np.ceil(1.0 / float(time[1])))
    if policy == "timestamp_reciprocal_median":
        return 1.0 / median
    raise FeCOCalciumFitError(f"unsupported sampling policy {policy!r}")


def add_candidate_prediction(frame: pd.DataFrame, candidate: Candidate) -> np.ndarray:
    if candidate.fit_kind != "affine_on_fixed_prediction":
        raise FeCOCalciumFitError(
            f"candidate {candidate.candidate_id} does not define a fixed prediction"
        )
    predicted = np.empty(len(frame), dtype=np.float64)
    group_columns = ["animal_id", "trial", "roi"]
    for _, group in frame.groupby(group_columns, sort=False, observed=True):
        positions = group["L1C_flex"].to_numpy(dtype=np.float64)
        values = predict_calcium(
            positions,
            sampling_hz=_sampling_hz(group, candidate.sampling_policy),
            model_type=candidate.model_type,  # type: ignore[arg-type]
            threshold_deg_s=candidate.threshold_deg_s,
            claw_center_deg=candidate.claw_center_deg,
            pad_first_sample=candidate.pad_first_sample,
        )
        predicted[group.index.to_numpy(dtype=np.int64)] = values
    if not np.isfinite(predicted).all():
        raise FeCOCalciumFitError(f"candidate {candidate.candidate_id} emitted non-finite values")
    return predicted


def _quartic_gcamp_design(frame: pd.DataFrame, candidate: Candidate) -> np.ndarray:
    if candidate.fit_kind != "quartic_gcamp_padded":
        raise FeCOCalciumFitError(f"candidate {candidate.candidate_id} is not a quartic fit")

    def group_design(group: pd.DataFrame) -> np.ndarray:
        centered = group["L1C_flex"].to_numpy(dtype=np.float64) - candidate.claw_center_deg
        padded = np.pad(centered, (candidate.pad_first_sample, 0), mode="edge")
        basis = np.column_stack(
            (padded**4, padded**3, padded**2, padded, np.ones(len(padded)))
        )
        if candidate.sampling_policy != "fixed_8_01_hz_from_imaging_poly_fun":
            raise FeCOCalciumFitError("claw quartic source path must use its pinned 8.01 Hz")
        kernel = gcamp_kernel(len(padded), 8.01)
        convolved = np.column_stack(
            [fftconvolve(basis[:, column], kernel, mode="full")[: len(padded)] for column in range(5)]
        )
        return convolved[candidate.pad_first_sample :]

    if candidate.grouping_policy == "concatenate_selected_rows_within_fold":
        ordered = frame.sort_values("_source_order", kind="stable")
        designed = group_design(ordered)
        result = np.empty((len(frame), 5), dtype=np.float64)
        result[ordered.index.to_numpy(dtype=np.int64)] = designed
        return result
    if candidate.grouping_policy == "per_animal_trial_roi":
        result = np.empty((len(frame), 5), dtype=np.float64)
        for _, group in frame.groupby(["animal_id", "trial", "roi"], sort=False, observed=True):
            result[group.index.to_numpy(dtype=np.int64)] = group_design(group)
        return result
    raise FeCOCalciumFitError(
        f"unsupported grouping policy {candidate.grouping_policy!r} for {candidate.candidate_id}"
    )


def _design_matrix(frame: pd.DataFrame, candidate: Candidate) -> tuple[np.ndarray, list[str]]:
    frame = frame.reset_index(drop=True)
    if candidate.fit_kind == "affine_on_fixed_prediction":
        prediction = add_candidate_prediction(frame, candidate)
        return np.column_stack((prediction, np.ones(len(frame)))), ["scale", "offset"]
    if candidate.fit_kind == "quartic_gcamp_padded":
        return _quartic_gcamp_design(frame, candidate), [
            "degree_4",
            "degree_3",
            "degree_2",
            "degree_1",
            "offset",
        ]
    raise FeCOCalciumFitError(
        f"unsupported fit_kind {candidate.fit_kind!r} for {candidate.candidate_id}"
    )


def _metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float | int | None]:
    residual = predicted - observed
    correlation: float | None = None
    if np.std(observed) > 0 and np.std(predicted) > 0:
        correlation = float(np.corrcoef(observed, predicted)[0, 1])
    return {
        "samples": int(len(observed)),
        "rmse_raw_calcium": float(np.sqrt(np.mean(residual**2))),
        "mae_raw_calcium": float(np.mean(np.abs(residual))),
        "pearson_r": correlation,
    }


def leave_one_animal_out(frame: pd.DataFrame, candidate: Candidate) -> dict[str, Any]:
    animals = sorted(frame["animal_id"].astype(str).unique().tolist())
    folds: list[dict[str, Any]] = []
    for held_out in animals:
        test = frame["animal_id"].astype(str).eq(held_out).to_numpy()
        train = ~test
        train_frame = frame.loc[train].reset_index(drop=True)
        held_out_frame = frame.loc[test].reset_index(drop=True)
        design, parameter_names = _design_matrix(train_frame, candidate)
        held_out_design, held_out_parameter_names = _design_matrix(held_out_frame, candidate)
        if held_out_parameter_names != parameter_names:
            raise FeCOCalciumFitError("train and held-out design contracts disagree")
        train_observed = train_frame["calcium"].to_numpy(dtype=np.float64)
        held_out_observed = held_out_frame["calcium"].to_numpy(dtype=np.float64)
        coefficients, _, rank, _ = np.linalg.lstsq(design, train_observed, rcond=None)
        if rank != len(parameter_names):
            folds.append(
                {
                    "held_out_animal": held_out,
                    "status": "blocked_rank_deficient_training_prediction",
                    "train_samples": int(train.sum()),
                    "held_out_samples": int(test.sum()),
                }
            )
            continue
        held_out_prediction = held_out_design @ coefficients
        folds.append(
            {
                "held_out_animal": held_out,
                "status": "evaluated",
                "train_samples": int(train.sum()),
                "held_out_samples": int(test.sum()),
                "fit": {
                    name: float(value) for name, value in zip(parameter_names, coefficients, strict=True)
                },
                "metrics": _metrics(held_out_observed, held_out_prediction),
            }
        )
    evaluated = [item for item in folds if item["status"] == "evaluated"]
    aggregate: dict[str, Any] = {
        "folds_total": len(folds),
        "folds_evaluated": len(evaluated),
        "folds_blocked": len(folds) - len(evaluated),
    }
    if evaluated:
        for name in ("rmse_raw_calcium", "mae_raw_calcium"):
            values = np.asarray([item["metrics"][name] for item in evaluated], dtype=np.float64)
            aggregate[f"median_{name}"] = float(np.median(values))
            aggregate[f"worst_{name}"] = float(np.max(values))
    return {
        "candidate_id": candidate.candidate_id,
        "fit_kind": candidate.fit_kind,
        "sampling_policy": candidate.sampling_policy,
        "grouping_policy": candidate.grouping_policy,
        "parameters_per_fold": len(parameter_names),
        "folds": folds,
        "aggregate": aggregate,
    }


def fit_dataset(frame: pd.DataFrame, dataset: Mapping[str, Any]) -> dict[str, Any]:
    prepared = prepare_frame(frame, dataset)
    results = [leave_one_animal_out(prepared.frame, candidate) for candidate in candidates_for(dataset)]
    return {
        "dataset_id": str(dataset["dataset_id"]),
        "functional_class": str(dataset["functional_class"]),
        "accounting": dict(prepared.accounting),
        "candidates": results,
        "candidate_winner_selected": False,
        "parameter_values_promoted": 0,
    }


def run(
    campaign_path: Path = CAMPAIGN_PATH,
    runner_path: Path = RUNNER_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    campaign = load_campaign(campaign_path)
    print("[1/4] Verifying preregistered FeCO table paths and hashes", flush=True)
    blocked: list[dict[str, str]] = []
    verified: list[tuple[Mapping[str, Any], Path]] = []
    for dataset in campaign["inputs"]["datasets"]:
        path = ROOT / str(dataset["path"])
        if not path.is_file():
            blocked.append({"dataset_id": str(dataset["dataset_id"]), "reason": "missing_file"})
            continue
        actual = _sha256(path)
        if actual != str(dataset["sha256"]):
            raise FeCOCalciumFitError(f"source hash drift for {path}: {actual}")
        verified.append((dataset, path))

    campaign_hash = _sha256(campaign_path)
    if blocked:
        semantic = {
            "campaign_sha256": campaign_hash,
            "datasets_expected": len(campaign["inputs"]["datasets"]),
            "datasets_verified": len(verified),
            "datasets_blocked": blocked,
            "candidate_winner_selected": False,
            "parameter_values_promoted": 0,
            "behavior_targets_exposed": 0,
            "topology_changes": 0,
        }
        summary = {
            "schema_version": 1,
            "id": "runner_result.feco_calcium_held_out_fit.v0",
            "generated_at": datetime.now(UTC).isoformat(),
            "campaign_id": campaign["id"],
            "campaign_sha256": campaign_hash,
            "status": "blocked_missing_authenticated_tables",
            "semantic_result_sha256": _canonical_hash(semantic),
            "accounting": semantic,
            "interpretation": {
                "biological_fit_completed": False,
                "native_representation_selected": False,
                "next_action": "set_DRYAD_BEARER_TOKEN_and_run_prepare_local_source_data",
            },
        }
        runner_path.parent.mkdir(parents=True, exist_ok=True)
        runner_path.write_text(yaml.safe_dump(summary, sort_keys=False), encoding="utf-8")
        print(f"[BLOCKED] {len(blocked)}/{len(campaign['inputs']['datasets'])} tables missing", flush=True)
        return summary

    print("[2/4] Loading tables and enforcing exhaustive row/group accounting", flush=True)
    results: list[dict[str, Any]] = []
    for index, (dataset, path) in enumerate(verified, start=1):
        print(f"      [{index}/{len(verified)}] {dataset['functional_class']}: {path.name}", flush=True)
        results.append(fit_dataset(pd.read_parquet(path), dataset))
    print("[3/4] Checking leave-one-animal-out fold and candidate accounting", flush=True)
    candidate_total = sum(len(item["candidates"]) for item in results)
    fold_total = sum(
        candidate["aggregate"]["folds_total"]
        for item in results
        for candidate in item["candidates"]
    )
    fold_blocked = sum(
        candidate["aggregate"]["folds_blocked"]
        for item in results
        for candidate in item["candidates"]
    )
    semantic = {
        "campaign_sha256": campaign_hash,
        "datasets_expected": len(results),
        "datasets_verified": len(results),
        "candidate_paths": candidate_total,
        "folds_total": fold_total,
        "folds_blocked": fold_blocked,
        "rows_retained": sum(item["accounting"]["rows_retained"] for item in results),
        "candidate_winner_selected": False,
        "parameter_values_promoted": 0,
        "native_representation_selected": False,
        "behavior_targets_exposed": 0,
        "topology_changes": 0,
    }
    status = "completed_candidate_ensemble_unpromoted" if fold_blocked == 0 else "completed_with_blocked_folds"
    summary = {
        "schema_version": 1,
        "id": "runner_result.feco_calcium_held_out_fit.v0",
        "generated_at": datetime.now(UTC).isoformat(),
        "campaign_id": campaign["id"],
        "campaign_sha256": campaign_hash,
        "status": status,
        "semantic_result_sha256": _canonical_hash({"accounting": semantic, "results": results}),
        "accounting": semantic,
        "results": results,
        "interpretation": {
            "biological_fit_completed": fold_blocked == 0,
            "candidate_winner_selected": False,
            "native_representation_selected": False,
            "calcium_is_native_spiking_evidence": False,
            "claim": "local source-path residual comparison only",
        },
    }
    print("[4/4] Writing compact lineage and ignored detailed result", flush=True)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    runner_path.parent.mkdir(parents=True, exist_ok=True)
    runner_path.write_text(yaml.safe_dump(summary, sort_keys=False), encoding="utf-8")
    print(f"[DONE] {candidate_total} candidates, {fold_total} folds, {fold_blocked} blocked", flush=True)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        result = run()
    except (FeCOCalciumFitError, OSError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr, flush=True)
        return 1
    return 2 if result["status"] == "blocked_missing_authenticated_tables" else 0


if __name__ == "__main__":
    raise SystemExit(main())

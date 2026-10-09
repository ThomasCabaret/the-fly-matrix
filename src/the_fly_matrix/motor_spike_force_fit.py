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

from .ledger import ROOT


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "motor-spike-force-pilot-fit-v0.yaml"
RUNNER_PATH = ROOT / "calibration" / "runner" / "motor-spike-force-pilot-fit-v0.yaml"
OUTPUT_ROOT = ROOT / "data" / "derived" / "calibration" / "motor-spike-force-pilot-fit-v0"


class MotorSpikeForceFitError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedClass:
    functional_class: str
    fit_status: str
    frame: pd.DataFrame
    accounting: Mapping[str, int]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = yaml.safe_load(path.read_text(encoding="utf-8"))
    if campaign.get("primary_class") != "local_interface":
        raise MotorSpikeForceFitError("campaign must remain local_interface")
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise MotorSpikeForceFitError("pilot must remain diagnostic_only")
    if campaign.get("behavior_targets") != []:
        raise MotorSpikeForceFitError("motor pilot may not expose behavior targets")
    if campaign.get("topology_changes_allowed") is not False:
        raise MotorSpikeForceFitError("motor pilot may not change topology")
    if campaign["selection_policy"].get("promote_values") is not False:
        raise MotorSpikeForceFitError("one-cell pilot may not promote values")
    return campaign


def _required_columns(campaign: Mapping[str, Any]) -> set[str]:
    return set(campaign["normalized_table_contract"]["required_columns"])


def prepare_class(
    frame: pd.DataFrame,
    functional_class: str,
    campaign: Mapping[str, Any],
) -> PreparedClass:
    missing = sorted(_required_columns(campaign) - set(frame.columns))
    if missing:
        raise MotorSpikeForceFitError(f"normalized table is missing columns: {missing}")
    expected = set(campaign["fit"]["class_policies"])
    if functional_class not in expected:
        raise MotorSpikeForceFitError(f"unexpected functional class: {functional_class}")
    classes = set(frame["functional_class"].dropna().astype(str).unique())
    if classes != {functional_class}:
        raise MotorSpikeForceFitError(
            f"table class accounting differs for {functional_class}: {sorted(classes)}"
        )
    if frame.empty:
        raise MotorSpikeForceFitError(f"empty normalized table for {functional_class}")
    if frame["cell_id"].astype(str).nunique() != 1:
        raise MotorSpikeForceFitError("v0 pilot requires exactly one declared cell per class")
    if frame["trial_id"].astype(str).duplicated().any():
        raise MotorSpikeForceFitError("trial_id values must be unique within a pilot class")

    numeric = (
        "peak_displacement_um",
        "peak_error_source_unit",
        "probe_position_source_value",
        "num_spikes",
        "firing_rate_hz",
        "rest_rate_hz",
        "step_index",
    )
    local = frame.copy()
    for column in numeric:
        local[column] = pd.to_numeric(local[column], errors="coerce")
    finite_peak = np.isfinite(local["peak_displacement_um"].to_numpy(dtype=float))
    finite_error = np.isfinite(local["peak_error_source_unit"].to_numpy(dtype=float))
    finite_position = np.isfinite(local["probe_position_source_value"].to_numpy(dtype=float))
    base = finite_peak & finite_error & finite_position

    if functional_class in {"fast_81A07", "intermediate_22A08"}:
        finite_spikes = np.isfinite(local["num_spikes"].to_numpy(dtype=float))
        selected = (
            base
            & finite_spikes
            & (local["num_spikes"].to_numpy(dtype=float) >= 0)
            & (local["num_spikes"].to_numpy(dtype=float) <= 30)
            & (local["peak_error_source_unit"].to_numpy(dtype=float) > 0)
            & (local["probe_position_source_value"].to_numpy(dtype=float) == 0)
        )
        x = local.loc[selected, "num_spikes"].to_numpy(dtype=float)
        fit_status = "derived_line_through_origin_diagnostic_extension"
    else:
        finite_rates = np.isfinite(
            local[["firing_rate_hz", "rest_rate_hz", "step_index"]].to_numpy(dtype=float)
        ).all(axis=1)
        selected = base & finite_rates & (local["step_index"].to_numpy(dtype=float) > 13)
        x_all = (
            local["firing_rate_hz"].to_numpy(dtype=float)
            - local["rest_rate_hz"].to_numpy(dtype=float)
        ) * float(campaign["fit"]["slow_stimulus_duration_s"])
        if np.any(x_all[selected] < 0):
            raise MotorSpikeForceFitError("selected slow rows contain a negative spike-count proxy")
        x = x_all[selected]
        fit_status = "source_reproduction_line_through_origin"

    retained = local.loc[selected].copy()
    retained["spike_count_for_fit"] = x
    retained["peak_force_uN"] = retained["peak_displacement_um"].to_numpy(dtype=float) * float(
        campaign["fit"]["force_probe_spring_constant_N_per_m"]
    )
    if len(retained) < 2 or not np.any(x > 0):
        raise MotorSpikeForceFitError(
            f"{functional_class} has insufficient selected rows for a diagnostic fit"
        )
    if not np.isfinite(retained["peak_force_uN"].to_numpy(dtype=float)).all():
        raise MotorSpikeForceFitError("non-finite force after declared unit conversion")
    accounting = {
        "rows_total": int(len(local)),
        "rows_retained": int(selected.sum()),
        "rows_excluded": int((~selected).sum()),
        "cells_total": int(local["cell_id"].astype(str).nunique()),
        "aggregate_groups_total": int(local["trial_id"].astype(str).nunique()),
    }
    return PreparedClass(functional_class, fit_status, retained.reset_index(drop=True), accounting)


def fit_line_through_origin(x: np.ndarray, y: np.ndarray) -> float:
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if x.shape != y.shape or x.ndim != 1:
        raise MotorSpikeForceFitError("fit vectors must be equal one-dimensional arrays")
    denominator = float(x @ x)
    if denominator <= 0 or not np.isfinite(denominator):
        raise MotorSpikeForceFitError("line-through-origin fit has no positive information")
    slope = float((x @ y) / denominator)
    if not np.isfinite(slope):
        raise MotorSpikeForceFitError("line-through-origin slope is non-finite")
    return slope


def fit_prepared(
    prepared: PreparedClass,
    campaign: Mapping[str, Any],
) -> dict[str, Any]:
    x = prepared.frame["spike_count_for_fit"].to_numpy(dtype=np.float64)
    y = prepared.frame["peak_force_uN"].to_numpy(dtype=np.float64)
    slope = fit_line_through_origin(x, y)
    prediction = slope * x
    residual = y - prediction
    seed = int(campaign["uncertainty"]["bootstrap_seed"])
    draws = int(campaign["uncertainty"]["bootstrap_draws"])
    rng = np.random.default_rng(seed)
    bootstrap = np.empty(draws, dtype=np.float64)
    # Zero-spike trials constrain the residual/intercept diagnosis but contain
    # no information about a slope forced through the origin.  Excluding them
    # from resampling also prevents an all-zero bootstrap draw.
    informative = x > 0
    bootstrap_x = x[informative]
    bootstrap_y = y[informative]
    for draw in range(draws):
        indices = rng.integers(0, len(bootstrap_x), len(bootstrap_x))
        bootstrap[draw] = fit_line_through_origin(
            bootstrap_x[indices], bootstrap_y[indices]
        )
    return {
        "functional_class": prepared.functional_class,
        "fit_status": prepared.fit_status,
        "accounting": dict(prepared.accounting),
        "slope_uN_per_spike": slope,
        "metrics": {
            "rmse_uN": float(np.sqrt(np.mean(residual**2))),
            "mae_uN": float(np.mean(np.abs(residual))),
        },
        "aggregate_row_bootstrap": {
            "draws": draws,
            "seed": seed,
            "informative_positive_spike_rows": int(informative.sum()),
            "percentile_2_5_uN_per_spike": float(np.percentile(bootstrap, 2.5)),
            "median_uN_per_spike": float(np.percentile(bootstrap, 50.0)),
            "percentile_97_5_uN_per_spike": float(np.percentile(bootstrap, 97.5)),
            "interpretation": "within_one_cell_aggregate_row_resampling_not_trial_or_population_uncertainty",
        },
        "promoted_parameter_values": 0,
    }


def _load_manifest(campaign: Mapping[str, Any]) -> tuple[dict[str, Any], Path] | None:
    path = ROOT / str(campaign["inputs"]["normalized_manifest"])
    if not path.is_file():
        return None
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not manifest.get("parser_id") or manifest.get("parser_id") == "pending":
        raise MotorSpikeForceFitError("normalized manifest lacks a versioned parser_id")
    expected_archives = {
        str(item["functional_class"]): str(item["sha256"])
        for item in campaign["inputs"]["source_archives"]
    }
    observed_archives = {
        str(item["functional_class"]): str(item["sha256"])
        for item in manifest.get("source_archives", [])
    }
    if observed_archives != expected_archives:
        raise MotorSpikeForceFitError("normalized manifest archive hashes differ from campaign")
    return manifest, path


def run(
    campaign_path: Path = CAMPAIGN_PATH,
    runner_path: Path = RUNNER_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    campaign = load_campaign(campaign_path)
    campaign_hash = _sha256(campaign_path)
    print("[1/4] Checking for a versioned raw-to-normalized parser manifest", flush=True)
    loaded = _load_manifest(campaign)
    if loaded is None:
        accounting = {
            "campaign_sha256": campaign_hash,
            "source_archives_expected": 3,
            "normalized_tables_verified": 0,
            "class_fits_completed": 0,
            "parameter_values_promoted": 0,
            "body_class_assignments_selected": 0,
            "behavior_targets_exposed": 0,
            "topology_changes": 0,
        }
        summary = {
            "schema_version": 1,
            "id": "runner_result.motor_spike_force_pilot_fit.v0",
            "generated_at": datetime.now(UTC).isoformat(),
            "campaign_id": campaign["id"],
            "status": "blocked_missing_versioned_parser_manifest",
            "semantic_result_sha256": _canonical_hash(accounting),
            "accounting": accounting,
            "interpretation": {
                "fit_completed": False,
                "twitch_kernel_identified": False,
                "population_parameters_identified": False,
                "next_action": "acquire_and_inventory_archives_then_version_raw_parser",
            },
        }
        runner_path.parent.mkdir(parents=True, exist_ok=True)
        runner_path.write_text(yaml.safe_dump(summary, sort_keys=False), encoding="utf-8")
        print("[BLOCKED] exact archives and versioned raw-variable parser are absent", flush=True)
        return summary

    manifest, manifest_path = loaded
    print("[2/4] Verifying normalized tables and exhaustive class accounting", flush=True)
    expected_classes = set(campaign["fit"]["class_policies"])
    table_items = manifest.get("tables", [])
    observed_classes = {str(item["functional_class"]) for item in table_items}
    if observed_classes != expected_classes or len(table_items) != len(expected_classes):
        raise MotorSpikeForceFitError("normalized manifest must contain exactly one table per class")
    prepared: list[PreparedClass] = []
    for item in table_items:
        path = ROOT / str(item["path"])
        if not path.is_file() or _sha256(path) != str(item["sha256"]):
            raise MotorSpikeForceFitError(f"normalized table missing or hash drifted: {path}")
        prepared.append(prepare_class(pd.read_parquet(path), str(item["functional_class"]), campaign))

    print("[3/4] Fitting three diagnostic line-through-origin candidates", flush=True)
    results = [fit_prepared(item, campaign) for item in prepared]
    accounting = {
        "campaign_sha256": campaign_hash,
        "normalized_manifest_sha256": _sha256(manifest_path),
        "source_archives_expected": 3,
        "normalized_tables_verified": len(results),
        "class_fits_completed": len(results),
        "source_reproduction_fits": sum(
            item["fit_status"] == "source_reproduction_line_through_origin" for item in results
        ),
        "derived_diagnostic_fits": sum(
            item["fit_status"] == "derived_line_through_origin_diagnostic_extension" for item in results
        ),
        "parameter_values_promoted": 0,
        "body_class_assignments_selected": 0,
        "behavior_targets_exposed": 0,
        "topology_changes": 0,
    }
    summary = {
        "schema_version": 1,
        "id": "runner_result.motor_spike_force_pilot_fit.v0",
        "generated_at": datetime.now(UTC).isoformat(),
        "campaign_id": campaign["id"],
        "status": "completed_diagnostic_one_cell_per_class_unpromoted",
        "semantic_result_sha256": _canonical_hash({"accounting": accounting, "results": results}),
        "accounting": accounting,
        "results": results,
        "interpretation": {
            "fit_completed": True,
            "twitch_kernel_identified": False,
            "population_parameters_identified": False,
            "class_ordering_is_body_crosswalk": False,
            "claim": "one-cell-per-class aggregate force-per-spike diagnostic only",
        },
    }
    print("[4/4] Writing compact lineage and ignored detailed result", flush=True)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    runner_path.parent.mkdir(parents=True, exist_ok=True)
    runner_path.write_text(yaml.safe_dump(summary, sort_keys=False), encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        result = run()
    except (MotorSpikeForceFitError, OSError, KeyError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr, flush=True)
        return 1
    if result["status"].startswith("blocked_"):
        return 2
    print("[DONE] Diagnostic aggregate fits complete; zero values promoted.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import sys
import zipfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml
from scipy.integrate import cumulative_trapezoid
from scipy.io import loadmat

from .ledger import ROOT


PARSER_ID = "parser.motor_spike_force.source_port.v0"
PARSER_CONTRACT = ROOT / "calibration" / "evidence" / "motor-spike-force-parser-v0.yaml"
INVENTORY_CAMPAIGN = ROOT / "calibration" / "campaigns" / "motor-spike-force-pilot-inventory-v0.yaml"
OUTPUT_ROOT = ROOT / "data" / "derived" / "calibration" / "motor-spike-force-normalized-v0"
RUNNER_PATH = ROOT / "calibration" / "runner" / "motor-spike-force-parser-v0.yaml"


class MotorSpikeForceParserError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _moving_mean(values: np.ndarray, span: int = 5) -> np.ndarray:
    """Port the unweighted moving-average branch of MATLAB smooth."""
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    if span <= 1 or len(values) <= 1:
        return values.copy()
    span = min(int(span), len(values))
    if span % 2 == 0:
        span -= 1
    half = span // 2
    result = np.empty_like(values)
    for index in range(len(values)):
        distance = min(index, len(values) - 1 - index, half)
        local_half = distance
        window = values[index - local_half : index + local_half + 1]
        result[index] = float(np.nanmean(window)) if np.isfinite(window).any() else np.nan
    return result


def _lowess_with_missing(values: np.ndarray, span: int = 5) -> np.ndarray:
    """Local-linear LOWESS used by MATLAB smooth when y contains NaNs."""
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    x = np.arange(len(values), dtype=np.float64)
    finite = np.isfinite(values)
    if finite.sum() < 2:
        raise MotorSpikeForceParserError("LOWESS requires at least two finite samples")
    source_x = x[finite]
    source_y = values[finite]
    count = min(max(2, int(span)), len(source_x))
    result = np.empty_like(values)
    for index, target in enumerate(x):
        order = np.argsort(np.abs(source_x - target), kind="stable")[:count]
        local_x = source_x[order]
        local_y = source_y[order]
        distance = np.abs(local_x - target)
        radius = float(np.max(distance))
        if radius == 0:
            result[index] = float(local_y[distance.argmin()])
            continue
        weights = (1.0 - (distance / radius) ** 3) ** 3
        # The farthest sample has zero tricube weight. Degenerate edge cases
        # fall back to the finite local mean instead of silently emitting NaN.
        design = np.column_stack((np.ones(len(local_x)), local_x - target))
        weighted = design * np.sqrt(weights)[:, None]
        response = local_y * np.sqrt(weights)
        if np.count_nonzero(weights) < 2:
            result[index] = float(np.mean(local_y))
        else:
            coefficients, *_ = np.linalg.lstsq(weighted, response, rcond=None)
            result[index] = float(coefficients[0])
    return result


def matlab_smooth(values: np.ndarray, span: int = 5) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    if np.isnan(values).any():
        return _lowess_with_missing(values, span)
    return _moving_mean(values, span)


def make_input_time(params: Mapping[str, Any]) -> np.ndarray:
    count = int(round(float(params["durSweep"]) * float(params["sampratein"])))
    time = np.arange(count, dtype=np.float64) / float(params["sampratein"])
    if "preDurInSec" in params:
        time -= float(params["preDurInSec"])
    return time


def make_frame_time(trial: Mapping[str, Any]) -> np.ndarray:
    """Port makeFrameTime/postHocExposure for these exact camera archives."""
    time = make_input_time(trial["params"])
    exposure = np.asarray(trial["exposure"]).reshape(-1).astype(bool)
    if len(exposure) != len(time):
        raise MotorSpikeForceParserError("exposure and input-time lengths differ")
    falling = np.flatnonzero(exposure[:-1] & ~exposure[1:])
    if len(falling) < 2:
        raise MotorSpikeForceParserError("cannot recover camera falling edges")
    frame_interval = int(np.bincount(np.diff(falling)).argmax())
    gaps = np.diff(falling)
    repaired = set(int(index) for index in falling)
    for index, gap in zip(falling[:-1], gaps, strict=True):
        if 1.95 * frame_interval < gap < 2.05 * frame_interval:
            repaired.add(int(index + frame_interval))
    frame_indices = np.asarray(sorted(repaired), dtype=np.int64)
    frame_count = len(np.asarray(trial["forceProbeStuff"]["CoM"]).reshape(-1))
    if len(frame_indices) < frame_count:
        raise MotorSpikeForceParserError(
            f"only {len(frame_indices)} camera exposures for {frame_count} force frames"
        )
    return time[frame_indices[:frame_count]]


def firing_rate(time: np.ndarray, spike_matrix: np.ndarray, dt: float) -> np.ndarray:
    """Port the published firingRate helper used by the slow-unit table."""
    matrix = np.asarray(spike_matrix, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] != len(time):
        raise MotorSpikeForceParserError("spike matrix must be time by trial")
    good = ~np.isnan(matrix[0])
    if not good.any():
        raise MotorSpikeForceParserError("firing-rate group contains no usable trials")
    spikes = np.nansum(matrix[:, good], axis=1) / int(good.sum())
    wind = int(np.sum(time <= time[0] + dt))
    backward = int(round(wind * 7 / 8))
    forward = int(round(wind * 1 / 8))
    summed = np.empty_like(spikes)
    cumulative = np.concatenate(([0.0], np.cumsum(spikes)))
    for index in range(len(spikes)):
        lo = max(0, index - backward)
        hi = min(len(spikes), index + forward + 1)
        summed[index] = cumulative[hi] - cumulative[lo]
    return matlab_smooth(summed / dt, max(1, int(round(wind / 4))))


def _spike_indices(trial: Mapping[str, Any]) -> np.ndarray:
    raw = np.asarray(trial.get("spikes", []), dtype=np.int64).reshape(-1)
    if raw.size == 1 and int(raw[0]) == 0:
        return np.asarray([], dtype=np.int64)
    # MATLAB stores one-based sample indices.
    result = raw - 1
    if np.any(result < 0):
        raise MotorSpikeForceParserError("negative spike index after MATLAB conversion")
    return result


def _position_from_tags(tags: Any, allowed: set[float]) -> float:
    if tags is None or (isinstance(tags, np.ndarray) and tags.size == 0):
        return 0.0
    if isinstance(tags, str):
        candidates: Iterable[Any] = [tags]
    else:
        candidates = np.asarray(tags, dtype=object).reshape(-1).tolist()
    selected: list[float] = []
    for value in candidates:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return math.nan
        if number in allowed:
            selected.append(number)
        else:
            return math.nan
    nonzero = {value for value in selected if value != 0}
    if len(nonzero) > 1:
        raise MotorSpikeForceParserError(f"conflicting probe-position tags: {selected}")
    return next(iter(nonzero), 0.0)


def _load_member(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    wanted = [
        "excluded",
        "exposure",
        "forceProbeStuff",
        "params",
        "spikes",
        "tags",
        "voltage_1",
    ]
    return loadmat(io.BytesIO(archive.read(name)), variable_names=wanted, simplify_cells=True)


def _trial_members(archive: zipfile.ZipFile, stem: str) -> dict[int, str]:
    result: dict[int, str] = {}
    for name in archive.namelist():
        filename = PurePosixPath(name).name
        if filename.startswith(stem) and filename.lower().endswith(".mat"):
            trial = int(PurePosixPath(filename).stem.rsplit("_", 1)[1])
            if trial in result:
                raise MotorSpikeForceParserError(f"duplicate raw trial {trial} in archive")
            result[trial] = name
    return result


def _nan_sem(values: np.ndarray) -> float:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if len(finite) < 2:
        return math.nan
    return float(np.std(finite, ddof=1) / np.sqrt(len(finite)))


def _parse_fast_or_intermediate(
    archive_path: Path, spec: Mapping[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    stem = f"{spec['protocol']}_Raw_{spec['cell_id']}_"
    records: list[dict[str, Any]] = []
    excluded = 0
    with zipfile.ZipFile(archive_path) as archive:
        members = _trial_members(archive, stem)
        for offset, trial_number in enumerate(range(int(spec["trial_first"]), int(spec["trial_last"]) + 1), start=1):
            if trial_number not in members:
                raise MotorSpikeForceParserError(f"missing declared trial {trial_number} in {archive_path.name}")
            trial = _load_member(archive, members[trial_number])
            if bool(trial.get("excluded", False)):
                excluded += 1
                continue
            params = trial["params"]
            if str(params["protocol"]) != str(spec["protocol"]):
                raise MotorSpikeForceParserError("protocol drift in selected trial")
            spikes = _spike_indices(trial)
            time = make_input_time(params)
            if len(spikes) and int(spikes.max()) >= len(time):
                raise MotorSpikeForceParserError("spike index exceeds input time")
            frame_time = make_frame_time(trial)
            twitch = np.asarray(trial["forceProbeStuff"]["CoM"], dtype=np.float64).reshape(-1)
            if len(spikes) == 0:
                aligned = frame_time - float(params["stimDurInSec"])
                before = np.flatnonzero(aligned < 0)
                if not len(before):
                    raise MotorSpikeForceParserError("no pre-stimulus force frame")
                twitch = twitch - twitch[before[-1]]
                window = (aligned > 0) & (aligned < 0.07)
                peak = float(np.nanmean(twitch[window]))
            else:
                aligned = frame_time - time[int(spikes[0])]
                before = np.flatnonzero(aligned < 0)
                if not len(before):
                    raise MotorSpikeForceParserError("no pre-spike force frame")
                twitch = twitch - twitch[before[-1]]
                window = (aligned > 0) & (aligned < 0.3)
                peak = float(np.nanmax(twitch[window]))
                if str(spec["functional_class"]) == "fast_81A07" and peak < 10:
                    peak = math.nan
            position = _position_from_tags(trial.get("tags"), set(float(x) for x in spec["positions"]))
            records.append(
                {
                    "trial": trial_number,
                    "position": position,
                    "num_spikes": int(len(spikes)),
                    "peak": peak,
                }
            )
            if offset % 25 == 0:
                print(f"        {spec['functional_class']}: {offset}/{spec['trial_count']} trials", flush=True)
    raw = pd.DataFrame(records)
    rows: list[dict[str, Any]] = []
    for (position, num_spikes), group in raw.groupby(["position", "num_spikes"], dropna=False):
        peaks = group["peak"].to_numpy(dtype=float)
        rows.append(
            {
                "cell_id": spec["cell_id"],
                "trial_id": ",".join(str(value) for value in group["trial"].tolist()),
                "functional_class": spec["functional_class"],
                "peak_displacement_um": float(np.nanmean(peaks)) if np.isfinite(peaks).any() else math.nan,
                "peak_error_source_unit": _nan_sem(peaks),
                "probe_position_source_value": float(position),
                "num_spikes": int(num_spikes),
                "firing_rate_hz": math.nan,
                "rest_rate_hz": math.nan,
                "step_index": math.nan,
            }
        )
    accounting = {
        "declared_trials": int(spec["trial_count"]),
        "excluded_trials": excluded,
        "usable_trials": len(records),
        "aggregated_rows": len(rows),
    }
    return pd.DataFrame(rows), accounting


def _parse_slow(archive_path: Path, spec: Mapping[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    stem = f"{spec['protocol']}_Raw_{spec['cell_id']}_"
    grouped: dict[float, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    excluded = 0
    with zipfile.ZipFile(archive_path) as archive:
        members = _trial_members(archive, stem)
        for trial_number in range(int(spec["trial_first"]), int(spec["trial_last"]) + 1):
            if trial_number not in members:
                raise MotorSpikeForceParserError(f"missing declared trial {trial_number} in {archive_path.name}")
            trial = _load_member(archive, members[trial_number])
            if bool(trial.get("excluded", False)):
                excluded += 1
                continue
            step = float(trial["params"]["step"])
            grouped[step].append((trial_number, trial))

    rows: list[dict[str, Any]] = []
    for step in sorted(grouped):
        trials = grouped[step]
        first = trials[0][1]
        params = first["params"]
        minimum_duration = min(float(trial["params"]["durSweep"]) for _, trial in trials)
        length = int(round(minimum_duration * float(params["sampratein"])))
        time = np.arange(length, dtype=np.float64) / float(params["sampratein"])
        time -= float(params["preDurInSec"])
        frame_time = make_frame_time(first)
        voltage = np.full((length, len(trials)), np.nan, dtype=np.float64)
        spike_matrix = np.full((length, len(trials)), np.nan, dtype=np.float64)
        probe = np.full((len(frame_time), len(trials)), np.nan, dtype=np.float64)
        for column, (_, trial) in enumerate(trials):
            v = np.asarray(trial["voltage_1"], dtype=np.float64).reshape(-1)
            voltage[:, column] = v[:length]
            spike_matrix[:, column] = 0.0
            spikes = _spike_indices(trial)
            spikes = spikes[spikes < length]
            spike_matrix[spikes, column] = 1.0
            trace = np.asarray(trial["forceProbeStuff"]["CoM"], dtype=np.float64).reshape(-1)
            probe[: min(len(trace), len(frame_time)), column] = trace[: len(frame_time)]
        mean_voltage = np.nanmean(voltage, axis=1)
        rate = firing_rate(time, spike_matrix, 10 / 300)
        finite_probe = np.isfinite(probe)
        probe_counts = finite_probe.sum(axis=1)
        probe_sums = np.nansum(probe, axis=1)
        mean_probe = np.divide(
            probe_sums,
            probe_counts,
            out=np.full(len(probe), np.nan, dtype=np.float64),
            where=probe_counts > 0,
        )
        mean_probe = matlab_smooth(mean_probe, 5)
        baseline_window = (frame_time < 0) & (frame_time > -0.2)
        mean_probe -= float(np.nanmean(mean_probe[baseline_window]))
        area = cumulative_trapezoid(mean_probe, frame_time, initial=0.0)
        before_zero = np.flatnonzero(frame_time <= 0)
        area -= area[before_zero[-1]]
        sign_index = np.flatnonzero(frame_time <= float(params["stimDurInSec"]) - 0.05)[-1]
        peak_window = (frame_time > 0) & (frame_time < float(params["stimDurInSec"]))
        candidates = np.flatnonzero(peak_window)
        if area[sign_index] >= 0:
            peak_index = candidates[int(np.nanargmax(mean_probe[peak_window]))]
        else:
            peak_index = candidates[int(np.nanargmin(mean_probe[peak_window]))]
        time_window = time > -float(params["preDurInSec"]) + 0.06
        rest = float(np.mean(rate[time_window & (time < 0)]))
        stimulus = (time > 0) & (time < float(params["stimDurInSec"]))
        if step < 0:
            active_rate = float(np.mean(rate[time_window & stimulus]))
        else:
            threshold = float(np.quantile(rate[stimulus], 0.5))
            active_rate = float(np.mean(rate[stimulus & (rate >= threshold)]))
        rows.append(
            {
                "cell_id": spec["cell_id"],
                "trial_id": ",".join(str(number) for number, _ in trials),
                "functional_class": spec["functional_class"],
                "peak_displacement_um": float(mean_probe[peak_index]),
                "peak_error_source_unit": 1.0,
                "probe_position_source_value": 0.0,
                "num_spikes": math.nan,
                "firing_rate_hz": active_rate,
                "rest_rate_hz": rest,
                # Historical name retained by the preregistered normalized contract;
                # the source value is the injected current step, not an ordinal index.
                "step_index": step,
            }
        )
    accounting = {
        "declared_trials": int(spec["trial_count"]),
        "excluded_trials": excluded,
        "usable_trials": sum(len(values) for values in grouped.values()),
        "aggregated_rows": len(rows),
    }
    return pd.DataFrame(rows), accounting


def run(
    contract_path: Path = PARSER_CONTRACT,
    inventory_campaign_path: Path = INVENTORY_CAMPAIGN,
    output_root: Path = OUTPUT_ROOT,
    runner_path: Path = RUNNER_PATH,
) -> dict[str, Any]:
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    inventory = yaml.safe_load(inventory_campaign_path.read_text(encoding="utf-8"))
    if contract.get("id") != PARSER_ID:
        raise MotorSpikeForceParserError("unexpected parser contract id")
    if contract.get("behavior_targets") != [] or contract.get("topology_changes_allowed") is not False:
        raise MotorSpikeForceParserError("parser contract may expose neither behavior nor topology changes")
    archive_items = {item["functional_class"]: item for item in inventory["inputs"]["archives"]}
    specs = contract["class_specs"]
    if set(specs) != set(archive_items):
        raise MotorSpikeForceParserError("parser class accounting differs from archive campaign")

    print("[1/4] Verifying exact source archives and parser provenance", flush=True)
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_archives: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    accounting: dict[str, Any] = {}
    for index, functional_class in enumerate(sorted(specs), start=1):
        item = archive_items[functional_class]
        path = ROOT / str(item["path"])
        if not path.is_file() or path.stat().st_size != int(item["expected_bytes"]):
            raise MotorSpikeForceParserError(f"missing or size-drifted archive: {path}")
        digest = _sha256(path)
        if digest != str(item["sha256"]):
            raise MotorSpikeForceParserError(f"archive hash drift: {path}")
        manifest_archives.append({"functional_class": functional_class, "path": item["path"], "sha256": digest})
        print(f"[2/4] [{index}/3] Porting published transforms for {functional_class}", flush=True)
        if functional_class == "slow_35C09":
            frame, local = _parse_slow(path, specs[functional_class])
        else:
            frame, local = _parse_fast_or_intermediate(path, specs[functional_class])
        table_path = output_root / f"{functional_class}.parquet"
        frame.to_parquet(table_path, index=False)
        tables.append(
            {
                "functional_class": functional_class,
                "path": str(table_path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": _sha256(table_path),
                "rows": len(frame),
            }
        )
        accounting[functional_class] = local

    print("[3/4] Writing hash-locked normalized manifest", flush=True)
    manifest = {
        "schema_version": 1,
        "parser_id": PARSER_ID,
        "parser_contract_sha256": _sha256(contract_path),
        "source_archives": manifest_archives,
        "tables": tables,
        "accounting": accounting,
        "scientific_boundary": {
            "source_transform_ported": True,
            "temporal_twitch_kernel_identified": False,
            "body_class_crosswalk_selected": False,
            "parameter_values_promoted": 0,
            "behavior_targets_exposed": 0,
            "topology_changes": 0,
        },
    }
    manifest_path = output_root / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    summary_accounting = {
        "archives_verified": len(manifest_archives),
        "classes_normalized": len(tables),
        "declared_trials": sum(value["declared_trials"] for value in accounting.values()),
        "excluded_trials": sum(value["excluded_trials"] for value in accounting.values()),
        "normalized_rows": sum(item["rows"] for item in tables),
        "parameter_values_promoted": 0,
        "body_class_assignments_selected": 0,
        "behavior_targets_exposed": 0,
        "topology_changes": 0,
    }
    summary = {
        "schema_version": 1,
        "id": "runner_result.motor_spike_force_parser.v0",
        "generated_at": datetime.now(UTC).isoformat(),
        "parser_id": PARSER_ID,
        "status": "completed_source_transform_port_zero_values_promoted",
        "semantic_result_sha256": _canonical_hash({"accounting": summary_accounting, "tables": tables}),
        "accounting": summary_accounting,
        "manifest_ref": str(manifest_path.relative_to(ROOT)).replace("\\", "/"),
        "interpretation": {
            "aggregate_source_tables_reconstructible": True,
            "twitch_kernel_identified": False,
            "population_parameters_identified": False,
            "next_action": "run_unpromoted_aggregate_fit_and_compare_ordering_to_article_constraints",
        },
    }
    runner_path.parent.mkdir(parents=True, exist_ok=True)
    runner_path.write_text(yaml.safe_dump(summary, sort_keys=False), encoding="utf-8")
    print("[4/4] Parser complete; no parameter or body-class assignment promoted", flush=True)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        result = run()
    except (MotorSpikeForceParserError, OSError, KeyError, ValueError, zipfile.BadZipFile) as error:
        print(f"[ERROR] {error}", file=sys.stderr, flush=True)
        return 1
    print(f"[DONE] {result['accounting']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

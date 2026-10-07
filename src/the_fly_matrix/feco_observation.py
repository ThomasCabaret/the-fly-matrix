from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Mapping

import numpy as np
import yaml

from .ledger import ROOT


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "feco-calcium-observation-source-v0.yaml"
RUNNER_PATH = ROOT / "calibration" / "runner" / "feco-calcium-observation-source-v0.yaml"
OUTPUT_ROOT = ROOT / "data" / "derived" / "calibration" / "feco-calcium-observation-source-v0"

CLAW_SOURCE_COEFFICIENTS = np.asarray(
    [
        -4.28350195279596e-09,
        -3.08701145496934e-07,
        0.000123726627502515,
        0.000474757347677466,
        -0.0357758464550021,
    ],
    dtype=np.float64,
)


class FeCOObservationError(ValueError):
    """Raised when a source observation contract is underspecified or drifts."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _vector(name: str, values: np.ndarray) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64)
    if result.ndim != 1 or not np.isfinite(result).all() or len(result) < 2:
        raise FeCOObservationError(f"{name} must be a finite vector with at least two samples")
    return result


def gcamp_kernel(
    samples: int,
    sampling_hz: float,
    *,
    tau_on_s: float = 0.03,
    tau_off_s: float = 0.30,
) -> np.ndarray:
    """Reproduce the source code's normalized causal GCaMP observation kernel."""

    if samples < 2 or not np.isfinite(sampling_hz) or sampling_hz <= 0:
        raise FeCOObservationError("samples and sampling_hz must be positive")
    if not (0 < tau_on_s < tau_off_s):
        raise FeCOObservationError("the source kernel requires 0 < tau_on_s < tau_off_s")
    time = np.linspace(0.0, samples / sampling_hz, samples)
    kernel = np.exp(-time / tau_off_s) - np.exp(-time / tau_on_s)
    total = float(kernel.sum())
    if not np.isfinite(total) or total <= 0:
        raise FeCOObservationError("invalid GCaMP kernel normalization")
    return kernel / total


def _velocity(position_deg: np.ndarray, sampling_hz: float) -> np.ndarray:
    delta = np.diff(position_deg) * sampling_hz
    return np.concatenate(([delta[0]], delta))


def source_activation(
    position_deg: np.ndarray,
    *,
    sampling_hz: float,
    model_type: Literal["claw", "hook_flex", "club"],
    threshold_deg_s: float | None = None,
    claw_center_deg: float = 80.0,
    claw_coefficients: np.ndarray = CLAW_SOURCE_COEFFICIENTS,
) -> np.ndarray:
    """Translate the public MATLAB activation functions without choosing native units."""

    position = _vector("position_deg", position_deg)
    if not np.isfinite(sampling_hz) or sampling_hz <= 0:
        raise FeCOObservationError("sampling_hz must be finite and positive")
    if model_type == "claw":
        coefficients = np.asarray(claw_coefficients, dtype=np.float64)
        if coefficients.shape != (5,) or not np.isfinite(coefficients).all():
            raise FeCOObservationError("claw_coefficients must contain five finite values")
        return np.polyval(coefficients, position - float(claw_center_deg))
    if threshold_deg_s is None or not np.isfinite(threshold_deg_s):
        raise FeCOObservationError(f"{model_type} requires an explicit finite threshold_deg_s")
    velocity = _velocity(position, sampling_hz)
    if model_type == "hook_flex":
        return (velocity < threshold_deg_s).astype(np.float64)
    if model_type == "club":
        return (np.abs(velocity) > abs(threshold_deg_s)).astype(np.float64)
    raise FeCOObservationError(f"unsupported model_type {model_type!r}")


def predict_calcium(
    position_deg: np.ndarray,
    *,
    sampling_hz: float,
    model_type: Literal["claw", "hook_flex", "club"],
    threshold_deg_s: float | None = None,
    claw_center_deg: float = 80.0,
    pad_first_sample: int = 0,
) -> np.ndarray:
    """Apply activation then the separate GCaMP observation kernel."""

    position = _vector("position_deg", position_deg)
    if pad_first_sample < 0:
        raise FeCOObservationError("pad_first_sample cannot be negative")
    padded = np.pad(position, (pad_first_sample, 0), mode="edge")
    activation = source_activation(
        padded,
        sampling_hz=sampling_hz,
        model_type=model_type,
        threshold_deg_s=threshold_deg_s,
        claw_center_deg=claw_center_deg,
    )
    kernel = gcamp_kernel(len(padded), sampling_hz)
    predicted = np.convolve(activation, kernel, mode="full")[: len(padded)]
    return predicted[pad_first_sample:]


def _load_campaign(path: Path) -> dict[str, Any]:
    campaign = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(campaign, dict):
        raise FeCOObservationError("campaign must be a YAML mapping")
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise FeCOObservationError("source fidelity campaign must remain diagnostic_only")
    if campaign.get("behavior_targets") != []:
        raise FeCOObservationError("source fidelity campaign cannot expose behavior targets")
    if campaign.get("topology_changes_allowed") is not False:
        raise FeCOObservationError("source fidelity campaign cannot change topology")
    if campaign.get("capacity_policy", {}).get("optimized_parameters") != 0:
        raise FeCOObservationError("source fidelity campaign cannot optimize parameters")
    return campaign


def _verify_sources(campaign: Mapping[str, Any]) -> list[dict[str, str]]:
    verified: list[dict[str, str]] = []
    for item in campaign["inputs"]["source_files"]:
        path = ROOT / str(item["path"])
        actual = _sha256(path)
        expected = str(item["sha256"])
        if actual != expected:
            raise FeCOObservationError(f"source hash drift for {path}: {actual} != {expected}")
        verified.append({"path": str(item["path"]), "sha256": actual})
    return verified


def run(
    campaign_path: Path = CAMPAIGN_PATH,
    runner_path: Path = RUNNER_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    campaign = _load_campaign(campaign_path)
    print("[1/4] Verifying pinned public source files", flush=True)
    sources = _verify_sources(campaign)
    probe = campaign["structural_probe"]
    samples = int(probe["samples"])
    sampling_hz = float(probe["sampling_hz"])
    low, high = map(float, probe["fixture_position_range_degrees"])
    position = np.linspace(low, high, samples)

    print("[2/4] Reproducing causal normalized observation kernels", flush=True)
    kernel = gcamp_kernel(samples, sampling_hz)
    predictor_claw = predict_calcium(
        position, sampling_hz=sampling_hz, model_type="claw", claw_center_deg=80.0
    )
    fit_recipe_claw = predict_calcium(
        position,
        sampling_hz=sampling_hz,
        model_type="claw",
        claw_center_deg=90.0,
        pad_first_sample=1000,
    )

    print("[3/4] Exercising explicit hook and club threshold candidates", flush=True)
    thresholds = probe["source_recipe_thresholds_degrees_per_second"]
    hook = predict_calcium(
        position,
        sampling_hz=sampling_hz,
        model_type="hook_flex",
        threshold_deg_s=float(thresholds["hook_flexion"]),
    )
    club_position = 90.0 + 45.0 * np.sin(np.linspace(0.0, 8.0 * np.pi, samples))
    club = predict_calcium(
        club_position,
        sampling_hz=sampling_hz,
        model_type="club",
        threshold_deg_s=float(thresholds["club"]),
    )
    discrepancy = predictor_claw - fit_recipe_claw
    semantic_payload = {
        "source_hashes": sources,
        "samples": samples,
        "sampling_hz": sampling_hz,
        "kernel_sum": round(float(kernel.sum()), 15),
        "kernel_first": float(kernel[0]),
        "claw_paths_equal": bool(np.array_equal(predictor_claw, fit_recipe_claw)),
        "claw_path_max_abs_difference": float(np.max(np.abs(discrepancy))),
        "hook_nonzero_samples": int(np.count_nonzero(hook)),
        "club_nonzero_samples": int(np.count_nonzero(club)),
        "optimized_parameters": 0,
        "promoted_parameter_values": 0,
        "native_representation_selected": False,
        "behavior_targets_exposed": 0,
        "topology_changes": 0,
    }
    semantic_hash = _canonical_hash(semantic_payload)
    summary = {
        "schema_version": 1,
        "id": "runner_result.feco_calcium_observation_source.v0",
        "generated_at": datetime.now(UTC).isoformat(),
        "campaign_id": campaign["id"],
        "campaign_sha256": _sha256(campaign_path),
        "semantic_result_sha256": semantic_hash,
        "accounting": semantic_payload,
        "interpretation": {
            "status": "source_contract_pass_data_fit_blocked",
            "calcium_is_native_spiking_evidence": False,
            "calcium_is_cns_runtime_unit": False,
            "source_path_discrepancy_detected": True,
            "source_path_discrepancy_silently_reconciled": False,
            "next_blocker": "authenticated_Dryad_tables_not_present",
        },
    }
    print("[4/4] Writing immutable compact result and derived diagnostic arrays", flush=True)
    output_root.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_root / "probe_arrays.npz",
        position_deg=position,
        gcamp_kernel=kernel,
        predictor_claw=predictor_claw,
        fit_recipe_claw=fit_recipe_claw,
        hook=hook,
        club=club,
    )
    (output_root / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    runner_path.parent.mkdir(parents=True, exist_ok=True)
    runner_path.write_text(yaml.safe_dump(summary, sort_keys=False), encoding="utf-8")
    print(f"[PASS] source discrepancy retained; semantic hash {semantic_hash}", flush=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

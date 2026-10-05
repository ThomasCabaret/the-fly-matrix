from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import yaml
from scipy import sparse

from .ledger import ROOT
from .lif_gate import LifConstants
from .lif_source_fidelity import run_numpy_source_aligned


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "neural-model-class-temporal-probes-v1.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "neural-model-class-temporal-probes-v1.yaml"
RUN_ROOT = ROOT / "runs" / "calibration" / "neural-model-class-temporal-probes-v1"


class TemporalProbeError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_value(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def bin_events(events: Sequence[tuple[int, float]], channels: int, bin_ms: float, duration_ms: float) -> np.ndarray:
    bins = int(math.ceil(duration_ms / bin_ms))
    result = np.zeros((channels, bins), dtype=np.float64)
    for channel, time_ms in events:
        if not 0 <= channel < channels or not 0 <= time_ms < duration_ms:
            raise TemporalProbeError("Event lies outside the declared probe support")
        result[channel, int(time_ms // bin_ms)] += 1000.0 / bin_ms
    return result


def event_trace(events: Sequence[tuple[int, float]], channels: int, dt_ms: float, duration_ms: float, tau_ms: float = 5.0) -> np.ndarray:
    steps = int(round(duration_ms / dt_ms))
    trace = np.zeros((channels, steps), dtype=np.float64)
    decay = math.exp(-dt_ms / tau_ms)
    by_step: dict[int, list[int]] = {}
    for channel, time_ms in events:
        by_step.setdefault(int(round(time_ms / dt_ms)), []).append(channel)
    state = np.zeros(channels, dtype=np.float64)
    for step in range(steps):
        state *= decay
        for channel in by_step.get(step, []):
            state[channel] += 1.0
        trace[:, step] = state
    return trace


def collision_probe(first, second, channels: int, bin_ms: float, dt_ms: float, duration_ms: float) -> dict[str, Any]:
    rate_a = bin_events(first, channels, bin_ms, duration_ms)
    rate_b = bin_events(second, channels, bin_ms, duration_ms)
    event_a = event_trace(first, channels, dt_ms, duration_ms)
    event_b = event_trace(second, channels, dt_ms, duration_ms)
    return {
        "rate_max_abs_error": float(np.max(np.abs(rate_a - rate_b))),
        "event_trace_l1_distance": float(np.sum(np.abs(event_a - event_b)) * dt_ms),
        "rate_representation_collision": bool(np.array_equal(rate_a, rate_b)),
        "event_representation_distinguishes": bool(not np.array_equal(event_a, event_b)),
    }


def _pathology_probes(dt_ms: float) -> dict[str, Any]:
    constants = LifConstants(-52.0, -52.0, -45.0, 20.0, 5.0, 2.2, 1.8)
    empty = sparse.csr_matrix((1, 1), dtype=np.float64)
    lif_quiet = run_numpy_source_aligned(empty, {}, constants, dt_ms, 100)
    lif_quiet_deviation = float(np.max(np.abs(lif_quiet["states"][:, :2] - np.asarray([-52.0, 0.0]))))

    # A normalized leaky-rate engineering comparator: no fitted biological units.
    decay = math.exp(-5.0 / 20.0)
    rate_quiet = np.zeros(20, dtype=np.float64)
    rate_impulse = np.zeros(20, dtype=np.float64)
    rate_impulse[0] = 1.0
    for index in range(1, len(rate_impulse)):
        rate_impulse[index] = decay * rate_impulse[index - 1]

    # Force repeated drive into one neuron; endogenous spikes must still respect rfc.
    loop = sparse.csr_matrix((np.asarray([20.0]), (np.asarray([0]), np.asarray([0]))), shape=(1, 1))
    forced = {step: np.asarray([0], dtype=np.int64) for step in range(0, 200, 5)}
    driven = run_numpy_source_aligned(loop, forced, constants, dt_ms, 200)
    spike_steps = [index for index, row in enumerate(driven["spike_raster"]) if row]
    intervals_ms = np.diff(spike_steps).astype(np.float64) * dt_ms
    minimum_isi = float(np.min(intervals_ms)) if len(intervals_ms) else None
    finite = bool(
        np.isfinite(lif_quiet["states"]).all()
        and np.isfinite(driven["states"]).all()
        and np.isfinite(rate_impulse).all()
    )
    return {
        "lif_quiescent_max_abs_deviation": lif_quiet_deviation,
        "rate_quiescent_max_abs_deviation": float(np.max(np.abs(rate_quiet))),
        "rate_bounded_impulse_peak": float(np.max(np.abs(rate_impulse))),
        "rate_bounded_impulse_final": float(rate_impulse[-1]),
        "event_endogenous_spike_count": len(spike_steps),
        "event_minimum_inter_spike_interval_ms": minimum_isi,
        "all_states_finite": finite,
    }


def run_probes() -> dict[str, Any]:
    campaign = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="utf-8"))
    if campaign.get("behavior_targets"):
        raise TemporalProbeError("Temporal probes cannot expose behavior targets")
    frozen = campaign["frozen_inputs"]
    acceptance = campaign["acceptance"]
    bin_ms = float(frozen["rate_bin_ms"])
    dt_ms = float(frozen["event_resolution_ms"])
    print("[1/4] Testing within-bin phase collision...", flush=True)
    phase = collision_probe([(0, 0.5), (0, 4.5)], [(0, 1.5), (0, 3.5)], 1, bin_ms, dt_ms, 10.0)
    print("[2/4] Testing cross-channel order collision...", flush=True)
    order = collision_probe([(0, 1.0), (1, 4.0)], [(1, 1.0), (0, 4.0)], 2, bin_ms, dt_ms, 10.0)
    print("[3/4] Testing delay aliasing and shared pathologies...", flush=True)
    delay = collision_probe([(0, 1.8)], [(0, 3.6)], 1, bin_ms, dt_ms, 10.0)
    pathologies = _pathology_probes(dt_ms)
    collisions = {"within_bin_phase": phase, "cross_channel_order": order, "fixed_delay_aliasing": delay}
    checks = {
        "all_rate_collisions_exact": all(item["rate_max_abs_error"] <= float(acceptance["rate_collision_max_abs_error"]) for item in collisions.values()),
        "all_event_traces_distinct": all(item["event_trace_l1_distance"] >= float(acceptance["event_trace_min_l1_distance"]) for item in collisions.values()),
        "shared_states_finite": bool(pathologies["all_states_finite"]),
        "both_quiescent": max(pathologies["lif_quiescent_max_abs_deviation"], pathologies["rate_quiescent_max_abs_deviation"]) <= float(acceptance["quiescent_response_max_abs"]),
        "event_refractory_respected": pathologies["event_minimum_inter_spike_interval_ms"] is None or pathologies["event_minimum_inter_spike_interval_ms"] >= float(acceptance["event_minimum_inter_spike_interval_ms"]),
    }
    if not all(checks.values()):
        raise TemporalProbeError(f"Preregistered temporal probe failed: {checks}")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "--temporal-probes-v1"
    run_dir = RUN_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    status = "information_loss_demonstrated_pathology_probes_passed_scientific_gate_open"
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "status": status,
        "claim_label": campaign["claim_label"],
        "campaign_hash": _sha256(CAMPAIGN_PATH),
        "collisions": collisions,
        "pathologies": pathologies,
        "checks": checks,
        "reproducibility": {"project_git_commit": _git_value("rev-parse", "HEAD")},
        "accepted_claims": [
            "At 5 ms bins, the tested rate representation is non-injective for phase, channel order and sub-bin delay.",
            "The event representation preserves those distinctions at 0.1 ms resolution.",
            "Both minimal comparators pass the preregistered quiescence and finiteness checks.",
        ],
        "forbidden_claims": [
            "The lost distinctions are proven necessary for all MaleCNS populations.",
            "The event model is therefore globally preferable or biologically accepted.",
            "These synthetic probes close the model-class gate.",
        ],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    compact = {
        "schema_version": 1,
        "id": "runner_result.neural_model_class_temporal_probes.v1",
        "status": status,
        "claim_label": campaign["claim_label"],
        "run_id": run_id,
        "run_summary_ref": str((run_dir / "summary.json").relative_to(ROOT)).replace("\\", "/"),
        "campaign_hash": summary["campaign_hash"],
        "collisions": collisions,
        "pathologies": pathologies,
        "checks": checks,
        "scientific_gate_closed": False,
        "next_action": "Execute the locked aBN1 comparison; select rate, event or typed/hybrid scope only from combined evidence.",
    }
    RESULT_PATH.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")
    print("[4/4] Compact result and heavy trace written.", flush=True)
    print(f"[TRACE] {run_dir / 'summary.json'}", flush=True)
    print(f"[RESULT] {RESULT_PATH}", flush=True)
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    argparse.ArgumentParser(description="Temporal representation and pathology probes").parse_args(list(argv) if argv is not None else None)
    run_probes()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

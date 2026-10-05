from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import yaml
from scipy import sparse

from .ledger import ROOT
from .lif_gate import LifConstants
from .lif_source_fidelity import run_numpy_source_aligned


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "neural-model-class-brian2-conformance-v1.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "neural-model-class-brian2-conformance-v1.yaml"
RUN_ROOT = ROOT / "runs" / "calibration" / "neural-model-class-brian2-conformance-v1"
REFERENCE_PYTHON = ROOT / "runs" / "reference-env" / "brian2-2.5.1" / "Scripts" / "python.exe"
REFERENCE_SCRIPT = ROOT / "scripts" / "brian2_reference_fixture.py"


class Brian2ConformanceError(RuntimeError):
    """Raised when a frozen reference or scheduler invariant differs."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, encoding="utf-8"
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _constants() -> LifConstants:
    return LifConstants(-52.0, -52.0, -45.0, 20.0, 5.0, 2.2, 1.8)


def _first_nonzero(values: list[float], atol: float = 1e-12) -> int | None:
    return next((index for index, value in enumerate(values) if abs(value) > atol), None)


def evaluate_fixture(reference: Mapping[str, Any], campaign: Mapping[str, Any]) -> dict[str, Any]:
    expected_runtime = campaign["frozen_inputs"]["reference_runtime"]
    versions = {
        "python": str(reference["python"]),
        "brian2": str(reference["brian2"]),
        "numpy": str(reference["numpy"]),
    }
    version_match = all(
        versions[key] == str(expected_runtime[key]) for key in ("python", "brian2", "numpy")
    )
    dt_ms = float(reference["dt_ms"])
    tolerance = float(campaign["acceptance"]["maximum_state_error_mV"])
    constants = _constants()

    empty = sparse.csr_matrix((1, 1), dtype=np.float64)
    continuous = run_numpy_source_aligned(
        empty,
        {},
        constants,
        dt_ms,
        len(reference["continuous"]["v_mV"]),
        initial_v_mV=np.asarray([-50.0]),
        initial_g_mV=np.asarray([2.0]),
    )
    continuous_reference = np.column_stack(
        (reference["continuous"]["v_mV"], reference["continuous"]["g_mV"])
    )
    continuous_error = float(
        np.max(np.abs(continuous["states"][:, :2] - continuous_reference))
    )

    reset = run_numpy_source_aligned(
        empty,
        {},
        constants,
        dt_ms,
        len(reference["reset_refractory"]["v_mV"]),
        initial_v_mV=np.asarray([-44.0]),
        initial_g_mV=np.asarray([3.0]),
    )
    reset_reference = np.column_stack(
        (
            reference["reset_refractory"]["v_mV"],
            reference["reset_refractory"]["g_mV"],
        )
    )
    reset_error = float(np.max(np.abs(reset["states"][:, :2] - reset_reference)))
    candidate_spike_steps = [index for index, row in enumerate(reset["spike_raster"]) if row]
    reference_spike_steps = [
        int(round(float(item) / dt_ms)) for item in reference["reset_refractory"]["spike_times_ms"]
    ]
    candidate_eligibility = [bool(value == 0) for value in reset["states"][:, 2]]
    reference_eligibility = [bool(value) for value in reference["reset_refractory"]["not_refractory"]]

    delay_graph = sparse.csr_matrix(
        (np.asarray([5.0]), (np.asarray([0]), np.asarray([1]))), shape=(2, 2)
    )
    delay = run_numpy_source_aligned(
        delay_graph,
        {0: np.asarray([0], dtype=np.int64)},
        constants,
        dt_ms,
        len(reference["delay"]["v_mV"]),
    )
    candidate_delay = delay["states"][:, [1, 3]]
    delay_reference = np.column_stack((reference["delay"]["v_mV"], reference["delay"]["g_mV"]))
    delay_error = float(np.max(np.abs(candidate_delay - delay_reference)))
    candidate_first_delivery = _first_nonzero(candidate_delay[:, 1].tolist())
    reference_first_delivery = _first_nonzero(reference["delay"]["g_mV"])

    checks = {
        "reference_versions_match": version_match,
        "exact_source_reset_compiles": bool(reference["exact_source_reset"]["compiles"]),
        "continuous_state_matches": continuous_error <= tolerance,
        "reset_state_matches": reset_error <= tolerance,
        "spike_raster_matches": candidate_spike_steps == reference_spike_steps,
        "refractory_eligibility_matches": candidate_eligibility == reference_eligibility,
        "delay_state_matches": delay_error <= tolerance,
        "first_delivery_sample_matches": candidate_first_delivery == reference_first_delivery,
    }
    return {
        "checks": checks,
        "maximum_state_error_mV": max(continuous_error, reset_error, delay_error),
        "continuous_max_abs_error_mV": continuous_error,
        "reset_max_abs_error_mV": reset_error,
        "delay_max_abs_error_mV": delay_error,
        "candidate_spike_steps": candidate_spike_steps,
        "reference_spike_steps": reference_spike_steps,
        "candidate_first_delivery_sample": candidate_first_delivery,
        "reference_first_delivery_sample": reference_first_delivery,
        "first_delivery_time_ms": (
            None if reference_first_delivery is None else reference_first_delivery * dt_ms
        ),
        "first_eligible_after_refractory_ms": next(
            (index * dt_ms for index, value in enumerate(reference_eligibility) if value), None
        ),
        "accepted": all(checks.values()),
    }


def run_conformance() -> dict[str, Any]:
    campaign = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="utf-8"))
    if campaign.get("behavior_targets"):
        raise Brian2ConformanceError("The conformance campaign cannot expose behavior targets")
    if not REFERENCE_PYTHON.is_file():
        raise Brian2ConformanceError(
            "The isolated reference runtime is missing; run setup_brian2_reference.bat first"
        )
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "--brian2-conformance-v1"
    run_dir = RUN_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    fixture_path = run_dir / "brian2-reference.json"
    print("[1/3] Executing the pinned Brian2 2.5.1 fixture...", flush=True)
    subprocess.run(
        [str(REFERENCE_PYTHON), str(REFERENCE_SCRIPT), "--output", str(fixture_path)],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    reference = json.loads(fixture_path.read_text(encoding="utf-8"))
    print("[2/3] Comparing integration, threshold, delay, reset and refractory boundaries...", flush=True)
    comparison = evaluate_fixture(reference, campaign)
    if not comparison["accepted"]:
        raise Brian2ConformanceError(f"Brian2 scheduler conformance failed: {comparison}")
    print(
        f"      max error {comparison['maximum_state_error_mV']:.3g} mV; "
        f"delivery at {comparison['first_delivery_time_ms']:.1f} ms",
        flush=True,
    )
    status = "brian2_scheduler_conformant_engineering_gate_passed_scientific_gate_open"
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "status": status,
        "claim_label": campaign["claim_label"],
        "campaign_hash": _sha256(CAMPAIGN_PATH),
        "reference_fixture_hash": _sha256(REFERENCE_SCRIPT),
        "reference_runtime": {
            "python": reference["python"],
            "brian2": reference["brian2"],
            "numpy": reference["numpy"],
        },
        "comparison": comparison,
        "reproducibility": {
            "orchestrator_python": platform.python_version(),
            "project_git_commit": _git_value("rev-parse", "HEAD"),
            "project_worktree_clean_before_result": False,
        },
        "accepted_claims": [
            "The v1 candidate matches Brian2 2.5.1 on the four preregistered scheduler probes.",
            "A delayed event becomes visible after the target state update at the declared delivery sample.",
            "The first post-spike eligible state update agrees with Brian2 refractory timing.",
        ],
        "forbidden_claims": [
            "The neural model class is scientifically accepted.",
            "The constants or point-neuron abstraction are physiological truth.",
            "Conformance predicts behavior or closes the aBN1 comparison.",
        ],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    compact = {
        "schema_version": 1,
        "id": "runner_result.neural_model_class_brian2_conformance.v1",
        "status": status,
        "claim_label": campaign["claim_label"],
        "run_id": run_id,
        "run_summary_ref": str((run_dir / "summary.json").relative_to(ROOT)).replace("\\", "/"),
        "campaign_hash": summary["campaign_hash"],
        "reference_fixture_hash": summary["reference_fixture_hash"],
        "reference_runtime": summary["reference_runtime"],
        "comparison": comparison,
        "scientific_gate_closed": False,
        "next_action": "Run shared information-loss/pathology probes, then execute the locked aBN1 comparison.",
    }
    RESULT_PATH.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")
    print("[3/3] Compact result and heavy trace written.", flush=True)
    print(f"[TRACE] {run_dir / 'summary.json'}", flush=True)
    print(f"[RESULT] {RESULT_PATH}", flush=True)
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    argparse.ArgumentParser(description="Brian2 2.5.1 scheduler conformance gate").parse_args(
        list(argv) if argv is not None else None
    )
    run_conformance()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import psutil
import yaml
from scipy import sparse

from .ledger import ROOT
from .lif_gate import (
    LifConstants,
    _expand_torch_events,
    build_outgoing_graph,
    validate_edge_sweep,
)
from .signed_dynamics import SignedDynamicsContract, load_neuron_classes


PROFILE_PATH = ROOT / "benchmarks" / "profiles" / "malecns-lif-gate-v1.yaml"
MODEL_PATH = ROOT / "calibration" / "models" / "malecns-lif-source-aligned-v1.yaml"
CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "neural-model-class-source-fidelity-v1.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "neural-model-class-source-fidelity-v1.yaml"
RUN_ROOT = ROOT / "runs" / "calibration" / "neural-model-class-source-fidelity-v1"


class LifSourceFidelityError(RuntimeError):
    """Raised when the source lock or source-aligned comparator loses an invariant."""


@dataclass(frozen=True)
class SourceAlignedProfile:
    raw: Mapping[str, Any]
    model: Mapping[str, Any]
    campaign: Mapping[str, Any]
    constants: LifConstants
    dt_ms: float
    measured_steps: int
    cpu_measured_steps: int
    warmup_steps: int
    forced_rates_hz: tuple[float, ...]
    edge_sweep_chunk_sources: int
    forced_weight_mV: float

    @classmethod
    def load(cls) -> "SourceAlignedProfile":
        raw = yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))
        model = yaml.safe_load(MODEL_PATH.read_text(encoding="utf-8"))
        campaign = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="utf-8"))
        expected = "MODEL CLASS GATE / SOURCE-ALIGNED / UNCALIBRATED / NO BEHAVIOR"
        if raw.get("claim_label") != expected:
            raise LifSourceFidelityError("The source-aligned no-behavior boundary drifted")
        if model.get("status") != "engineering_reference_unfitted":
            raise LifSourceFidelityError("The v1 comparator must remain unfitted")
        if campaign.get("behavior_targets"):
            raise LifSourceFidelityError("The source-fidelity campaign cannot use behavior targets")
        reference = model["reference_constants"]
        constants = LifConstants(
            **{
                name: float(reference[name]["value"])
                for name in (
                    "v_rest_mV",
                    "reset_mV",
                    "threshold_mV",
                    "tau_membrane_ms",
                    "tau_syn_ms",
                    "refractory_ms",
                    "fixed_delay_ms",
                )
            }
        )
        execution = raw["execution"]
        dt_ms = float(execution["dt_ms"])
        for duration in (constants.refractory_ms, constants.fixed_delay_ms):
            if not math.isclose(duration / dt_ms, round(duration / dt_ms), abs_tol=1e-9):
                raise LifSourceFidelityError("dt_ms must exactly resolve delay and refractory")
        return cls(
            raw=raw,
            model=model,
            campaign=campaign,
            constants=constants,
            dt_ms=dt_ms,
            measured_steps=int(execution["measured_steps"]),
            cpu_measured_steps=int(execution["cpu_measured_steps"]),
            warmup_steps=int(execution["warmup_steps"]),
            forced_rates_hz=tuple(float(x) for x in execution["forced_mean_rates_hz"]),
            edge_sweep_chunk_sources=int(execution["edge_sweep_chunk_sources"]),
            forced_weight_mV=float(execution["forced_load_unitary_weight_mV"]),
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_value(cwd: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=cwd, text=True, encoding="utf-8"
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def audit_pinned_source(profile: SourceAlignedProfile) -> dict[str, Any]:
    source_lock = profile.model["source_lock"]
    checkout = ROOT / profile.campaign["frozen_inputs"]["source_checkout"]
    if not checkout.is_dir():
        raise LifSourceFidelityError(
            "Pinned source checkout is missing. Clone https://github.com/philshiu/"
            "Drosophila_brain_model into runs/reference-source/Drosophila_brain_model."
        )
    commit = _git_value(checkout, "rev-parse", "HEAD")
    if commit != str(source_lock["commit"]):
        raise LifSourceFidelityError(
            f"Pinned source commit drift: expected {source_lock['commit']}, got {commit}"
        )
    hashes: dict[str, str] = {}
    for name, expected in source_lock["files"].items():
        actual = _sha256(checkout / name)
        if actual != str(expected):
            raise LifSourceFidelityError(
                f"Pinned source hash drift for {name}: expected {expected}, got {actual}"
            )
        hashes[str(name)] = actual
    model_text = (checkout / "model.py").read_text(encoding="utf-8")
    required_fragments = {
        "linear_integrator": "method='linear'",
        "refractory_freeze_v": "dv/dt = (v_0 - v + g) / t_mbr : volt (unless refractory)",
        "refractory_freeze_g": "dg/dt = -g / tau               : volt (unless refractory)",
        "reset_g": "g = 0 * mV",
        "fixed_delay": "'t_dly'     : 1.8*ms",
        "trial_duration": "'t_run'     : 1000 * ms",
        "trial_count": "'n_run'     : 30",
    }
    present = {key: value in model_text for key, value in required_fragments.items()}
    if not all(present.values()):
        raise LifSourceFidelityError(f"Pinned source semantics drift: {present}")
    environment_text = (checkout / "environment.yml").read_text(encoding="utf-8")
    environment_present = {
        "python_3_10": "python=3.10" in environment_text,
        "brian2_2_5_1": "brian2=2.5.1" in environment_text,
    }
    if not all(environment_present.values()):
        raise LifSourceFidelityError(f"Pinned source environment drift: {environment_present}")
    return {
        "checkout": str(checkout.relative_to(ROOT)).replace("\\", "/"),
        "commit": commit,
        "file_hashes": hashes,
        "required_semantics_present": present,
        "source_environment_present": environment_present,
        "source_environment_policy": "isolated_python_3_10_brian2_2_5_1",
        "accepted": True,
    }


def _linear_factors(constants: LifConstants, dt_ms: float) -> tuple[float, float, float]:
    membrane_decay = math.exp(-dt_ms / constants.tau_membrane_ms)
    synaptic_decay = math.exp(-dt_ms / constants.tau_syn_ms)
    if math.isclose(constants.tau_membrane_ms, constants.tau_syn_ms):
        coupling = (dt_ms / constants.tau_membrane_ms) * membrane_decay
    else:
        coupling = (
            constants.tau_syn_ms
            / (constants.tau_syn_ms - constants.tau_membrane_ms)
            * (synaptic_decay - membrane_decay)
        )
    return membrane_decay, synaptic_decay, coupling


def _small_graph() -> tuple[sparse.csr_matrix, dict[int, np.ndarray], LifConstants, float]:
    rows = np.asarray([0, 1, 2, 2], dtype=np.int32)
    cols = np.asarray([1, 2, 1, 3], dtype=np.int32)
    values = np.asarray([5.0, 5.0, 5.0, 2.0], dtype=np.float64)
    graph = sparse.coo_matrix((values, (rows, cols)), shape=(4, 4)).tocsr()
    return graph, {0: np.asarray([0], dtype=np.int64)}, LifConstants(-1, -1, 0, 2, 1, 1, 2), 1.0


def run_numpy_source_aligned(
    outgoing: sparse.csr_matrix,
    forced_by_step: Mapping[int, np.ndarray],
    constants: LifConstants,
    dt_ms: float,
    steps: int,
) -> dict[str, Any]:
    node_count = outgoing.shape[0]
    delay_steps = int(round(constants.fixed_delay_ms / dt_ms))
    refractory_steps = int(round(constants.refractory_ms / dt_ms))
    queue: list[list[int]] = [[] for _ in range(steps + delay_steps + 1)]
    v = np.full(node_count, constants.v_rest_mV, dtype=np.float64)
    g = np.zeros(node_count, dtype=np.float64)
    refractory = np.zeros(node_count, dtype=np.int32)
    states: list[np.ndarray] = []
    raster: list[list[int]] = []
    delivered = 0
    membrane_decay, synaptic_decay, coupling = _linear_factors(constants, dt_ms)
    for step in range(steps):
        arriving = np.zeros(node_count, dtype=np.float64)
        for source in np.asarray(queue[step], dtype=np.int64):
            start, end = outgoing.indptr[source : source + 2]
            np.add.at(arriving, outgoing.indices[start:end], outgoing.data[start:end])
            delivered += int(end - start)
        g += arriving
        active = refractory == 0
        v_active = v[active]
        g_active = g[active]
        v[active] = constants.v_rest_mV + (
            (v_active - constants.v_rest_mV) * membrane_decay + g_active * coupling
        )
        g[active] = g_active * synaptic_decay
        refractory[~active] -= 1
        generated = np.flatnonzero(active & (v > constants.threshold_mV)).astype(np.int64)
        if len(generated):
            v[generated] = constants.reset_mV
            g[generated] = 0.0
            refractory[generated] = refractory_steps
        forced = np.asarray(forced_by_step.get(step, np.empty(0, dtype=np.int64)))
        if len(forced) and len(generated):
            generated = generated[~np.isin(generated, forced)]
        emitted = np.concatenate((forced, generated))
        queue[step + delay_steps].extend(int(item) for item in emitted)
        raster.append([int(item) for item in generated])
        states.append(np.concatenate((v.copy(), g.copy(), refractory.astype(np.float64))))
    return {"states": np.stack(states), "spike_raster": raster, "delivered_edge_events": delivered}


def run_torch_source_aligned(
    outgoing: sparse.csr_matrix,
    forced_by_step: Mapping[int, np.ndarray],
    constants: LifConstants,
    dt_ms: float,
    steps: int,
    device: str,
) -> dict[str, Any]:
    import torch

    indptr = torch.from_numpy(outgoing.indptr.astype(np.int64, copy=False)).to(device)
    indices = torch.from_numpy(outgoing.indices.astype(np.int64, copy=False)).to(device)
    weights = torch.from_numpy(outgoing.data.astype(np.float64, copy=False)).to(device)
    node_count = outgoing.shape[0]
    delay_steps = int(round(constants.fixed_delay_ms / dt_ms))
    refractory_steps = int(round(constants.refractory_ms / dt_ms))
    queue: list[list[int]] = [[] for _ in range(steps + delay_steps + 1)]
    v = torch.full((node_count,), constants.v_rest_mV, dtype=torch.float64, device=device)
    g = torch.zeros(node_count, dtype=torch.float64, device=device)
    refractory = torch.zeros(node_count, dtype=torch.int32, device=device)
    states: list[np.ndarray] = []
    raster: list[list[int]] = []
    delivered = 0
    membrane_decay, synaptic_decay, coupling = _linear_factors(constants, dt_ms)
    with torch.inference_mode():
        for step in range(steps):
            sources = torch.tensor(queue[step], dtype=torch.int64, device=device)
            arriving, count = _expand_torch_events(indptr, indices, weights, sources, node_count)
            delivered += count
            g += arriving
            active = refractory == 0
            v[active] = constants.v_rest_mV + (
                (v[active] - constants.v_rest_mV) * membrane_decay + g[active] * coupling
            )
            g[active] = g[active] * synaptic_decay
            refractory[~active] -= 1
            generated = torch.nonzero(active & (v > constants.threshold_mV)).flatten()
            if generated.numel():
                v[generated] = constants.reset_mV
                g[generated] = 0.0
                refractory[generated] = refractory_steps
            forced = torch.as_tensor(
                forced_by_step.get(step, np.empty(0, dtype=np.int64)),
                dtype=torch.int64,
                device=device,
            )
            if forced.numel() and generated.numel():
                generated = generated[~torch.isin(generated, forced)]
            emitted = torch.cat((forced, generated))
            queue[step + delay_steps].extend(int(item) for item in emitted.cpu().tolist())
            raster.append([int(item) for item in generated.cpu().tolist()])
            states.append(torch.cat((v, g, refractory.to(torch.float64))).cpu().numpy().copy())
    return {"states": np.stack(states), "spike_raster": raster, "delivered_edge_events": delivered}


def validate_small_graph(device: str) -> dict[str, Any]:
    graph, forced, constants, dt_ms = _small_graph()
    numpy_result = run_numpy_source_aligned(graph, forced, constants, dt_ms, 10)
    torch_cpu = run_torch_source_aligned(graph, forced, constants, dt_ms, 10, "cpu")
    difference = np.abs(numpy_result["states"] - torch_cpu["states"])
    generated = [node for step in numpy_result["spike_raster"] for node in step]
    spike_steps = [i for i, row in enumerate(numpy_result["spike_raster"]) if row]
    reset_g_observed = all(
        math.isclose(float(numpy_result["states"][step, 4 + node]), 0.0, abs_tol=1e-12)
        for step, row in enumerate(numpy_result["spike_raster"])
        for node in row
    )
    result: dict[str, Any] = {
        "steps": 10,
        "nodes": 4,
        "edges": int(graph.nnz),
        "numpy_torch_cpu_max_abs_error": float(difference.max()),
        "numpy_torch_cpu_states_match": bool(np.allclose(difference, 0.0, atol=1e-6)),
        "numpy_torch_cpu_spikes_match": numpy_result["spike_raster"] == torch_cpu["spike_raster"],
        "numpy_delivered_edge_events": int(numpy_result["delivered_edge_events"]),
        "torch_cpu_delivered_edge_events": int(torch_cpu["delivered_edge_events"]),
        "recurrent_spike_observed": generated.count(1) >= 2 and generated.count(2) >= 1,
        "reset_g_observed": reset_g_observed,
        "spike_steps": spike_steps,
    }
    if device.startswith("cuda"):
        torch_gpu = run_torch_source_aligned(graph, forced, constants, dt_ms, 10, device)
        gpu_difference = np.abs(numpy_result["states"] - torch_gpu["states"])
        result.update(
            {
                "numpy_torch_gpu_max_abs_error": float(gpu_difference.max()),
                "numpy_torch_gpu_states_match": bool(np.allclose(gpu_difference, 0.0, atol=1e-6)),
                "numpy_torch_gpu_spikes_match": numpy_result["spike_raster"] == torch_gpu["spike_raster"],
            }
        )
    checks = [value for key, value in result.items() if key.endswith("_match")]
    result["accepted"] = bool(all(checks) and result["recurrent_spike_observed"] and reset_g_observed)
    if not result["accepted"]:
        raise LifSourceFidelityError(f"Source-aligned small graph failed: {result}")
    return result


def _forced_sources(node_count: int, step: int, period_steps: int, device: str) -> Any:
    import torch

    return torch.arange(step % period_steps, node_count, period_steps, dtype=torch.int64, device=device)


def benchmark_full_graph(
    outgoing: sparse.csr_matrix,
    body_ids: np.ndarray,
    profile: SourceAlignedProfile,
    device: str,
    rate_hz: float,
    steps: int,
) -> dict[str, Any]:
    import torch

    contract = SignedDynamicsContract.load()
    class_indices, _ = load_neuron_classes(body_ids, contract)
    class_signs = np.sign(
        np.asarray([contract.probe_efficacies[item] for item in contract.class_ids], dtype=np.float32)
    )
    signs_np = class_signs[class_indices]
    c = profile.constants
    delay_steps = int(round(c.fixed_delay_ms / profile.dt_ms))
    refractory_steps = int(round(c.refractory_ms / profile.dt_ms))
    period_steps = max(1, int(round(1000.0 / (rate_hz * profile.dt_ms))))
    node_count = outgoing.shape[0]
    indptr = torch.from_numpy(outgoing.indptr.astype(np.int64, copy=False)).to(device)
    indices = torch.from_numpy(outgoing.indices.astype(np.int64, copy=False)).to(device)
    weights = torch.from_numpy(outgoing.data.astype(np.float32, copy=False)).to(device)
    weights *= profile.forced_weight_mV
    signs = torch.from_numpy(signs_np.astype(np.float32, copy=False)).to(device)
    v = torch.full((node_count,), c.v_rest_mV, dtype=torch.float32, device=device)
    g = torch.zeros(node_count, dtype=torch.float32, device=device)
    refractory = torch.zeros(node_count, dtype=torch.int32, device=device)
    queue = [torch.empty(0, dtype=torch.int64, device=device) for _ in range(delay_steps + 1)]
    membrane_decay, synaptic_decay, coupling = _linear_factors(c, profile.dt_ms)
    process = psutil.Process(os.getpid())
    rss_before = int(process.memory_info().rss)
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)
    delivered = expected = forced_count = generated_count = 0
    rss_peak = rss_before
    warmup = min(profile.warmup_steps, steps)
    measured_started = 0.0
    with torch.inference_mode():
        for step in range(warmup + steps):
            if step == warmup:
                if device.startswith("cuda"):
                    torch.cuda.synchronize(device)
                    torch.cuda.reset_peak_memory_stats(device)
                measured_started = time.perf_counter()
                delivered = expected = forced_count = generated_count = 0
                rss_before = int(process.memory_info().rss)
                rss_peak = rss_before
            slot = step % len(queue)
            sources = queue[slot]
            queue[slot] = torch.empty(0, dtype=torch.int64, device=device)
            arriving, count = _expand_torch_events(
                indptr, indices, weights, sources, node_count, signs
            )
            if step >= warmup:
                delivered += count
                if sources.numel():
                    expected += int((indptr[sources + 1] - indptr[sources]).sum().item())
            g += arriving
            active = refractory == 0
            v[active] = c.v_rest_mV + (
                (v[active] - c.v_rest_mV) * membrane_decay + g[active] * coupling
            )
            g[active] = g[active] * synaptic_decay
            refractory[~active] -= 1
            generated = torch.nonzero(active & (v > c.threshold_mV)).flatten()
            if generated.numel():
                v[generated] = c.reset_mV
                g[generated] = 0.0
                refractory[generated] = refractory_steps
            forced = _forced_sources(node_count, step, period_steps, device)
            if generated.numel() and forced.numel():
                generated = generated[~torch.isin(generated, forced)]
            queue[(step + delay_steps) % len(queue)] = torch.cat((forced, generated))
            if step >= warmup:
                forced_count += int(forced.numel())
                generated_count += int(generated.numel())
                rss_peak = max(rss_peak, int(process.memory_info().rss))
    if device.startswith("cuda"):
        torch.cuda.synchronize(device)
    elapsed = time.perf_counter() - measured_started
    finite_fraction = float(torch.mean(torch.isfinite(v).to(torch.float32)).item())
    result = {
        "backend": device,
        "forced_mean_rate_hz": rate_hz,
        "steps": steps,
        "simulated_ms": steps * profile.dt_ms,
        "wall_seconds": elapsed,
        "steps_per_second": steps / elapsed,
        "simulated_to_wall_clock_ratio": (steps * profile.dt_ms / 1000.0) / elapsed,
        "forced_spikes_emitted": forced_count,
        "endogenous_spikes_emitted": generated_count,
        "delivered_edge_events": delivered,
        "expected_edge_events": expected,
        "finite_state_fraction": finite_fraction,
        "process_rss_sampled_delta_bytes": max(0, rss_peak - rss_before),
        "event_accounting_exact": delivered == expected,
    }
    if device.startswith("cuda"):
        result.update(
            {
                "gpu_peak_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
                "gpu_peak_reserved_bytes": int(torch.cuda.max_memory_reserved(device)),
                "gpu_total_bytes": int(torch.cuda.get_device_properties(device).total_memory),
            }
        )
    result["accepted"] = bool(result["event_accounting_exact"] and finite_fraction == 1.0)
    if not result["accepted"]:
        raise LifSourceFidelityError(f"Full graph source-aligned load failed: {result}")
    return result


def _select_devices(requested: str) -> tuple[str, ...]:
    import torch

    if requested == "both":
        if not torch.cuda.is_available():
            raise LifSourceFidelityError("CPU/GPU comparison requested but CUDA is unavailable")
        return ("cpu", "cuda")
    if requested == "auto":
        return ("cuda" if torch.cuda.is_available() else "cpu",)
    if requested == "cuda" and not torch.cuda.is_available():
        raise LifSourceFidelityError("CUDA requested but unavailable")
    return (requested,)


def run_gate(backend: str = "auto", quick: bool = False) -> dict[str, Any]:
    import torch

    profile = SourceAlignedProfile.load()
    devices = _select_devices(backend)
    reference_device = "cuda" if "cuda" in devices else devices[0]
    print("[1/4] Audit du commit, des hashes et des sémantiques publiées...", flush=True)
    source_audit = audit_pinned_source(profile)
    print(f"      OK: source {source_audit['commit'][:12]}", flush=True)
    print("[2/4] Référence NumPy/Torch avec reset-g et gel réfractaire...", flush=True)
    small = validate_small_graph(reference_device)
    print(f"      OK: spikes récurrents aux pas {small['spike_steps']}", flush=True)
    print("[3/4] Balayage exhaustif du graphe canonique...", flush=True)
    outgoing, body_ids = build_outgoing_graph()
    edge_sweep = validate_edge_sweep(outgoing, profile.edge_sweep_chunk_sources)
    print(f"      OK: {edge_sweep['counted_edges']:,} arêtes", flush=True)
    rates = profile.forced_rates_hz[:1] if quick else profile.forced_rates_hz
    loads: list[dict[str, Any]] = []
    for device in devices:
        base_steps = profile.cpu_measured_steps if device == "cpu" else profile.measured_steps
        steps = min(25, base_steps) if quick else base_steps
        for index, rate in enumerate(rates, start=1):
            print(f"[4/4] {device} charge {index}/{len(rates)} à {rate:g} Hz...", flush=True)
            item = benchmark_full_graph(outgoing, body_ids, profile, device, rate, steps)
            loads.append(item)
            print(
                f"      {item['steps_per_second']:.1f} pas/s; "
                f"{item['simulated_to_wall_clock_ratio']:.4f} x temps réel; "
                f"{item['delivered_edge_events']:,} événements",
                flush=True,
            )
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "--lif-source-fidelity-v1"
    run_dir = RUN_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    status = "source_aligned_engineering_stages_passed_scientific_gate_open"
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "status": status,
        "claim_label": profile.raw["claim_label"],
        "backends": list(devices),
        "source_audit": source_audit,
        "small_graph": small,
        "canonical_edge_sweep": edge_sweep,
        "full_graph_loads": loads,
        "reproducibility": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "torch": torch.__version__,
            "project_git_commit": _git_value(ROOT, "rev-parse", "HEAD"),
            "project_worktree_clean": _git_value(ROOT, "status", "--porcelain") == "",
        },
        "accepted_claims": [
            "The pinned source revision and source files match the reviewed hashes.",
            "Independent NumPy and Torch implementations agree on source-aligned reset and refractory semantics.",
            "Every canonical graph row and edge remains accounted for under the corrected comparator.",
        ],
        "forbidden_claims": [
            "Exact Brian2 scheduler conformance has been established.",
            "The model class or physiological constants are scientifically accepted.",
            "The synthetic full-graph loads represent neural activity or behavior.",
        ],
        "remaining_gate_work": [
            "run a direct Brian2 scheduler-boundary conformance test",
            "execute the locked JO-CE versus JO-F aBN1 reference on rate and event candidates",
            "run shared information-loss and pathology probes",
            "issue a population-scoped go, revise, or stop decision",
        ],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    compact = {
        "schema_version": 1,
        "id": "runner_result.neural_model_class_source_fidelity.v1",
        "status": status,
        "claim_label": summary["claim_label"],
        "run_id": run_id,
        "run_summary_ref": str((run_dir / "summary.json").relative_to(ROOT)).replace("\\", "/"),
        "source_audit": source_audit,
        "small_graph": small,
        "canonical_edge_sweep": edge_sweep,
        "full_graph_loads": loads,
        "scientific_gate_closed": False,
        "remaining_gate_work": summary["remaining_gate_work"],
        "next_action": "Run Brian2 conformance and the locked aBN1 comparison; do not resume model-dependent calibration.",
    }
    RESULT_PATH.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")
    print(f"[TRACE] {run_dir / 'summary.json'}", flush=True)
    print(f"[RÉSULTAT] {RESULT_PATH}", flush=True)
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Source-aligned MaleCNS event-LIF gate")
    parser.add_argument("--backend", choices=("auto", "cpu", "cuda", "both"), default="auto")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    run_gate(args.backend, args.quick)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

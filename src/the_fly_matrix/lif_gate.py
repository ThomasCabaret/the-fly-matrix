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

from .connectome_benchmark import DynamicsProfile, build_graph_cache
from .ledger import ROOT
from .runtime import CentralConnectomeBox
from .signed_dynamics import SignedDynamicsContract, load_neuron_classes


PROFILE_PATH = ROOT / "benchmarks" / "profiles" / "malecns-lif-gate-v0.yaml"
MODEL_PATH = ROOT / "calibration" / "models" / "malecns-lif-fixed-delay-v0.yaml"
CAMPAIGN_PATH = (
    ROOT / "calibration" / "campaigns" / "neural-model-class-lif-feasibility-v0.yaml"
)
RESULT_PATH = (
    ROOT / "calibration" / "runner" / "neural-model-class-lif-feasibility-v0.yaml"
)
RUN_ROOT = ROOT / "runs" / "calibration" / "neural-model-class-lif-feasibility-v0"
OUTGOING_CACHE_PATH = (
    ROOT / "data" / "derived" / "execution-benchmark" / "malecns-full-outgoing-csr-v1.npz"
)


class LifGateError(RuntimeError):
    """Raised when the bounded LIF gate loses a declared invariant."""


@dataclass(frozen=True)
class LifConstants:
    v_rest_mV: float
    reset_mV: float
    threshold_mV: float
    tau_membrane_ms: float
    tau_syn_ms: float
    refractory_ms: float
    fixed_delay_ms: float


@dataclass(frozen=True)
class LifGateProfile:
    raw: Mapping[str, Any]
    constants: LifConstants
    dt_ms: float
    measured_steps: int
    cpu_measured_steps: int
    warmup_steps: int
    forced_rates_hz: tuple[float, ...]
    edge_sweep_chunk_sources: int
    forced_weight_mV: float

    @classmethod
    def load(
        cls,
        profile_path: Path = PROFILE_PATH,
        model_path: Path = MODEL_PATH,
        campaign_path: Path = CAMPAIGN_PATH,
    ) -> "LifGateProfile":
        raw = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        model = yaml.safe_load(model_path.read_text(encoding="utf-8"))
        campaign = yaml.safe_load(campaign_path.read_text(encoding="utf-8"))
        if raw.get("claim_label") != "MODEL CLASS GATE / UNCALIBRATED / NO BEHAVIOR":
            raise LifGateError("The LIF benchmark lost its no-behavior claim boundary")
        if model.get("status") != "engineering_reference_unfitted":
            raise LifGateError("The LIF model must remain an unfitted engineering reference")
        if campaign.get("status") != "runnable_diagnostic":
            raise LifGateError("The bounded LIF feasibility campaign is not runnable")
        if campaign.get("behavior_targets"):
            raise LifGateError("The LIF feasibility gate cannot consume behavior targets")
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
        if dt_ms <= 0 or constants.tau_membrane_ms <= 0 or constants.tau_syn_ms <= 0:
            raise LifGateError("Temporal constants must be positive")
        for duration in (constants.refractory_ms, constants.fixed_delay_ms):
            steps = duration / dt_ms
            if not math.isclose(steps, round(steps), abs_tol=1e-9):
                raise LifGateError("dt_ms must exactly resolve delay and refractory durations")
        rates = tuple(float(item) for item in execution["forced_mean_rates_hz"])
        if not rates or any(item <= 0 for item in rates):
            raise LifGateError("Forced engineering loads must be positive")
        return cls(
            raw=raw,
            constants=constants,
            dt_ms=dt_ms,
            measured_steps=int(execution["measured_steps"]),
            cpu_measured_steps=int(execution["cpu_measured_steps"]),
            warmup_steps=int(execution["warmup_steps"]),
            forced_rates_hz=rates,
            edge_sweep_chunk_sources=int(execution["edge_sweep_chunk_sources"]),
            forced_weight_mV=float(execution["forced_load_unitary_weight_mV"]),
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _small_graph() -> tuple[sparse.csr_matrix, dict[int, np.ndarray], LifConstants, float]:
    # Rows are presynaptic sources. The 1<->2 cycle forces recurrent delivery.
    rows = np.asarray([0, 1, 2, 2], dtype=np.int32)
    cols = np.asarray([1, 2, 1, 3], dtype=np.int32)
    values = np.asarray([1.25, 1.25, 1.25, 0.5], dtype=np.float32)
    outgoing = sparse.coo_matrix((values, (rows, cols)), shape=(4, 4)).tocsr()
    forced = {0: np.asarray([0], dtype=np.int64)}
    constants = LifConstants(-1.0, -1.0, 0.0, 1.0, 1.0, 1.0, 2.0)
    return outgoing, forced, constants, 1.0


def run_numpy_event_reference(
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
    delivered_events = 0
    emitted_events = 0
    decay = math.exp(-dt_ms / constants.tau_syn_ms)
    for step in range(steps):
        sources = np.asarray(queue[step], dtype=np.int64)
        arriving = np.zeros(node_count, dtype=np.float64)
        for source in sources:
            start, end = outgoing.indptr[source : source + 2]
            np.add.at(arriving, outgoing.indices[start:end], outgoing.data[start:end])
            delivered_events += int(end - start)
        g = g * decay + arriving
        active = refractory == 0
        v[active] += (dt_ms / constants.tau_membrane_ms) * (
            constants.v_rest_mV - v[active] + g[active]
        )
        refractory[~active] -= 1
        generated = np.flatnonzero(active & (v >= constants.threshold_mV)).astype(np.int64)
        if len(generated):
            v[generated] = constants.reset_mV
            refractory[generated] = refractory_steps
        forced = np.asarray(forced_by_step.get(step, np.empty(0, dtype=np.int64)))
        if len(forced) and len(generated):
            generated = generated[~np.isin(generated, forced)]
        emitted = np.concatenate((forced, generated))
        queue[step + delay_steps].extend(int(item) for item in emitted)
        emitted_events += len(emitted)
        raster.append([int(item) for item in generated])
        states.append(np.concatenate((v.copy(), g.copy(), refractory.astype(np.float64))))
    return {
        "states": np.stack(states),
        "spike_raster": raster,
        "delivered_edge_events": delivered_events,
        "emitted_spikes": emitted_events,
    }


def _expand_torch_events(
    outgoing_indptr: Any,
    outgoing_indices: Any,
    outgoing_weights: Any,
    source_events: Any,
    node_count: int,
    source_signs: Any | None = None,
) -> tuple[Any, int]:
    import torch

    arriving = torch.zeros(node_count, dtype=outgoing_weights.dtype, device=outgoing_weights.device)
    if source_events.numel() == 0:
        return arriving, 0
    degrees = outgoing_indptr[source_events + 1] - outgoing_indptr[source_events]
    total = int(degrees.sum().item())
    if total == 0:
        return arriving, 0
    segment_offsets = torch.cumsum(degrees, dim=0) - degrees
    bases = outgoing_indptr[source_events] - segment_offsets
    edge_positions = torch.arange(total, dtype=torch.int64, device=source_events.device)
    edge_positions += torch.repeat_interleave(bases, degrees)
    targets = outgoing_indices[edge_positions]
    contributions = outgoing_weights[edge_positions]
    if source_signs is not None:
        contributions = contributions * torch.repeat_interleave(source_signs[source_events], degrees)
    arriving.index_add_(0, targets, contributions)
    return arriving, total


def run_torch_event_reference(
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
    delivered_events = 0
    emitted_events = 0
    decay = math.exp(-dt_ms / constants.tau_syn_ms)
    with torch.inference_mode():
        for step in range(steps):
            sources = torch.tensor(queue[step], dtype=torch.int64, device=device)
            arriving, count = _expand_torch_events(
                indptr, indices, weights, sources, node_count
            )
            delivered_events += count
            g = g * decay + arriving
            active = refractory == 0
            v[active] += (dt_ms / constants.tau_membrane_ms) * (
                constants.v_rest_mV - v[active] + g[active]
            )
            refractory[~active] -= 1
            generated = torch.nonzero(active & (v >= constants.threshold_mV)).flatten()
            if generated.numel():
                v[generated] = constants.reset_mV
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
            emitted_events += int(emitted.numel())
            raster.append([int(item) for item in generated.cpu().tolist()])
            states.append(
                torch.cat((v, g, refractory.to(torch.float64))).cpu().numpy().copy()
            )
    return {
        "states": np.stack(states),
        "spike_raster": raster,
        "delivered_edge_events": delivered_events,
        "emitted_spikes": emitted_events,
    }


def validate_small_graph(device: str) -> dict[str, Any]:
    outgoing, forced, constants, dt_ms = _small_graph()
    numpy_result = run_numpy_event_reference(outgoing, forced, constants, dt_ms, 10)
    torch_cpu = run_torch_event_reference(outgoing, forced, constants, dt_ms, 10, "cpu")
    difference = np.abs(numpy_result["states"] - torch_cpu["states"])
    result: dict[str, Any] = {
        "steps": 10,
        "nodes": 4,
        "edges": int(outgoing.nnz),
        "numpy_torch_cpu_max_abs_error": float(difference.max()),
        "numpy_torch_cpu_states_match": bool(np.allclose(difference, 0.0, atol=1e-6)),
        "numpy_torch_cpu_spikes_match": numpy_result["spike_raster"] == torch_cpu["spike_raster"],
        "numpy_delivered_edge_events": int(numpy_result["delivered_edge_events"]),
        "torch_cpu_delivered_edge_events": int(torch_cpu["delivered_edge_events"]),
        "recurrent_spike_observed": any(2 in item for item in numpy_result["spike_raster"]),
    }
    if device.startswith("cuda"):
        torch_gpu = run_torch_event_reference(outgoing, forced, constants, dt_ms, 10, device)
        gpu_difference = np.abs(numpy_result["states"] - torch_gpu["states"])
        result.update(
            {
                "numpy_torch_gpu_max_abs_error": float(gpu_difference.max()),
                "numpy_torch_gpu_states_match": bool(np.allclose(gpu_difference, 0.0, atol=1e-6)),
                "numpy_torch_gpu_spikes_match": numpy_result["spike_raster"] == torch_gpu["spike_raster"],
                "torch_gpu_delivered_edge_events": int(torch_gpu["delivered_edge_events"]),
            }
        )
    checks = [value for key, value in result.items() if key.endswith("_match")]
    result["accepted"] = bool(all(checks) and result["recurrent_spike_observed"])
    if not result["accepted"]:
        raise LifGateError(f"Deterministic small-graph reference failed: {result}")
    return result


def build_outgoing_graph() -> tuple[sparse.csr_matrix, np.ndarray]:
    graph = build_graph_cache(
        CentralConnectomeBox.from_generated_wiring(), DynamicsProfile.load(), scope="full"
    )
    if OUTGOING_CACHE_PATH.is_file():
        outgoing = sparse.load_npz(OUTGOING_CACHE_PATH).tocsr()
    else:
        print("[GRAPH] Construction du cache CSR sortant (une seule fois)...", flush=True)
        outgoing = graph.matrix.transpose().tocsr()
        outgoing.sort_indices()
        OUTGOING_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        sparse.save_npz(OUTGOING_CACHE_PATH, outgoing, compressed=False)
    if outgoing.shape != graph.matrix.shape or outgoing.nnz != graph.matrix.nnz:
        raise LifGateError("Outgoing graph cache does not match the canonical incoming graph")
    return outgoing, graph.body_ids


def validate_edge_sweep(outgoing: sparse.csr_matrix, chunk_sources: int) -> dict[str, Any]:
    started = time.perf_counter()
    counted_edges = 0
    counted_contacts = 0.0
    chunks = 0
    for start in range(0, outgoing.shape[0], chunk_sources):
        end = min(start + chunk_sources, outgoing.shape[0])
        edge_start = int(outgoing.indptr[start])
        edge_end = int(outgoing.indptr[end])
        counted_edges += edge_end - edge_start
        counted_contacts += float(np.sum(outgoing.data[edge_start:edge_end], dtype=np.float64))
        chunks += 1
    result = {
        "canonical_neurons": int(outgoing.shape[0]),
        "runtime_edges": int(outgoing.nnz),
        "outgoing_csr_bytes": int(
            outgoing.data.nbytes + outgoing.indices.nbytes + outgoing.indptr.nbytes
        ),
        "counted_edges": int(counted_edges),
        "published_synaptic_contacts": int(round(counted_contacts)),
        "source_rows_visited": int(outgoing.shape[0]),
        "chunks": chunks,
        "elapsed_seconds": time.perf_counter() - started,
        "accepted": counted_edges == outgoing.nnz,
    }
    if not result["accepted"]:
        raise LifGateError("Canonical edge sweep did not account for every runtime edge")
    return result


def _forced_sources(node_count: int, step: int, period_steps: int, device: str) -> Any:
    import torch

    offset = step % period_steps
    return torch.arange(offset, node_count, period_steps, dtype=torch.int64, device=device)


def benchmark_full_graph_load(
    outgoing: sparse.csr_matrix,
    body_ids: np.ndarray,
    profile: LifGateProfile,
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
    neuron_signs = class_signs[class_indices]
    constants = profile.constants
    delay_steps = int(round(constants.fixed_delay_ms / profile.dt_ms))
    refractory_steps = int(round(constants.refractory_ms / profile.dt_ms))
    period_steps = max(1, int(round(1000.0 / (rate_hz * profile.dt_ms))))
    node_count = outgoing.shape[0]
    indptr = torch.from_numpy(outgoing.indptr.astype(np.int64, copy=False)).to(device)
    indices = torch.from_numpy(outgoing.indices.astype(np.int64, copy=False)).to(device)
    weights = torch.from_numpy(outgoing.data.astype(np.float32, copy=False)).to(device)
    weights = weights * profile.forced_weight_mV
    signs = torch.from_numpy(neuron_signs.astype(np.float32, copy=False)).to(device)
    process = psutil.Process(os.getpid())
    rss_before = int(process.memory_info().rss)
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)
    v = torch.full((node_count,), constants.v_rest_mV, dtype=torch.float32, device=device)
    g = torch.zeros(node_count, dtype=torch.float32, device=device)
    refractory = torch.zeros(node_count, dtype=torch.int32, device=device)
    queue: list[Any] = [torch.empty(0, dtype=torch.int64, device=device) for _ in range(delay_steps + 1)]
    decay = math.exp(-profile.dt_ms / constants.tau_syn_ms)
    delivered_edges = 0
    expected_edges = 0
    forced_spikes = 0
    endogenous_spikes = 0
    rss_peak = rss_before
    warmup = min(profile.warmup_steps, steps)
    total_steps = warmup + steps
    measured_started = 0.0
    with torch.inference_mode():
        for step in range(total_steps):
            if step == warmup:
                if device.startswith("cuda"):
                    torch.cuda.synchronize(device)
                    torch.cuda.reset_peak_memory_stats(device)
                measured_started = time.perf_counter()
                delivered_edges = expected_edges = forced_spikes = endogenous_spikes = 0
                rss_before = int(process.memory_info().rss)
                rss_peak = rss_before
            slot = step % len(queue)
            sources = queue[slot]
            queue[slot] = torch.empty(0, dtype=torch.int64, device=device)
            arriving, count = _expand_torch_events(
                indptr, indices, weights, sources, node_count, signs
            )
            if step >= warmup:
                delivered_edges += count
                if sources.numel():
                    expected_edges += int(
                        (indptr[sources + 1] - indptr[sources]).sum().item()
                    )
            g = g * decay + arriving
            active = refractory == 0
            v[active] += (profile.dt_ms / constants.tau_membrane_ms) * (
                constants.v_rest_mV - v[active] + g[active]
            )
            refractory[~active] -= 1
            generated = torch.nonzero(active & (v >= constants.threshold_mV)).flatten()
            if generated.numel():
                v[generated] = constants.reset_mV
                refractory[generated] = refractory_steps
            forced = _forced_sources(node_count, step, period_steps, device)
            if generated.numel() and forced.numel():
                generated = generated[~torch.isin(generated, forced)]
            emitted = torch.cat((forced, generated))
            destination = (step + delay_steps) % len(queue)
            queue[destination] = emitted
            if step >= warmup:
                forced_spikes += int(forced.numel())
                endogenous_spikes += int(generated.numel())
                rss_peak = max(rss_peak, int(process.memory_info().rss))
    if device.startswith("cuda"):
        torch.cuda.synchronize(device)
    elapsed = time.perf_counter() - measured_started
    finite_fraction = float(torch.mean(torch.isfinite(v).to(torch.float32)).item())
    result = {
        "backend": device,
        "forced_mean_rate_hz": rate_hz,
        "period_steps": period_steps,
        "steps": steps,
        "simulated_ms": steps * profile.dt_ms,
        "wall_seconds": elapsed,
        "steps_per_second": steps / elapsed,
        "simulated_to_wall_clock_ratio": (steps * profile.dt_ms / 1000.0) / elapsed,
        "forced_spikes_emitted": forced_spikes,
        "endogenous_spikes_emitted": endogenous_spikes,
        "delivered_edge_events": delivered_edges,
        "expected_edge_events": expected_edges,
        "finite_state_fraction": finite_fraction,
        "process_rss_before_bytes": rss_before,
        "process_rss_peak_sampled_bytes": rss_peak,
        "process_rss_sampled_delta_bytes": max(0, rss_peak - rss_before),
        "event_accounting_exact": delivered_edges == expected_edges,
    }
    if device.startswith("cuda"):
        result.update(
            {
                "gpu_peak_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
                "gpu_peak_reserved_bytes": int(torch.cuda.max_memory_reserved(device)),
                "gpu_total_bytes": int(torch.cuda.get_device_properties(device).total_memory),
            }
        )
    result["accepted"] = bool(
        result["event_accounting_exact"] and math.isclose(finite_fraction, 1.0)
    )
    del indptr, indices, weights, signs, v, g, refractory, queue
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    if not result["accepted"]:
        raise LifGateError(f"Full graph load failed: {result}")
    return result


def _git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, encoding="utf-8"
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _select_device(requested: str) -> str:
    import torch

    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise LifGateError("CUDA was requested but is unavailable")
    return requested


def run_gate(backend: str = "auto", quick: bool = False) -> dict[str, Any]:
    import torch

    profile = LifGateProfile.load()
    if backend == "both":
        if not torch.cuda.is_available():
            raise LifGateError("The CPU/GPU comparison requested by 'both' needs CUDA")
        devices = ("cpu", "cuda")
    else:
        devices = (_select_device(backend),)
    reference_device = "cuda" if "cuda" in devices else devices[0]
    rates = profile.forced_rates_hz[:1] if quick else profile.forced_rates_hz
    print(f"[GATE] Backend(s): {', '.join(devices)}; pas temporel: {profile.dt_ms} ms", flush=True)
    print("[1/3] Référence déterministe NumPy/Torch sur petit graphe...", flush=True)
    small = validate_small_graph(reference_device)
    print("      OK: spikes, états, délai et événements concordent.", flush=True)
    print("[2/3] Chargement du graphe canonique et balayage exhaustif...", flush=True)
    outgoing, body_ids = build_outgoing_graph()
    edge_sweep = validate_edge_sweep(outgoing, profile.edge_sweep_chunk_sources)
    print(
        f"      OK: {edge_sweep['canonical_neurons']:,} neurones; "
        f"{edge_sweep['counted_edges']:,} arêtes; "
        f"{edge_sweep['published_synaptic_contacts']:,} contacts.",
        flush=True,
    )
    loads = []
    for device in devices:
        base_steps = profile.cpu_measured_steps if device == "cpu" else profile.measured_steps
        steps = min(25, base_steps) if quick else base_steps
        for index, rate in enumerate(rates, start=1):
            print(
                f"[3/3] {device} charge {index}/{len(rates)}: "
                f"{rate:g} spikes/s/neuron sur {steps} pas...",
                flush=True,
            )
            result = benchmark_full_graph_load(outgoing, body_ids, profile, device, rate, steps)
            loads.append(result)
            print(
                f"      {result['steps_per_second']:.1f} pas/s; "
                f"{result['simulated_to_wall_clock_ratio']:.4f} x temps réel; "
                f"{result['delivered_edge_events']:,} événements d'arête.",
                flush=True,
            )
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "--lif-feasibility-v0"
    run_dir = RUN_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    input_paths = (PROFILE_PATH, MODEL_PATH, CAMPAIGN_PATH)
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "claim_label": profile.raw["claim_label"],
        "status": "engineering_stages_passed_scientific_gate_open",
        "backends": list(devices),
        "device_name": torch.cuda.get_device_name(0) if "cuda" in devices else platform.processor(),
        "quick": quick,
        "small_graph": small,
        "canonical_edge_sweep": edge_sweep,
        "full_graph_loads": loads,
        "inputs": [{"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)} for path in input_paths],
        "reproducibility": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "torch": torch.__version__,
            "git_commit": _git_value("rev-parse", "HEAD"),
            "git_worktree_clean": _git_value("status", "--porcelain") == "",
        },
        "accepted_claims": [
            "Independent NumPy and Torch implementations agree on the fixed small graph.",
            "Every canonical neuron row and runtime edge is accounted for.",
            "The measured backend can execute fixed-delay LIF state and event delivery under declared synthetic loads.",
        ],
        "forbidden_claims": [
            "The LIF model class is scientifically accepted.",
            "The measured speed predicts a calibrated recurrent MaleCNS run.",
            "The forced spike loads represent fly neural activity or behavior.",
            "The fixed delay makes morphology-dependent timing unnecessary.",
        ],
        "remaining_gate_work": [
            "preregister and run model-independent rate-versus-event technical probes",
            "lock and run an independent circuit-level reference",
            "issue explicit go, revise, or stop model-class decision",
        ],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    compact = {
        "schema_version": 1,
        "id": "runner_result.neural_model_class_lif_feasibility.v0",
        "status": summary["status"],
        "claim_label": summary["claim_label"],
        "run_id": run_id,
        "run_summary_ref": str((run_dir / "summary.json").relative_to(ROOT)).replace("\\", "/"),
        "backends": list(devices),
        "small_graph": small,
        "canonical_edge_sweep": edge_sweep,
        "full_graph_loads": loads,
        "scientific_gate_closed": False,
        "remaining_gate_work": summary["remaining_gate_work"],
        "next_action": "Specify model-independent probes and the locked circuit reference; do not resume model-dependent calibration yet.",
    }
    RESULT_PATH.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")
    print(f"[TRACE] {run_dir / 'summary.json'}", flush=True)
    print(f"[RÉSULTAT COMPACT] {RESULT_PATH}", flush=True)
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded MaleCNS event-LIF model-class gate")
    parser.add_argument("--backend", choices=("auto", "cpu", "cuda", "both"), default="auto")
    parser.add_argument("--quick", action="store_true")
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    run_gate(arguments.backend, arguments.quick)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

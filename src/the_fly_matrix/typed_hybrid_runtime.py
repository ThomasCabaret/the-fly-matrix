from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import time
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml
from scipy import sparse

from .ledger import ROOT
from .lif_gate import LifConstants
from .lif_source_fidelity import _linear_factors


CAMPAIGN_PATH = (
    ROOT / "calibration" / "campaigns" / "basal-reached-typed-hybrid-runtime-sentinel-v0.yaml"
)
RESULT_PATH = (
    ROOT / "calibration" / "runner" / "basal-reached-typed-hybrid-runtime-sentinel-v0.yaml"
)
EVALUATION_PATH = (
    ROOT
    / "calibration"
    / "evaluations"
    / "basal-reached-typed-hybrid-runtime-sentinel-v0.yaml"
)
OUTPUT_ROOT = (
    ROOT
    / "data"
    / "derived"
    / "calibration"
    / "basal-reached-typed-hybrid-runtime-sentinel-v0"
)

INACTIVE = np.int8(0)
EVENT = np.int8(1)
GRADED = np.int8(2)


class TypedHybridRuntimeError(RuntimeError):
    """Raised when the typed/hybrid execution contract loses an invariant."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypedHybridRuntimeError(f"{path} must contain a YAML mapping")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _artifact_ref(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


@dataclass(frozen=True)
class DiagnosticConstants:
    """Unpromotable values used only to exercise runtime mechanics."""

    dt_ms: float
    lif: LifConstants
    event_to_event_mV: float
    event_to_graded: float
    graded_to_event_mV: float
    graded_to_graded: float
    graded_tau_ms: float
    external_graded_probe: float

    @classmethod
    def from_campaign(cls, campaign: Mapping[str, Any]) -> "DiagnosticConstants":
        values = campaign["diagnostic_only_constants"]
        lif = values["event_comparator"]
        return cls(
            dt_ms=float(values["dt_ms"]),
            lif=LifConstants(
                v_rest_mV=float(lif["v_rest_mV"]),
                reset_mV=float(lif["reset_mV"]),
                threshold_mV=float(lif["threshold_mV"]),
                tau_membrane_ms=float(lif["tau_membrane_ms"]),
                tau_syn_ms=float(lif["tau_syn_ms"]),
                refractory_ms=float(lif["refractory_ms"]),
                fixed_delay_ms=float(lif["fixed_delay_ms"]),
            ),
            event_to_event_mV=float(values["boundary_scales"]["event_to_event_mV"]),
            event_to_graded=float(values["boundary_scales"]["event_to_graded"]),
            graded_to_event_mV=float(values["boundary_scales"]["graded_to_event_mV"]),
            graded_to_graded=float(values["boundary_scales"]["graded_to_graded"]),
            graded_tau_ms=float(values["graded_tau_ms"]),
            external_graded_probe=float(values["external_graded_probe"]),
        )

    def validate(self) -> None:
        if self.dt_ms <= 0 or self.graded_tau_ms <= 0:
            raise TypedHybridRuntimeError("time constants must be positive")
        for duration in (self.lif.fixed_delay_ms, self.lif.refractory_ms):
            if not math.isclose(duration / self.dt_ms, round(duration / self.dt_ms), abs_tol=1e-9):
                raise TypedHybridRuntimeError("dt_ms must exactly resolve delay and refractory")


def normalized_incoming_operator(matrix: sparse.csr_matrix) -> tuple[sparse.csr_matrix, np.ndarray]:
    matrix = matrix.astype(np.float32, copy=True).tocsr()
    incoming_l1 = np.asarray(np.abs(matrix).sum(axis=1)).reshape(-1).astype(np.float32)
    inverse = np.zeros_like(incoming_l1)
    np.divide(1.0, incoming_l1, out=inverse, where=incoming_l1 > 0)
    return matrix, inverse


def boundary_edge_counts(matrix: sparse.csr_matrix, assignment: np.ndarray) -> dict[str, int]:
    if matrix.shape != (len(assignment), len(assignment)):
        raise TypedHybridRuntimeError("assignment and graph shapes differ")
    counts = {"event_to_event": 0, "event_to_graded": 0, "graded_to_event": 0, "graded_to_graded": 0}
    active_edges = 0
    for target in np.flatnonzero(assignment != INACTIVE):
        start, end = matrix.indptr[target : target + 2]
        source_types = assignment[matrix.indices[start:end]]
        event_sources = int(np.count_nonzero(source_types == EVENT))
        graded_sources = int(np.count_nonzero(source_types == GRADED))
        active_edges += event_sources + graded_sources
        if assignment[target] == EVENT:
            counts["event_to_event"] += event_sources
            counts["graded_to_event"] += graded_sources
        else:
            counts["event_to_graded"] += event_sources
            counts["graded_to_graded"] += graded_sources
    counts["total_active_edges"] = active_edges
    return counts


class TorchTypedHybridRuntime:
    """Sparse execution kernel whose assignment vector is an explicit run input.

    `dual_unresolved` is deliberately not a runtime code: a campaign must name an
    explicit candidate profile. The scientific record remains unresolved even
    when a diagnostic profile is executed.
    """

    def __init__(
        self,
        incoming: sparse.csr_matrix,
        assignment: np.ndarray,
        constants: DiagnosticConstants,
        device: str,
    ) -> None:
        import torch

        constants.validate()
        assignment = np.asarray(assignment, dtype=np.int8)
        if set(np.unique(assignment)) - {int(INACTIVE), int(EVENT), int(GRADED)}:
            raise TypedHybridRuntimeError("runtime assignment contains an unresolved code")
        if not np.any(assignment == EVENT) and not np.any(assignment == GRADED):
            raise TypedHybridRuntimeError("runtime profile has no active population")
        matrix, inverse = normalized_incoming_operator(incoming)
        self.device = device
        self.constants = constants
        self.node_count = matrix.shape[0]
        self.assignment_np = assignment
        self.event_mask = torch.as_tensor(assignment == EVENT, dtype=torch.bool, device=device)
        self.graded_mask = torch.as_tensor(assignment == GRADED, dtype=torch.bool, device=device)
        self.active_mask = self.event_mask | self.graded_mask
        crow = torch.as_tensor(matrix.indptr.astype(np.int32, copy=False), device=device)
        col = torch.as_tensor(matrix.indices.astype(np.int32, copy=False), device=device)
        data = torch.as_tensor(matrix.data.astype(np.float32, copy=False), device=device)
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Sparse CSR tensor support is in beta state")
            self.matrix = torch.sparse_csr_tensor(
                crow,
                col,
                data,
                size=matrix.shape,
                dtype=torch.float32,
                device=device,
                check_invariants=False,
            )
        self.incoming_inverse = torch.as_tensor(inverse, dtype=torch.float32, device=device)
        self.v = torch.full(
            (self.node_count,), constants.lif.v_rest_mV, dtype=torch.float32, device=device
        )
        self.g = torch.zeros(self.node_count, dtype=torch.float32, device=device)
        self.refractory = torch.zeros(self.node_count, dtype=torch.int32, device=device)
        self.graded = torch.zeros(self.node_count, dtype=torch.float32, device=device)
        self.delay_steps = int(round(constants.lif.fixed_delay_ms / constants.dt_ms))
        self.refractory_steps = int(round(constants.lif.refractory_ms / constants.dt_ms))
        self.queue = [
            torch.empty(0, dtype=torch.int64, device=device) for _ in range(self.delay_steps + 1)
        ]
        self.step_index = 0
        self.membrane_decay, self.synaptic_decay, self.membrane_coupling = _linear_factors(
            constants.lif, constants.dt_ms
        )
        self.graded_decay = math.exp(-constants.dt_ms / constants.graded_tau_ms)

    def _projection(self, source: Any) -> Any:
        import torch

        return torch.sparse.mm(self.matrix, source[:, None]).flatten() * self.incoming_inverse

    def step(
        self,
        *,
        forced_event_indices: Sequence[int] | np.ndarray = (),
        external_graded: np.ndarray | None = None,
    ) -> dict[str, float | int]:
        import torch

        c = self.constants
        slot = self.step_index % len(self.queue)
        arriving_sources = self.queue[slot]
        self.queue[slot] = torch.empty(0, dtype=torch.int64, device=self.device)

        self.refractory[self.refractory > 0] -= 1
        eligible = self.event_mask & (self.refractory == 0)
        previous_v = self.v[eligible]
        previous_g = self.g[eligible]
        self.v[eligible] = c.lif.v_rest_mV + (
            (previous_v - c.lif.v_rest_mV) * self.membrane_decay
            + previous_g * self.membrane_coupling
        )
        self.g[eligible] = previous_g * self.synaptic_decay
        generated = torch.nonzero(eligible & (self.v > c.lif.threshold_mV)).flatten()

        event_vector = torch.zeros(self.node_count, dtype=torch.float32, device=self.device)
        if arriving_sources.numel():
            event_vector[arriving_sources] = 1.0
        event_projection = self._projection(event_vector) if arriving_sources.numel() else event_vector
        self.g[self.event_mask] += c.event_to_event_mV * event_projection[self.event_mask]

        if generated.numel():
            self.v[generated] = c.lif.reset_mV
            self.g[generated] = 0.0
            self.refractory[generated] = self.refractory_steps

        forced = torch.as_tensor(forced_event_indices, dtype=torch.int64, device=self.device)
        if forced.numel():
            if int(forced.min()) < 0 or int(forced.max()) >= self.node_count:
                raise TypedHybridRuntimeError("forced event index is outside the graph")
            if not bool(torch.all(self.event_mask[forced]).item()):
                raise TypedHybridRuntimeError("forced event was assigned to a non-event population")
        emitted = torch.unique(torch.cat((generated, forced)))
        destination = (self.step_index + self.delay_steps) % len(self.queue)
        self.queue[destination] = emitted

        graded_source = torch.where(self.graded_mask, self.graded, torch.zeros_like(self.graded))
        graded_projection = self._projection(graded_source) if bool(self.graded_mask.any()) else graded_source
        if external_graded is None:
            external = torch.zeros(self.node_count, dtype=torch.float32, device=self.device)
        else:
            external = torch.as_tensor(external_graded, dtype=torch.float32, device=self.device)
            if external.shape != (self.node_count,):
                raise TypedHybridRuntimeError("external graded vector has the wrong shape")
            if bool(torch.any(external[~self.graded_mask] != 0).item()):
                raise TypedHybridRuntimeError("graded input was applied outside graded populations")
        proposal = torch.tanh(
            c.graded_to_graded * graded_projection
            + c.event_to_graded * event_projection
            + external
        )
        self.graded[self.graded_mask] = (
            self.graded_decay * self.graded[self.graded_mask]
            + (1.0 - self.graded_decay) * proposal[self.graded_mask]
        )
        self.graded[~self.graded_mask] = 0.0
        self.g[self.event_mask] += c.graded_to_event_mV * graded_projection[self.event_mask]
        self.g[~self.event_mask] = 0.0
        self.v[~self.event_mask] = c.lif.v_rest_mV
        self.refractory[~self.event_mask] = 0

        metrics = {
            "step": self.step_index,
            "forced_events": int(forced.numel()),
            "generated_events": int(generated.numel()),
            "delivered_event_sources": int(arriving_sources.numel()),
            "event_to_event_l1": float(torch.sum(torch.abs(event_projection[self.event_mask])).item()),
            "event_to_graded_l1": float(torch.sum(torch.abs(event_projection[self.graded_mask])).item()),
            "graded_to_event_l1": float(torch.sum(torch.abs(graded_projection[self.event_mask])).item()),
            "graded_to_graded_l1": float(torch.sum(torch.abs(graded_projection[self.graded_mask])).item()),
            "event_state_max_abs": float(torch.max(torch.abs(self.g[self.event_mask])).item())
            if bool(self.event_mask.any())
            else 0.0,
            "graded_state_max_abs": float(torch.max(torch.abs(self.graded[self.graded_mask])).item())
            if bool(self.graded_mask.any())
            else 0.0,
        }
        self.step_index += 1
        return metrics

    def state_arrays(self) -> dict[str, np.ndarray]:
        return {
            "v": self.v.detach().cpu().numpy().copy(),
            "g": self.g.detach().cpu().numpy().copy(),
            "refractory": self.refractory.detach().cpu().numpy().copy(),
            "graded": self.graded.detach().cpu().numpy().copy(),
        }


def _micro_graph() -> tuple[sparse.csr_matrix, np.ndarray]:
    # 0(event)->1(event), 0(event)->2(graded), 2(graded)->1(event),
    # and 2(graded)->3(graded): all four boundary classes are present.
    rows = np.asarray([1, 2, 1, 3], dtype=np.int32)
    cols = np.asarray([0, 0, 2, 2], dtype=np.int32)
    values = np.asarray([1.0, 2.0, -1.0, 3.0], dtype=np.float32)
    matrix = sparse.csr_matrix((values, (rows, cols)), shape=(4, 4))
    return matrix, np.asarray([EVENT, EVENT, GRADED, GRADED], dtype=np.int8)


def run_micro_oracle(constants: DiagnosticConstants, device: str) -> dict[str, Any]:
    graph, assignment = _micro_graph()
    runtime = TorchTypedHybridRuntime(graph, assignment, constants, device)
    traces: list[dict[str, float | int]] = []
    states: list[dict[str, np.ndarray]] = []
    for step in range(runtime.delay_steps + 3):
        external = np.zeros(4, dtype=np.float32)
        if step == 0:
            external[2] = constants.external_graded_probe
        traces.append(
            runtime.step(
                forced_event_indices=[0] if step == 0 else [],
                external_graded=external,
            )
        )
        states.append(runtime.state_arrays())
    pre_delay = traces[: runtime.delay_steps]
    at_delay = traces[runtime.delay_steps]
    result = {
        "device": device,
        "nodes": 4,
        "edges": 4,
        "boundary_counts": boundary_edge_counts(graph, assignment),
        "delay_steps": runtime.delay_steps,
        "event_projection_zero_before_delay": all(
            row["event_to_event_l1"] == 0.0 and row["event_to_graded_l1"] == 0.0
            for row in pre_delay
        ),
        "event_projection_nonzero_at_delay": bool(
            at_delay["event_to_event_l1"] > 0.0 and at_delay["event_to_graded_l1"] > 0.0
        ),
        "graded_boundaries_nonzero": bool(
            max(row["graded_to_event_l1"] for row in traces) > 0.0
            and max(row["graded_to_graded_l1"] for row in traces) > 0.0
        ),
        "finite": bool(
            all(np.isfinite(value).all() for state in states for value in state.values())
        ),
        "final_state": {key: value.tolist() for key, value in states[-1].items()},
    }
    result["accepted"] = bool(
        result["boundary_counts"]
        == {
            "event_to_event": 1,
            "event_to_graded": 1,
            "graded_to_event": 1,
            "graded_to_graded": 1,
            "total_active_edges": 4,
        }
        and result["event_projection_zero_before_delay"]
        and result["event_projection_nonzero_at_delay"]
        and result["graded_boundaries_nonzero"]
        and result["finite"]
    )
    return result


def _verify_campaign(campaign: Mapping[str, Any]) -> dict[str, Path]:
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise TypedHybridRuntimeError("runtime sentinel cannot optimize parameters")
    if campaign.get("behavior_targets"):
        raise TypedHybridRuntimeError("runtime sentinel cannot expose named behavior")
    if campaign.get("topology_changes_allowed") is not False:
        raise TypedHybridRuntimeError("runtime sentinel cannot change topology")
    if int(campaign.get("parameter_values_promoted", -1)) != 0:
        raise TypedHybridRuntimeError("runtime sentinel cannot promote parameters")
    paths: dict[str, Path] = {}
    for key, record in campaign["frozen_inputs"].items():
        path = ROOT / str(record["path"])
        if not path.is_file():
            raise TypedHybridRuntimeError(f"missing frozen input {key}: {path}")
        observed = _sha256(path)
        if observed != str(record["sha256"]):
            raise TypedHybridRuntimeError(
                f"frozen input drift for {key}: {observed} != {record['sha256']}"
            )
        paths[key] = path
    return paths


def _load_assignments(paths: Mapping[str, Path], campaign: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    nodes = pd.read_parquet(paths["central_nodes"]).sort_values("runtime_node_index")
    nodes = nodes.loc[nodes["included_in_neural_runtime"].astype(bool)].reset_index(drop=True)
    reached = pd.read_parquet(paths["reached_populations"]).sort_values("runtime_node_index")
    expected_nodes = int(campaign["acceptance"]["expected_canonical_neurons"])
    if len(nodes) != expected_nodes or not np.array_equal(
        nodes["runtime_node_index"].to_numpy(np.int64), np.arange(expected_nodes)
    ):
        raise TypedHybridRuntimeError("canonical node order drift")
    assignment = np.full(expected_nodes, INACTIVE, dtype=np.int8)
    indices = reached["runtime_node_index"].to_numpy(np.int64)
    assignment[indices] = GRADED
    event_indices = reached.loc[reached["assignment"].eq("event_required"), "runtime_node_index"].to_numpy(np.int64)
    assignment[event_indices] = EVENT
    if len(reached) != int(campaign["acceptance"]["expected_reached_neurons"]):
        raise TypedHybridRuntimeError("reached population count drift")
    if len(event_indices) != int(campaign["acceptance"]["expected_exact_event_neurons"]):
        raise TypedHybridRuntimeError("exact event requirement count drift")
    return assignment, nodes["body_id"].to_numpy(np.int64)


def _profile_probe_indices(
    incoming: sparse.csr_matrix,
    assignment: np.ndarray,
    event_indices: np.ndarray,
    source_indices: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    forced = np.asarray(event_indices, dtype=np.int64)
    graded_presynaptic: list[np.ndarray] = []
    for target in event_indices:
        start, end = incoming.indptr[target : target + 2]
        sources = incoming.indices[start:end]
        graded_presynaptic.append(sources[assignment[sources] == GRADED])
    graded_candidates = (
        np.unique(np.concatenate(graded_presynaptic))
        if graded_presynaptic
        else np.empty(0, dtype=np.int64)
    )
    if not len(graded_candidates):
        graded_candidates = source_indices[assignment[source_indices] == GRADED]
    graded = graded_candidates[:4096]
    if not len(forced) or not len(graded):
        raise TypedHybridRuntimeError("could not construct four-boundary diagnostic probes")
    return forced, graded


def _execute_profile(
    incoming: sparse.csr_matrix,
    assignment: np.ndarray,
    constants: DiagnosticConstants,
    device: str,
    steps: int,
    forced_indices: np.ndarray,
    graded_indices: np.ndarray,
) -> dict[str, Any]:
    import torch

    gc.collect()
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)
    runtime = TorchTypedHybridRuntime(incoming, assignment, constants, device)
    boundary_counts = boundary_edge_counts(incoming, assignment)
    maxima = {
        "event_to_event_l1": 0.0,
        "event_to_graded_l1": 0.0,
        "graded_to_event_l1": 0.0,
        "graded_to_graded_l1": 0.0,
    }
    delivered_steps: list[int] = []
    external = np.zeros(len(assignment), dtype=np.float32)
    external[graded_indices] = constants.external_graded_probe
    if device.startswith("cuda"):
        torch.cuda.synchronize(device)
    started = time.perf_counter()
    trace: list[dict[str, float | int]] = []
    with torch.inference_mode():
        for step in range(steps):
            row = runtime.step(
                forced_event_indices=forced_indices if step == 0 else [],
                external_graded=external if step == 0 else None,
            )
            trace.append(row)
            if row["delivered_event_sources"]:
                delivered_steps.append(step)
            for key in maxima:
                maxima[key] = max(maxima[key], float(row[key]))
    if device.startswith("cuda"):
        torch.cuda.synchronize(device)
    elapsed = time.perf_counter() - started
    states = runtime.state_arrays()
    inactive = assignment == INACTIVE
    inactive_zero = bool(
        np.all(states["g"][inactive] == 0)
        and np.all(states["graded"][inactive] == 0)
        and np.all(states["refractory"][inactive] == 0)
        and np.all(states["v"][inactive] == constants.lif.v_rest_mV)
    )
    result = {
        "node_counts": {
            "inactive": int(np.count_nonzero(assignment == INACTIVE)),
            "event": int(np.count_nonzero(assignment == EVENT)),
            "graded": int(np.count_nonzero(assignment == GRADED)),
        },
        "boundary_edge_counts": boundary_counts,
        "steps": steps,
        "simulated_ms": steps * constants.dt_ms,
        "elapsed_seconds": elapsed,
        "steps_per_second": steps / elapsed,
        "simulated_to_wall_ratio": (steps * constants.dt_ms / 1000.0) / elapsed,
        "forced_event_sources": int(len(forced_indices)),
        "graded_probe_sources": int(len(graded_indices)),
        "first_delivered_event_step": min(delivered_steps) if delivered_steps else None,
        "boundary_projection_max_l1": maxima,
        "finite_state": bool(all(np.isfinite(value).all() for value in states.values())),
        "inactive_state_exactly_zero_or_rest": inactive_zero,
        "generated_event_count": int(sum(int(row["generated_events"]) for row in trace)),
        "state_semantic_sha256": _canonical_hash(
            {
                key: hashlib.sha256(value.tobytes()).hexdigest()
                for key, value in states.items()
            }
        ),
        "peak_gpu_bytes": int(torch.cuda.max_memory_allocated(device))
        if device.startswith("cuda")
        else None,
    }
    del runtime
    gc.collect()
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    return result


def run_sentinel(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    import torch

    campaign = _load_yaml(campaign_path)
    constants = DiagnosticConstants.from_campaign(campaign)
    constants.validate()

    print("[1/8] Verifying frozen topology, assignments, model and zero-promotion contract", flush=True)
    paths = _verify_campaign(campaign)
    incoming = sparse.load_npz(paths["incoming_graph"]).tocsr()
    mixed_assignment, body_ids = _load_assignments(paths, campaign)
    if incoming.shape != (len(body_ids), len(body_ids)):
        raise TypedHybridRuntimeError("canonical graph shape drift")
    source_rows = pd.read_csv(paths["source_terminals"])
    source_positions = np.searchsorted(body_ids, source_rows["body_id"].to_numpy(np.int64))
    if np.any(body_ids[source_positions] != source_rows["body_id"].to_numpy(np.int64)):
        raise TypedHybridRuntimeError("source terminal body mapping drift")

    print("[2/8] Running the four-boundary micro-oracle on CPU", flush=True)
    micro_cpu = run_micro_oracle(constants, "cpu")
    if not micro_cpu["accepted"]:
        raise TypedHybridRuntimeError(f"CPU micro-oracle failed: {micro_cpu}")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    micro_device = run_micro_oracle(constants, device)
    cpu_final = micro_cpu["final_state"]
    device_final = micro_device["final_state"]
    parity_error = max(
        float(np.max(np.abs(np.asarray(cpu_final[key]) - np.asarray(device_final[key]))))
        for key in cpu_final
    )
    parity_ok = parity_error <= float(campaign["acceptance"]["micro_backend_atol"])
    if not micro_device["accepted"] or not parity_ok:
        raise TypedHybridRuntimeError("micro-oracle backend parity failed")

    print("[3/8] Compiling the exact-event plus all-dual-as-graded diagnostic extreme", flush=True)
    event_indices = np.flatnonzero(mixed_assignment == EVENT)
    mixed_forced, mixed_graded = _profile_probe_indices(
        incoming, mixed_assignment, event_indices, source_positions
    )
    mixed_counts = boundary_edge_counts(incoming, mixed_assignment)
    expected_mixed = campaign["acceptance"]["expected_mixed_boundary_counts"]
    if mixed_counts != {str(k): int(v) for k, v in expected_mixed.items()}:
        raise TypedHybridRuntimeError(f"mixed boundary counts drift: {mixed_counts}")

    print(f"[4/8] Executing mixed diagnostic extreme on {device} ({len(mixed_assignment):,} nodes)", flush=True)
    steps = int(campaign["execution"]["steps"])
    mixed = _execute_profile(
        incoming,
        mixed_assignment,
        constants,
        device,
        steps,
        mixed_forced,
        mixed_graded,
    )

    print("[5/8] Compiling the all-dual-as-event diagnostic extreme", flush=True)
    all_event = mixed_assignment.copy()
    all_event[all_event == GRADED] = EVENT
    all_event_forced = source_positions[: int(campaign["execution"]["all_event_forced_sources"])]
    all_event_graded = np.empty(0, dtype=np.int64)
    all_event_counts = boundary_edge_counts(incoming, all_event)

    print(f"[6/8] Executing event diagnostic extreme on {device}", flush=True)
    event_only = _execute_profile(
        incoming,
        all_event,
        constants,
        device,
        steps,
        all_event_forced,
        all_event_graded,
    )

    print("[7/8] Applying execution, uncertainty and scientific-boundary gates", flush=True)
    mixed_projection = mixed["boundary_projection_max_l1"]
    event_projection = event_only["boundary_projection_max_l1"]
    checks = {
        "micro_all_four_boundaries_and_delay_pass": bool(micro_cpu["accepted"] and micro_device["accepted"]),
        "micro_cpu_backend_parity_pass": parity_ok,
        "mixed_profile_preserves_12_exact_event_requirements": mixed["node_counts"]["event"] == 12,
        "mixed_profile_executes_all_four_boundary_classes": all(
            float(mixed_projection[key]) > 0.0 for key in mixed_projection
        ),
        "all_event_profile_executes_event_boundary": float(event_projection["event_to_event_l1"]) > 0.0,
        "event_delivery_occurs_at_declared_delay": bool(
            mixed["first_delivered_event_step"] == int(round(constants.lif.fixed_delay_ms / constants.dt_ms))
            and event_only["first_delivered_event_step"] == int(round(constants.lif.fixed_delay_ms / constants.dt_ms))
        ),
        "both_full_graph_profiles_finite": bool(mixed["finite_state"] and event_only["finite_state"]),
        "inactive_269_neurons_remain_quiescent": bool(
            mixed["inactive_state_exactly_zero_or_rest"]
            and event_only["inactive_state_exactly_zero_or_rest"]
            and mixed["node_counts"]["inactive"] == 269
        ),
        "assignment_is_explicit_runtime_input": True,
        "dual_assignment_not_scientifically_selected": True,
        "parameter_values_promoted": False,
        "named_behavior_exposed": False,
    }
    required = [key for key in checks if key not in {"parameter_values_promoted", "named_behavior_exposed"}]
    if not all(checks[key] for key in required) or checks["parameter_values_promoted"] or checks["named_behavior_exposed"]:
        raise TypedHybridRuntimeError(f"typed/hybrid sentinel failed: {checks}")

    def semantic_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
        stable = {
            key: profile[key]
            for key in (
                "node_counts",
                "boundary_edge_counts",
                "steps",
                "simulated_ms",
                "forced_event_sources",
                "graded_probe_sources",
                "first_delivered_event_step",
                "finite_state",
                "inactive_state_exactly_zero_or_rest",
                "generated_event_count",
            )
        }
        stable["boundary_projection_nonzero"] = {
            key: float(value) > 0.0
            for key, value in profile["boundary_projection_max_l1"].items()
        }
        return stable

    summary_for_hash = {
        "campaign_id": campaign["id"],
        "frozen_input_sha256": {
            key: str(record["sha256"])
            for key, record in sorted(campaign["frozen_inputs"].items())
        },
        "backend": device,
        "micro_parity_max_abs_error": parity_error,
        "mixed": semantic_profile(mixed),
        "all_event": semantic_profile(event_only),
        "checks": checks,
        "scientific_boundary": {
            "profiles_executed": 2,
            "scientific_assignment_space_size": "2^166419",
            "higher_order_assignment_space_covered": False,
            "population_assignments_promoted": 0,
            "parameter_values_promoted": 0,
            "source_bridges_executed": 0,
            "behavior_targets_exposed": 0,
        },
    }
    semantic_hash = _canonical_hash(summary_for_hash)
    result = {
        "schema_version": 1,
        "id": "runner_result.basal_reached_typed_hybrid_runtime_sentinel.v0",
        "campaign_id": campaign["id"],
        "status": "accepted_execution_engine_two_extremes_zero_scientific_assignment_or_values",
        "completed_at": datetime.now(UTC).isoformat(),
        "command": "basal_typed_hybrid_runtime_sentinel.bat",
        "claim_label": campaign["claim_label"],
        "backend": device,
        "micro_oracle": {
            "cpu": micro_cpu,
            "selected_backend": micro_device,
            "max_abs_state_error": parity_error,
        },
        "profiles": {
            "exact_event_plus_all_dual_as_graded": mixed,
            "all_reached_as_event_candidate": event_only,
        },
        "checks": checks,
        "scientific_boundary": summary_for_hash["scientific_boundary"],
        "reproducibility_boundary": {
            "semantic_hash_includes": [
                "assignment_and_boundary_counts",
                "step_and_delay_accounting",
                "finite_and_inactive_state_gates",
                "nonzero_boundary_consumption_gates",
                "promotion_and_exposure_gates",
            ],
            "semantic_hash_excludes": [
                "elapsed_seconds",
                "steps_per_second",
                "peak_gpu_bytes",
                "raw_gpu_state_bytes",
                "raw_boundary_projection_magnitudes",
            ],
            "reason": (
                "CUDA sparse reductions may change last-place floating values with reduction order; "
                "performance and byte identity are retained diagnostically but are not semantic claims."
            ),
        },
        "semantic_result_sha256": semantic_hash,
        "next_action": (
            "Define bounded source event-process and Hz-to-graded conversion families, then execute "
            "the preregistered basal sensitivity shapes through this engine without selecting a native "
            "population assignment from numerical convenience."
        ),
    }
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.basal_reached_typed_hybrid_runtime_sentinel.v0",
        "campaign_id": campaign["id"],
        "status": "accepted_runtime_mechanics_source_bridges_and_population_assignments_still_open",
        "conclusion": (
            "The 166,431-neuron basal-reached scope now executes under an explicit arbitrary typed "
            "assignment vector. The mixed extreme exercises all four event/graded boundaries and the "
            "event extreme preserves delayed event mechanics. These two profiles are mechanics probes, "
            "not coverage of 2^166419 assignments, physiology, calibration, or behavior."
        ),
        "metrics": {
            "reached_neurons": 166431,
            "inactive_neurons": 269,
            "exact_event_requirements_preserved": 12,
            "dual_unresolved_scientific_assignments": 166419,
            "diagnostic_extremes_executed": 2,
            "boundary_classes_executed_in_mixed_profile": 4,
            "parameter_values_promoted": 0,
            "population_assignments_promoted": 0,
            "source_bridges_executed": 0,
            "behavior_targets_exposed": 0,
        },
        "reproducibility": {
            "command": "basal_typed_hybrid_runtime_sentinel.bat",
            "runner_semantic_sha256": semantic_hash,
            "derived_summary": _artifact_ref(output_root / "summary.json"),
            "semantic_boundary": "counts_delays_and_gates_not_timing_or_raw_cuda_reduction_bytes",
        },
        "next_action": result["next_action"],
    }

    print("[8/8] Writing compact versioned result and ignored full summary", flush=True)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    result_path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    evaluation_path.write_text(
        yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    print(
        f"[OK] {device}: mixed {mixed['steps_per_second']:.1f} steps/s; "
        f"event {event_only['steps_per_second']:.1f} steps/s; four boundaries exercised; "
        "zero assignment or value promoted.",
        flush=True,
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    run_sentinel()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

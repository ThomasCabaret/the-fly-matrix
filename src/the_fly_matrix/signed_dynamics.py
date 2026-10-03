from __future__ import annotations

import hashlib
import json
import math
import time
import warnings
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml
from scipy import sparse

from .connectome_benchmark import DynamicsProfile, build_graph_cache
from .ledger import ROOT
from .runtime import CentralConnectomeBox


MODEL_PATH = ROOT / "calibration" / "models" / "malecns-typed-signed-rate-v0.yaml"
PRIOR_TABLE_PATH = (
    ROOT
    / "data"
    / "derived"
    / "calibration"
    / "transmitter-sign-prior-v0"
    / "neuron-priors.parquet"
)
PRIOR_SUMMARY_PATH = PRIOR_TABLE_PATH.parent / "summary.json"
DIAGNOSTIC_PATH = (
    ROOT / "calibration" / "diagnostics" / "central-unfitted-regimes-v0.yaml"
)
INPUT_ROUTE_PATHS = tuple(
    ROOT / "data" / "derived" / "wiring" / name
    for name in (
        "basal-clamp-routes.parquet",
        "proprioception-routes.parquet",
        "mechanosensation-routes.parquet",
        "vision-routes.parquet",
        "unclassified-sensory-routes.parquet",
    )
)


class SignedDynamicsError(ValueError):
    """Raised when the signed model would hide or misinterpret a graph edge."""


@dataclass(frozen=True)
class SignedDynamicsContract:
    model_id: str
    class_ids: tuple[str, ...]
    sign_constraints: Mapping[str, str]
    probe_efficacies: Mapping[str, float]
    raw: Mapping[str, Any]

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> "SignedDynamicsContract":
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("status") != "candidate_executable_unfitted":
            raise SignedDynamicsError("Signed dynamics contract must be an unfitted candidate")
        classes = raw.get("parameterization", {}).get("synaptic_parameters", {}).get(
            "classes"
        )
        if not isinstance(classes, list) or not classes:
            raise SignedDynamicsError("Signed dynamics contract needs transmitter classes")
        class_ids = tuple(str(item["id"]) for item in classes)
        if len(class_ids) != len(set(class_ids)):
            raise SignedDynamicsError("Transmitter class identifiers must be unique")
        constraints = {str(item["id"]): str(item["sign_constraint"]) for item in classes}
        probe = raw.get("validation_probe", {}).get("class_efficacies")
        if not isinstance(probe, dict) or set(probe) != set(class_ids):
            raise SignedDynamicsError("The structural probe must cover every transmitter class")
        probe_values = {str(key): float(value) for key, value in probe.items()}
        _validate_efficacies(class_ids, constraints, probe_values, require_nonzero=True)
        if raw["parameterization"].get("fitted_degrees_of_freedom") != len(class_ids) + 3:
            raise SignedDynamicsError("Declared model dimension does not match its parameters")
        return cls(str(raw["id"]), class_ids, constraints, probe_values, raw)


@dataclass(frozen=True)
class SignedRuntimeAssets:
    graph: Any
    contract: SignedDynamicsContract
    neuron_class_indices: np.ndarray
    input_indices: np.ndarray


def _validate_efficacies(
    class_ids: tuple[str, ...],
    sign_constraints: Mapping[str, str],
    efficacies: Mapping[str, float],
    *,
    require_nonzero: bool = False,
) -> np.ndarray:
    if set(efficacies) != set(class_ids):
        missing = sorted(set(class_ids) - set(efficacies))
        extra = sorted(set(efficacies) - set(class_ids))
        raise SignedDynamicsError(f"Class efficacy mismatch: missing={missing}, extra={extra}")
    values = np.asarray([efficacies[item] for item in class_ids], dtype=np.float32)
    if not np.isfinite(values).all():
        raise SignedDynamicsError("Class efficacies must be finite")
    if require_nonzero and np.any(values == 0):
        raise SignedDynamicsError("The structural probe must exercise every class non-trivially")
    for index, class_id in enumerate(class_ids):
        constraint = sign_constraints[class_id]
        if constraint == "positive_prior" and values[index] <= 0:
            raise SignedDynamicsError(f"{class_id} violates its positive typed prior")
        if constraint == "negative_prior" and values[index] >= 0:
            raise SignedDynamicsError(f"{class_id} violates its negative typed prior")
        if constraint not in {"positive_prior", "negative_prior", "unresolved_signed"}:
            raise SignedDynamicsError(f"Unsupported sign constraint for {class_id}: {constraint}")
    return values


def load_neuron_classes(
    body_ids: np.ndarray,
    contract: SignedDynamicsContract,
    prior_path: Path = PRIOR_TABLE_PATH,
) -> tuple[np.ndarray, np.ndarray]:
    frame = pd.read_parquet(
        prior_path,
        columns=["body_id", "runtime_node_index", "effective_transmitter", "sign_code"],
    ).sort_values("runtime_node_index")
    observed_body_ids = frame["body_id"].to_numpy(dtype=np.int64)
    if len(frame) != len(body_ids) or not np.array_equal(observed_body_ids, body_ids):
        raise SignedDynamicsError("Frozen transmitter prior does not match graph node order")
    runtime_indices = frame["runtime_node_index"].to_numpy(dtype=np.int64)
    if not np.array_equal(runtime_indices, np.arange(len(body_ids), dtype=np.int64)):
        raise SignedDynamicsError("Frozen transmitter prior runtime indices are not dense")
    class_lookup = {class_id: index for index, class_id in enumerate(contract.class_ids)}
    observed_labels = set(frame["effective_transmitter"].astype(str))
    if observed_labels != set(class_lookup):
        raise SignedDynamicsError(
            f"Transmitter class drift: expected={sorted(class_lookup)}, observed={sorted(observed_labels)}"
        )
    class_indices = frame["effective_transmitter"].map(class_lookup).to_numpy(dtype=np.uint8)
    sign_codes = frame["sign_code"].to_numpy(dtype=np.int8)
    return class_indices, sign_codes


def compile_signed_matrix(
    matrix: sparse.csr_matrix,
    neuron_class_indices: np.ndarray,
    contract: SignedDynamicsContract,
    efficacies: Mapping[str, float],
) -> sparse.csr_matrix:
    if matrix.shape[1] != len(neuron_class_indices):
        raise SignedDynamicsError("Presynaptic class vector does not match graph columns")
    values = _validate_efficacies(
        contract.class_ids, contract.sign_constraints, efficacies, require_nonzero=False
    )
    result = matrix.copy().astype(np.float32)
    result.data *= values[neuron_class_indices[result.indices]]
    return result


def numpy_signed_step(
    signed_matrix: sparse.csr_matrix,
    incoming_count_inverse: np.ndarray,
    state: np.ndarray,
    input_vector: np.ndarray,
    *,
    dt_ms: float,
    time_constant_ms: float,
    input_gain: float,
    bias: float,
) -> np.ndarray:
    scalars = np.asarray([dt_ms, time_constant_ms, input_gain, bias], dtype=np.float64)
    if not np.isfinite(scalars).all() or dt_ms <= 0 or time_constant_ms <= 0:
        raise SignedDynamicsError("Temporal parameters must be finite with positive times")
    if state.shape != input_vector.shape or state.shape != incoming_count_inverse.shape:
        raise SignedDynamicsError("State, input and normalization vectors must have equal shape")
    alpha = 1.0 - math.exp(-dt_ms / time_constant_ms)
    drive = signed_matrix.dot(state).astype(np.float32, copy=False)
    drive *= incoming_count_inverse
    proposal = np.tanh(drive + input_gain * input_vector + bias).astype(
        np.float32, copy=False
    )
    return ((1.0 - alpha) * state + alpha * proposal).astype(np.float32, copy=False)


def load_diagnostic_probe(
    probe_id: str, path: Path = DIAGNOSTIC_PATH
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("status") != "runnable_diagnostic":
        raise SignedDynamicsError("Unfitted diagnostic profile is not runnable")
    probes = raw.get("probes")
    if not isinstance(probes, dict) or probe_id not in probes:
        raise SignedDynamicsError(f"Unknown unfitted diagnostic probe: {probe_id}")
    simulation = dict(raw.get("simulation", {}))
    probe = dict(probes[probe_id])
    combined = {**simulation, **probe}
    required = {
        "backend",
        "dt_ms",
        "steps",
        "time_constant_ms",
        "input_gain",
        "bias",
        "initial_state_std",
        "perturbation_amplitude",
        "perturbation_nodes",
        "numerical_activity_threshold",
        "numerical_saturation_threshold",
        "cpu_gpu_atol",
        "cpu_gpu_rtol",
        "input_amplitude",
        "class_efficacies",
    }
    if missing := required - set(combined):
        raise SignedDynamicsError(f"Diagnostic probe omits fields: {sorted(missing)}")
    return raw, combined


def _declared_input_body_ids() -> np.ndarray:
    frames = []
    for path in INPUT_ROUTE_PATHS:
        if not path.is_file():
            raise FileNotFoundError(f"Declared CNS input routes are absent: {path}")
        frames.append(pd.read_parquet(path, columns=["target_body_id"]))
    body_ids = np.sort(
        pd.concat(frames, ignore_index=True)["target_body_id"]
        .drop_duplicates()
        .to_numpy(dtype=np.int64)
    )
    if len(body_ids) != 17_884:
        raise SignedDynamicsError(f"Expected 17,884 declared CNS inputs, got {len(body_ids)}")
    return body_ids


@lru_cache(maxsize=1)
def load_signed_runtime_assets() -> SignedRuntimeAssets:
    contract = SignedDynamicsContract.load()
    graph = build_graph_cache(
        CentralConnectomeBox.from_generated_wiring(), DynamicsProfile.load(), scope="full"
    )
    class_indices, _ = load_neuron_classes(graph.body_ids, contract)
    input_body_ids = _declared_input_body_ids()
    input_indices = np.searchsorted(graph.body_ids, input_body_ids)
    if not np.array_equal(graph.body_ids[input_indices], input_body_ids):
        raise SignedDynamicsError("Declared CNS inputs do not all belong to the runtime graph")
    return SignedRuntimeAssets(graph, contract, class_indices, input_indices)


def characterize_unfitted_regime(probe_id: str, seed: int) -> dict[str, bool | int | float | str]:
    """Measure a preregistered full-graph regime without selecting parameter values."""
    import torch

    _, probe = load_diagnostic_probe(probe_id)
    assets = load_signed_runtime_assets()
    signed = compile_signed_matrix(
        assets.graph.matrix,
        assets.neuron_class_indices,
        assets.contract,
        probe["class_efficacies"],
    )
    device = str(probe["backend"])
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise SignedDynamicsError("CUDA diagnostic requested but torch.cuda.is_available() is false")

    rng = np.random.default_rng(seed)
    node_count = len(assets.graph.body_ids)
    initial = rng.normal(0.0, float(probe["initial_state_std"]), node_count).astype(
        np.float32
    )
    input_vector = np.zeros(node_count, dtype=np.float32)
    terminal_values = rng.normal(0.0, 1.0, len(assets.input_indices)).astype(np.float32)
    terminal_rms = float(np.sqrt(np.mean(np.square(terminal_values))))
    if terminal_rms > 0:
        terminal_values /= terminal_rms
    input_vector[assets.input_indices] = terminal_values * float(probe["input_amplitude"])
    perturbed = initial.copy()
    perturbation_nodes = int(probe["perturbation_nodes"])
    selected = rng.choice(node_count, size=perturbation_nodes, replace=False)
    perturbation = rng.choice(np.asarray([-1.0, 1.0], dtype=np.float32), perturbation_nodes)
    perturbed[selected] += perturbation * float(probe["perturbation_amplitude"])
    initial_perturbation_norm = float(np.linalg.norm(perturbed - initial))
    if initial_perturbation_norm == 0:
        raise SignedDynamicsError("Diagnostic perturbation has zero norm")

    temporal = {
        "dt_ms": float(probe["dt_ms"]),
        "time_constant_ms": float(probe["time_constant_ms"]),
        "input_gain": float(probe["input_gain"]),
        "bias": float(probe["bias"]),
    }
    cpu_first = np.stack(
        [
            numpy_signed_step(
                signed,
                assets.graph.incoming_inverse,
                initial,
                input_vector,
                **temporal,
            ),
            numpy_signed_step(
                signed,
                assets.graph.incoming_inverse,
                perturbed,
                input_vector,
                **temporal,
            ),
        ],
        axis=1,
    )

    crow = torch.from_numpy(signed.indptr.astype(np.int32, copy=False)).to(device)
    col = torch.from_numpy(signed.indices.astype(np.int32, copy=False)).to(device)
    data = torch.from_numpy(signed.data.astype(np.float32, copy=False)).to(device)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Sparse CSR tensor support is in beta state")
        matrix = torch.sparse_csr_tensor(
            crow,
            col,
            data,
            size=signed.shape,
            dtype=torch.float32,
            device=device,
            check_invariants=False,
        )
    inverse = torch.from_numpy(assets.graph.incoming_inverse).to(device)
    stimulus = torch.from_numpy(input_vector).to(device)[:, None]
    states = torch.from_numpy(np.stack([initial, perturbed], axis=1)).to(device)
    alpha = 1.0 - math.exp(-temporal["dt_ms"] / temporal["time_constant_ms"])
    active_threshold = float(probe["numerical_activity_threshold"])
    saturation_threshold = float(probe["numerical_saturation_threshold"])
    persistent_quiescent = torch.ones(node_count, dtype=torch.bool, device=device)
    persistent_saturated = torch.ones(node_count, dtype=torch.bool, device=device)
    perturbation_gains: list[float] = []
    first_gpu: np.ndarray | None = None
    if device.startswith("cuda"):
        torch.cuda.synchronize(device)
    started = time.perf_counter()
    with torch.inference_mode():
        for step in range(int(probe["steps"])):
            drive = torch.sparse.mm(matrix, states) * inverse[:, None]
            proposal = torch.tanh(
                drive + temporal["input_gain"] * stimulus + temporal["bias"]
            )
            states = (1.0 - alpha) * states + alpha * proposal
            base_abs = torch.abs(states[:, 0])
            persistent_quiescent &= base_abs < active_threshold
            persistent_saturated &= base_abs > saturation_threshold
            perturbation_gains.append(
                float(
                    torch.linalg.vector_norm(states[:, 1] - states[:, 0]).item()
                    / initial_perturbation_norm
                )
            )
            if step == 0:
                first_gpu = states.detach().cpu().numpy()
    if device.startswith("cuda"):
        torch.cuda.synchronize(device)
    elapsed = time.perf_counter() - started
    final = states[:, 0]
    finite_fraction = float(torch.mean(torch.isfinite(final).to(torch.float32)).item())
    final_abs = torch.abs(final)
    metrics: dict[str, bool | int | float | str] = {
        "probe_id": probe_id,
        "backend": device,
        "steps_completed": int(probe["steps"]),
        "simulated_ms": float(probe["steps"]) * temporal["dt_ms"],
        "input_terminals": int(len(assets.input_indices)),
        "finite_state_fraction": finite_fraction,
        "final_active_fraction": float(
            torch.mean((final_abs >= active_threshold).to(torch.float32)).item()
        ),
        "final_saturated_fraction": float(
            torch.mean((final_abs > saturation_threshold).to(torch.float32)).item()
        ),
        "persistently_quiescent_fraction": float(
            torch.mean(persistent_quiescent.to(torch.float32)).item()
        ),
        "persistently_saturated_fraction": float(
            torch.mean(persistent_saturated.to(torch.float32)).item()
        ),
        "final_state_mean": float(torch.mean(final).item()),
        "final_state_std": float(torch.std(final, unbiased=False).item()),
        "final_max_abs": float(torch.max(final_abs).item()),
        "perturbation_peak_gain": float(max(perturbation_gains)),
        "perturbation_final_gain": float(perturbation_gains[-1]),
        "perturbation_peak_step": int(np.argmax(perturbation_gains) + 1),
        "perturbation_stable_half_recovery_step": int(
            next(
                (
                    index + 1
                    for index in range(len(perturbation_gains))
                    if max(perturbation_gains[index:]) <= 0.5
                ),
                -1,
            )
        ),
        "measured_steps_per_second": float(probe["steps"]) / elapsed,
        "simulated_to_wall_clock_ratio": (
            float(probe["steps"]) * temporal["dt_ms"] / 1000.0 / elapsed
        ),
    }
    if first_gpu is None:
        raise SignedDynamicsError("Diagnostic did not execute its first step")
    difference = np.abs(cpu_first - first_gpu)
    metrics["cpu_gpu_max_abs_error"] = float(difference.max())
    metrics["cpu_gpu_agreement"] = bool(
        np.allclose(
            cpu_first,
            first_gpu,
            atol=float(probe["cpu_gpu_atol"]),
            rtol=float(probe["cpu_gpu_rtol"]),
        )
    )
    for class_index, class_id in enumerate(assets.contract.class_ids):
        mask = torch.from_numpy(assets.neuron_class_indices == class_index).to(device)
        class_values = final[mask]
        safe_id = class_id.replace("-", "_")
        metrics[f"final_rms_{safe_id}"] = float(
            torch.sqrt(torch.mean(torch.square(class_values))).item()
        )
        metrics[f"final_active_fraction_{safe_id}"] = float(
            torch.mean((torch.abs(class_values) >= active_threshold).to(torch.float32)).item()
        )
    finite_metrics = [
        value
        for value in metrics.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    metrics["all_metrics_finite"] = bool(np.isfinite(finite_metrics).all())
    del matrix, crow, col, data, inverse, stimulus, states
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    return metrics


def validate_full_graph_contract() -> dict[str, bool | int | str]:
    """Validate exhaustive class assignment without accepting any calibration value."""
    contract = SignedDynamicsContract.load()
    profile = DynamicsProfile.load()
    graph = build_graph_cache(CentralConnectomeBox.from_generated_wiring(), profile, scope="full")
    class_indices, sign_codes = load_neuron_classes(graph.body_ids, contract)
    edge_class_indices = class_indices[graph.matrix.indices]
    edge_counts = np.bincount(edge_class_indices, minlength=len(contract.class_ids))
    typed_positive = int(edge_counts[contract.class_ids.index("acetylcholine")])
    typed_negative = int(edge_counts[contract.class_ids.index("gaba")])
    unknown_context = int(graph.matrix.nnz - typed_positive - typed_negative)
    probe_values = _validate_efficacies(
        contract.class_ids,
        contract.sign_constraints,
        contract.probe_efficacies,
        require_nonzero=True,
    )
    edge_probe = probe_values[edge_class_indices]
    zero_probe_edges = int(np.count_nonzero(edge_probe == 0))
    prior_summary = json.loads(PRIOR_SUMMARY_PATH.read_text(encoding="utf-8"))
    expected = prior_summary["edge_accounting"]["edge_counts_by_prior"]
    if typed_positive != int(expected["excitatory_prior"]):
        raise SignedDynamicsError("ACh edge count differs from the frozen prior summary")
    if typed_negative != int(expected["inhibitory_prior"]):
        raise SignedDynamicsError("GABA edge count differs from the frozen prior summary")
    if unknown_context != int(expected["unknown_or_context_dependent"]):
        raise SignedDynamicsError("Unknown/context edge count differs from the frozen prior summary")
    if np.any(sign_codes[class_indices == contract.class_ids.index("acetylcholine")] != 1):
        raise SignedDynamicsError("ACh neuron signs drifted from the typed prior")
    if np.any(sign_codes[class_indices == contract.class_ids.index("gaba")] != -1):
        raise SignedDynamicsError("GABA neuron signs drifted from the typed prior")
    semantic = hashlib.sha256()
    semantic.update("\n".join(contract.class_ids).encode("utf-8"))
    semantic.update(class_indices.tobytes())
    semantic.update(np.asarray(edge_counts, dtype="<i8").tobytes())
    semantic.update(prior_summary["semantic_prior_sha256"].encode("ascii"))
    return {
        "canonical_neurons": int(len(graph.body_ids)),
        "runtime_edges": int(graph.matrix.nnz),
        "transmitter_classes": len(contract.class_ids),
        "class_mapped_edges": int(edge_counts.sum()),
        "typed_excitatory_edges": typed_positive,
        "typed_inhibitory_edges": typed_negative,
        "unknown_or_context_edges": unknown_context,
        "zero_probe_edges": zero_probe_edges,
        "all_classes_have_neurons": bool(np.all(np.bincount(class_indices, minlength=len(contract.class_ids)) > 0)),
        "semantic_contract_sha256": semantic.hexdigest(),
    }

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
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

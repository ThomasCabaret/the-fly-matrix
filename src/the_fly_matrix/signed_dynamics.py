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
from scipy.stats import qmc

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
FIT_CAMPAIGN_PATH = (
    ROOT / "calibration" / "campaigns" / "technical-neural-dynamics-pilot-v0.yaml"
)
MOTOR_SENSITIVITY_PATH = (
    ROOT / "calibration" / "diagnostics" / "central-ensemble-motor-sensitivity-v0.yaml"
)
TIMESTEP_CONVERGENCE_PATH = (
    ROOT / "calibration" / "diagnostics" / "central-timestep-convergence-v0.yaml"
)
TIMESTEP_CONVERGENCE_V1_PATH = (
    ROOT / "calibration" / "diagnostics" / "central-timestep-convergence-v1.yaml"
)
MOTOR_ROUTE_PATH = ROOT / "data" / "derived" / "wiring" / "motor-routes.parquet"
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
    motor_indices: np.ndarray


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


def load_fit_campaign(path: Path = FIT_CAMPAIGN_PATH) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("status") != "runnable":
        raise SignedDynamicsError("Technical dynamics fitting campaign is not runnable")
    if raw.get("claim_label") != "TRAINED TECHNICAL STABILITY PILOT / NOT PHYSIOLOGY / NO BEHAVIOR":
        raise SignedDynamicsError("Technical dynamics campaign lost its claim boundary")
    method = raw.get("method", {})
    order = method.get("parameter_order")
    bounds = method.get("bounds")
    if not isinstance(order, list) or len(order) != 12 or not isinstance(bounds, dict):
        raise SignedDynamicsError("Technical dynamics campaign needs twelve ordered bounds")
    if set(order) != set(bounds):
        raise SignedDynamicsError("Technical dynamics parameter order and bounds differ")
    splits = raw.get("scenario_splits", {})
    if not splits.get("train") or not splits.get("validation"):
        raise SignedDynamicsError("Technical dynamics campaign needs train and validation scenarios")
    if splits.get("diagnostic") or splits.get("held_out"):
        raise SignedDynamicsError("Pilot fitting cannot consume diagnostic or held-out scenarios")
    return raw


def _transform_unit_value(value: float, specification: Mapping[str, Any]) -> float:
    transform = str(specification.get("transform"))
    if transform == "linear":
        lower = float(specification["lower"])
        upper = float(specification["upper"])
        return lower + value * (upper - lower)
    if transform == "log":
        lower = float(specification["lower"])
        upper = float(specification["upper"])
        return math.exp(math.log(lower) + value * (math.log(upper) - math.log(lower)))
    if transform in {"positive_log", "negative_log"}:
        lower = float(specification["lower_abs"])
        upper = float(specification["upper_abs"])
        magnitude = math.exp(
            math.log(lower) + value * (math.log(upper) - math.log(lower))
        )
        return magnitude if transform == "positive_log" else -magnitude
    if transform == "signed_log":
        lower = float(specification["lower_abs"])
        upper = float(specification["upper_abs"])
        sign = -1.0 if value < 0.5 else 1.0
        local = value * 2.0 if value < 0.5 else (value - 0.5) * 2.0
        magnitude = math.exp(
            math.log(lower) + local * (math.log(upper) - math.log(lower))
        )
        return sign * magnitude
    raise SignedDynamicsError(f"Unsupported search transform: {transform}")


def generate_pilot_candidate(
    candidate_index: int, path: Path = FIT_CAMPAIGN_PATH
) -> dict[str, float]:
    """Reconstruct one immutable low-discrepancy candidate from the campaign recipe."""
    raw = load_fit_campaign(path)
    method = raw["method"]
    count = int(method["candidate_count"])
    if not 0 <= candidate_index < count:
        raise SignedDynamicsError(
            f"Candidate index {candidate_index} is outside the declared 0..{count - 1} range"
        )
    if count <= 0 or count & (count - 1):
        raise SignedDynamicsError("Sobol candidate count must be a positive power of two")
    order = tuple(str(item) for item in method["parameter_order"])
    sampler = qmc.Sobol(d=len(order), scramble=True, seed=int(method["sobol_seed"]))
    samples = sampler.random_base2(m=int(math.log2(count)))
    candidate = {
        name: _transform_unit_value(
            float(samples[candidate_index, index]), method["bounds"][name]
        )
        for index, name in enumerate(order)
    }
    contract = SignedDynamicsContract.load()
    _validate_efficacies(
        contract.class_ids,
        contract.sign_constraints,
        {class_id: candidate[class_id] for class_id in contract.class_ids},
    )
    return candidate


def load_motor_sensitivity_protocol(
    path: Path = MOTOR_SENSITIVITY_PATH,
) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("status") != "runnable_diagnostic":
        raise SignedDynamicsError("Motor-sensitivity protocol is not runnable")
    if raw.get("claim_label") != (
        "CENTRAL ENSEMBLE SENSITIVITY / DIAGNOSTIC ONLY / "
        "NO SELECTION / NO BEHAVIOR"
    ):
        raise SignedDynamicsError("Motor-sensitivity protocol lost its claim boundary")
    candidates = raw.get("candidate_indices")
    if candidates != list(range(32)):
        raise SignedDynamicsError("Motor sensitivity must account for all 32 pilot members")
    scenarios = raw.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) < 2:
        raise SignedDynamicsError("Motor sensitivity needs at least two scenarios")
    scenario_ids = [item.get("id") for item in scenarios if isinstance(item, dict)]
    if len(scenario_ids) != len(scenarios) or len(set(scenario_ids)) != len(scenarios):
        raise SignedDynamicsError("Motor-sensitivity scenario ids must be unique")
    simulation = raw.get("simulation")
    required = {
        "backend",
        "dt_ms",
        "steps",
        "response_window_steps",
        "initial_state_std",
        "near_zero_response_rms",
        "semantic_response_quantization",
    }
    if not isinstance(simulation, dict) or required - set(simulation):
        raise SignedDynamicsError("Motor-sensitivity simulation contract is incomplete")
    if int(simulation["response_window_steps"]) > int(simulation["steps"]):
        raise SignedDynamicsError("Response window cannot exceed the simulated horizon")
    bands = raw.get("descriptive_bands")
    if not isinstance(bands, dict) or set(bands) != {
        "pattern_cosine_distance_p90",
        "amplitude_p90_to_p10_ratio",
    }:
        raise SignedDynamicsError("Motor-sensitivity descriptive bands are incomplete")
    if raw.get("selection_policy") != "forbidden":
        raise SignedDynamicsError("Motor sensitivity must forbid candidate selection")
    return raw


def load_timestep_convergence_protocol(
    path: Path = TIMESTEP_CONVERGENCE_PATH,
) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("status") != "runnable_constraint":
        raise SignedDynamicsError("Timestep-convergence protocol is not runnable")
    if raw.get("claim_label") != (
        "TRAINED TECHNICAL NUMERICAL CONSISTENCY / NO PHYSIOLOGY / NO BEHAVIOR"
    ):
        raise SignedDynamicsError("Timestep-convergence protocol lost its claim boundary")
    if raw.get("candidate_indices") != list(range(32)):
        raise SignedDynamicsError("Timestep convergence must account for all pilot members")
    simulation = raw.get("simulation")
    required = {
        "backend",
        "horizon_ms",
        "response_window_ms",
        "timestep_ms",
        "reference_timestep_ms",
        "initial_state_std",
        "near_zero_response_rms",
    }
    if not isinstance(simulation, dict) or required - set(simulation):
        raise SignedDynamicsError("Timestep-convergence simulation contract is incomplete")
    timesteps = [float(item) for item in simulation["timestep_ms"]]
    if timesteps != [5.0, 2.5, 1.25] or float(simulation["reference_timestep_ms"]) != 1.25:
        raise SignedDynamicsError("Timestep-convergence levels drifted from the locked protocol")
    horizon = float(simulation["horizon_ms"])
    window = float(simulation["response_window_ms"])
    if not 0 < window <= horizon:
        raise SignedDynamicsError("Timestep response window must fit inside the horizon")
    for timestep in timesteps:
        if not math.isclose(horizon / timestep, round(horizon / timestep)):
            raise SignedDynamicsError("Horizon must contain an integer number of steps")
        if not math.isclose(window / timestep, round(window / timestep)):
            raise SignedDynamicsError("Response window must contain an integer number of steps")
    scenarios = raw.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != 3:
        raise SignedDynamicsError("Timestep convergence needs three locked scenarios")
    scenario_ids = [item.get("id") for item in scenarios if isinstance(item, dict)]
    if len(scenario_ids) != 3 or len(set(scenario_ids)) != 3:
        raise SignedDynamicsError("Timestep-convergence scenario ids must be unique")
    thresholds = raw.get("acceptance_thresholds")
    required_thresholds = {
        "full_response_relative_l2",
        "motor_response_relative_l2",
        "motor_pattern_cosine_distance",
        "monotonic_refinement_required_for_all_scenarios",
        "near_zero_reference_responses_allowed",
    }
    allowed_thresholds = required_thresholds | {"monotonic_relative_l2_floor"}
    if (
        not isinstance(thresholds, dict)
        or required_thresholds - set(thresholds)
        or set(thresholds) - allowed_thresholds
    ):
        raise SignedDynamicsError("Timestep-convergence thresholds are incomplete")
    if raw.get("ranking_policy") != "none":
        raise SignedDynamicsError("Timestep convergence cannot rank passing candidates")
    floor = float(simulation.get("monotonic_relative_l2_floor", 0.0))
    if floor < 0:
        raise SignedDynamicsError("Monotonic numerical floor cannot be negative")
    return raw


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


def _declared_motor_indices(body_ids: np.ndarray) -> np.ndarray:
    if not MOTOR_ROUTE_PATH.is_file():
        raise FileNotFoundError(f"Declared motor routes are absent: {MOTOR_ROUTE_PATH}")
    frame = pd.read_parquet(MOTOR_ROUTE_PATH, columns=["source_body_id"])
    motor_body_ids = np.sort(frame["source_body_id"].drop_duplicates().to_numpy(dtype=np.int64))
    if len(frame) != 815 or len(motor_body_ids) != 815:
        raise SignedDynamicsError(
            f"Expected 815 unique declared motor outputs, got {len(frame)} rows and "
            f"{len(motor_body_ids)} unique ids"
        )
    indices = np.searchsorted(body_ids, motor_body_ids)
    if np.any(indices >= len(body_ids)) or not np.array_equal(body_ids[indices], motor_body_ids):
        raise SignedDynamicsError("Declared motor outputs do not all belong to the runtime graph")
    return indices.astype(np.int64, copy=False)


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
    motor_indices = _declared_motor_indices(graph.body_ids)
    return SignedRuntimeAssets(
        graph, contract, class_indices, input_indices, motor_indices
    )


def _descriptive_band(value: float, thresholds: Mapping[str, Any]) -> str:
    low_max = float(thresholds["low_max"])
    mixed_max = float(thresholds["mixed_max"])
    if not 0 <= low_max < mixed_max:
        raise SignedDynamicsError("Descriptive sensitivity bands must be ordered")
    if value <= low_max:
        return "low"
    if value <= mixed_max:
        return "mixed"
    return "high"


def summarize_motor_response_ensemble(
    responses: np.ndarray,
    scenario_ids: tuple[str, ...],
    *,
    near_zero_rms: float,
    descriptive_bands: Mapping[str, Mapping[str, Any]],
    semantic_quantization: float,
) -> dict[str, bool | int | float | str]:
    """Summarize candidate dispersion without ranking or selecting a member."""
    values = np.asarray(responses, dtype=np.float64)
    if values.ndim != 3 or values.shape[1] != len(scenario_ids):
        raise SignedDynamicsError(
            "Motor responses must have shape candidate x scenario x motor-output"
        )
    if values.shape[0] < 2 or values.shape[2] < 1:
        raise SignedDynamicsError("Motor sensitivity needs multiple candidates and outputs")
    if len(set(scenario_ids)) != len(scenario_ids):
        raise SignedDynamicsError("Motor-sensitivity scenario ids must be unique")
    if not np.isfinite(values).all():
        raise SignedDynamicsError("Motor-response ensemble contains non-finite values")
    if near_zero_rms <= 0 or semantic_quantization <= 0:
        raise SignedDynamicsError("Sensitivity numerical resolutions must be positive")

    rms = np.sqrt(np.mean(np.square(values), axis=2))
    metrics: dict[str, bool | int | float | str] = {
        "candidate_count": int(values.shape[0]),
        "scenario_count": int(values.shape[1]),
        "motor_outputs": int(values.shape[2]),
        "response_vectors_accounted": int(values.shape[0] * values.shape[1]),
        "near_zero_response_count": int(np.count_nonzero(rms <= near_zero_rms)),
        "motor_response_rms_min": float(np.min(rms)),
        "motor_response_rms_median": float(np.median(rms)),
        "motor_response_rms_max": float(np.max(rms)),
        "candidate_selection_performed": False,
    }
    pattern_p90_values: list[float] = []
    amplitude_ratio_values: list[float] = []
    upper = np.triu_indices(values.shape[0], k=1)
    for scenario_index, scenario_id in enumerate(scenario_ids):
        safe_id = scenario_id.replace("-", "_").replace(".", "_")
        scenario_vectors = values[:, scenario_index, :]
        scenario_rms = rms[:, scenario_index]
        norms = np.linalg.norm(scenario_vectors, axis=1)
        usable = norms > near_zero_rms * math.sqrt(values.shape[2])
        normalized = np.zeros_like(scenario_vectors)
        normalized[usable] = scenario_vectors[usable] / norms[usable, None]
        cosine_distance = 1.0 - np.clip(normalized @ normalized.T, -1.0, 1.0)
        pairwise = cosine_distance[upper]
        valid_pairs = usable[upper[0]] & usable[upper[1]]
        pairwise = pairwise[valid_pairs]
        if len(pairwise):
            cosine_median = float(np.median(pairwise))
            cosine_p90 = float(np.quantile(pairwise, 0.9))
            cosine_max = float(np.max(pairwise))
        else:
            cosine_median = cosine_p90 = cosine_max = 2.0
        p10 = float(np.quantile(scenario_rms, 0.1))
        p90 = float(np.quantile(scenario_rms, 0.9))
        amplitude_ratio = p90 / max(p10, near_zero_rms)
        centroid = np.mean(scenario_vectors, axis=0)
        centroid_norm = max(float(np.linalg.norm(centroid)), near_zero_rms)
        centroid_distance = np.linalg.norm(scenario_vectors - centroid, axis=1) / centroid_norm
        metrics.update(
            {
                f"{safe_id}_usable_response_count": int(np.count_nonzero(usable)),
                f"{safe_id}_response_rms_p10": p10,
                f"{safe_id}_response_rms_p90": p90,
                f"{safe_id}_amplitude_p90_to_p10_ratio": float(amplitude_ratio),
                f"{safe_id}_pairwise_cosine_distance_median": cosine_median,
                f"{safe_id}_pairwise_cosine_distance_p90": cosine_p90,
                f"{safe_id}_pairwise_cosine_distance_max": cosine_max,
                f"{safe_id}_centroid_relative_distance_median": float(
                    np.median(centroid_distance)
                ),
                f"{safe_id}_centroid_relative_distance_p90": float(
                    np.quantile(centroid_distance, 0.9)
                ),
            }
        )
        for candidate_index, candidate_rms in enumerate(scenario_rms):
            metrics[f"{safe_id}_candidate_{candidate_index:02d}_response_rms"] = float(
                candidate_rms
            )
        pattern_p90_values.append(cosine_p90)
        amplitude_ratio_values.append(float(amplitude_ratio))

    pattern_max = max(pattern_p90_values)
    amplitude_max = max(amplitude_ratio_values)
    pattern_band = _descriptive_band(
        pattern_max, descriptive_bands["pattern_cosine_distance_p90"]
    )
    amplitude_band = _descriptive_band(
        amplitude_max, descriptive_bands["amplitude_p90_to_p10_ratio"]
    )
    severity = {"low": 0, "mixed": 1, "high": 2}
    overall_band = max((pattern_band, amplitude_band), key=severity.__getitem__)
    quantized = np.rint(values / semantic_quantization).astype("<i8", copy=False)
    metrics.update(
        {
            "pattern_cosine_distance_p90_max": float(pattern_max),
            "amplitude_p90_to_p10_ratio_max": float(amplitude_max),
            "pattern_sensitivity_band": pattern_band,
            "amplitude_sensitivity_band": amplitude_band,
            "overall_sensitivity_band": overall_band,
            "semantic_response_sha256": hashlib.sha256(quantized.tobytes()).hexdigest(),
        }
    )
    numeric = [
        value
        for value in metrics.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    metrics["all_metrics_finite"] = bool(np.isfinite(numeric).all())
    return metrics


def compare_timestep_responses(
    responses_by_timestep: Mapping[float, np.ndarray],
    scenario_ids: tuple[str, ...],
    *,
    motor_indices: np.ndarray,
    near_zero_rms: float,
    monotonic_relative_l2_floor: float = 0.0,
) -> dict[str, bool | int | float | str]:
    """Compare 5 and 2.5 ms responses with the locked 1.25 ms reference."""
    expected = {5.0, 2.5, 1.25}
    if set(responses_by_timestep) != expected:
        raise SignedDynamicsError("Timestep response comparison requires 5, 2.5 and 1.25 ms")
    reference = np.asarray(responses_by_timestep[1.25], dtype=np.float64)
    if reference.ndim != 2 or reference.shape[0] != len(scenario_ids):
        raise SignedDynamicsError("Timestep responses must have shape scenario x neuron")
    indices = np.asarray(motor_indices, dtype=np.int64)
    if len(indices) != 815 or len(np.unique(indices)) != 815:
        raise SignedDynamicsError("Timestep comparison requires 815 unique motor indices")
    if np.any(indices < 0) or np.any(indices >= reference.shape[1]):
        raise SignedDynamicsError("Motor indices fall outside the central response")
    if near_zero_rms <= 0 or monotonic_relative_l2_floor < 0:
        raise SignedDynamicsError("Response thresholds must be non-negative with positive RMS")

    metrics: dict[str, bool | int | float | str] = {
        "scenario_count": len(scenario_ids),
        "motor_outputs": len(indices),
    }
    comparison_values: dict[tuple[str, float], np.ndarray] = {}
    reference_rms = np.sqrt(np.mean(np.square(reference), axis=1))
    motor_reference = reference[:, indices]
    motor_reference_rms = np.sqrt(np.mean(np.square(motor_reference), axis=1))
    metrics["near_zero_full_reference_response_count"] = int(
        np.count_nonzero(reference_rms <= near_zero_rms)
    )
    metrics["near_zero_motor_reference_response_count"] = int(
        np.count_nonzero(motor_reference_rms <= near_zero_rms)
    )

    for timestep, label in ((5.0, "coarse"), (2.5, "middle")):
        observed = np.asarray(responses_by_timestep[timestep], dtype=np.float64)
        if observed.shape != reference.shape or not np.isfinite(observed).all():
            raise SignedDynamicsError("Timestep response shape or finiteness mismatch")
        full_difference = observed - reference
        full_relative = np.linalg.norm(full_difference, axis=1) / np.maximum(
            np.linalg.norm(reference, axis=1), near_zero_rms * math.sqrt(reference.shape[1])
        )
        motor_observed = observed[:, indices]
        motor_difference = motor_observed - motor_reference
        motor_relative = np.linalg.norm(motor_difference, axis=1) / np.maximum(
            np.linalg.norm(motor_reference, axis=1), near_zero_rms * math.sqrt(len(indices))
        )
        observed_norm = np.linalg.norm(motor_observed, axis=1)
        reference_norm = np.linalg.norm(motor_reference, axis=1)
        cosine = np.sum(motor_observed * motor_reference, axis=1) / np.maximum(
            observed_norm * reference_norm, near_zero_rms**2 * len(indices)
        )
        cosine_distance = 1.0 - np.clip(cosine, -1.0, 1.0)
        comparison_values[("full", timestep)] = full_relative
        comparison_values[("motor", timestep)] = motor_relative
        for scenario_index, scenario_id in enumerate(scenario_ids):
            safe_id = scenario_id.replace("-", "_").replace(".", "_")
            metrics[f"{safe_id}_{label}_full_relative_l2"] = float(
                full_relative[scenario_index]
            )
            metrics[f"{safe_id}_{label}_motor_relative_l2"] = float(
                motor_relative[scenario_index]
            )
            metrics[f"{safe_id}_{label}_motor_cosine_distance"] = float(
                cosine_distance[scenario_index]
            )
        metrics[f"{label}_reference_full_relative_l2_max"] = float(
            np.max(full_relative)
        )
        metrics[f"{label}_reference_motor_relative_l2_max"] = float(
            np.max(motor_relative)
        )
        metrics[f"{label}_reference_motor_cosine_distance_max"] = float(
            np.max(cosine_distance)
        )

    full_coarse = comparison_values[("full", 5.0)]
    full_middle = comparison_values[("full", 2.5)]
    motor_coarse = comparison_values[("motor", 5.0)]
    motor_middle = comparison_values[("motor", 2.5)]
    full_monotonic = (full_middle <= full_coarse) | (
        (full_middle <= monotonic_relative_l2_floor)
        & (full_coarse <= monotonic_relative_l2_floor)
    )
    motor_monotonic = (motor_middle <= motor_coarse) | (
        (motor_middle <= monotonic_relative_l2_floor)
        & (motor_coarse <= monotonic_relative_l2_floor)
    )
    monotonic = full_monotonic & motor_monotonic
    metrics["monotonic_refinement_scenario_count"] = int(np.count_nonzero(monotonic))
    metrics["full_reference_response_rms_min"] = float(np.min(reference_rms))
    metrics["motor_reference_response_rms_min"] = float(np.min(motor_reference_rms))
    numeric = [
        value
        for value in metrics.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    metrics["all_metrics_finite"] = bool(np.isfinite(numeric).all())
    return metrics


def evaluate_timestep_convergence_candidate(
    candidate_index: int,
    seed: int,
    protocol_path: Path = TIMESTEP_CONVERGENCE_PATH,
) -> dict[str, bool | int | float | str]:
    """Apply a locked numerical-refinement constraint to one pilot member."""
    import torch

    protocol = load_timestep_convergence_protocol(protocol_path)
    if seed != int(protocol["evaluation_seed"]):
        raise SignedDynamicsError("Trial seed differs from the timestep protocol")
    if candidate_index not in protocol["candidate_indices"]:
        raise SignedDynamicsError("Candidate is outside the timestep protocol")
    candidate = generate_pilot_candidate(candidate_index)
    simulation = protocol["simulation"]
    scenarios = protocol["scenarios"]
    assets = load_signed_runtime_assets()
    node_count = len(assets.graph.body_ids)
    initial_columns: list[np.ndarray] = []
    input_columns: list[np.ndarray] = []
    for scenario in scenarios:
        rng = np.random.default_rng(int(scenario["rng_seed"]))
        base = rng.normal(
            0.0, float(simulation["initial_state_std"]), node_count
        ).astype(np.float32)
        stimulus = np.zeros(node_count, dtype=np.float32)
        terminal_values = rng.normal(0.0, 1.0, len(assets.input_indices)).astype(
            np.float32
        )
        terminal_values /= float(np.sqrt(np.mean(np.square(terminal_values))))
        stimulus[assets.input_indices] = terminal_values * float(
            scenario["input_amplitude"]
        )
        initial_columns.extend((base, base.copy()))
        input_columns.extend((np.zeros(node_count, dtype=np.float32), stimulus))
    initial_states = np.stack(initial_columns, axis=1)
    input_matrix = np.stack(input_columns, axis=1)

    signed = compile_signed_matrix(
        assets.graph.matrix,
        assets.neuron_class_indices,
        assets.contract,
        {class_id: candidate[class_id] for class_id in assets.contract.class_ids},
    )
    device = str(simulation["backend"])
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise SignedDynamicsError("CUDA timestep constraint requested but CUDA is unavailable")
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
    stimuli = torch.from_numpy(input_matrix).to(device)
    responses: dict[float, np.ndarray] = {}
    started = time.perf_counter()
    with torch.inference_mode():
        for timestep in [float(item) for item in simulation["timestep_ms"]]:
            steps = int(round(float(simulation["horizon_ms"]) / timestep))
            window_steps = int(round(float(simulation["response_window_ms"]) / timestep))
            alpha = 1.0 - math.exp(-timestep / float(candidate["time_constant_ms"]))
            states = torch.from_numpy(initial_states).to(device)
            response_sum = torch.zeros(
                (node_count, len(scenarios)), dtype=torch.float32, device=device
            )
            for step in range(steps):
                drive = torch.sparse.mm(matrix, states) * inverse[:, None]
                proposal = torch.tanh(
                    drive
                    + float(candidate["input_gain"]) * stimuli
                    + float(candidate["bias"])
                )
                states = (1.0 - alpha) * states + alpha * proposal
                if step >= steps - window_steps:
                    response_sum += states[:, 1::2] - states[:, 0::2]
            responses[timestep] = (response_sum / window_steps).T.cpu().numpy()
            del states, response_sum
    if device.startswith("cuda"):
        torch.cuda.synchronize(device)
    elapsed = time.perf_counter() - started
    metrics = compare_timestep_responses(
        responses,
        tuple(str(item["id"]) for item in scenarios),
        motor_indices=assets.motor_indices,
        near_zero_rms=float(simulation["near_zero_response_rms"]),
        monotonic_relative_l2_floor=float(
            simulation.get("monotonic_relative_l2_floor", 0.0)
        ),
    )
    metrics.update(
        {
            "candidate_index": int(candidate_index),
            "timestep_count": 3,
            "horizon_ms": float(simulation["horizon_ms"]),
            "input_terminals": int(len(assets.input_indices)),
            "backend": device,
            "measured_simulated_ms_per_second": float(
                len(scenarios) * float(simulation["horizon_ms"]) * 3 / elapsed
            ),
        }
    )
    del matrix, crow, col, data, inverse, stimuli
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    return metrics


def evaluate_motor_ensemble_sensitivity(
    seed: int,
) -> dict[str, bool | int | float | str]:
    """Measure raw central motor-output dispersion for every pilot member."""
    import torch

    protocol = load_motor_sensitivity_protocol()
    if seed != int(protocol["seed"]):
        raise SignedDynamicsError("Trial seed differs from the sensitivity protocol")
    simulation = protocol["simulation"]
    assets = load_signed_runtime_assets()
    node_count = len(assets.graph.body_ids)
    scenarios = protocol["scenarios"]
    state_columns: list[np.ndarray] = []
    input_columns: list[np.ndarray] = []
    for scenario in scenarios:
        rng = np.random.default_rng(int(scenario["rng_seed"]))
        base = rng.normal(
            0.0, float(simulation["initial_state_std"]), node_count
        ).astype(np.float32)
        stimulus = np.zeros(node_count, dtype=np.float32)
        terminal_values = rng.normal(0.0, 1.0, len(assets.input_indices)).astype(
            np.float32
        )
        terminal_rms = float(np.sqrt(np.mean(np.square(terminal_values))))
        if terminal_rms <= 0:
            raise SignedDynamicsError("Sensitivity terminal stimulus has zero RMS")
        terminal_values /= terminal_rms
        stimulus[assets.input_indices] = terminal_values * float(
            scenario["input_amplitude"]
        )
        state_columns.extend((base, base.copy()))
        input_columns.extend((np.zeros(node_count, dtype=np.float32), stimulus))

    initial_states = np.stack(state_columns, axis=1)
    input_matrix = np.stack(input_columns, axis=1)
    device = str(simulation["backend"])
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise SignedDynamicsError("CUDA sensitivity study requested but CUDA is unavailable")
    inverse = torch.from_numpy(assets.graph.incoming_inverse).to(device)
    stimuli = torch.from_numpy(input_matrix).to(device)
    motor_indices = torch.from_numpy(assets.motor_indices).to(device)
    response_window = int(simulation["response_window_steps"])
    steps = int(simulation["steps"])
    responses: list[np.ndarray] = []
    started = time.perf_counter()
    with torch.inference_mode():
        for candidate_index in protocol["candidate_indices"]:
            candidate = generate_pilot_candidate(int(candidate_index))
            signed = compile_signed_matrix(
                assets.graph.matrix,
                assets.neuron_class_indices,
                assets.contract,
                {
                    class_id: candidate[class_id]
                    for class_id in assets.contract.class_ids
                },
            )
            crow = torch.from_numpy(signed.indptr.astype(np.int32, copy=False)).to(device)
            col = torch.from_numpy(signed.indices.astype(np.int32, copy=False)).to(device)
            data = torch.from_numpy(signed.data.astype(np.float32, copy=False)).to(device)
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore", message="Sparse CSR tensor support is in beta state"
                )
                matrix = torch.sparse_csr_tensor(
                    crow,
                    col,
                    data,
                    size=signed.shape,
                    dtype=torch.float32,
                    device=device,
                    check_invariants=False,
                )
            states = torch.from_numpy(initial_states).to(device)
            alpha = 1.0 - math.exp(
                -float(simulation["dt_ms"]) / float(candidate["time_constant_ms"])
            )
            motor_sum = torch.zeros(
                (len(assets.motor_indices), len(scenarios)),
                dtype=torch.float32,
                device=device,
            )
            for step in range(steps):
                drive = torch.sparse.mm(matrix, states) * inverse[:, None]
                proposal = torch.tanh(
                    drive
                    + float(candidate["input_gain"]) * stimuli
                    + float(candidate["bias"])
                )
                states = (1.0 - alpha) * states + alpha * proposal
                if step >= steps - response_window:
                    motor_states = states[motor_indices]
                    motor_sum += motor_states[:, 1::2] - motor_states[:, 0::2]
            candidate_response = (motor_sum / response_window).T.cpu().numpy()
            responses.append(candidate_response)
            del matrix, crow, col, data, states, motor_sum

    if device.startswith("cuda"):
        torch.cuda.synchronize(device)
    elapsed = time.perf_counter() - started
    metrics = summarize_motor_response_ensemble(
        np.stack(responses, axis=0),
        tuple(str(item["id"]) for item in scenarios),
        near_zero_rms=float(simulation["near_zero_response_rms"]),
        descriptive_bands=protocol["descriptive_bands"],
        semantic_quantization=float(simulation["semantic_response_quantization"]),
    )
    metrics.update(
        {
            "backend": device,
            "steps_completed": steps,
            "input_terminals": int(len(assets.input_indices)),
            "measured_candidate_scenarios_per_second": float(
                len(protocol["candidate_indices"]) * len(scenarios) / elapsed
            ),
        }
    )
    del inverse, stimuli, motor_indices
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    return metrics


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


def evaluate_technical_candidate(
    candidate_index: int, seed: int
) -> dict[str, bool | int | float | str]:
    """Evaluate one preregistered pilot candidate on train and validation scenarios."""
    import torch

    campaign = load_fit_campaign()
    if seed != int(campaign["method"]["evaluation_seed"]):
        raise SignedDynamicsError("Trial seed differs from the preregistered evaluation seed")
    candidate = generate_pilot_candidate(candidate_index)
    simulation = campaign["simulation"]
    scenarios: list[tuple[str, Mapping[str, Any]]] = []
    for split in ("train", "validation"):
        scenarios.extend((split, item) for item in campaign["scenario_splits"][split])
    assets = load_signed_runtime_assets()
    efficacies = {
        class_id: candidate[class_id] for class_id in assets.contract.class_ids
    }
    signed = compile_signed_matrix(
        assets.graph.matrix,
        assets.neuron_class_indices,
        assets.contract,
        efficacies,
    )
    node_count = len(assets.graph.body_ids)
    perturbation_nodes = int(simulation["perturbation_nodes"])
    state_columns: list[np.ndarray] = []
    input_columns: list[np.ndarray] = []
    initial_norms: list[float] = []
    for _, scenario in scenarios:
        rng = np.random.default_rng(int(scenario["rng_seed"]))
        base = rng.normal(
            0.0, float(simulation["initial_state_std"]), node_count
        ).astype(np.float32)
        input_vector = np.zeros(node_count, dtype=np.float32)
        terminal_values = rng.normal(0.0, 1.0, len(assets.input_indices)).astype(
            np.float32
        )
        terminal_rms = float(np.sqrt(np.mean(np.square(terminal_values))))
        if terminal_rms <= 0:
            raise SignedDynamicsError("Scenario terminal input has zero RMS")
        terminal_values /= terminal_rms
        input_vector[assets.input_indices] = terminal_values * float(
            scenario["input_amplitude"]
        )
        perturbed = base.copy()
        selected = rng.choice(node_count, size=perturbation_nodes, replace=False)
        signs = rng.choice(
            np.asarray([-1.0, 1.0], dtype=np.float32), perturbation_nodes
        )
        perturbed[selected] += signs * float(simulation["perturbation_amplitude"])
        norm = float(np.linalg.norm(perturbed - base))
        if norm <= 0:
            raise SignedDynamicsError("Scenario perturbation has zero norm")
        state_columns.extend((base, perturbed))
        input_columns.extend((input_vector, input_vector))
        initial_norms.append(norm)

    initial_states = np.stack(state_columns, axis=1)
    input_matrix = np.stack(input_columns, axis=1)
    temporal = {
        "dt_ms": float(simulation["dt_ms"]),
        "time_constant_ms": float(candidate["time_constant_ms"]),
        "input_gain": float(candidate["input_gain"]),
        "bias": float(candidate["bias"]),
    }
    cpu_first = np.stack(
        [
            numpy_signed_step(
                signed,
                assets.graph.incoming_inverse,
                initial_states[:, column],
                input_matrix[:, column],
                **temporal,
            )
            for column in (0, 1)
        ],
        axis=1,
    )

    device = str(simulation["backend"])
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise SignedDynamicsError("CUDA fitting campaign requested but CUDA is unavailable")
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
    stimulus = torch.from_numpy(input_matrix).to(device)
    states = torch.from_numpy(initial_states).to(device)
    initial_norm_tensor = torch.tensor(initial_norms, dtype=torch.float32, device=device)
    alpha = 1.0 - math.exp(-temporal["dt_ms"] / temporal["time_constant_ms"])
    active_threshold = float(simulation["numerical_activity_threshold"])
    saturation_threshold = float(simulation["numerical_saturation_threshold"])
    scenario_count = len(scenarios)
    persistent_quiescent = torch.ones(
        (node_count, scenario_count), dtype=torch.bool, device=device
    )
    persistent_saturated = torch.ones(
        (node_count, scenario_count), dtype=torch.bool, device=device
    )
    gain_history: list[np.ndarray] = []
    first_gpu: np.ndarray | None = None
    if device.startswith("cuda"):
        torch.cuda.synchronize(device)
    started = time.perf_counter()
    with torch.inference_mode():
        for step in range(int(simulation["steps"])):
            drive = torch.sparse.mm(matrix, states) * inverse[:, None]
            proposal = torch.tanh(
                drive + temporal["input_gain"] * stimulus + temporal["bias"]
            )
            states = (1.0 - alpha) * states + alpha * proposal
            base_abs = torch.abs(states[:, 0::2])
            persistent_quiescent &= base_abs < active_threshold
            persistent_saturated &= base_abs > saturation_threshold
            delta = states[:, 1::2] - states[:, 0::2]
            gains = torch.linalg.vector_norm(delta, dim=0) / initial_norm_tensor
            gain_history.append(gains.detach().cpu().numpy())
            if step == 0:
                first_gpu = states[:, :2].detach().cpu().numpy()
    if device.startswith("cuda"):
        torch.cuda.synchronize(device)
    elapsed = time.perf_counter() - started
    final = states[:, 0::2]
    final_abs = torch.abs(final)
    finite_fraction = (
        torch.mean(torch.isfinite(final).to(torch.float32), dim=0).cpu().numpy()
    )
    active_fraction = (
        torch.mean((final_abs >= active_threshold).to(torch.float32), dim=0)
        .cpu()
        .numpy()
    )
    saturated_fraction = (
        torch.mean((final_abs > saturation_threshold).to(torch.float32), dim=0)
        .cpu()
        .numpy()
    )
    quiescent_fraction = (
        torch.mean(persistent_quiescent.to(torch.float32), dim=0).cpu().numpy()
    )
    persistent_saturated_fraction = (
        torch.mean(persistent_saturated.to(torch.float32), dim=0).cpu().numpy()
    )
    gains = np.stack(gain_history, axis=0)
    peak_gains = np.max(gains, axis=0)
    final_gains = gains[-1]
    recovery_steps = np.asarray(
        [
            next(
                (
                    index + 1
                    for index in range(len(gains))
                    if float(np.max(gains[index:, scenario_index])) <= 0.5
                ),
                -1,
            )
            for scenario_index in range(scenario_count)
        ],
        dtype=np.int32,
    )
    split_indices = {
        split: np.asarray(
            [index for index, (item_split, _) in enumerate(scenarios) if item_split == split],
            dtype=np.int32,
        )
        for split in ("train", "validation")
    }
    metrics: dict[str, bool | int | float | str] = {
        "candidate_index": int(candidate_index),
        "scenario_count": scenario_count,
        "train_scenario_count": int(len(split_indices["train"])),
        "validation_scenario_count": int(len(split_indices["validation"])),
        "steps_completed": int(simulation["steps"]),
        "input_terminals": int(len(assets.input_indices)),
        "finite_state_fraction_min": float(np.min(finite_fraction)),
        "saturated_fraction_max": float(np.max(saturated_fraction)),
        "persistently_quiescent_fraction_max": float(np.max(quiescent_fraction)),
        "persistently_saturated_fraction_max": float(
            np.max(persistent_saturated_fraction)
        ),
        "perturbation_peak_gain_max": float(np.max(peak_gains)),
        "perturbation_final_gain_max": float(np.max(final_gains)),
        "perturbation_recovery_failure_count": int(np.count_nonzero(recovery_steps < 0)),
        "perturbation_stable_half_recovery_step_max": int(
            np.max(recovery_steps) if np.all(recovery_steps >= 0) else -1
        ),
        "measured_scenario_steps_per_second": float(simulation["steps"])
        * scenario_count
        / elapsed,
        "simulated_to_wall_clock_ratio_per_scenario": (
            float(simulation["steps"])
            * float(simulation["dt_ms"])
            / 1000.0
            * scenario_count
            / elapsed
        ),
    }
    for split, indices in split_indices.items():
        metrics[f"{split}_finite_state_fraction_min"] = float(
            np.min(finite_fraction[indices])
        )
        metrics[f"{split}_active_fraction_min"] = float(
            np.min(active_fraction[indices])
        )
        metrics[f"{split}_active_fraction_max"] = float(
            np.max(active_fraction[indices])
        )
        metrics[f"{split}_saturated_fraction_max"] = float(
            np.max(saturated_fraction[indices])
        )
        metrics[f"{split}_perturbation_peak_gain_max"] = float(
            np.max(peak_gains[indices])
        )
        metrics[f"{split}_perturbation_final_gain_max"] = float(
            np.max(final_gains[indices])
        )
    if first_gpu is None:
        raise SignedDynamicsError("Fitting evaluator did not execute its first step")
    difference = np.abs(cpu_first - first_gpu)
    metrics["cpu_gpu_max_abs_error"] = float(difference.max())
    metrics["cpu_gpu_agreement"] = bool(
        np.allclose(
            cpu_first,
            first_gpu,
            atol=float(simulation["cpu_gpu_atol"]),
            rtol=float(simulation["cpu_gpu_rtol"]),
        )
    )
    for name, value in candidate.items():
        metrics[f"parameter_{name}"] = float(value)
    for class_index, class_id in enumerate(assets.contract.class_ids):
        mask = torch.from_numpy(assets.neuron_class_indices == class_index).to(device)
        class_active = torch.mean(
            (torch.abs(final[mask]) >= active_threshold).to(torch.float32), dim=0
        )
        metrics[f"class_active_fraction_min_{class_id}"] = float(
            torch.min(class_active).item()
        )
        metrics[f"class_active_fraction_max_{class_id}"] = float(
            torch.max(class_active).item()
        )
    finite_metrics = [
        value
        for value in metrics.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    metrics["all_metrics_finite"] = bool(np.isfinite(finite_metrics).all())
    del matrix, crow, col, data, inverse, stimulus, states, final
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

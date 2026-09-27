from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import time
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml
from scipy import sparse

from .ledger import ROOT
from .runtime import (
    BasalClampBox,
    CNSInputBuffer,
    CentralConnectomeBox,
    FlyBodyActuatorInterface,
    FlyBodyGroundContactSensor,
    FlyBodyLocalContactSensor,
    FlyBodyProprioceptionSensor,
    FlyBodyVisionSensor,
    MechanosensationRoutingBox,
    MechanosensationTransductionBox,
    MotorRoutingBox,
    MotorTransductionBox,
    ProprioceptionRoutingBox,
    ProprioceptionTransductionBox,
    ResidualSensoryNominalSourceBox,
    UnclassifiedSensoryRoutingBox,
    VisionRoutingBox,
    VisionTransductionBox,
)


PROFILE_PATH = ROOT / "benchmarks" / "profiles" / "malecns-benchmark-v0.yaml"
CACHE_ROOT = ROOT / "data" / "derived" / "execution-benchmark"
RUN_ROOT = ROOT / "runs" / "execution-benchmark"
CLAMP_IDS = ("clamp.olfaction", "clamp.gustation", "clamp.thermohygro")
RESIDUAL_SOURCE_IDS = (
    "source.sensory.residual.chemosensory",
    "source.sensory.residual.mechanosensory_tbc",
    "source.sensory.residual.unknown",
)


class BenchmarkError(RuntimeError):
    pass


@dataclass(frozen=True)
class DynamicsProfile:
    profile_id: str
    claim_label: str
    dt_ms: float
    leak: float
    recurrent_scale: float
    input_scale: float
    initial_state_std: float
    seed: int
    warmup_steps: int
    measured_steps: int
    reference_steps: int
    trace_stride: int
    sampled_neurons: int
    agreement_atol: float
    agreement_rtol: float
    motor_weight_std: float
    raw: Mapping[str, Any]

    @classmethod
    def load(cls, path: Path = PROFILE_PATH) -> "DynamicsProfile":
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw.get("claim_label") != "BENCHMARK ONLY / UNCALIBRATED":
            raise BenchmarkError("Benchmark profile must carry the uncalibrated claim label")
        dynamics = raw.get("dynamics", {})
        benchmark = raw.get("benchmark", {})
        interfaces = raw.get("interfaces", {})
        if dynamics.get("rule") != "leaky_tanh_v0":
            raise BenchmarkError(f"Unsupported benchmark dynamics: {dynamics.get('rule')}")
        if dynamics.get("dtype") != "float32":
            raise BenchmarkError("The v0 benchmark supports float32 only")
        if dynamics.get("edge_weight_normalization") != "incoming_l1":
            raise BenchmarkError("The v0 benchmark requires incoming_l1 normalization")
        values = {
            "dt_ms": float(dynamics["dt_ms"]),
            "leak": float(dynamics["leak"]),
            "recurrent_scale": float(dynamics["recurrent_scale"]),
            "input_scale": float(dynamics["input_scale"]),
            "initial_state_std": float(dynamics["initial_state_std"]),
            "agreement_atol": float(benchmark["agreement_atol"]),
            "agreement_rtol": float(benchmark["agreement_rtol"]),
            "motor_weight_std": float(interfaces["motor_weight_std"]),
        }
        if not 0.0 < values["leak"] <= 1.0 or values["dt_ms"] <= 0.0:
            raise BenchmarkError("Invalid temporal benchmark profile")
        return cls(
            profile_id=str(raw["id"]),
            claim_label=str(raw["claim_label"]),
            seed=int(benchmark["seed"]),
            warmup_steps=int(benchmark["warmup_steps"]),
            measured_steps=int(benchmark["measured_steps"]),
            reference_steps=int(benchmark["reference_steps"]),
            trace_stride=int(benchmark["trace_stride"]),
            sampled_neurons=int(benchmark["sampled_neurons"]),
            raw=raw,
            **values,
        )


@dataclass(frozen=True)
class CompiledInterfaces:
    input_vector: np.ndarray
    motor_node_indices: np.ndarray
    motor_decoder: np.ndarray
    motor_body_ids: np.ndarray
    actuator_names: tuple[str, ...]
    input_body_ids: np.ndarray
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class GraphCache:
    matrix: sparse.csr_matrix
    incoming_inverse: np.ndarray
    body_ids: np.ndarray
    metadata: Mapping[str, Any]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _process_rss_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except (ImportError, OSError):
        return None


def _locate(sorted_body_ids: np.ndarray, body_ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    indices = np.searchsorted(sorted_body_ids, body_ids)
    clipped = np.minimum(indices, len(sorted_body_ids) - 1)
    valid = (indices < len(sorted_body_ids)) & (sorted_body_ids[clipped] == body_ids)
    return indices, valid


def _cache_paths(scope: str) -> tuple[Path, Path, Path]:
    stem = f"malecns-{scope}-csr-v1"
    return (
        CACHE_ROOT / f"{stem}.npz",
        CACHE_ROOT / f"{stem}-incoming-inverse.npy",
        CACHE_ROOT / f"{stem}.json",
    )


def _scope_body_ids(central: CentralConnectomeBox, scope: str) -> np.ndarray:
    if scope == "full":
        return central.body_ids.copy()
    if scope != "causal-core":
        raise BenchmarkError(f"Unknown graph scope: {scope}")
    path = ROOT / "data" / "derived" / "analysis" / "cycle-topology" / "node-classification.parquet"
    if not path.is_file():
        raise BenchmarkError("Causal-core classification is absent; run cycle_topology.bat")
    frame = pd.read_parquet(path, columns=["body_id", "behavioral_relevance"])
    result = np.sort(
        frame.loc[frame["behavioral_relevance"].eq("causal_core"), "body_id"]
        .to_numpy(dtype=np.int64)
    )
    if not len(result):
        raise BenchmarkError("Causal-core scope is empty")
    return result


def build_graph_cache(
    central: CentralConnectomeBox,
    profile: DynamicsProfile,
    scope: str = "full",
    rebuild: bool = False,
) -> GraphCache:
    matrix_path, inverse_path, metadata_path = _cache_paths(scope)
    body_ids = _scope_body_ids(central, scope)
    body_digest = _sha256_bytes(body_ids.tobytes())
    expected_edges = central.expected_induced_edges if scope == "full" else None
    if not rebuild and matrix_path.is_file() and inverse_path.is_file() and metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (
            metadata.get("body_id_sha256") == body_digest
            and metadata.get("weight_file_bytes") == central.weight_path.stat().st_size
            and metadata.get("dataset_sha256") == profile.raw["dataset"]["sha256"]
        ):
            matrix = sparse.load_npz(matrix_path).tocsr()
            inverse = np.load(inverse_path)
            if matrix.shape == (len(body_ids), len(body_ids)) and inverse.shape == (len(body_ids),):
                return GraphCache(matrix, inverse.astype(np.float32, copy=False), body_ids, metadata)

    print("[CACHE] Construction du CSR canonique depuis les lots Feather...", flush=True)
    import pyarrow as pa

    fixed_allocation = expected_edges is not None
    if fixed_allocation:
        sources = np.empty(int(expected_edges), dtype=np.int32)
        targets = np.empty(int(expected_edges), dtype=np.int32)
        values = np.empty(int(expected_edges), dtype=np.float32)
    else:
        source_chunks: list[np.ndarray] = []
        target_chunks: list[np.ndarray] = []
        value_chunks: list[np.ndarray] = []
    cursor = 0
    with pa.memory_map(str(central.weight_path), "r") as mapped:
        reader = pa.ipc.open_file(mapped)
        for batch_index in range(reader.num_record_batches):
            batch = reader.get_batch(batch_index)
            pre = batch.column(0).to_numpy(zero_copy_only=False)
            post = batch.column(1).to_numpy(zero_copy_only=False)
            pre_indices, pre_valid = _locate(body_ids, pre)
            post_indices, post_valid = _locate(body_ids, post)
            valid = pre_valid & post_valid
            count = int(np.count_nonzero(valid))
            if count:
                selected_sources = pre_indices[valid].astype(np.int32, copy=False)
                selected_targets = post_indices[valid].astype(np.int32, copy=False)
                selected_values = batch.column(2).to_numpy(zero_copy_only=False)[valid].astype(
                    np.float32, copy=False
                )
                if fixed_allocation:
                    end = cursor + count
                    if end > len(sources):
                        raise BenchmarkError("Runtime edge count exceeds the declared allocation")
                    sources[cursor:end] = selected_sources
                    targets[cursor:end] = selected_targets
                    values[cursor:end] = selected_values
                else:
                    source_chunks.append(selected_sources.copy())
                    target_chunks.append(selected_targets.copy())
                    value_chunks.append(selected_values.copy())
                cursor += count
            if (batch_index + 1) % 250 == 0 or batch_index + 1 == reader.num_record_batches:
                print(
                    f"[CACHE] {batch_index + 1:,}/{reader.num_record_batches:,} lots; "
                    f"{cursor:,} arêtes retenues",
                    flush=True,
                )
    if expected_edges is not None and cursor != expected_edges:
        raise BenchmarkError(f"Runtime edge count mismatch: {cursor} != {expected_edges}")
    if not fixed_allocation:
        sources = np.concatenate(source_chunks)
        targets = np.concatenate(target_chunks)
        values = np.concatenate(value_chunks)
    matrix = sparse.coo_matrix(
        (values, (targets, sources)), shape=(len(body_ids), len(body_ids)), dtype=np.float32
    ).tocsr()
    matrix.sum_duplicates()
    matrix.sort_indices()
    if matrix.nnz != cursor:
        raise BenchmarkError(f"Duplicate graph edges collapsed unexpectedly: {cursor} -> {matrix.nnz}")
    incoming = np.asarray(matrix.sum(axis=1), dtype=np.float32).reshape(-1)
    inverse = np.zeros_like(incoming)
    nonzero = incoming > 0
    inverse[nonzero] = 1.0 / incoming[nonzero]
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    sparse.save_npz(matrix_path, matrix, compressed=False)
    np.save(inverse_path, inverse, allow_pickle=False)
    metadata = {
        "schema_version": 1,
        "scope": scope,
        "nodes": len(body_ids),
        "edges": int(matrix.nnz),
        "dtype": "float32",
        "orientation": "rows_are_postsynaptic_columns_are_presynaptic",
        "weight_semantics": "published_integer_synapse_count_cast_to_float32",
        "normalization": "incoming_l1_applied_after_sparse_matvec",
        "body_id_sha256": body_digest,
        "dataset_sha256": profile.raw["dataset"]["sha256"],
        "weight_file_bytes": central.weight_path.stat().st_size,
        "csr_bytes": int(matrix.data.nbytes + matrix.indices.nbytes + matrix.indptr.nbytes),
        "created_at": datetime.now(UTC).isoformat(),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return GraphCache(matrix, inverse, body_ids, metadata)


def _retinal_registration(box: VisionTransductionBox) -> dict[str, str]:
    available: dict[tuple[str, str], list[str]] = {}
    for row in box.physical_channels.itertuples(index=False):
        side = "L" if str(row.eye) == "left" else "R"
        available.setdefault((side, str(row.ommatidium_type)), []).append(str(row.channel_id))
    result: dict[str, str] = {}
    used: set[str] = set()
    constrained = box.columns.loc[~box.columns["expected_flybody_sample_type"].eq("any")]
    unconstrained = box.columns.loc[box.columns["expected_flybody_sample_type"].eq("any")]
    for row in constrained.itertuples(index=False):
        candidates = available[(str(row.side), str(row.expected_flybody_sample_type))]
        source = next(value for value in candidates if value not in used)
        result[str(row.column_id)] = source
        used.add(source)
    for row in unconstrained.itertuples(index=False):
        eye = "left" if str(row.side) == "L" else "right"
        source = next(
            str(value)
            for value in box.physical_channels.loc[box.physical_channels["eye"].eq(eye), "channel_id"]
            if str(value) not in used
        )
        result[str(row.column_id)] = source
        used.add(source)
    return result


def _remainder_registration(box: VisionTransductionBox) -> dict[str, str]:
    available = {
        side: [item for item in box.physical_channel_ids if box._physical_side[item] == side]
        for side in ("L", "R")
    }
    offsets = {"L": 0, "R": 0}
    result: dict[str, str] = {}
    for channel_id in box.registration_channel_ids:
        side = box._remainder_side[channel_id]
        result[channel_id] = available[side][offsets[side] % len(available[side])]
        offsets[side] += 1
    return result


def compile_interfaces(
    body_ids: np.ndarray, profile: DynamicsProfile
) -> CompiledInterfaces:
    rng = np.random.default_rng(profile.seed)
    input_parts = []
    box_ids: list[str] = []

    for box_id in CLAMP_IDS:
        box = BasalClampBox.from_generated_wiring(box_id)
        input_parts.append(box.step(rng.uniform(0.0, 0.1, len(box.channel_ids))))
        box_ids.append(box.box_id)

    proprio_sensor = FlyBodyProprioceptionSensor.from_generated_wiring()
    proprio_transduction = ProprioceptionTransductionBox.from_generated_wiring()
    proprio_router = ProprioceptionRoutingBox.from_generated_wiring()
    joint_state = proprio_sensor.step(
        rng.normal(0.0, 0.05, proprio_sensor.qpos_size),
        rng.normal(0.0, 0.05, proprio_sensor.qvel_size),
    )
    proprio_activity = proprio_transduction.step(
        joint_state, rng.normal(0.0, 0.05, len(proprio_transduction.parameter_ids))
    )
    input_parts.append(proprio_router.step(proprio_activity.values))
    box_ids.extend((proprio_sensor.box_id, proprio_transduction.box_id, proprio_router.box_id))

    contact_sensor = FlyBodyGroundContactSensor.from_generated_wiring()
    local_contact_sensor = FlyBodyLocalContactSensor.from_generated_wiring()
    mechano_transduction = MechanosensationTransductionBox.from_generated_wiring()
    mechano_router = MechanosensationRoutingBox.from_generated_wiring()
    contact_state = contact_sensor.step(rng.normal(0.0, 0.02, contact_sensor.sensor_data_size))
    local_state = local_contact_sensor.step(
        rng.normal(0.0, 0.02, (len(local_contact_sensor.segment_names), 3))
    )
    mechano_activity = mechano_transduction.step(
        contact_state,
        local_state,
        joint_state,
        rng.normal(0.0, 0.05, len(mechano_transduction.parameter_ids)),
        np.zeros(len(mechano_transduction.unresolved_channel_ids), dtype=np.float64),
    )
    input_parts.append(mechano_router.step(mechano_activity.values))
    box_ids.extend((contact_sensor.box_id, mechano_transduction.box_id, mechano_router.box_id))

    vision_sensor = FlyBodyVisionSensor.from_generated_wiring()
    vision_transduction = VisionTransductionBox.from_generated_wiring()
    vision_router = VisionRoutingBox.from_generated_wiring()
    retinal = vision_sensor.step(rng.uniform(0.0, 1.0, vision_sensor.readout_shape))
    vision_activity = vision_transduction.step(
        retinal,
        _retinal_registration(vision_transduction),
        _remainder_registration(vision_transduction),
        rng.normal(0.0, 0.05, len(vision_transduction.parameter_ids)),
    )
    input_parts.append(vision_router.step(vision_activity.values))
    box_ids.extend((vision_sensor.box_id, vision_transduction.box_id, vision_router.box_id))

    residual_router = UnclassifiedSensoryRoutingBox.from_generated_wiring()
    residual_values: dict[str, float] = {}
    for source_id in RESIDUAL_SOURCE_IDS:
        source = ResidualSensoryNominalSourceBox.from_generated_wiring(source_id)
        activity = source.step(rng.uniform(0.0, 0.1, len(source.channel_ids)))
        residual_values.update(zip(activity.channel_ids, activity.values))
        box_ids.append(source.box_id)
    input_parts.append(residual_router.step(residual_values))
    box_ids.append(residual_router.box_id)

    merged = CNSInputBuffer.merge(*input_parts)
    if len(merged.body_ids) != 17884:
        raise BenchmarkError(f"Expected 17,884 declared CNS inputs, got {len(merged.body_ids)}")
    input_indices, input_valid = _locate(body_ids, merged.body_ids)
    dense_input = np.zeros(len(body_ids), dtype=np.float32)
    dense_input[input_indices[input_valid]] = merged.values[input_valid].astype(np.float32)
    max_abs = float(np.max(np.abs(dense_input)))
    if max_abs > 0:
        dense_input /= max_abs

    motor = MotorRoutingBox.from_generated_wiring()
    motor_transduction = MotorTransductionBox.from_generated_wiring()
    actuator = FlyBodyActuatorInterface.from_generated_wiring()
    motor_body_ids = np.asarray(motor.source_body_ids, dtype=np.int64)
    motor_indices, motor_valid = _locate(body_ids, motor_body_ids)
    if not motor_valid.all():
        raise BenchmarkError(f"Graph scope excludes {np.count_nonzero(~motor_valid)} motor neurons")
    motor_weights = rng.normal(
        0.0, profile.motor_weight_std, len(motor_transduction.parameter_ids)
    )
    channel_index = {channel_id: index for index, channel_id in enumerate(motor.channel_ids)}
    actuator_index = {name: index for index, name in enumerate(actuator.actuator_names)}
    decoder = np.zeros((len(actuator.actuator_names), len(motor.channel_ids)), dtype=np.float32)
    source_indices = np.asarray(
        [channel_index[str(value)] for value in motor_transduction.candidates["source_channel_id"]],
        dtype=np.int64,
    )
    target_indices = np.asarray(
        [actuator_index[str(value)] for value in motor_transduction.candidates["target_actuator_name"]],
        dtype=np.int64,
    )
    np.add.at(decoder, (target_indices, source_indices), motor_weights.astype(np.float32))
    check_state = rng.normal(0.0, 0.1, len(body_ids))
    routed = motor.step(check_state[motor_indices])
    expected = actuator.step(motor_transduction.step(routed, motor_weights).values).values
    actual = decoder @ check_state[motor_indices].astype(np.float32)
    if not np.allclose(actual, expected, atol=2e-6, rtol=2e-5):
        raise BenchmarkError("Compiled motor decoder differs from the declared output boxes")
    box_ids.extend((motor.box_id, motor_transduction.box_id, actuator.box_id))
    metadata = {
        "input_box_ids": box_ids[:-3],
        "output_box_ids": box_ids[-3:],
        "declared_input_terminals": len(merged.body_ids),
        "included_input_terminals": int(np.count_nonzero(input_valid)),
        "excluded_input_terminals_for_scope": int(np.count_nonzero(~input_valid)),
        "motor_neurons": len(motor_indices),
        "motor_groups": len(set(motor.motor_group_ids)),
        "actuator_commands": len(actuator.actuator_names),
        "input_parameter_origin": "deterministic_random_benchmark_only",
        "motor_parameter_origin": "deterministic_random_benchmark_only",
        "scientific_review": "executable_prewiring_requires_independent_revalidation",
    }
    return CompiledInterfaces(
        dense_input,
        motor_indices.astype(np.int64),
        decoder,
        motor_body_ids,
        actuator.actuator_names,
        merged.body_ids.copy(),
        metadata,
    )


def numpy_step(
    matrix: sparse.csr_matrix,
    incoming_inverse: np.ndarray,
    state: np.ndarray,
    input_vector: np.ndarray,
    profile: DynamicsProfile,
) -> np.ndarray:
    drive = matrix.dot(state).astype(np.float32, copy=False)
    drive *= incoming_inverse
    proposal = np.tanh(
        profile.recurrent_scale * drive + profile.input_scale * input_vector
    ).astype(np.float32, copy=False)
    return ((1.0 - profile.leak) * state + profile.leak * proposal).astype(
        np.float32, copy=False
    )


def run_numpy_steps(
    graph: GraphCache,
    interfaces: CompiledInterfaces,
    profile: DynamicsProfile,
    initial_state: np.ndarray,
    steps: int,
) -> tuple[np.ndarray, float]:
    state = initial_state.copy()
    started = time.perf_counter()
    for _ in range(steps):
        state = numpy_step(
            graph.matrix, graph.incoming_inverse, state, interfaces.input_vector, profile
        )
    return state, time.perf_counter() - started


def _torch_components(graph: GraphCache, interfaces: CompiledInterfaces, device: str):
    import torch

    crow = torch.from_numpy(graph.matrix.indptr.astype(np.int32, copy=False)).to(device)
    col = torch.from_numpy(graph.matrix.indices.astype(np.int32, copy=False)).to(device)
    data = torch.from_numpy(graph.matrix.data.astype(np.float32, copy=False)).to(device)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Sparse CSR tensor support is in beta state")
        matrix = torch.sparse_csr_tensor(
            crow,
            col,
            data,
            size=graph.matrix.shape,
            dtype=torch.float32,
            device=device,
            check_invariants=False,
        )
    return (
        matrix,
        torch.from_numpy(graph.incoming_inverse).to(device),
        torch.from_numpy(interfaces.input_vector).to(device),
        torch.from_numpy(interfaces.motor_node_indices).to(device),
        torch.from_numpy(interfaces.motor_decoder).to(device),
    )


def _torch_step(matrix, incoming_inverse, state, input_vector, profile: DynamicsProfile):
    import torch

    drive = torch.sparse.mm(matrix, state[:, None]).squeeze(1) * incoming_inverse
    proposal = torch.tanh(
        profile.recurrent_scale * drive + profile.input_scale * input_vector
    )
    return (1.0 - profile.leak) * state + profile.leak * proposal


def run_torch_steps(
    graph: GraphCache,
    interfaces: CompiledInterfaces,
    profile: DynamicsProfile,
    initial_state: np.ndarray,
    device: str,
    warmup_steps: int,
    measured_steps: int,
    record_trace: bool,
) -> tuple[np.ndarray, float, dict[str, np.ndarray], int | None]:
    import torch

    if device.startswith("cuda") and not torch.cuda.is_available():
        raise BenchmarkError("CUDA backend requested but torch.cuda.is_available() is false")
    matrix, incoming_inverse, input_vector, motor_indices, decoder = _torch_components(
        graph, interfaces, device
    )
    state = torch.from_numpy(initial_state).to(device)
    sample_count = min(profile.sampled_neurons, len(initial_state))
    sample_indices_np = np.linspace(0, len(initial_state) - 1, sample_count, dtype=np.int64)
    sample_indices = torch.from_numpy(sample_indices_np).to(device)
    timestamps: list[float] = []
    summaries: list[np.ndarray] = []
    samples: list[np.ndarray] = []
    commands: list[np.ndarray] = []
    if device.startswith("cuda"):
        torch.cuda.reset_peak_memory_stats(device)
    with torch.inference_mode():
        for _ in range(warmup_steps):
            state = _torch_step(matrix, incoming_inverse, state, input_vector, profile)
        if device.startswith("cuda"):
            torch.cuda.synchronize(device)
        started = time.perf_counter()
        for step in range(measured_steps):
            state = _torch_step(matrix, incoming_inverse, state, input_vector, profile)
            if record_trace and step % profile.trace_stride == 0:
                motor_values = state[motor_indices]
                actuator_values = decoder @ motor_values
                summary = torch.stack(
                    (
                        state.mean(),
                        state.std(unbiased=False),
                        state.min(),
                        state.max(),
                        torch.mean((torch.abs(state) > 1e-4).to(torch.float32)),
                        torch.mean((torch.abs(state) > 0.95).to(torch.float32)),
                    )
                )
                timestamps.append((step + 1) * profile.dt_ms / 1000.0)
                summaries.append(summary.cpu().numpy())
                samples.append(state[sample_indices].cpu().numpy())
                commands.append(actuator_values.cpu().numpy())
        if device.startswith("cuda"):
            torch.cuda.synchronize(device)
        elapsed = time.perf_counter() - started
    peak_device = (
        int(torch.cuda.max_memory_allocated(device)) if device.startswith("cuda") else None
    )
    trace = {
        "timestamps_s": np.asarray(timestamps, dtype=np.float32),
        "neural_summary": np.asarray(summaries, dtype=np.float32).reshape(-1, 6),
        "sampled_state": np.asarray(samples, dtype=np.float32).reshape(-1, sample_count),
        "sampled_node_indices": sample_indices_np,
        "actuator_commands": np.asarray(commands, dtype=np.float32).reshape(
            -1, len(interfaces.actuator_names)
        ),
    }
    return state.cpu().numpy(), elapsed, trace, peak_device


def _hardware() -> dict[str, Any]:
    import torch

    result: dict[str, Any] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
    }
    if torch.cuda.is_available():
        properties = torch.cuda.get_device_properties(0)
        result.update(
            {
                "gpu": properties.name,
                "gpu_total_memory_bytes": int(properties.total_memory),
            }
        )
    return result


def run_benchmark(
    profile_path: Path = PROFILE_PATH,
    backend: str = "auto",
    scope: str = "full",
    steps: int | None = None,
    warmup: int | None = None,
    reference_steps: int | None = None,
    rebuild_cache: bool = False,
    output_root: Path = RUN_ROOT,
) -> dict[str, Any]:
    import torch

    profile = DynamicsProfile.load(profile_path)
    measured_steps = profile.measured_steps if steps is None else int(steps)
    warmup_steps = profile.warmup_steps if warmup is None else int(warmup)
    cpu_steps = profile.reference_steps if reference_steps is None else int(reference_steps)
    if min(measured_steps, cpu_steps) < 1 or warmup_steps < 0:
        raise BenchmarkError("Benchmark step counts are invalid")
    selected_backend = "cuda" if backend == "auto" and torch.cuda.is_available() else backend
    if selected_backend == "auto":
        selected_backend = "cpu"
    if selected_backend not in {"cpu", "cuda", "both"}:
        raise BenchmarkError(f"Unsupported backend: {selected_backend}")
    if selected_backend in {"cuda", "both"} and not torch.cuda.is_available():
        raise BenchmarkError("CUDA backend requested but unavailable")

    print(f"[1/6] Profil {profile.profile_id} — {profile.claim_label}", flush=True)
    central = CentralConnectomeBox.from_generated_wiring()
    print(f"[2/6] Graphe {scope}: préparation/cache CSR", flush=True)
    cache_started = time.perf_counter()
    graph = build_graph_cache(central, profile, scope=scope, rebuild=rebuild_cache)
    cache_seconds = time.perf_counter() - cache_started
    print(
        f"[OK] {len(graph.body_ids):,} neurones, {graph.matrix.nnz:,} arêtes, "
        f"{graph.metadata['csr_bytes'] / 1024**2:.1f} MiB CSR",
        flush=True,
    )
    print("[3/6] Compilation des boîtes d'entrée et de sortie", flush=True)
    interface_started = time.perf_counter()
    interfaces = compile_interfaces(graph.body_ids, profile)
    interface_seconds = time.perf_counter() - interface_started
    print(
        f"[OK] {interfaces.metadata['included_input_terminals']:,} entrées, "
        f"{interfaces.metadata['motor_neurons']:,} sorties motrices, "
        f"{interfaces.metadata['actuator_commands']:,} actionneurs",
        flush=True,
    )
    initial_state = np.random.default_rng(profile.seed + 1).normal(
        0.0, profile.initial_state_std, len(graph.body_ids)
    ).astype(np.float32)
    print(f"[4/6] Référence CPU déterministe ({cpu_steps} pas)", flush=True)
    cpu_state, cpu_elapsed = run_numpy_steps(
        graph, interfaces, profile, initial_state, cpu_steps
    )
    cpu_repeat, _ = run_numpy_steps(graph, interfaces, profile, initial_state, cpu_steps)
    cpu_deterministic = bool(np.array_equal(cpu_state, cpu_repeat))
    if not cpu_deterministic:
        raise BenchmarkError("CPU reference is not bitwise deterministic")

    agreement: dict[str, Any] | None = None
    trace: dict[str, np.ndarray]
    peak_device: int | None = None
    if selected_backend in {"cuda", "both"}:
        print(f"[5/6] Backend CUDA: accord puis {measured_steps} pas mesurés", flush=True)
        gpu_reference, _, _, _ = run_torch_steps(
            graph, interfaces, profile, initial_state, "cuda:0", 0, cpu_steps, False
        )
        difference = np.abs(cpu_state - gpu_reference)
        agrees = bool(
            np.allclose(
                cpu_state,
                gpu_reference,
                atol=profile.agreement_atol,
                rtol=profile.agreement_rtol,
            )
        )
        agreement = {
            "steps": cpu_steps,
            "atol": profile.agreement_atol,
            "rtol": profile.agreement_rtol,
            "max_abs_error": float(difference.max()),
            "mean_abs_error": float(difference.mean()),
            "passed": agrees,
        }
        if not agrees:
            raise BenchmarkError(f"CPU/GPU agreement failed: {agreement}")
        final_state, measured_elapsed, trace, peak_device = run_torch_steps(
            graph,
            interfaces,
            profile,
            initial_state,
            "cuda:0",
            warmup_steps,
            measured_steps,
            True,
        )
        backend_name = "cuda"
    else:
        print(f"[5/6] Backend CPU: {measured_steps} pas mesurés", flush=True)
        state = initial_state.copy()
        for _ in range(warmup_steps):
            state = numpy_step(
                graph.matrix, graph.incoming_inverse, state, interfaces.input_vector, profile
            )
        final_state, measured_elapsed = run_numpy_steps(
            graph, interfaces, profile, state, measured_steps
        )
        sampled = np.linspace(
            0, len(final_state) - 1, min(profile.sampled_neurons, len(final_state)), dtype=np.int64
        )
        motor_values = final_state[interfaces.motor_node_indices]
        trace = {
            "timestamps_s": np.asarray([measured_steps * profile.dt_ms / 1000], dtype=np.float32),
            "neural_summary": np.asarray(
                [[
                    final_state.mean(), final_state.std(), final_state.min(), final_state.max(),
                    np.mean(np.abs(final_state) > 1e-4), np.mean(np.abs(final_state) > 0.95),
                ]],
                dtype=np.float32,
            ),
            "sampled_state": final_state[sampled][None, :],
            "sampled_node_indices": sampled,
            "actuator_commands": (interfaces.motor_decoder @ motor_values)[None, :],
        }
        backend_name = "cpu"

    simulated_seconds = measured_steps * profile.dt_ms / 1000.0
    steps_per_second = measured_steps / measured_elapsed
    realtime_factor = simulated_seconds / measured_elapsed
    run_id = datetime.now(UTC).strftime("benchmark-%Y%m%dT%H%M%SZ")
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    trace_path = run_dir / "replay-trace.npz"
    np.savez_compressed(
        trace_path,
        **trace,
        sampled_body_ids=graph.body_ids[trace["sampled_node_indices"]],
        actuator_names=np.asarray(interfaces.actuator_names),
        motor_body_ids=interfaces.motor_body_ids,
        dt_ms=np.asarray(profile.dt_ms, dtype=np.float32),
    )
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "claim_label": profile.claim_label,
        "scientific_claim": "none; engineering execution benchmark only",
        "profile_id": profile.profile_id,
        "profile_path": str(profile_path.relative_to(ROOT)).replace("\\", "/"),
        "profile_sha256": _sha256_bytes(profile_path.read_bytes()),
        "git_commit": _git_commit(),
        "backend": backend_name,
        "scope": scope,
        "hardware": _hardware(),
        "graph": graph.metadata,
        "interfaces": interfaces.metadata,
        "timing": {
            "cache_load_or_build_seconds": cache_seconds,
            "interface_compile_seconds": interface_seconds,
            "cpu_reference_steps": cpu_steps,
            "cpu_reference_seconds": cpu_elapsed,
            "warmup_steps": warmup_steps,
            "measured_steps": measured_steps,
            "steady_state_seconds": measured_elapsed,
            "steps_per_second": steps_per_second,
            "simulated_seconds": simulated_seconds,
            "simulated_to_wall_clock_ratio": realtime_factor,
        },
        "memory": {
            "host_rss_bytes_after_run": _process_rss_bytes(),
            "csr_bytes": graph.metadata["csr_bytes"],
            "peak_device_allocated_bytes": peak_device,
        },
        "correctness": {
            "cpu_bitwise_deterministic": cpu_deterministic,
            "cpu_gpu_agreement": agreement,
            "finite_final_state": bool(np.isfinite(final_state).all()),
        },
        "trace": {
            "path": str(trace_path.relative_to(ROOT)).replace("\\", "/"),
            "bytes": trace_path.stat().st_size,
            "samples": int(len(trace["timestamps_s"])),
            "contents": [
                "timestamps",
                "six neural summary metrics",
                "fixed sampled neuron state",
                "102 actuator command chronograms",
            ],
            "replay_contract": "apply actuator_commands in order from the declared FlyBody initial state at dt_ms",
        },
        "known_limits": [
            "Dynamics and interface parameter values are deterministic engineering placeholders.",
            "Current interface manifests remain executable prewiring under independent scientific revalidation.",
            "This run does not execute MuJoCo; its actuator trace is intended for a later offline physical replay.",
            "No neurotransmitter sign, neuronal time constant, threshold or physiological gain is asserted.",
        ],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("[6/6] Rapport et trace compacte", flush=True)
    print(f"[OK] {steps_per_second:,.1f} pas/s; x{realtime_factor:.3f} temps réel", flush=True)
    print(f"[OK] {trace_path} ({trace_path.stat().st_size / 1024**2:.2f} MiB)", flush=True)
    print(f"[OK] {run_dir / 'summary.json'}", flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the real canonical MaleCNS graph")
    parser.add_argument("--profile", type=Path, default=PROFILE_PATH)
    parser.add_argument("--backend", choices=("auto", "cpu", "cuda", "both"), default="auto")
    parser.add_argument("--scope", choices=("full", "causal-core"), default="full")
    parser.add_argument("--steps", type=int)
    parser.add_argument("--warmup", type=int)
    parser.add_argument("--reference-steps", type=int)
    parser.add_argument("--rebuild-cache", action="store_true")
    args = parser.parse_args()
    run_benchmark(
        profile_path=args.profile,
        backend=args.backend,
        scope=args.scope,
        steps=args.steps,
        warmup=args.warmup,
        reference_steps=args.reference_steps,
        rebuild_cache=args.rebuild_cache,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

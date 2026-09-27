from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter, sleep
from typing import Any

import numpy as np

from .connectome_benchmark import (
    CLAMP_IDS,
    PROFILE_PATH,
    RESIDUAL_SOURCE_IDS,
    CompiledInterfaces,
    DynamicsProfile,
    GraphCache,
    _locate,
    _retinal_registration,
    _remainder_registration,
    _torch_components,
    _torch_step,
    build_graph_cache,
    compile_interfaces,
)
from .ledger import ROOT
from .physical_trajectory import (
    PassiveFlyViewer,
    PhysicalTrajectory,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    model_contract,
)
from .runtime import (
    ActuatorCommands,
    BasalClampBox,
    CNSInputBuffer,
    CentralConnectomeBox,
    FlyBodyGroundContactSensor,
    FlyBodyLocalContactSensor,
    FlyBodyPhysicsLoop,
    FlyBodyProprioceptionSensor,
    FlyBodyVisionSensor,
    MechanosensationRoutingBox,
    MechanosensationTransductionBox,
    ProprioceptionRoutingBox,
    ProprioceptionTransductionBox,
    ResidualSensoryNominalSourceBox,
    UnclassifiedSensoryRoutingBox,
    VisionRoutingBox,
    VisionTransductionBox,
)


RUN_ROOT = ROOT / "runs" / "closed-loop"
CLAIM_LABEL = "REAL MALECNS / UNCALIBRATED CLOSED LOOP"


class ClosedLoopError(RuntimeError):
    pass


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class ClosedLoopConfig:
    duration_s: float = 1.0
    command_scale: float = 0.001
    vision_stride: int = 1
    render_fps: float = 30.0
    realtime_speed: float = 0.0
    record: bool = True
    live_viewer: bool = False

    def __post_init__(self) -> None:
        if self.duration_s < 0:
            raise ValueError("duration_s must be non-negative")
        if not 0 < self.command_scale <= 0.01:
            raise ValueError("command_scale must be in (0, 0.01]")
        if self.vision_stride < 1:
            raise ValueError("vision_stride must be at least one")
        if self.render_fps <= 0 or self.realtime_speed < 0:
            raise ValueError("render_fps must be positive and realtime_speed non-negative")
        if not self.live_viewer and self.duration_s == 0:
            raise ValueError("headless recording requires a finite duration")


class DynamicInputRuntime:
    """Execute every declared input box from the current physical state.

    Parameters are fixed deterministic engineering placeholders for the whole run.
    They are deliberately kept outside the graph topology so a future calibrated
    parameter bundle can replace them without changing the loop.
    """

    def __init__(self, graph_body_ids: np.ndarray, profile: DynamicsProfile):
        self.graph_body_ids = graph_body_ids
        self.profile = profile
        rng = np.random.default_rng(profile.seed + 10_000)

        self.proprio_sensor = FlyBodyProprioceptionSensor.from_generated_wiring()
        self.proprio_transduction = ProprioceptionTransductionBox.from_generated_wiring()
        self.proprio_router = ProprioceptionRoutingBox.from_generated_wiring()
        self.proprio_parameters = rng.normal(
            0.0, 0.05, len(self.proprio_transduction.parameter_ids)
        )

        self.contact_sensor = FlyBodyGroundContactSensor.from_generated_wiring()
        self.local_contact_sensor = FlyBodyLocalContactSensor.from_generated_wiring()
        self.mechano_transduction = MechanosensationTransductionBox.from_generated_wiring()
        self.mechano_router = MechanosensationRoutingBox.from_generated_wiring()
        self.mechano_parameters = rng.normal(
            0.0, 0.05, len(self.mechano_transduction.parameter_ids)
        )
        self.mechano_unresolved = np.zeros(
            len(self.mechano_transduction.unresolved_channel_ids), dtype=np.float64
        )

        self.vision_sensor = FlyBodyVisionSensor.from_generated_wiring()
        self.vision_transduction = VisionTransductionBox.from_generated_wiring()
        self.vision_router = VisionRoutingBox.from_generated_wiring()
        self.vision_registration = _retinal_registration(self.vision_transduction)
        self.vision_remainder_registration = _remainder_registration(
            self.vision_transduction
        )
        self.vision_parameters = rng.normal(
            0.0, 0.05, len(self.vision_transduction.parameter_ids)
        )
        self._last_vision = None
        self._last_retinal_values = None

        self.static_parts = []
        for box_id in CLAMP_IDS:
            box = BasalClampBox.from_generated_wiring(box_id)
            self.static_parts.append(
                box.step(rng.uniform(0.0, 0.1, len(box.channel_ids)))
            )
        residual_values: dict[str, float] = {}
        for source_id in RESIDUAL_SOURCE_IDS:
            source = ResidualSensoryNominalSourceBox.from_generated_wiring(source_id)
            activity = source.step(rng.uniform(0.0, 0.1, len(source.channel_ids)))
            residual_values.update(zip(activity.channel_ids, activity.values))
        residual_router = UnclassifiedSensoryRoutingBox.from_generated_wiring()
        self.static_parts.append(residual_router.step(residual_values))

        static_ids = CNSInputBuffer.merge(*self.static_parts).body_ids
        if len(static_ids) != 6041:
            raise ClosedLoopError(f"Expected 6,041 basal/residual inputs, got {len(static_ids)}")

    def encode(
        self, loop: FlyBodyPhysicsLoop, step_index: int, vision_stride: int
    ) -> tuple[np.ndarray, dict[str, float], dict[str, np.ndarray]]:
        joint_state = loop.read_joint_state()
        proprio_activity = self.proprio_transduction.step(
            joint_state, self.proprio_parameters
        )
        proprio = self.proprio_router.step(proprio_activity.values)

        ground = loop.read_ground_contact_state(self.contact_sensor)
        local = loop.read_local_contact_state(self.local_contact_sensor)
        mechano_activity = self.mechano_transduction.step(
            ground,
            local,
            joint_state,
            self.mechano_parameters,
            self.mechano_unresolved,
        )
        mechano = self.mechano_router.step(mechano_activity.values)

        if self._last_vision is None or step_index % vision_stride == 0:
            retinal = loop.read_vision(self.vision_sensor)
            self._last_retinal_values = retinal.values.astype(np.float32, copy=True)
            vision_activity = self.vision_transduction.step(
                retinal,
                self.vision_registration,
                self.vision_remainder_registration,
                self.vision_parameters,
            )
            self._last_vision = self.vision_router.step(vision_activity.values)

        merged = CNSInputBuffer.merge(*self.static_parts, proprio, mechano, self._last_vision)
        if len(merged.body_ids) != 17884:
            raise ClosedLoopError(f"Expected 17,884 live inputs, got {len(merged.body_ids)}")
        indices, valid = _locate(self.graph_body_ids, merged.body_ids)
        if not valid.all():
            raise ClosedLoopError(
                f"Live input references {np.count_nonzero(~valid)} nodes outside the graph"
            )
        dense = np.zeros(len(self.graph_body_ids), dtype=np.float32)
        dense[indices] = merged.values.astype(np.float32)
        raw_max = float(np.max(np.abs(dense)))
        if raw_max > 0:
            dense /= raw_max
        contact_values = np.column_stack(
            (
                ground.contact_found,
                ground.forces,
                ground.torques,
                ground.positions,
                ground.normals,
                ground.tangents,
            )
        ).reshape(-1)
        observations = {
            "joint_state": np.concatenate((joint_state.positions, joint_state.velocities)).astype(
                np.float32, copy=False
            ),
            "ground_contacts": contact_values.astype(np.float32, copy=False),
            "local_contacts": local.forces.reshape(-1).astype(np.float32, copy=False),
            "retinal_samples": self._last_retinal_values,
        }
        return dense, {
            "raw_max_abs": raw_max,
            "normalized_mean": float(dense.mean()),
            "normalized_std": float(dense.std()),
            "contacting_legs": float(np.count_nonzero(ground.contact_found)),
        }, observations

    def reset(self) -> None:
        self._last_vision = None
        self._last_retinal_values = None


class TorchMaleCNSRuntime:
    """Persistent GPU state for one-step closed-loop execution."""

    def __init__(
        self,
        graph: GraphCache,
        interfaces: CompiledInterfaces,
        profile: DynamicsProfile,
        device: str = "cuda:0",
    ):
        import torch

        if device.startswith("cuda") and not torch.cuda.is_available():
            raise ClosedLoopError("CUDA closed-loop runtime requested but unavailable")
        self.torch = torch
        self.device = device
        self.profile = profile
        self.graph = graph
        self.interfaces = interfaces
        (
            self.matrix,
            self.incoming_inverse,
            self.input_vector,
            self.motor_indices,
            self.decoder,
        ) = _torch_components(graph, interfaces, device)
        self._initial_state = np.random.default_rng(profile.seed + 1).normal(
            0.0, profile.initial_state_std, len(graph.body_ids)
        ).astype(np.float32)
        self.reset()

    def reset(self) -> None:
        self.state = self.torch.from_numpy(self._initial_state.copy()).to(self.device)

    def step(self, input_vector: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        torch = self.torch
        if input_vector.shape != (len(self.graph.body_ids),):
            raise ClosedLoopError("live input vector has the wrong graph dimension")
        with torch.inference_mode():
            self.input_vector.copy_(torch.from_numpy(input_vector).to(self.device))
            self.state = _torch_step(
                self.matrix,
                self.incoming_inverse,
                self.state,
                self.input_vector,
                self.profile,
            )
            motor_values = self.state[self.motor_indices]
            commands = self.decoder @ motor_values
            summary = torch.stack(
                (
                    self.state.mean(),
                    self.state.std(unbiased=False),
                    self.state.min(),
                    self.state.max(),
                    torch.mean((torch.abs(self.state) > 1e-4).to(torch.float32)),
                    torch.mean((torch.abs(self.state) > 0.95).to(torch.float32)),
                )
            )
            return commands.cpu().numpy(), summary.cpu().numpy()


def _build_metadata(
    loop: FlyBodyPhysicsLoop,
    profile_path: Path,
    profile: DynamicsProfile,
    config: ClosedLoopConfig,
    graph: GraphCache,
    run_id: str,
) -> dict[str, Any]:
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "creator": "the_fly_matrix.embodied_runtime.closed_loop_v0",
        "claim_label": CLAIM_LABEL,
        "scientific_claim": "none; executable uncalibrated closed-loop integration only",
        "git_commit": _git_commit(),
        "profile": {
            "id": profile.profile_id,
            "path": str(profile_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": _sha256(profile_path),
            "dt_ms": profile.dt_ms,
        },
        "model": model_contract(loop),
        "graph": {
            "nodes": len(graph.body_ids),
            "edges": int(graph.matrix.nnz),
            "scope": graph.metadata.get("scope"),
            "body_id_sha256": graph.metadata.get("body_id_sha256"),
            "dataset_sha256": graph.metadata.get("dataset_sha256"),
        },
        "execution": {
            "command_envelope": "tanh(raw_command) * command_scale",
            "command_scale": config.command_scale,
            "vision_stride": config.vision_stride,
            "physics_timestep_s": float(loop.simulation.mj_model.opt.timestep),
            "neural_dt_ms": profile.dt_ms,
            "input_parameter_origin": "deterministic_random_benchmark_only",
            "motor_parameter_origin": "deterministic_random_benchmark_only",
            "interface_parameter_seed": profile.seed + 10_000,
            "initial_neural_state_seed": profile.seed + 1,
        },
        "sensory_observations": {
            "joint_state": "102 positions followed by 102 velocities in declared joint order",
            "ground_contacts": "six rows of 16 FlyGym ground-contact scalars",
            "local_contacts": "c_head and c_thorax world-frame force vectors",
            "retinal_samples": "1,442 active FlyBody ommatidium channels; held between vision updates",
        },
        "known_limits": [
            "The temporal rule and every interface parameter are uncalibrated engineering placeholders.",
            "The command envelope is a numerical safety guard, not physiology.",
            "Interface mappings remain executable prewiring under independent scientific revalidation.",
            "This trajectory demonstrates a real closed computational loop but no plausible behavior.",
        ],
    }


def run_closed_loop(
    config: ClosedLoopConfig,
    *,
    profile_path: Path = PROFILE_PATH,
    output_root: Path = RUN_ROOT,
) -> dict[str, Any]:
    profile = DynamicsProfile.load(profile_path)
    central = CentralConnectomeBox.from_generated_wiring()
    print(f"[1/7] Graphe MaleCNS {profile.claim_label}", flush=True)
    graph = build_graph_cache(central, profile, scope="full")
    print(f"[OK] {len(graph.body_ids):,} neurones, {graph.matrix.nnz:,} arêtes", flush=True)
    print("[2/7] Compilation des interfaces et paramètres de diagnostic", flush=True)
    compiled = compile_interfaces(graph.body_ids, profile)
    dynamic_inputs = DynamicInputRuntime(graph.body_ids, profile)
    neural = TorchMaleCNSRuntime(graph, compiled, profile)
    run_id = datetime.now(UTC).strftime("closed-loop-%Y%m%dT%H%M%SZ")
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    timestamps: list[float] = []
    qpos: list[np.ndarray] = []
    qvel: list[np.ndarray] = []
    commands_log: list[np.ndarray] = []
    neural_log: list[np.ndarray] = []
    input_log: list[dict[str, float]] = []
    sensory_log: dict[str, list[np.ndarray]] = {}
    sensor_seconds = 0.0
    neural_seconds = 0.0
    physics_seconds = 0.0
    viewer = None
    completed_reason = "duration_reached"
    wall_started = perf_counter()

    print("[3/7] Construction du corps FlyBody avec vision et contacts", flush=True)
    with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=True) as loop:
        physics_dt = float(loop.simulation.mj_model.opt.timestep)
        neural_dt = profile.dt_ms / 1000.0
        substeps_float = neural_dt / physics_dt
        substeps = int(round(substeps_float))
        if not np.isclose(substeps * physics_dt, neural_dt, atol=1e-12, rtol=0):
            raise ClosedLoopError(
                f"Neural dt {neural_dt} is not an integer multiple of physics dt {physics_dt}"
            )
        total_steps = None if config.duration_s == 0 else int(np.ceil(config.duration_s / neural_dt))
        metadata = _build_metadata(loop, profile_path, profile, config, graph, run_id)
        print(
            f"[OK] neural dt={neural_dt:g}s; physics dt={physics_dt:g}s; "
            f"{substeps} sous-pas/commande",
            flush=True,
        )
        if config.live_viewer:
            viewer = PassiveFlyViewer(loop, "LIVE REAL MALECNS", CLAIM_LABEL)
            print("[4/7] Viewer live ouvert", flush=True)
        else:
            print("[4/7] Exécution headless pour enregistrement", flush=True)

        step_index = 0
        episode_wall_anchor = perf_counter()
        last_render_sim = -np.inf
        try:
            while total_steps is None or step_index < total_steps:
                if viewer is not None and not viewer.is_running():
                    completed_reason = "viewer_closed"
                    break
                if viewer is not None and viewer.controls.reset_requested:
                    loop.reset()
                    neural.reset()
                    dynamic_inputs.reset()
                    timestamps.clear()
                    qpos.clear()
                    qvel.clear()
                    commands_log.clear()
                    neural_log.clear()
                    input_log.clear()
                    sensory_log.clear()
                    step_index = 0
                    episode_wall_anchor = perf_counter()
                    viewer.controls.reset_requested = False
                    print("[INFO] Corps, MaleCNS et enregistrement réinitialisés.", flush=True)
                if viewer is not None and viewer.controls.paused:
                    viewer.sync(float(loop.simulation.mj_data.time), "PAUSED")
                    sleep(0.02)
                    episode_wall_anchor = perf_counter() - float(loop.simulation.mj_data.time) / max(
                        config.realtime_speed or 1.0, 1e-12
                    )
                    continue

                started = perf_counter()
                input_vector, input_summary, sensory_observations = dynamic_inputs.encode(
                    loop, step_index, config.vision_stride
                )
                sensor_seconds += perf_counter() - started

                started = perf_counter()
                raw_commands, neural_summary = neural.step(input_vector)
                neural_seconds += perf_counter() - started
                safe_values = np.tanh(raw_commands.astype(np.float64)) * config.command_scale
                addressed = loop.actuator_interface.step(safe_values)

                started = perf_counter()
                physical = loop.step(addressed, substeps=substeps)
                physics_seconds += perf_counter() - started
                step_index += 1

                if config.record:
                    timestamps.append(physical.simulation_time)
                    qpos.append(np.asarray(loop.simulation.mj_data.qpos, dtype=np.float64).copy())
                    qvel.append(np.asarray(loop.simulation.mj_data.qvel, dtype=np.float64).copy())
                    commands_log.append(physical.applied_commands.astype(np.float32, copy=True))
                    neural_log.append(neural_summary.astype(np.float32, copy=True))
                    input_log.append(input_summary)
                    for name, values in sensory_observations.items():
                        sensory_log.setdefault(name, []).append(values.copy())
                    sensory_log.setdefault("actuator_forces", []).append(
                        physical.actuator_forces.astype(np.float32, copy=True)
                    )

                simulation_time = physical.simulation_time
                if viewer is not None and simulation_time - last_render_sim >= 1.0 / config.render_fps:
                    elapsed = max(perf_counter() - episode_wall_anchor, 1e-12)
                    viewer.sync(
                        simulation_time,
                        f"live {simulation_time / elapsed:.2f}x | step {step_index:,}",
                    )
                    last_render_sim = simulation_time
                if step_index == 1 or step_index % 20 == 0:
                    elapsed = max(perf_counter() - wall_started, 1e-12)
                    print(
                        f"[RUN] step={step_index:,} sim={simulation_time:.3f}s "
                        f"wall={elapsed:.3f}s ratio={simulation_time / elapsed:.2f}x",
                        flush=True,
                    )
                if config.realtime_speed > 0:
                    target = episode_wall_anchor + simulation_time / (
                        config.realtime_speed
                        * (viewer.controls.speed_multiplier if viewer is not None else 1.0)
                    )
                    remaining = target - perf_counter()
                    if remaining > 0:
                        sleep(remaining)
        finally:
            if viewer is not None:
                viewer.close()

        wall_seconds = perf_counter() - wall_started
        simulated_seconds = float(loop.simulation.mj_data.time)
        trajectory_path = run_dir / "physical-trajectory.npz"
        if config.record:
            trajectory = PhysicalTrajectory(
                timestamps_s=np.asarray(timestamps, dtype=np.float64),
                qpos=np.asarray(qpos, dtype=np.float64),
                qvel=np.asarray(qvel, dtype=np.float64),
                actuator_commands=np.asarray(commands_log, dtype=np.float32),
                neural_summary=np.asarray(neural_log, dtype=np.float32),
                sensory_observations={
                    name: np.asarray(values, dtype=np.float32)
                    for name, values in sensory_log.items()
                },
                metadata=metadata,
            )
            trajectory.save(trajectory_path)
            trajectory_bytes = trajectory_path.stat().st_size
        else:
            trajectory_bytes = None

    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "claim_label": CLAIM_LABEL,
        "completed_reason": completed_reason,
        "git_commit": _git_commit(),
        "profile_id": profile.profile_id,
        "steps": step_index,
        "simulated_seconds": simulated_seconds,
        "wall_seconds": wall_seconds,
        "simulated_to_wall_ratio": simulated_seconds / max(wall_seconds, 1e-12),
        "timing": {
            "sensor_and_interface_seconds": sensor_seconds,
            "neural_seconds": neural_seconds,
            "physics_seconds": physics_seconds,
        },
        "loop": {
            "closed": True,
            "live_vision": True,
            "live_proprioception": True,
            "live_contacts": True,
            "motor_commands_applied_to_mujoco": True,
            "external_behavioral_controller": False,
            "vision_stride": config.vision_stride,
        },
        "trajectory": {
            "path": str(trajectory_path.relative_to(ROOT)).replace("\\", "/") if config.record else None,
            "bytes": trajectory_bytes,
            "frames": len(timestamps),
            "controller_independent_schema": SCHEMA_NAME,
        },
        "input_summary_last": input_log[-1] if input_log else None,
        "known_limits": metadata["known_limits"],
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output_root / "latest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("[5/7] Boucle corps → capteurs → MaleCNS → actionneurs → corps terminée", flush=True)
    print(
        f"[OK] {simulated_seconds:.3f}s simulées en {wall_seconds:.3f}s "
        f"({summary['simulated_to_wall_ratio']:.2f}x)",
        flush=True,
    )
    print(
        f"[6/7] capteurs={sensor_seconds:.3f}s neural={neural_seconds:.3f}s "
        f"physique={physics_seconds:.3f}s",
        flush=True,
    )
    if config.record:
        print(
            f"[7/7] {trajectory_path} ({trajectory_bytes / 1024**2:.2f} MiB)",
            flush=True,
        )
    else:
        print("[7/7] Mode live sans enregistrement", flush=True)
    print(f"[OK] {summary_path}", flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real MaleCNS in a closed FlyBody loop")
    parser.add_argument("--profile", type=Path, default=PROFILE_PATH)
    parser.add_argument("--duration", type=float, default=1.0)
    parser.add_argument("--command-scale", type=float, default=0.001)
    parser.add_argument("--vision-stride", type=int, default=1)
    parser.add_argument("--render-fps", type=float, default=30.0)
    parser.add_argument("--speed", type=float, default=0.0)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--record-live", action="store_true")
    args = parser.parse_args()
    run_closed_loop(
        ClosedLoopConfig(
            duration_s=args.duration,
            command_scale=args.command_scale,
            vision_stride=args.vision_stride,
            render_fps=args.render_fps,
            realtime_speed=args.speed,
            record=not args.live or args.record_live,
            live_viewer=args.live,
        ),
        profile_path=args.profile,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

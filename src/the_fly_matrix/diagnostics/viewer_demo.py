from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from time import perf_counter, sleep
from typing import Any

import numpy as np

from ..runtime import FlyBodyPhysicsLoop, JointState


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = ROOT / "runs" / "diagnostic-viewer" / "latest.json"


@dataclass(frozen=True)
class DiagnosticDemoConfig:
    """Runtime settings for the isolated physical viewer demonstration."""

    seed: int = 260925
    duration_seconds: float = 0.0
    amplitude: float = 0.003
    realtime_speed: float = 1.0
    physics_timestep: float = 0.0005
    control_substeps: int = 20
    render_fps: float = 30.0
    hidden_size: int = 64
    headless: bool = False
    output: Path = DEFAULT_OUTPUT

    def __post_init__(self) -> None:
        if self.duration_seconds < 0:
            raise ValueError("duration_seconds must be non-negative")
        if not 0 < self.amplitude <= 0.01:
            raise ValueError("amplitude must be in (0, 0.01]")
        if self.realtime_speed < 0:
            raise ValueError("realtime_speed must be non-negative")
        if not 0.00005 <= self.physics_timestep <= 0.001:
            raise ValueError("physics_timestep must be in [0.00005, 0.001]")
        if self.control_substeps < 1:
            raise ValueError("control_substeps must be at least one")
        if self.render_fps <= 0:
            raise ValueError("render_fps must be positive")
        if self.hidden_size < 4:
            raise ValueError("hidden_size must be at least four")
        if self.headless and self.duration_seconds == 0:
            raise ValueError("headless mode requires a finite duration")


class DiagnosticToyCNS:
    """Small deterministic recurrent signal processor used only for the viewer.

    This is deliberately not a reduced MaleCNS model.  It has no anatomical
    interpretation, no learned target and no reusable scientific parameters.  It
    merely proves that continuously processed internal signals can drive the
    physical body and react to joint-state feedback at interactive speed.
    """

    scientific_status = "diagnostic_only_not_malecns_not_calibration"

    def __init__(
        self,
        joint_count: int,
        actuator_count: int,
        *,
        seed: int,
        hidden_size: int = 64,
    ):
        if joint_count < 1 or actuator_count < 1:
            raise ValueError("joint_count and actuator_count must be positive")
        self.joint_count = joint_count
        self.actuator_count = actuator_count
        self.hidden_size = hidden_size
        self.seed = seed
        rng = np.random.default_rng(seed)

        input_size = joint_count * 2
        self.input_weights = rng.normal(
            0.0, 1.0 / np.sqrt(input_size), (hidden_size, input_size)
        )
        recurrent = rng.normal(0.0, 1.0, (hidden_size, hidden_size))
        recurrent *= rng.random((hidden_size, hidden_size)) < 0.08
        row_bound = np.max(np.sum(np.abs(recurrent), axis=1))
        self.recurrent_weights = recurrent / max(float(row_bound), 1.0)
        self.output_weights = rng.normal(
            0.0, 1.0 / np.sqrt(hidden_size), (actuator_count, hidden_size)
        )
        self.hidden_phase = rng.uniform(0.0, 2.0 * np.pi, hidden_size)
        self.hidden_frequency_hz = rng.uniform(0.7, 3.0, hidden_size)
        self.output_phase = rng.uniform(0.0, 2.0 * np.pi, actuator_count)
        self.output_frequency_hz = rng.uniform(0.5, 2.5, actuator_count)
        self.edge_count = int(np.count_nonzero(self.recurrent_weights))
        self.reset()

    def reset(self) -> None:
        self.state = np.zeros(self.hidden_size, dtype=np.float64)
        self.time_seconds = 0.0

    def step(self, joint_state: JointState, dt: float) -> np.ndarray:
        if joint_state.positions.shape != (self.joint_count,):
            raise ValueError("joint positions do not match the diagnostic input size")
        if joint_state.velocities.shape != (self.joint_count,):
            raise ValueError("joint velocities do not match the diagnostic input size")
        if not np.isfinite(dt) or dt <= 0:
            raise ValueError("dt must be finite and positive")

        sensory = np.concatenate(
            (
                np.tanh(joint_state.positions / 0.5),
                np.tanh(joint_state.velocities * 0.02),
            )
        )
        hidden_oscillation = np.sin(
            self.hidden_phase + 2.0 * np.pi * self.hidden_frequency_hz * self.time_seconds
        )
        drive = self.input_weights @ sensory + 0.45 * hidden_oscillation
        self.state = np.tanh(
            0.90 * self.state
            + 0.35 * (self.recurrent_weights @ self.state)
            + 0.25 * drive
        )
        output_oscillation = np.sin(
            self.output_phase + 2.0 * np.pi * self.output_frequency_hz * self.time_seconds
        )
        output = np.tanh(self.output_weights @ self.state + 0.30 * output_oscillation)
        self.time_seconds += dt
        if not np.isfinite(output).all():
            raise RuntimeError("diagnostic toy CNS produced non-finite output")
        return output


class _ViewerControls:
    def __init__(self) -> None:
        self.paused = False
        self.reset_requested = False
        self.quit_requested = False

    def on_key(self, keycode: int) -> None:
        if keycode == 32:  # Space
            self.paused = not self.paused
        elif keycode in (82, 259):  # R or Backspace
            self.reset_requested = True
        elif keycode in (81, 256):  # Q or Escape
            self.quit_requested = True


def _configure_viewer(viewer: Any) -> None:
    import mujoco

    viewer.cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    viewer.cam.lookat[:] = np.asarray([0.0, 0.0, 1.0])
    viewer.cam.distance = 8.0
    viewer.cam.azimuth = 135.0
    viewer.cam.elevation = -20.0


def _update_overlay(
    viewer: Any,
    *,
    simulation_time: float,
    realtime_factor: float,
    paused: bool,
) -> None:
    import mujoco

    viewer.set_texts(
        [
            (
                mujoco.mjtFontScale.mjFONTSCALE_150,
                mujoco.mjtGridPos.mjGRID_TOPLEFT,
                "DIAGNOSTIC TOY CNS",
                "NOT MALECNS / NOT CALIBRATION",
            ),
            (
                mujoco.mjtFontScale.mjFONTSCALE_100,
                mujoco.mjtGridPos.mjGRID_BOTTOMLEFT,
                f"sim {simulation_time:7.3f} s | {realtime_factor:5.2f}x realtime",
                "PAUSED" if paused else "Space pause | R reset | Q quit",
            ),
        ]
    )


def run_diagnostic_demo(config: DiagnosticDemoConfig) -> dict[str, object]:
    """Run the isolated toy-CNS body demonstration and return a compact summary."""
    import mujoco

    print("\n==> DIAGNOSTIC VIEWER — NOT MALECNS — NOT CALIBRATION")
    print("[INFO] This tool bypasses the real connectome and scientific motor mapping.")
    print("[INFO] It exercises only a toy recurrent signal processor and the physical body.")
    print(
        f"[INFO] seed={config.seed}, amplitude={config.amplitude:g}, "
        f"speed={'unthrottled' if config.realtime_speed == 0 else f'{config.realtime_speed:g}x'}"
    )

    controls = _ViewerControls()
    viewer = None
    completed_reason = "duration_reached"
    total_control_steps = 0
    total_physics_steps = 0
    max_abs_command = 0.0
    sum_abs_command = 0.0
    command_samples = 0
    wall_start = perf_counter()

    with FlyBodyPhysicsLoop.from_generated_wiring() as loop:
        native_physics_dt = float(loop.simulation.mj_model.opt.timestep)
        loop.simulation.mj_model.opt.timestep = config.physics_timestep
        physics_dt = float(loop.simulation.mj_model.opt.timestep)
        control_dt = physics_dt * config.control_substeps
        toy = DiagnosticToyCNS(
            len(loop.joint_names),
            len(loop.actuator_names),
            seed=config.seed,
            hidden_size=config.hidden_size,
        )
        print(
            f"[OK] Toy CNS: {toy.hidden_size} states, {toy.edge_count} recurrent edges, "
            f"{toy.joint_count * 2} inputs, {toy.actuator_count} outputs"
        )
        print(
            f"[OK] Physics: diagnostic dt={physics_dt:g}s "
            f"(model native dt={native_physics_dt:g}s), control every "
            f"{config.control_substeps} steps ({control_dt:g}s)"
        )

        if not config.headless:
            import mujoco.viewer

            viewer = mujoco.viewer.launch_passive(
                loop.simulation.mj_model,
                loop.simulation.mj_data,
                key_callback=controls.on_key,
                show_left_ui=True,
                show_right_ui=True,
            )
            _configure_viewer(viewer)
            print("[OK] MuJoCo viewer opened. Close the window or press Q to stop.")

        episode_wall_anchor = perf_counter()
        loop_wall_start = episode_wall_anchor
        last_report_wall = episode_wall_anchor
        last_render_sim = -np.inf
        current_state = loop.read_joint_state()
        initial_joint_positions = current_state.positions.copy()

        try:
            while True:
                if viewer is not None and not viewer.is_running():
                    completed_reason = "viewer_closed"
                    break
                if controls.quit_requested:
                    completed_reason = "user_quit"
                    break
                if controls.reset_requested:
                    loop.reset()
                    toy.reset()
                    current_state = loop.read_joint_state()
                    initial_joint_positions = current_state.positions.copy()
                    controls.reset_requested = False
                    episode_wall_anchor = perf_counter()
                    last_render_sim = -np.inf
                    print("[INFO] Physics and toy CNS reset to their initial state.")

                if controls.paused:
                    if viewer is not None:
                        elapsed_wall = max(perf_counter() - episode_wall_anchor, 1e-12)
                        _update_overlay(
                            viewer,
                            simulation_time=float(loop.simulation.mj_data.time),
                            realtime_factor=float(loop.simulation.mj_data.time) / elapsed_wall,
                            paused=True,
                        )
                        viewer.sync()
                    sleep(0.02)
                    episode_wall_anchor = perf_counter() - (
                        float(loop.simulation.mj_data.time)
                        / max(config.realtime_speed, 1e-12)
                        if config.realtime_speed > 0
                        else 0.0
                    )
                    continue

                raw_output = toy.step(current_state, control_dt)
                values = np.clip(raw_output * config.amplitude, -config.amplitude, config.amplitude)
                commands = loop.actuator_interface.step(values)
                loop.simulation.set_actuator_inputs(
                    "flybody", loop.actuator_type, commands.values
                )
                # Keep the high-rate physics loop inside MuJoCo's native call.  The
                # diagnostic controller only needs to cross Python at its own lower
                # control rate; this does not alter the physical model or timestep.
                mujoco.mj_step(
                    loop.simulation.mj_model,
                    loop.simulation.mj_data,
                    nstep=config.control_substeps,
                )
                current_state = loop.read_joint_state()
                total_control_steps += 1
                total_physics_steps += config.control_substeps
                abs_values = np.abs(values)
                max_abs_command = max(max_abs_command, float(abs_values.max()))
                sum_abs_command += float(abs_values.sum())
                command_samples += len(values)

                if not np.isfinite(loop.simulation.mj_data.qpos).all() or not np.isfinite(
                    loop.simulation.mj_data.qvel
                ).all():
                    completed_reason = "non_finite_physics_state"
                    raise RuntimeError("MuJoCo produced a non-finite state")

                simulation_time = float(loop.simulation.mj_data.time)
                if (
                    viewer is not None
                    and simulation_time - last_render_sim >= 1.0 / config.render_fps
                ):
                    elapsed_wall = max(perf_counter() - episode_wall_anchor, 1e-12)
                    _update_overlay(
                        viewer,
                        simulation_time=simulation_time,
                        realtime_factor=simulation_time / elapsed_wall,
                        paused=False,
                    )
                    viewer.sync()
                    last_render_sim = simulation_time

                now = perf_counter()
                if now - last_report_wall >= 1.0:
                    elapsed_wall = max(now - episode_wall_anchor, 1e-12)
                    print(
                        f"[RUN] sim={simulation_time:7.3f}s | "
                        f"wall={elapsed_wall:7.3f}s | {simulation_time / elapsed_wall:5.2f}x | "
                        f"max|ctrl|={max_abs_command:.5f}"
                    )
                    last_report_wall = now

                if config.duration_seconds > 0 and simulation_time >= config.duration_seconds:
                    break

                if config.realtime_speed > 0:
                    target_wall = episode_wall_anchor + simulation_time / config.realtime_speed
                    remaining = target_wall - perf_counter()
                    if remaining > 0:
                        sleep(remaining)
        finally:
            if viewer is not None:
                viewer.close()

        final_simulation_time = float(loop.simulation.mj_data.time)
        joint_delta = current_state.positions - initial_joint_positions
        max_abs_joint_delta = float(np.max(np.abs(joint_delta)))
        rms_joint_delta = float(np.sqrt(np.mean(np.square(joint_delta))))

    wall_seconds = perf_counter() - wall_start
    loop_wall_seconds = perf_counter() - loop_wall_start
    loop_realtime_factor = final_simulation_time / max(loop_wall_seconds, 1e-12)
    result: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": "interactive physical-engine diagnostic with an isolated toy recurrent signal processor",
        "scientific_status": DiagnosticToyCNS.scientific_status,
        "forbidden_claims": [
            "MaleCNS behavior",
            "emergent fly behavior",
            "calibrated motor behavior",
            "closed-loop connectome validation",
        ],
        "bypassed_components": [
            "cns.malecns",
            "adapter.motor.routing",
            "adapter.motor.transduction",
        ],
        "used_components": [
            "body.flybody",
            "sensor.proprioception exact joint-state API",
            "body.flybody exact actuator addresses",
        ],
        "config": {
            "seed": config.seed,
            "duration_seconds": config.duration_seconds,
            "amplitude": config.amplitude,
            "realtime_speed": config.realtime_speed,
            "physics_timestep": config.physics_timestep,
            "native_physics_timestep": native_physics_dt,
            "control_substeps": config.control_substeps,
            "render_fps": config.render_fps,
            "hidden_size": config.hidden_size,
            "headless": config.headless,
        },
        "toy_cns": {
            "hidden_states": toy.hidden_size,
            "recurrent_edges": toy.edge_count,
            "input_channels": toy.joint_count * 2,
            "output_channels": toy.actuator_count,
            "parameter_origin": "seeded_random_diagnostic_only",
        },
        "result": {
            "completed_reason": completed_reason,
            "simulation_seconds": final_simulation_time,
            "wall_seconds": wall_seconds,
            "startup_and_shutdown_wall_seconds": wall_seconds - loop_wall_seconds,
            "loop_wall_seconds": loop_wall_seconds,
            "realtime_factor": loop_realtime_factor,
            "control_steps": total_control_steps,
            "physics_steps": total_physics_steps,
            "max_abs_command": max_abs_command,
            "mean_abs_command": sum_abs_command / max(command_samples, 1),
            "max_abs_joint_delta": max_abs_joint_delta,
            "rms_joint_delta": rms_joint_delta,
            "finite_physics_state": True,
        },
    }
    config.output.parent.mkdir(parents=True, exist_ok=True)
    config.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        f"[OK] Demo finished: {final_simulation_time:.3f}s simulated in "
        f"{loop_wall_seconds:.3f}s of loop time ({loop_realtime_factor:.2f}x realtime); "
        f"{wall_seconds - loop_wall_seconds:.3f}s startup/shutdown."
    )
    print(
        f"[OK] Physical response: max joint displacement={max_abs_joint_delta:.6f}, "
        f"RMS={rms_joint_delta:.6f}."
    )
    print(f"[OK] Diagnostic summary: {config.output}")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open the isolated toy-CNS MuJoCo physical diagnostic viewer"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="simulated seconds; 0 runs until the viewer is closed",
    )
    parser.add_argument("--seed", type=int, default=260925)
    parser.add_argument("--amplitude", type=float, default=0.003)
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="target realtime multiplier; 0 runs as fast as possible",
    )
    parser.add_argument("--physics-timestep", type=float, default=0.0005)
    parser.add_argument("--control-substeps", type=int, default=20)
    parser.add_argument("--render-fps", type=float, default=30.0)
    parser.add_argument("--hidden-size", type=int, default=64)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = DiagnosticDemoConfig(
        seed=args.seed,
        duration_seconds=args.duration,
        amplitude=args.amplitude,
        realtime_speed=args.speed,
        physics_timestep=args.physics_timestep,
        control_substeps=args.control_substeps,
        render_fps=args.render_fps,
        hidden_size=args.hidden_size,
        headless=args.headless,
        output=args.output,
    )
    run_diagnostic_demo(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

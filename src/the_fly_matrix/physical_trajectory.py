from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter, sleep
from typing import Any, Mapping

import numpy as np

from .ledger import ROOT
from .runtime import FlyBodyPhysicsLoop


SCHEMA_NAME = "the_fly_matrix.physical_trajectory"
SCHEMA_VERSION = 1
DEFAULT_RUN_ROOT = ROOT / "runs" / "closed-loop"


class TrajectoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class PhysicalFrame:
    timestamp_s: float
    qpos: np.ndarray
    qvel: np.ndarray
    actuator_commands: np.ndarray
    neural_summary: np.ndarray


@dataclass(frozen=True)
class PhysicalTrajectory:
    """Portable physical replay independent of the controller that created it.

    The stable boundary is the complete MuJoCo generalized state plus the ordered
    actuator commands. Neural details are optional diagnostics and are never
    required by the player.
    """

    timestamps_s: np.ndarray
    qpos: np.ndarray
    qvel: np.ndarray
    actuator_commands: np.ndarray
    neural_summary: np.ndarray
    sensory_observations: Mapping[str, np.ndarray]
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        timestamps = np.asarray(self.timestamps_s)
        qpos = np.asarray(self.qpos)
        qvel = np.asarray(self.qvel)
        commands = np.asarray(self.actuator_commands)
        neural = np.asarray(self.neural_summary)
        if timestamps.ndim != 1 or not len(timestamps):
            raise TrajectoryError("trajectory must contain at least one timestamp")
        count = len(timestamps)
        if qpos.ndim != 2 or qvel.ndim != 2 or commands.ndim != 2 or neural.ndim != 2:
            raise TrajectoryError("trajectory arrays must be rank one or two as declared")
        if any(len(values) != count for values in (qpos, qvel, commands, neural)):
            raise TrajectoryError("every trajectory array must contain one row per timestamp")
        if not all(np.isfinite(values).all() for values in (timestamps, qpos, qvel, commands, neural)):
            raise TrajectoryError("trajectory contains non-finite values")
        for name, values in self.sensory_observations.items():
            if not name or "__" in name:
                raise TrajectoryError("sensory observation names must be non-empty and cannot contain '__'")
            array = np.asarray(values)
            if array.ndim != 2 or len(array) != count or not np.isfinite(array).all():
                raise TrajectoryError(f"invalid sensory observation array: {name}")
        if timestamps[0] < 0 or np.any(np.diff(timestamps) <= 0):
            raise TrajectoryError("timestamps must be non-negative and strictly increasing")
        if self.metadata.get("schema_name") != SCHEMA_NAME:
            raise TrajectoryError("unknown physical trajectory schema")
        if int(self.metadata.get("schema_version", -1)) != SCHEMA_VERSION:
            raise TrajectoryError("unsupported physical trajectory schema version")
        model = self.metadata.get("model", {})
        expected = (int(model.get("nq", -1)), int(model.get("nv", -1)), int(model.get("nu", -1)))
        actual = (qpos.shape[1], qvel.shape[1], commands.shape[1])
        if actual != expected:
            raise TrajectoryError(f"trajectory/model dimensions disagree: {actual} != {expected}")
        actuator_names = tuple(model.get("actuator_names", ()))
        if len(actuator_names) != commands.shape[1] or len(set(actuator_names)) != len(actuator_names):
            raise TrajectoryError("trajectory actuator identity list is invalid")

    @property
    def frame_count(self) -> int:
        return len(self.timestamps_s)

    @property
    def duration_s(self) -> float:
        return float(self.timestamps_s[-1])

    def frame(self, index: int) -> PhysicalFrame:
        return PhysicalFrame(
            timestamp_s=float(self.timestamps_s[index]),
            qpos=self.qpos[index],
            qvel=self.qvel[index],
            actuator_commands=self.actuator_commands[index],
            neural_summary=self.neural_summary[index],
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamps_s": np.asarray(self.timestamps_s, dtype=np.float64),
            "qpos": np.asarray(self.qpos, dtype=np.float64),
            "qvel": np.asarray(self.qvel, dtype=np.float64),
            "actuator_commands": np.asarray(self.actuator_commands, dtype=np.float32),
            "neural_summary": np.asarray(self.neural_summary, dtype=np.float32),
            "metadata_json": np.asarray(json.dumps(dict(self.metadata), sort_keys=True)),
        }
        payload.update(
            {
                f"sensor__{name}": np.asarray(values, dtype=np.float32)
                for name, values in self.sensory_observations.items()
            }
        )
        np.savez_compressed(path, **payload)

    @classmethod
    def load(cls, path: Path) -> "PhysicalTrajectory":
        if not path.is_file():
            raise FileNotFoundError(path)
        with np.load(path, allow_pickle=False) as archive:
            required = {
                "timestamps_s",
                "qpos",
                "qvel",
                "actuator_commands",
                "neural_summary",
                "metadata_json",
            }
            missing = required - set(archive.files)
            if missing:
                raise TrajectoryError(f"trajectory archive is missing {sorted(missing)}")
            metadata = json.loads(str(archive["metadata_json"].item()))
            sensory = {
                name.removeprefix("sensor__"): archive[name].copy()
                for name in archive.files
                if name.startswith("sensor__")
            }
            return cls(
                timestamps_s=archive["timestamps_s"].copy(),
                qpos=archive["qpos"].copy(),
                qvel=archive["qvel"].copy(),
                actuator_commands=archive["actuator_commands"].copy(),
                neural_summary=archive["neural_summary"].copy(),
                sensory_observations=sensory,
                metadata=metadata,
            )


def model_contract(loop: FlyBodyPhysicsLoop) -> dict[str, Any]:
    model = loop.simulation.mj_model
    identity = {
        "id": "flybody.generated-wiring-v1",
        "nq": int(model.nq),
        "nv": int(model.nv),
        "nu": len(loop.actuator_names),
        "actuator_names": list(loop.actuator_names),
        "joint_names": list(loop.joint_names),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    identity["contract_sha256"] = hashlib.sha256(encoded).hexdigest()
    return identity


def validate_model_contract(loop: FlyBodyPhysicsLoop, metadata: Mapping[str, Any]) -> None:
    recorded = metadata.get("model", {})
    current = model_contract(loop)
    for key in ("nq", "nv", "nu", "actuator_names", "joint_names", "contract_sha256"):
        if recorded.get(key) != current.get(key):
            raise TrajectoryError(f"physical replay model mismatch for {key}")


def apply_frame(loop: FlyBodyPhysicsLoop, frame: PhysicalFrame) -> None:
    import mujoco

    data = loop.simulation.mj_data
    if frame.qpos.shape != data.qpos.shape or frame.qvel.shape != data.qvel.shape:
        raise TrajectoryError("physical frame dimensions do not match the presentation model")
    data.qpos[:] = frame.qpos
    data.qvel[:] = frame.qvel
    data.time = frame.timestamp_s
    mujoco.mj_forward(loop.simulation.mj_model, data)


def latest_trajectory(root: Path = DEFAULT_RUN_ROOT) -> Path:
    candidates = sorted(root.glob("*/physical-trajectory.npz"))
    if not candidates:
        raise FileNotFoundError(f"No physical trajectory found below {root}")
    return candidates[-1]


class ViewerControls:
    def __init__(self) -> None:
        self.paused = False
        self.reset_requested = False
        self.quit_requested = False
        self.speed_multiplier = 1.0

    def on_key(self, keycode: int) -> None:
        if keycode == 32:
            self.paused = not self.paused
        elif keycode in (82, 259):
            self.reset_requested = True
        elif keycode in (81, 256):
            self.quit_requested = True
        elif keycode in (45, 333):
            self.speed_multiplier = max(self.speed_multiplier / 2.0, 0.125)
        elif keycode in (61, 334):
            self.speed_multiplier = min(self.speed_multiplier * 2.0, 16.0)


class PassiveFlyViewer:
    """One viewer shell shared by recorded and live physical frame producers."""

    def __init__(self, loop: FlyBodyPhysicsLoop, title: str, status: str):
        import mujoco
        import mujoco.viewer

        self._mujoco = mujoco
        self.loop = loop
        self.title = title
        self.status = status
        self.controls = ViewerControls()
        self.viewer = mujoco.viewer.launch_passive(
            loop.simulation.mj_model,
            loop.simulation.mj_data,
            key_callback=self.controls.on_key,
            show_left_ui=True,
            show_right_ui=True,
        )
        self.viewer.cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        self.viewer.cam.lookat[:] = np.asarray([0.0, 0.0, 1.0])
        self.viewer.cam.distance = 8.0
        self.viewer.cam.azimuth = 135.0
        self.viewer.cam.elevation = -20.0

    def is_running(self) -> bool:
        return self.viewer.is_running() and not self.controls.quit_requested

    def sync(self, simulation_time: float, detail: str) -> None:
        self.viewer.set_texts(
            [
                (
                    self._mujoco.mjtFontScale.mjFONTSCALE_150,
                    self._mujoco.mjtGridPos.mjGRID_TOPLEFT,
                    self.title,
                    self.status,
                ),
                (
                    self._mujoco.mjtFontScale.mjFONTSCALE_100,
                    self._mujoco.mjtGridPos.mjGRID_BOTTOMLEFT,
                    f"sim {simulation_time:7.3f} s | {detail}",
                    "Space pause | R reset | -/+ speed | Q quit",
                ),
            ]
        )
        self.viewer.sync()

    def close(self) -> None:
        self.viewer.close()

    def __enter__(self) -> "PassiveFlyViewer":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()


def run_replay(path: Path, *, speed: float = 1.0, render_fps: float = 60.0, headless: bool = False) -> dict[str, Any]:
    if speed <= 0 or render_fps <= 0:
        raise ValueError("speed and render_fps must be positive")
    trajectory = PhysicalTrajectory.load(path)
    print(f"[OK] Replay: {trajectory.frame_count:,} frames, {trajectory.duration_s:.3f} s")
    with FlyBodyPhysicsLoop.from_generated_wiring() as loop:
        validate_model_contract(loop, trajectory.metadata)
        if headless:
            for index in range(trajectory.frame_count):
                apply_frame(loop, trajectory.frame(index))
            return {
                "path": str(path),
                "frames_presented": trajectory.frame_count,
                "duration_s": trajectory.duration_s,
                "model_contract_passed": True,
                "headless": True,
            }

        with PassiveFlyViewer(
            loop,
            title="PHYSICAL TRAJECTORY REPLAY",
            status=str(trajectory.metadata.get("claim_label", "UNSPECIFIED CLAIM STATUS")),
        ) as presentation:
            index = 0
            effective_speed = speed
            wall_anchor = perf_counter()
            sim_anchor = float(trajectory.timestamps_s[0])
            last_wall = wall_anchor
            ended = False
            while presentation.is_running():
                if presentation.controls.reset_requested:
                    index = 0
                    ended = False
                    presentation.controls.paused = False
                    wall_anchor = perf_counter()
                    sim_anchor = float(trajectory.timestamps_s[0])
                    presentation.controls.reset_requested = False
                requested_speed = speed * presentation.controls.speed_multiplier
                if requested_speed != effective_speed:
                    sim_anchor = float(trajectory.timestamps_s[index])
                    wall_anchor = perf_counter()
                    effective_speed = requested_speed
                if presentation.controls.paused:
                    detail = "END — R restart" if ended else "PAUSED"
                    presentation.sync(float(trajectory.timestamps_s[index]), detail)
                    sleep(0.02)
                    wall_anchor = perf_counter()
                    sim_anchor = float(trajectory.timestamps_s[index])
                    continue
                target_sim = sim_anchor + (perf_counter() - wall_anchor) * effective_speed
                if target_sim >= trajectory.timestamps_s[-1]:
                    index = trajectory.frame_count - 1
                    apply_frame(loop, trajectory.frame(index))
                    ended = True
                    presentation.controls.paused = True
                    presentation.sync(float(trajectory.timestamps_s[index]), "END — R restart")
                    continue
                index = min(
                    max(int(np.searchsorted(trajectory.timestamps_s, target_sim, side="right")) - 1, 0),
                    trajectory.frame_count - 1,
                )
                frame = trajectory.frame(index)
                apply_frame(loop, frame)
                presentation.sync(frame.timestamp_s, f"replay {effective_speed:.2f}x | frame {index + 1:,}/{trajectory.frame_count:,}")
                now = perf_counter()
                remaining = 1.0 / render_fps - (now - last_wall)
                if remaining > 0:
                    sleep(remaining)
                last_wall = perf_counter()
    return {
        "path": str(path),
        "frames_presented": trajectory.frame_count,
        "duration_s": trajectory.duration_s,
        "model_contract_passed": True,
        "headless": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Play a controller-independent FlyBody trajectory")
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--render-fps", type=float, default=60.0)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    path = args.path or latest_trajectory()
    run_replay(path, speed=args.speed, render_fps=args.render_fps, headless=args.headless)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

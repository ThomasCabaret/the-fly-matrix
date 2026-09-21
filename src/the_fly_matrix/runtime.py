from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from .ledger import ROOT


WIRING_ROOT = ROOT / "data" / "derived" / "wiring"
CHANNEL_PATH = WIRING_ROOT / "basal-clamp-channels.csv"
ROUTE_PATH = WIRING_ROOT / "basal-clamp-routes.parquet"
PROPRIO_CHANNEL_PATH = WIRING_ROOT / "proprioception-channels.csv"
PROPRIO_ROUTE_PATH = WIRING_ROOT / "proprioception-routes.parquet"
MECHANO_CHANNEL_PATH = WIRING_ROOT / "mechanosensation-channels.csv"
MECHANO_ROUTE_PATH = WIRING_ROOT / "mechanosensation-routes.parquet"
VISION_CHANNEL_PATH = WIRING_ROOT / "vision-channels.csv"
VISION_ROUTE_PATH = WIRING_ROOT / "vision-routes.parquet"
MOTOR_CHANNEL_PATH = WIRING_ROOT / "motor-channels.csv"
MOTOR_ROUTE_PATH = WIRING_ROOT / "motor-routes.parquet"
MOTOR_ACTUATOR_CANDIDATE_PATH = WIRING_ROOT / "motor-actuator-candidates.parquet"
UNCLASSIFIED_CHANNEL_PATH = WIRING_ROOT / "unclassified-sensory-channels.csv"
UNCLASSIFIED_ROUTE_PATH = WIRING_ROOT / "unclassified-sensory-routes.parquet"
FLYBODY_PROPRIO_CHANNEL_PATH = WIRING_ROOT / "flybody-proprioception-channels.csv"
FLYBODY_TOUCH_CHANNEL_PATH = WIRING_ROOT / "flybody-touch-channels.csv"
FLYBODY_ACTUATOR_CHANNEL_PATH = WIRING_ROOT / "flybody-actuator-channels.csv"
FLYBODY_VISION_CHANNEL_PATH = WIRING_ROOT / "flybody-vision-channels.csv"


@dataclass(frozen=True)
class SparseActivity:
    """Activity addressed directly to MaleCNS body IDs."""

    body_ids: np.ndarray
    values: np.ndarray

    def __post_init__(self) -> None:
        if self.body_ids.ndim != 1 or self.values.ndim != 1:
            raise ValueError("body_ids and values must be one-dimensional")
        if len(self.body_ids) != len(self.values):
            raise ValueError("body_ids and values must have identical lengths")
        if len(np.unique(self.body_ids)) != len(self.body_ids):
            raise ValueError("SparseActivity body IDs must be unique")
        if not np.isfinite(self.values).all():
            raise ValueError("activity values must be finite")


@dataclass(frozen=True)
class ChannelActivity:
    """Activity addressed to generated adapter channels."""

    channel_ids: tuple[str, ...]
    values: np.ndarray

    def __post_init__(self) -> None:
        if self.values.ndim != 1:
            raise ValueError("channel values must be one-dimensional")
        if len(self.channel_ids) != len(self.values):
            raise ValueError("channel_ids and values must have identical lengths")
        if len(set(self.channel_ids)) != len(self.channel_ids):
            raise ValueError("ChannelActivity IDs must be unique")
        if not np.isfinite(self.values).all():
            raise ValueError("channel values must be finite")


@dataclass(frozen=True)
class GroupedChannelActivity:
    """Lossless channel activity annotated with a structural group per value."""

    channel_ids: tuple[str, ...]
    group_ids: tuple[str, ...]
    values: np.ndarray

    def __post_init__(self) -> None:
        if self.values.ndim != 1:
            raise ValueError("grouped channel values must be one-dimensional")
        if len(self.channel_ids) != len(self.values) or len(self.group_ids) != len(self.values):
            raise ValueError("channel_ids, group_ids and values must have identical lengths")
        if len(set(self.channel_ids)) != len(self.channel_ids):
            raise ValueError("GroupedChannelActivity channel IDs must be unique")
        if not all(self.group_ids):
            raise ValueError("GroupedChannelActivity group IDs must be non-empty")
        if not np.isfinite(self.values).all():
            raise ValueError("grouped channel values must be finite")


@dataclass(frozen=True)
class JointState:
    """Uncalibrated FlyBody joint positions and velocities in manifest order."""

    joint_names: tuple[str, ...]
    positions: np.ndarray
    velocities: np.ndarray

    def __post_init__(self) -> None:
        expected = (len(self.joint_names),)
        if self.positions.shape != expected or self.velocities.shape != expected:
            raise ValueError("joint positions and velocities must match joint_names")
        if len(set(self.joint_names)) != len(self.joint_names):
            raise ValueError("JointState names must be unique")
        if not np.isfinite(self.positions).all() or not np.isfinite(self.velocities).all():
            raise ValueError("joint state values must be finite")


class FlyBodyProprioceptionSensor:
    """Extract the 102 physical joint observables from a compiled FlyBody state."""

    box_id = "sensor.proprioception"

    def __init__(self, channels: pd.DataFrame):
        if channels.empty:
            raise ValueError("No generated FlyBody proprioception channels found")
        required = {
            "channel_id",
            "joint_name",
            "joint_id",
            "qpos_address",
            "qvel_address",
        }
        missing = required - set(channels.columns)
        if missing:
            raise ValueError(f"Missing FlyBody channel columns: {sorted(missing)}")
        self.channels = channels.sort_values("joint_id").reset_index(drop=True)
        if self.channels["channel_id"].duplicated().any():
            raise ValueError("Duplicate FlyBody proprioception channel IDs")
        if self.channels["joint_name"].duplicated().any():
            raise ValueError("Duplicate FlyBody joint names")
        self.channel_ids = tuple(self.channels["channel_id"].astype(str))
        self.joint_names = tuple(self.channels["joint_name"].astype(str))
        self._qpos_addresses = self.channels["qpos_address"].to_numpy(dtype=np.int64)
        self._qvel_addresses = self.channels["qvel_address"].to_numpy(dtype=np.int64)
        if len(np.unique(self._qpos_addresses)) != len(self._qpos_addresses):
            raise ValueError("Duplicate qpos addresses")
        if len(np.unique(self._qvel_addresses)) != len(self._qvel_addresses):
            raise ValueError("Duplicate qvel addresses")
        self.qpos_size = int(self._qpos_addresses.max()) + 1
        self.qvel_size = int(self._qvel_addresses.max()) + 1

    @classmethod
    def from_generated_wiring(
        cls, channel_path: Path = FLYBODY_PROPRIO_CHANNEL_PATH
    ) -> "FlyBodyProprioceptionSensor":
        if not channel_path.is_file():
            raise FileNotFoundError(
                "FlyBody proprioception wiring is absent; run the wiring builder first"
            )
        return cls(pd.read_csv(channel_path))

    def _state_vector(
        self,
        values: Mapping[str, float] | np.ndarray,
        expected_size: int,
        label: str,
    ) -> np.ndarray:
        if isinstance(values, Mapping):
            missing = set(self.joint_names) - set(values)
            extra = set(values) - set(self.joint_names)
            if missing or extra:
                raise ValueError(
                    f"{label}: joint mismatch; missing={len(missing)}, extra={len(extra)}"
                )
            result = np.asarray([values[name] for name in self.joint_names], dtype=np.float64)
            if not np.isfinite(result).all():
                raise ValueError(f"{label} values must be finite")
            return result
        result = np.asarray(values, dtype=np.float64)
        if result.shape != (expected_size,):
            raise ValueError(f"{label}: expected raw shape {(expected_size,)}, got {result.shape}")
        if not np.isfinite(result).all():
            raise ValueError(f"{label} values must be finite")
        return result

    def step(
        self,
        qpos: Mapping[str, float] | np.ndarray,
        qvel: Mapping[str, float] | np.ndarray,
    ) -> JointState:
        positions = self._state_vector(qpos, self.qpos_size, "qpos")
        velocities = self._state_vector(qvel, self.qvel_size, "qvel")
        if not isinstance(qpos, Mapping):
            positions = positions[self._qpos_addresses]
        if not isinstance(qvel, Mapping):
            velocities = velocities[self._qvel_addresses]
        return JointState(
            joint_names=self.joint_names,
            positions=positions.copy(),
            velocities=velocities.copy(),
        )


@dataclass(frozen=True)
class GroundContactState:
    """Six aggregate FlyGym leg-ground contact observations."""

    leg_names: tuple[str, ...]
    contact_found: np.ndarray
    forces: np.ndarray
    torques: np.ndarray
    positions: np.ndarray
    normals: np.ndarray
    tangents: np.ndarray

    def __post_init__(self) -> None:
        count = len(self.leg_names)
        if self.contact_found.shape != (count,):
            raise ValueError("contact_found must contain one value per leg")
        for label, values in (
            ("forces", self.forces),
            ("torques", self.torques),
            ("positions", self.positions),
            ("normals", self.normals),
            ("tangents", self.tangents),
        ):
            if values.shape != (count, 3):
                raise ValueError(f"{label} must have shape {(count, 3)}")
            if not np.isfinite(values).all():
                raise ValueError(f"{label} values must be finite")
        if not np.isfinite(self.contact_found).all():
            raise ValueError("contact_found values must be finite")


class FlyBodyGroundContactSensor:
    """Decode FlyGym's six native 16-scalar aggregate leg contact sensors."""

    box_id = "sensor.touch"

    def __init__(self, channels: pd.DataFrame):
        if channels.empty:
            raise ValueError("No generated FlyBody touch channels found")
        required = {
            "channel_id",
            "leg",
            "sensor_name",
            "sensor_address",
            "sensor_dimension",
        }
        missing = required - set(channels.columns)
        if missing:
            raise ValueError(f"Missing FlyBody touch columns: {sorted(missing)}")
        self.channels = channels.sort_values("sensor_address").reset_index(drop=True)
        if self.channels["channel_id"].duplicated().any():
            raise ValueError("Duplicate FlyBody touch channel IDs")
        if not self.channels["sensor_dimension"].eq(16).all():
            raise ValueError("FlyBody aggregate ground-contact sensors must be 16-dimensional")
        self.channel_ids = tuple(self.channels["channel_id"].astype(str))
        self.leg_names = tuple(self.channels["leg"].astype(str))
        self._addresses = self.channels["sensor_address"].to_numpy(dtype=np.int64)
        self._dimensions = self.channels["sensor_dimension"].to_numpy(dtype=np.int64)
        self.sensor_data_size = int(np.max(self._addresses + self._dimensions))

    @classmethod
    def from_generated_wiring(
        cls, channel_path: Path = FLYBODY_TOUCH_CHANNEL_PATH
    ) -> "FlyBodyGroundContactSensor":
        if not channel_path.is_file():
            raise FileNotFoundError("FlyBody touch wiring is absent; run the wiring builder first")
        return cls(pd.read_csv(channel_path))

    def step(self, sensor_data: np.ndarray) -> GroundContactState:
        raw = np.asarray(sensor_data, dtype=np.float64)
        if raw.ndim != 1 or len(raw) < self.sensor_data_size:
            raise ValueError(
                f"sensordata: expected a vector of at least {self.sensor_data_size} values, "
                f"got {raw.shape}"
            )
        if not np.isfinite(raw).all():
            raise ValueError("sensordata values must be finite")
        rows = np.stack(
            [raw[address : address + dimension] for address, dimension in zip(self._addresses, self._dimensions)]
        )
        return GroundContactState(
            leg_names=self.leg_names,
            contact_found=rows[:, 0].copy(),
            forces=rows[:, 1:4].copy(),
            torques=rows[:, 4:7].copy(),
            positions=rows[:, 7:10].copy(),
            normals=rows[:, 10:13].copy(),
            tangents=rows[:, 13:16].copy(),
        )


@dataclass(frozen=True)
class ActuatorCommands:
    """Control vector addressed to the compiled FlyBody actuators."""

    actuator_names: tuple[str, ...]
    values: np.ndarray

    def __post_init__(self) -> None:
        if self.values.shape != (len(self.actuator_names),):
            raise ValueError("actuator command values must match actuator_names")
        if len(set(self.actuator_names)) != len(self.actuator_names):
            raise ValueError("Actuator command names must be unique")
        if not np.isfinite(self.values).all():
            raise ValueError("actuator command values must be finite")


class FlyBodyActuatorInterface:
    """Address pre-transduced values to all 102 FlyBody control slots."""

    box_id = "body.flybody"

    def __init__(self, channels: pd.DataFrame):
        if channels.empty:
            raise ValueError("No generated FlyBody actuator channels found")
        required = {"channel_id", "actuator_name", "control_address", "target_joint_name"}
        missing = required - set(channels.columns)
        if missing:
            raise ValueError(f"Missing FlyBody actuator columns: {sorted(missing)}")
        self.channels = channels.sort_values("control_address").reset_index(drop=True)
        if self.channels["channel_id"].duplicated().any():
            raise ValueError("Duplicate FlyBody actuator channel IDs")
        if self.channels["actuator_name"].duplicated().any():
            raise ValueError("Duplicate FlyBody actuator names")
        self.channel_ids = tuple(self.channels["channel_id"].astype(str))
        self.actuator_names = tuple(self.channels["actuator_name"].astype(str))
        self._control_addresses = self.channels["control_address"].to_numpy(dtype=np.int64)
        if len(np.unique(self._control_addresses)) != len(self._control_addresses):
            raise ValueError("Duplicate FlyBody control addresses")
        self.control_size = int(self._control_addresses.max()) + 1

    @classmethod
    def from_generated_wiring(
        cls, channel_path: Path = FLYBODY_ACTUATOR_CHANNEL_PATH
    ) -> "FlyBodyActuatorInterface":
        if not channel_path.is_file():
            raise FileNotFoundError(
                "FlyBody actuator wiring is absent; run the wiring builder first"
            )
        return cls(pd.read_csv(channel_path))

    def step(self, command_values: Mapping[str, float] | np.ndarray) -> ActuatorCommands:
        if isinstance(command_values, Mapping):
            missing = set(self.actuator_names) - set(command_values)
            extra = set(command_values) - set(self.actuator_names)
            if missing or extra:
                raise ValueError(
                    f"actuator commands: mismatch; missing={len(missing)}, extra={len(extra)}"
                )
            values = np.asarray(
                [command_values[name] for name in self.actuator_names], dtype=np.float64
            )
        else:
            values = np.asarray(command_values, dtype=np.float64)
        if values.shape != (len(self.actuator_names),):
            raise ValueError(
                f"actuator commands: expected {len(self.actuator_names)} values, got {values.shape}"
            )
        if not np.isfinite(values).all():
            raise ValueError("actuator command values must be finite")
        controls = np.zeros(self.control_size, dtype=np.float64)
        controls[self._control_addresses] = values
        names_by_address = tuple(
            name
            for _, name in sorted(zip(self._control_addresses, self.actuator_names))
        )
        return ActuatorCommands(actuator_names=names_by_address, values=controls)


class FlyBodyVisionSensor:
    """Extract one active yellow/pale sample per FlyGym ommatidium."""

    box_id = "sensor.vision"

    def __init__(self, channels: pd.DataFrame):
        if channels.empty:
            raise ValueError("No generated FlyBody vision channels found")
        required = {
            "channel_id",
            "eye_index",
            "eye",
            "ommatidium_id",
            "ommatidium_type",
            "component_index",
        }
        missing = required - set(channels.columns)
        if missing:
            raise ValueError(f"Missing FlyBody vision columns: {sorted(missing)}")
        self.channels = channels.sort_values(["eye_index", "ommatidium_id"]).reset_index(
            drop=True
        )
        if self.channels["channel_id"].duplicated().any():
            raise ValueError("Duplicate FlyBody vision channel IDs")
        if self.channels.duplicated(["eye_index", "ommatidium_id"]).any():
            raise ValueError("Duplicate FlyBody eye/ommatidium pairs")
        self.channel_ids = tuple(self.channels["channel_id"].astype(str))
        self._eye_indices = self.channels["eye_index"].to_numpy(dtype=np.int64)
        self._ommatidium_indices = self.channels["ommatidium_id"].to_numpy(dtype=np.int64)
        self._component_indices = self.channels["component_index"].to_numpy(dtype=np.int64)
        self.eye_count = int(self._eye_indices.max()) + 1
        self.ommatidia_per_eye = int(self._ommatidium_indices.max()) + 1
        self.readout_shape = (self.eye_count, self.ommatidia_per_eye, 2)

    @classmethod
    def from_generated_wiring(
        cls, channel_path: Path = FLYBODY_VISION_CHANNEL_PATH
    ) -> "FlyBodyVisionSensor":
        if not channel_path.is_file():
            raise FileNotFoundError("FlyBody vision wiring is absent; run the wiring builder first")
        return cls(pd.read_csv(channel_path))

    def step(self, ommatidia_readouts: np.ndarray) -> ChannelActivity:
        readouts = np.asarray(ommatidia_readouts, dtype=np.float64)
        if readouts.shape != self.readout_shape:
            raise ValueError(
                f"ommatidia readouts: expected {self.readout_shape}, got {readouts.shape}"
            )
        if not np.isfinite(readouts).all():
            raise ValueError("ommatidia readouts must be finite")
        values = readouts[
            self._eye_indices,
            self._ommatidium_indices,
            self._component_indices,
        ]
        return ChannelActivity(channel_ids=self.channel_ids, values=values.copy())


class BasalClampBox:
    """Executable type-A box whose scientific values are injected from outside.

    The box owns terminal channels and exact fan-out routes. It deliberately does
    not choose rates, noise distributions or calibration values.
    """

    adapter_type = "A"

    def __init__(self, box_id: str, channels: pd.DataFrame, routes: pd.DataFrame):
        self.box_id = box_id
        self.channels = channels.loc[channels["clamp_id"].eq(box_id)].copy()
        self.routes = routes.loc[routes["clamp_id"].eq(box_id)].copy()
        if self.channels.empty or self.routes.empty:
            raise ValueError(f"No generated wiring found for {box_id}")
        if self.channels["channel_id"].duplicated().any():
            raise ValueError(f"Duplicate channel IDs for {box_id}")
        if self.routes["target_body_id"].duplicated().any():
            raise ValueError(f"Duplicate target body IDs for {box_id}")
        channel_ids = self.channels["channel_id"].astype(str).tolist()
        self.channel_ids = tuple(channel_ids)
        channel_index = {channel_id: index for index, channel_id in enumerate(channel_ids)}
        unknown = set(self.routes["channel_id"].astype(str)) - set(channel_index)
        if unknown:
            raise ValueError(f"Routes refer to unknown channels for {box_id}: {sorted(unknown)[:3]}")
        self._route_channel_indices = np.asarray(
            [channel_index[str(value)] for value in self.routes["channel_id"]], dtype=np.int64
        )
        self._target_body_ids = self.routes["target_body_id"].to_numpy(dtype=np.int64)

    @classmethod
    def from_generated_wiring(
        cls,
        box_id: str,
        channel_path: Path = CHANNEL_PATH,
        route_path: Path = ROUTE_PATH,
    ) -> "BasalClampBox":
        if not channel_path.is_file() or not route_path.is_file():
            raise FileNotFoundError("Basal clamp wiring is absent; run the wiring builder first")
        return cls(box_id, pd.read_csv(channel_path), pd.read_parquet(route_path))

    def step(self, channel_values: Mapping[str, float] | np.ndarray) -> SparseActivity:
        """Fan injected channel values out to exact MaleCNS body IDs."""
        if isinstance(channel_values, Mapping):
            missing = set(self.channel_ids) - set(channel_values)
            extra = set(channel_values) - set(self.channel_ids)
            if missing or extra:
                raise ValueError(
                    f"{self.box_id}: channel parameter mismatch; missing={len(missing)}, extra={len(extra)}"
                )
            values = np.asarray([channel_values[item] for item in self.channel_ids], dtype=np.float64)
        else:
            values = np.asarray(channel_values, dtype=np.float64)
        if values.shape != (len(self.channel_ids),):
            raise ValueError(
                f"{self.box_id}: expected {len(self.channel_ids)} channel values, got {values.shape}"
            )
        return SparseActivity(
            body_ids=self._target_body_ids.copy(),
            values=values[self._route_channel_indices],
        )


class ProprioceptionRoutingBox:
    """Executable type-C downstream router with an explicitly deferred upstream map."""

    adapter_type = "C"
    box_id = "adapter.proprioception.routing"

    def __init__(self, channels: pd.DataFrame, routes: pd.DataFrame):
        self.channels = channels.loc[channels["routing_box_id"].eq(self.box_id)].copy()
        self.routes = routes.loc[routes["routing_box_id"].eq(self.box_id)].copy()
        if self.channels.empty or self.routes.empty:
            raise ValueError("No generated proprioceptive wiring found")
        if self.channels["channel_id"].duplicated().any():
            raise ValueError("Duplicate proprioceptive channel IDs")
        if self.routes["target_body_id"].duplicated().any():
            raise ValueError("Duplicate proprioceptive target body IDs")
        channel_ids = self.channels["channel_id"].astype(str).tolist()
        self.channel_ids = tuple(channel_ids)
        channel_index = {channel_id: index for index, channel_id in enumerate(channel_ids)}
        unknown = set(self.routes["channel_id"].astype(str)) - set(channel_index)
        if unknown:
            raise ValueError(f"Routes refer to unknown proprioceptive channels: {sorted(unknown)[:3]}")
        self._route_channel_indices = np.asarray(
            [channel_index[str(value)] for value in self.routes["channel_id"]], dtype=np.int64
        )
        self._target_body_ids = self.routes["target_body_id"].to_numpy(dtype=np.int64)

    @classmethod
    def from_generated_wiring(
        cls,
        channel_path: Path = PROPRIO_CHANNEL_PATH,
        route_path: Path = PROPRIO_ROUTE_PATH,
    ) -> "ProprioceptionRoutingBox":
        if not channel_path.is_file() or not route_path.is_file():
            raise FileNotFoundError("Proprioceptive wiring is absent; run the wiring builder first")
        return cls(pd.read_csv(channel_path), pd.read_parquet(route_path))

    def step(self, channel_values: Mapping[str, float] | np.ndarray) -> SparseActivity:
        if isinstance(channel_values, Mapping):
            missing = set(self.channel_ids) - set(channel_values)
            extra = set(channel_values) - set(self.channel_ids)
            if missing or extra:
                raise ValueError(
                    f"{self.box_id}: channel mismatch; missing={len(missing)}, extra={len(extra)}"
                )
            values = np.asarray([channel_values[item] for item in self.channel_ids], dtype=np.float64)
        else:
            values = np.asarray(channel_values, dtype=np.float64)
        if values.shape != (len(self.channel_ids),):
            raise ValueError(
                f"{self.box_id}: expected {len(self.channel_ids)} channel values, got {values.shape}"
            )
        return SparseActivity(
            body_ids=self._target_body_ids.copy(),
            values=values[self._route_channel_indices],
        )


class MechanosensationRoutingBox:
    """Executable type-C downstream router with physical contact mapping deferred."""

    adapter_type = "C"
    box_id = "adapter.touch.routing"

    def __init__(self, channels: pd.DataFrame, routes: pd.DataFrame):
        self.channels = channels.loc[channels["routing_box_id"].eq(self.box_id)].copy()
        self.routes = routes.loc[routes["routing_box_id"].eq(self.box_id)].copy()
        if self.channels.empty or self.routes.empty:
            raise ValueError("No generated mechanosensory wiring found")
        if self.channels["channel_id"].duplicated().any():
            raise ValueError("Duplicate mechanosensory channel IDs")
        if self.routes["target_body_id"].duplicated().any():
            raise ValueError("Duplicate mechanosensory target body IDs")
        channel_ids = self.channels["channel_id"].astype(str).tolist()
        self.channel_ids = tuple(channel_ids)
        channel_index = {channel_id: index for index, channel_id in enumerate(channel_ids)}
        unknown = set(self.routes["channel_id"].astype(str)) - set(channel_index)
        if unknown:
            raise ValueError(f"Routes refer to unknown mechanosensory channels: {sorted(unknown)[:3]}")
        self._route_channel_indices = np.asarray(
            [channel_index[str(value)] for value in self.routes["channel_id"]], dtype=np.int64
        )
        self._target_body_ids = self.routes["target_body_id"].to_numpy(dtype=np.int64)

    @classmethod
    def from_generated_wiring(
        cls,
        channel_path: Path = MECHANO_CHANNEL_PATH,
        route_path: Path = MECHANO_ROUTE_PATH,
    ) -> "MechanosensationRoutingBox":
        if not channel_path.is_file() or not route_path.is_file():
            raise FileNotFoundError("Mechanosensory wiring is absent; run the wiring builder first")
        return cls(pd.read_csv(channel_path), pd.read_parquet(route_path))

    def step(self, channel_values: Mapping[str, float] | np.ndarray) -> SparseActivity:
        if isinstance(channel_values, Mapping):
            missing = set(self.channel_ids) - set(channel_values)
            extra = set(channel_values) - set(self.channel_ids)
            if missing or extra:
                raise ValueError(
                    f"{self.box_id}: channel mismatch; missing={len(missing)}, extra={len(extra)}"
                )
            values = np.asarray([channel_values[item] for item in self.channel_ids], dtype=np.float64)
        else:
            values = np.asarray(channel_values, dtype=np.float64)
        if values.shape != (len(self.channel_ids),):
            raise ValueError(
                f"{self.box_id}: expected {len(self.channel_ids)} channel values, got {values.shape}"
            )
        return SparseActivity(
            body_ids=self._target_body_ids.copy(),
            values=values[self._route_channel_indices],
        )


class VisionRoutingBox:
    """Executable type-C one-to-one visual router with retinotopy deferred."""

    adapter_type = "C"
    box_id = "adapter.vision.routing"

    def __init__(self, channels: pd.DataFrame, routes: pd.DataFrame):
        self.channels = channels.loc[channels["routing_box_id"].eq(self.box_id)].copy()
        self.routes = routes.loc[routes["routing_box_id"].eq(self.box_id)].copy()
        if self.channels.empty or self.routes.empty:
            raise ValueError("No generated visual wiring found")
        if self.channels["channel_id"].duplicated().any():
            raise ValueError("Duplicate visual channel IDs")
        if self.routes["target_body_id"].duplicated().any():
            raise ValueError("Duplicate visual target body IDs")
        channel_ids = self.channels["channel_id"].astype(str).tolist()
        self.channel_ids = tuple(channel_ids)
        channel_index = {channel_id: index for index, channel_id in enumerate(channel_ids)}
        unknown = set(self.routes["channel_id"].astype(str)) - set(channel_index)
        if unknown:
            raise ValueError(f"Routes refer to unknown visual channels: {sorted(unknown)[:3]}")
        self._route_channel_indices = np.asarray(
            [channel_index[str(value)] for value in self.routes["channel_id"]], dtype=np.int64
        )
        self._target_body_ids = self.routes["target_body_id"].to_numpy(dtype=np.int64)

    @classmethod
    def from_generated_wiring(
        cls,
        channel_path: Path = VISION_CHANNEL_PATH,
        route_path: Path = VISION_ROUTE_PATH,
    ) -> "VisionRoutingBox":
        if not channel_path.is_file() or not route_path.is_file():
            raise FileNotFoundError("Visual wiring is absent; run the wiring builder first")
        return cls(pd.read_csv(channel_path), pd.read_parquet(route_path))

    def step(self, channel_values: Mapping[str, float] | np.ndarray) -> SparseActivity:
        if isinstance(channel_values, Mapping):
            missing = set(self.channel_ids) - set(channel_values)
            extra = set(channel_values) - set(self.channel_ids)
            if missing or extra:
                raise ValueError(
                    f"{self.box_id}: channel mismatch; missing={len(missing)}, extra={len(extra)}"
                )
            values = np.asarray([channel_values[item] for item in self.channel_ids], dtype=np.float64)
        else:
            values = np.asarray(channel_values, dtype=np.float64)
        if values.shape != (len(self.channel_ids),):
            raise ValueError(
                f"{self.box_id}: expected {len(self.channel_ids)} channel values, got {values.shape}"
            )
        return SparseActivity(
            body_ids=self._target_body_ids.copy(),
            values=values[self._route_channel_indices],
        )


class MotorRoutingBox:
    """Type-E router preserving every value and its annotated muscle group."""

    adapter_type = "E"
    box_id = "adapter.motor.routing"

    def __init__(self, channels: pd.DataFrame, routes: pd.DataFrame):
        self.channels = channels.loc[channels["routing_box_id"].eq(self.box_id)].copy()
        self.routes = routes.loc[routes["routing_box_id"].eq(self.box_id)].copy()
        if self.channels.empty or self.routes.empty:
            raise ValueError("No generated motor wiring found")
        if self.channels["channel_id"].duplicated().any():
            raise ValueError("Duplicate motor channel IDs")
        if self.routes["source_body_id"].duplicated().any():
            raise ValueError("Duplicate motor source body IDs")
        channels_by_id = self.channels.set_index("channel_id", drop=False)
        route_channel_ids = self.routes["channel_id"].astype(str).tolist()
        unknown = set(route_channel_ids) - set(channels_by_id.index.astype(str))
        if unknown:
            raise ValueError(f"Routes refer to unknown motor channels: {sorted(unknown)[:3]}")
        self.channel_ids = tuple(route_channel_ids)
        self.source_body_ids = tuple(int(value) for value in self.routes["source_body_id"])
        if "motor_group_id" not in self.routes:
            raise ValueError("Motor routes do not contain annotation-backed group IDs")
        self.motor_group_ids = tuple(self.routes["motor_group_id"].astype(str))
        if len(set(self.motor_group_ids)) != 441:
            raise ValueError("Expected 441 annotation-backed motor groups")

    @classmethod
    def from_generated_wiring(
        cls,
        channel_path: Path = MOTOR_CHANNEL_PATH,
        route_path: Path = MOTOR_ROUTE_PATH,
    ) -> "MotorRoutingBox":
        if not channel_path.is_file() or not route_path.is_file():
            raise FileNotFoundError("Motor wiring is absent; run the wiring builder first")
        return cls(pd.read_csv(channel_path), pd.read_parquet(route_path))

    def step(self, source_values: Mapping[int, float] | np.ndarray) -> GroupedChannelActivity:
        if isinstance(source_values, Mapping):
            missing = set(self.source_body_ids) - set(source_values)
            extra = set(source_values) - set(self.source_body_ids)
            if missing or extra:
                raise ValueError(
                    f"{self.box_id}: source mismatch; missing={len(missing)}, extra={len(extra)}"
                )
            values = np.asarray([source_values[item] for item in self.source_body_ids], dtype=np.float64)
        else:
            values = np.asarray(source_values, dtype=np.float64)
        if values.shape != (len(self.source_body_ids),):
            raise ValueError(
                f"{self.box_id}: expected {len(self.source_body_ids)} source values, got {values.shape}"
            )
        return GroupedChannelActivity(
            channel_ids=self.channel_ids,
            group_ids=self.motor_group_ids,
            values=values.copy(),
        )


class MotorTransductionBox:
    """Sparse type-F candidate transform whose gains are supplied explicitly."""

    adapter_type = "F"
    box_id = "adapter.motor.transduction"

    def __init__(self, candidates: pd.DataFrame, actuators: pd.DataFrame):
        if candidates.empty or actuators.empty:
            raise ValueError("No generated motor transduction candidates found")
        required = {
            "parameter_id",
            "motor_group_id",
            "source_channel_id",
            "source_body_id",
            "target_actuator_id",
            "target_actuator_name",
        }
        missing = required - set(candidates.columns)
        if missing:
            raise ValueError(f"Missing motor candidate columns: {sorted(missing)}")
        self.candidates = candidates.sort_values(
            ["source_body_id", "target_actuator_id"]
        ).reset_index(drop=True)
        self.actuators = actuators.sort_values("actuator_id").reset_index(drop=True)
        if self.candidates["parameter_id"].duplicated().any():
            raise ValueError("Duplicate motor transduction parameter IDs")
        if self.actuators["actuator_id"].duplicated().any():
            raise ValueError("Duplicate target actuator IDs")
        self.parameter_ids = tuple(self.candidates["parameter_id"].astype(str))
        self.actuator_names = tuple(self.actuators["actuator_name"].astype(str))
        self.source_channel_ids = tuple(
            self.candidates["source_channel_id"].astype(str).drop_duplicates()
        )
        self.resolved_group_ids = tuple(
            self.candidates["motor_group_id"].astype(str).drop_duplicates()
        )
        self._edge_source_channel_ids = tuple(
            self.candidates["source_channel_id"].astype(str)
        )
        self._edge_group_ids = tuple(self.candidates["motor_group_id"].astype(str))
        self._target_actuator_ids = self.candidates["target_actuator_id"].to_numpy(
            dtype=np.int64
        )
        self.covered_actuator_ids = tuple(sorted(set(self._target_actuator_ids.tolist())))
        all_actuator_ids = set(self.actuators["actuator_id"].astype(int))
        self.uncovered_actuator_ids = tuple(sorted(all_actuator_ids - set(self.covered_actuator_ids)))
        if len(self.parameter_ids) != 7536:
            raise ValueError("Expected 7,536 constrained motor-to-actuator parameters")
        if len(self.source_channel_ids) != 722 or len(self.resolved_group_ids) != 368:
            raise ValueError("Unexpected resolved motor candidate coverage")
        if len(self.actuator_names) != 102:
            raise ValueError("Expected 102 FlyBody actuator outputs")
        if len(self.covered_actuator_ids) != 91 or len(self.uncovered_actuator_ids) != 11:
            raise ValueError("Unexpected FlyBody actuator candidate coverage")

    @classmethod
    def from_generated_wiring(
        cls,
        candidate_path: Path = MOTOR_ACTUATOR_CANDIDATE_PATH,
        actuator_path: Path = FLYBODY_ACTUATOR_CHANNEL_PATH,
    ) -> "MotorTransductionBox":
        if not candidate_path.is_file() or not actuator_path.is_file():
            raise FileNotFoundError(
                "Motor transduction candidates are absent; run the wiring builder first"
            )
        return cls(pd.read_parquet(candidate_path), pd.read_csv(actuator_path))

    def step(
        self,
        activity: GroupedChannelActivity,
        parameters: Mapping[str, float] | np.ndarray,
    ) -> ActuatorCommands:
        channel_index = {channel_id: index for index, channel_id in enumerate(activity.channel_ids)}
        missing_channels = set(self.source_channel_ids) - set(channel_index)
        if missing_channels:
            raise ValueError(
                f"{self.box_id}: missing {len(missing_channels)} resolved motor channels"
            )
        group_by_channel = dict(zip(activity.channel_ids, activity.group_ids))
        mismatched_groups = sum(
            group_by_channel[channel_id] != group_id
            for channel_id, group_id in zip(self._edge_source_channel_ids, self._edge_group_ids)
        )
        if mismatched_groups:
            raise ValueError(f"{self.box_id}: {mismatched_groups} candidate group labels mismatch")
        if isinstance(parameters, Mapping):
            missing = set(self.parameter_ids) - set(parameters)
            extra = set(parameters) - set(self.parameter_ids)
            if missing or extra:
                raise ValueError(
                    f"{self.box_id}: parameter mismatch; missing={len(missing)}, extra={len(extra)}"
                )
            weights = np.asarray([parameters[item] for item in self.parameter_ids], dtype=np.float64)
        else:
            weights = np.asarray(parameters, dtype=np.float64)
        if weights.shape != (len(self.parameter_ids),):
            raise ValueError(
                f"{self.box_id}: expected {len(self.parameter_ids)} parameters, got {weights.shape}"
            )
        if not np.isfinite(weights).all():
            raise ValueError("motor transduction parameters must be finite")
        source_indices = np.asarray(
            [channel_index[channel_id] for channel_id in self._edge_source_channel_ids],
            dtype=np.int64,
        )
        commands = np.zeros(len(self.actuator_names), dtype=np.float64)
        np.add.at(
            commands,
            self._target_actuator_ids,
            activity.values[source_indices] * weights,
        )
        return ActuatorCommands(actuator_names=self.actuator_names, values=commands)


class UnclassifiedSensoryRoutingBox:
    """Executable type-C residual router that deliberately leaves modality unknown."""

    adapter_type = "C"
    box_id = "adapter.sensory.unclassified.routing"

    def __init__(self, channels: pd.DataFrame, routes: pd.DataFrame):
        self.channels = channels.loc[channels["routing_box_id"].eq(self.box_id)].copy()
        self.routes = routes.loc[routes["routing_box_id"].eq(self.box_id)].copy()
        if self.channels.empty or self.routes.empty:
            raise ValueError("No generated unclassified sensory wiring found")
        if self.channels["channel_id"].duplicated().any():
            raise ValueError("Duplicate unclassified sensory channel IDs")
        if self.routes["target_body_id"].duplicated().any():
            raise ValueError("Duplicate unclassified sensory target body IDs")
        channel_ids = self.channels["channel_id"].astype(str).tolist()
        self.channel_ids = tuple(channel_ids)
        channel_index = {channel_id: index for index, channel_id in enumerate(channel_ids)}
        unknown = set(self.routes["channel_id"].astype(str)) - set(channel_index)
        if unknown:
            raise ValueError(
                f"Routes refer to unknown unclassified sensory channels: {sorted(unknown)[:3]}"
            )
        self._route_channel_indices = np.asarray(
            [channel_index[str(value)] for value in self.routes["channel_id"]], dtype=np.int64
        )
        self._target_body_ids = self.routes["target_body_id"].to_numpy(dtype=np.int64)

    @classmethod
    def from_generated_wiring(
        cls,
        channel_path: Path = UNCLASSIFIED_CHANNEL_PATH,
        route_path: Path = UNCLASSIFIED_ROUTE_PATH,
    ) -> "UnclassifiedSensoryRoutingBox":
        if not channel_path.is_file() or not route_path.is_file():
            raise FileNotFoundError(
                "Unclassified sensory wiring is absent; run the wiring builder first"
            )
        return cls(pd.read_csv(channel_path), pd.read_parquet(route_path))

    def step(self, channel_values: Mapping[str, float] | np.ndarray) -> SparseActivity:
        if isinstance(channel_values, Mapping):
            missing = set(self.channel_ids) - set(channel_values)
            extra = set(channel_values) - set(self.channel_ids)
            if missing or extra:
                raise ValueError(
                    f"{self.box_id}: channel mismatch; missing={len(missing)}, extra={len(extra)}"
                )
            values = np.asarray([channel_values[item] for item in self.channel_ids], dtype=np.float64)
        else:
            values = np.asarray(channel_values, dtype=np.float64)
        if values.shape != (len(self.channel_ids),):
            raise ValueError(
                f"{self.box_id}: expected {len(self.channel_ids)} channel values, got {values.shape}"
            )
        return SparseActivity(
            body_ids=self._target_body_ids.copy(),
            values=values[self._route_channel_indices],
        )


class CNSInputBuffer:
    """Minimal type-D ingress stub keyed by MaleCNS body ID."""

    adapter_type = "D"

    @staticmethod
    def merge(*inputs: SparseActivity) -> SparseActivity:
        if not inputs:
            return SparseActivity(
                body_ids=np.asarray([], dtype=np.int64),
                values=np.asarray([], dtype=np.float64),
            )
        body_ids = np.concatenate([item.body_ids for item in inputs])
        values = np.concatenate([item.values for item in inputs])
        order = np.argsort(body_ids, kind="stable")
        body_ids = body_ids[order]
        values = values[order]
        unique_ids, first_indices = np.unique(body_ids, return_index=True)
        summed = np.add.reduceat(values, first_indices)
        return SparseActivity(body_ids=unique_ids, values=summed)

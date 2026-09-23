from __future__ import annotations

import json
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
PROPRIO_INPUT_CANDIDATE_PATH = WIRING_ROOT / "proprioception-input-candidates.parquet"
MECHANO_CHANNEL_PATH = WIRING_ROOT / "mechanosensation-channels.csv"
MECHANO_ROUTE_PATH = WIRING_ROOT / "mechanosensation-routes.parquet"
MECHANO_INPUT_CANDIDATE_PATH = WIRING_ROOT / "mechanosensation-input-candidates.parquet"
VISION_CHANNEL_PATH = WIRING_ROOT / "vision-channels.csv"
VISION_ROUTE_PATH = WIRING_ROOT / "vision-routes.parquet"
VISION_COLUMN_PATH = WIRING_ROOT / "vision-optic-columns.csv"
VISION_COLUMN_RECEPTOR_PATH = WIRING_ROOT / "vision-column-photoreceptors.parquet"
VISION_REMAINDER_RECEPTOR_PATH = WIRING_ROOT / "vision-remainder-transduction.parquet"
MOTOR_CHANNEL_PATH = WIRING_ROOT / "motor-channels.csv"
MOTOR_ROUTE_PATH = WIRING_ROOT / "motor-routes.parquet"
MOTOR_ACTUATOR_CANDIDATE_PATH = WIRING_ROOT / "motor-actuator-candidates.parquet"
UNCLASSIFIED_CHANNEL_PATH = WIRING_ROOT / "unclassified-sensory-channels.csv"
UNCLASSIFIED_ROUTE_PATH = WIRING_ROOT / "unclassified-sensory-routes.parquet"
FLYBODY_PROPRIO_CHANNEL_PATH = WIRING_ROOT / "flybody-proprioception-channels.csv"
FLYBODY_TOUCH_CHANNEL_PATH = WIRING_ROOT / "flybody-touch-channels.csv"
FLYBODY_LOCAL_TOUCH_CHANNEL_PATH = WIRING_ROOT / "flybody-local-touch-channels.csv"
FLYBODY_ACTUATOR_CHANNEL_PATH = WIRING_ROOT / "flybody-actuator-channels.csv"
FLYBODY_VISION_CHANNEL_PATH = WIRING_ROOT / "flybody-vision-channels.csv"
CENTRAL_NODE_INDEX_PATH = WIRING_ROOT / "central-node-index.parquet"
CENTRAL_GRAPH_SUMMARY_PATH = WIRING_ROOT / "central-connectome.json"
CENTRAL_WEIGHT_PATH = (
    ROOT
    / "data"
    / "raw"
    / "malecns"
    / "v1.0"
    / "connectome-weights-male-cns-v1.0-minconf-0.5.feather"
)


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


class ProprioceptionTransductionBox:
    """Sparse, uncalibrated joint-state candidates feeding proprioceptor channels."""

    adapter_type = "B"
    box_id = "adapter.proprioception.transduction"

    def __init__(
        self,
        candidates: pd.DataFrame,
        receptor_channels: pd.DataFrame,
        joint_channels: pd.DataFrame,
    ):
        if candidates.empty or receptor_channels.empty or joint_channels.empty:
            raise ValueError("No generated proprioception transduction candidates found")
        required = {
            "parameter_id",
            "source_joint_id",
            "source_joint_name",
            "source_observable",
            "target_channel_id",
        }
        missing = required - set(candidates.columns)
        if missing:
            raise ValueError(f"Missing proprioception candidate columns: {sorted(missing)}")
        self.candidates = candidates.sort_values(
            ["target_channel_id", "source_joint_id", "source_observable"]
        ).reset_index(drop=True)
        self.receptor_channels = receptor_channels.reset_index(drop=True)
        self.joint_channels = joint_channels.sort_values("joint_id").reset_index(drop=True)
        if self.candidates["parameter_id"].duplicated().any():
            raise ValueError("Duplicate proprioception transduction parameter IDs")
        if self.receptor_channels["channel_id"].duplicated().any():
            raise ValueError("Duplicate proprioceptor terminal channel IDs")
        if self.joint_channels["joint_id"].duplicated().any():
            raise ValueError("Duplicate physical joint IDs")
        self.parameter_ids = tuple(self.candidates["parameter_id"].astype(str))
        self.channel_ids = tuple(self.receptor_channels["channel_id"].astype(str))
        self.joint_names = tuple(self.joint_channels["joint_name"].astype(str))
        channel_index = {channel_id: index for index, channel_id in enumerate(self.channel_ids)}
        unknown_targets = set(self.candidates["target_channel_id"].astype(str)) - set(channel_index)
        if unknown_targets:
            raise ValueError(f"Unknown proprioceptor candidate targets: {sorted(unknown_targets)[:3]}")
        self._target_indices = np.asarray(
            [channel_index[str(value)] for value in self.candidates["target_channel_id"]],
            dtype=np.int64,
        )
        self._source_joint_indices = self.candidates["source_joint_id"].to_numpy(dtype=np.int64)
        if self._source_joint_indices.min() < 0 or self._source_joint_indices.max() >= len(
            self.joint_names
        ):
            raise ValueError("Proprioception candidates reference invalid physical joint IDs")
        expected_names = np.asarray(self.joint_names, dtype=object)[self._source_joint_indices]
        if not np.array_equal(
            expected_names, self.candidates["source_joint_name"].astype(str).to_numpy()
        ):
            raise ValueError("Proprioception candidate joint names do not match joint IDs")
        observables = self.candidates["source_observable"].astype(str)
        if not set(observables) <= {"position", "velocity"}:
            raise ValueError("Unsupported proprioception source observable")
        self._velocity_edges = observables.eq("velocity").to_numpy()
        self.resolved_channel_ids = tuple(
            self.candidates["target_channel_id"].astype(str).drop_duplicates()
        )
        self.unresolved_channel_ids = tuple(
            channel_id for channel_id in self.channel_ids if channel_id not in self.resolved_channel_ids
        )
        self._unresolved_indices = np.asarray(
            [channel_index[channel_id] for channel_id in self.unresolved_channel_ids], dtype=np.int64
        )
        if len(self.parameter_ids) != 1439:
            raise ValueError("Expected 1,439 constrained proprioception parameters")
        if (len(self.resolved_channel_ids), len(self.unresolved_channel_ids)) != (171, 91):
            raise ValueError("Unexpected proprioceptor candidate coverage")

    @classmethod
    def from_generated_wiring(
        cls,
        candidate_path: Path = PROPRIO_INPUT_CANDIDATE_PATH,
        receptor_channel_path: Path = PROPRIO_CHANNEL_PATH,
        joint_channel_path: Path = FLYBODY_PROPRIO_CHANNEL_PATH,
    ) -> "ProprioceptionTransductionBox":
        if (
            not candidate_path.is_file()
            or not receptor_channel_path.is_file()
            or not joint_channel_path.is_file()
        ):
            raise FileNotFoundError(
                "Proprioception transduction candidates are absent; run the wiring builder first"
            )
        return cls(
            pd.read_parquet(candidate_path),
            pd.read_csv(receptor_channel_path),
            pd.read_csv(joint_channel_path),
        )

    def step(
        self,
        joint_state: JointState,
        parameters: Mapping[str, float] | np.ndarray,
        unresolved_values: Mapping[str, float] | np.ndarray,
    ) -> ChannelActivity:
        if joint_state.joint_names != self.joint_names:
            raise ValueError(f"{self.box_id}: physical joint order mismatch")
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
        if weights.shape != (len(self.parameter_ids),) or not np.isfinite(weights).all():
            raise ValueError(f"{self.box_id}: invalid candidate parameter vector")
        if isinstance(unresolved_values, Mapping):
            missing = set(self.unresolved_channel_ids) - set(unresolved_values)
            extra = set(unresolved_values) - set(self.unresolved_channel_ids)
            if missing or extra:
                raise ValueError(
                    f"{self.box_id}: unresolved input mismatch; "
                    f"missing={len(missing)}, extra={len(extra)}"
                )
            fallback = np.asarray(
                [unresolved_values[item] for item in self.unresolved_channel_ids], dtype=np.float64
            )
        else:
            fallback = np.asarray(unresolved_values, dtype=np.float64)
        if fallback.shape != (len(self.unresolved_channel_ids),) or not np.isfinite(fallback).all():
            raise ValueError(f"{self.box_id}: invalid unresolved terminal vector")
        source_values = joint_state.positions[self._source_joint_indices].copy()
        source_values[self._velocity_edges] = joint_state.velocities[
            self._source_joint_indices[self._velocity_edges]
        ]
        values = np.zeros(len(self.channel_ids), dtype=np.float64)
        np.add.at(values, self._target_indices, source_values * weights)
        values[self._unresolved_indices] = fallback
        return ChannelActivity(channel_ids=self.channel_ids, values=values)


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
class LocalBodyContactState:
    """Net world-frame contact force on selected FlyBody body segments."""

    segment_names: tuple[str, ...]
    forces: np.ndarray

    def __post_init__(self) -> None:
        if self.forces.shape != (len(self.segment_names), 3):
            raise ValueError(
                f"forces must have shape {(len(self.segment_names), 3)}"
            )
        if not np.isfinite(self.forces).all():
            raise ValueError("local body contact forces must be finite")


class FlyBodyLocalContactSensor:
    """Validate FlyGym net contact forces for the head and central thorax."""

    box_id = "sensor.touch"

    def __init__(self, channels: pd.DataFrame):
        if channels.empty:
            raise ValueError("No generated FlyBody local touch channels found")
        required = {"channel_id", "segment_name"}
        missing = required - set(channels.columns)
        if missing:
            raise ValueError(f"Missing FlyBody local touch columns: {sorted(missing)}")
        self.channels = channels.sort_values("segment_name").reset_index(drop=True)
        if self.channels["channel_id"].duplicated().any():
            raise ValueError("Duplicate FlyBody local touch channel IDs")
        if self.channels["segment_name"].duplicated().any():
            raise ValueError("Duplicate FlyBody local touch body segments")
        self.channel_ids = tuple(self.channels["channel_id"].astype(str))
        self.segment_names = tuple(self.channels["segment_name"].astype(str))
        if len(self.segment_names) != 2 or set(self.segment_names) != {"c_head", "c_thorax"}:
            raise ValueError("Expected exactly the c_head and c_thorax contact segments")

    @classmethod
    def from_generated_wiring(
        cls, channel_path: Path = FLYBODY_LOCAL_TOUCH_CHANNEL_PATH
    ) -> "FlyBodyLocalContactSensor":
        if not channel_path.is_file():
            raise FileNotFoundError(
                "FlyBody local touch wiring is absent; run the wiring builder first"
            )
        return cls(pd.read_csv(channel_path))

    def step(self, forces: np.ndarray) -> LocalBodyContactState:
        values = np.asarray(forces, dtype=np.float64)
        return LocalBodyContactState(
            segment_names=self.segment_names,
            forces=values.copy(),
        )


class MechanosensationTransductionBox:
    """Sparse, uncalibrated local physical candidates feeding mechanoreceptors."""

    adapter_type = "B"
    box_id = "adapter.touch.transduction"

    def __init__(
        self,
        candidates: pd.DataFrame,
        receptor_channels: pd.DataFrame,
        contact_channels: pd.DataFrame,
        local_contact_channels: pd.DataFrame,
        joint_channels: pd.DataFrame,
    ):
        if (
            candidates.empty
            or receptor_channels.empty
            or contact_channels.empty
            or local_contact_channels.empty
            or joint_channels.empty
        ):
            raise ValueError("No generated mechanosensation transduction candidates found")
        required = {
            "parameter_id",
            "source_kind",
            "source_leg",
            "source_joint_id",
            "source_joint_name",
            "source_observable",
            "target_channel_id",
        }
        missing = required - set(candidates.columns)
        if missing:
            raise ValueError(f"Missing mechanosensation candidate columns: {sorted(missing)}")
        self.candidates = candidates.sort_values(
            ["target_channel_id", "source_kind", "source_channel_id", "source_observable"]
        ).reset_index(drop=True)
        self.receptor_channels = receptor_channels.reset_index(drop=True)
        self.contact_channels = contact_channels.sort_values("sensor_address").reset_index(drop=True)
        self.local_contact_channels = local_contact_channels.sort_values(
            "segment_name"
        ).reset_index(drop=True)
        self.joint_channels = joint_channels.sort_values("joint_id").reset_index(drop=True)
        if self.candidates["parameter_id"].duplicated().any():
            raise ValueError("Duplicate mechanosensation transduction parameter IDs")
        if self.receptor_channels["channel_id"].duplicated().any():
            raise ValueError("Duplicate mechanoreceptor terminal channel IDs")
        if self.contact_channels["leg"].duplicated().any():
            raise ValueError("Duplicate physical leg-contact channels")
        if self.joint_channels["joint_id"].duplicated().any():
            raise ValueError("Duplicate physical joint IDs")
        self.parameter_ids = tuple(self.candidates["parameter_id"].astype(str))
        self.channel_ids = tuple(self.receptor_channels["channel_id"].astype(str))
        self.leg_names = tuple(self.contact_channels["leg"].astype(str))
        self.local_segment_names = tuple(
            self.local_contact_channels["segment_name"].astype(str)
        )
        self.joint_names = tuple(self.joint_channels["joint_name"].astype(str))
        channel_index = {channel_id: index for index, channel_id in enumerate(self.channel_ids)}
        leg_index = {leg: index for index, leg in enumerate(self.leg_names)}
        local_segment_index = {
            name: index for index, name in enumerate(self.local_segment_names)
        }
        unknown_targets = set(self.candidates["target_channel_id"].astype(str)) - set(channel_index)
        source_kinds = self.candidates["source_kind"].astype(str)
        if not set(source_kinds) <= {"contact_load", "body_contact", "joint_state"}:
            raise ValueError("Unsupported mechanosensation candidate source kind")
        self._contact_edges = source_kinds.eq("contact_load").to_numpy()
        self._body_contact_edges = source_kinds.eq("body_contact").to_numpy()
        self._joint_edges = source_kinds.eq("joint_state").to_numpy()
        contact_rows = self.candidates.loc[self._contact_edges]
        body_contact_rows = self.candidates.loc[self._body_contact_edges]
        joint_rows = self.candidates.loc[self._joint_edges]
        unknown_legs = set(contact_rows["source_leg"].astype(str)) - set(leg_index)
        unknown_segments = set(body_contact_rows["source_body_group"].astype(str)) - set(
            local_segment_index
        )
        if unknown_targets or unknown_legs or unknown_segments:
            raise ValueError(
                "Mechanosensation candidates reference unknown channels: "
                f"targets={len(unknown_targets)}, legs={len(unknown_legs)}, "
                f"body_segments={len(unknown_segments)}"
            )
        self._target_indices = np.asarray(
            [channel_index[str(value)] for value in self.candidates["target_channel_id"]],
            dtype=np.int64,
        )
        self._contact_leg_indices = np.asarray(
            [leg_index[str(value)] for value in contact_rows["source_leg"]],
            dtype=np.int64,
        )
        contact_observable_index = {
            "contact_found": 0,
            "force_x": 1,
            "force_y": 2,
            "force_z": 3,
            "torque_x": 4,
            "torque_y": 5,
            "torque_z": 6,
        }
        unknown_contact_observables = set(contact_rows["source_observable"].astype(str)) - set(
            contact_observable_index
        )
        if unknown_contact_observables:
            raise ValueError(
                f"Unsupported contact observables: {sorted(unknown_contact_observables)}"
            )
        self._contact_observable_indices = np.asarray(
            [
                contact_observable_index[str(value)]
                for value in contact_rows["source_observable"]
            ],
            dtype=np.int64,
        )
        self._body_contact_segment_indices = np.asarray(
            [
                local_segment_index[str(value)]
                for value in body_contact_rows["source_body_group"]
            ],
            dtype=np.int64,
        )
        body_contact_observable_index = {"force_x": 0, "force_y": 1, "force_z": 2}
        unknown_body_contact_observables = set(
            body_contact_rows["source_observable"].astype(str)
        ) - set(body_contact_observable_index)
        if unknown_body_contact_observables:
            raise ValueError(
                "Unsupported local body contact observables: "
                f"{sorted(unknown_body_contact_observables)}"
            )
        self._body_contact_observable_indices = np.asarray(
            [
                body_contact_observable_index[str(value)]
                for value in body_contact_rows["source_observable"]
            ],
            dtype=np.int64,
        )
        self._joint_indices = joint_rows["source_joint_id"].to_numpy(dtype=np.int64)
        if self._joint_indices.size and (
            self._joint_indices.min() < 0 or self._joint_indices.max() >= len(self.joint_names)
        ):
            raise ValueError("Mechanosensation candidates reference invalid physical joint IDs")
        expected_joint_names = np.asarray(self.joint_names, dtype=object)[self._joint_indices]
        if not np.array_equal(
            expected_joint_names, joint_rows["source_joint_name"].astype(str).to_numpy()
        ):
            raise ValueError("Mechanosensation candidate joint names do not match joint IDs")
        joint_observables = joint_rows["source_observable"].astype(str)
        if not set(joint_observables) <= {"position", "velocity"}:
            raise ValueError("Unsupported mechanosensation joint observable")
        self._joint_velocity_edges = joint_observables.eq("velocity").to_numpy()
        self.resolved_channel_ids = tuple(
            self.candidates["target_channel_id"].astype(str).drop_duplicates()
        )
        self.unresolved_channel_ids = tuple(
            channel_id for channel_id in self.channel_ids if channel_id not in self.resolved_channel_ids
        )
        self._unresolved_indices = np.asarray(
            [channel_index[channel_id] for channel_id in self.unresolved_channel_ids], dtype=np.int64
        )
        if len(self.parameter_ids) != 2108:
            raise ValueError("Expected 2,108 constrained mechanosensation parameters")
        if (len(self.resolved_channel_ids), len(self.unresolved_channel_ids)) != (323, 0):
            raise ValueError("Unexpected mechanoreceptor candidate coverage")

    @classmethod
    def from_generated_wiring(
        cls,
        candidate_path: Path = MECHANO_INPUT_CANDIDATE_PATH,
        receptor_channel_path: Path = MECHANO_CHANNEL_PATH,
        contact_channel_path: Path = FLYBODY_TOUCH_CHANNEL_PATH,
        local_contact_channel_path: Path = FLYBODY_LOCAL_TOUCH_CHANNEL_PATH,
        joint_channel_path: Path = FLYBODY_PROPRIO_CHANNEL_PATH,
    ) -> "MechanosensationTransductionBox":
        if (
            not candidate_path.is_file()
            or not receptor_channel_path.is_file()
            or not contact_channel_path.is_file()
            or not local_contact_channel_path.is_file()
            or not joint_channel_path.is_file()
        ):
            raise FileNotFoundError(
                "Mechanosensation transduction candidates are absent; run the wiring builder first"
            )
        return cls(
            pd.read_parquet(candidate_path),
            pd.read_csv(receptor_channel_path),
            pd.read_csv(contact_channel_path),
            pd.read_csv(local_contact_channel_path),
            pd.read_csv(joint_channel_path),
        )

    def step(
        self,
        contact_state: GroundContactState,
        local_contact_state: LocalBodyContactState,
        joint_state: JointState,
        parameters: Mapping[str, float] | np.ndarray,
        unresolved_values: Mapping[str, float] | np.ndarray,
    ) -> ChannelActivity:
        if contact_state.leg_names != self.leg_names:
            raise ValueError(f"{self.box_id}: physical leg order mismatch")
        if local_contact_state.segment_names != self.local_segment_names:
            raise ValueError(f"{self.box_id}: local body segment order mismatch")
        if joint_state.joint_names != self.joint_names:
            raise ValueError(f"{self.box_id}: physical joint order mismatch")
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
        if weights.shape != (len(self.parameter_ids),) or not np.isfinite(weights).all():
            raise ValueError(f"{self.box_id}: invalid candidate parameter vector")
        if isinstance(unresolved_values, Mapping):
            missing = set(self.unresolved_channel_ids) - set(unresolved_values)
            extra = set(unresolved_values) - set(self.unresolved_channel_ids)
            if missing or extra:
                raise ValueError(
                    f"{self.box_id}: unresolved input mismatch; "
                    f"missing={len(missing)}, extra={len(extra)}"
                )
            fallback = np.asarray(
                [unresolved_values[item] for item in self.unresolved_channel_ids], dtype=np.float64
            )
        else:
            fallback = np.asarray(unresolved_values, dtype=np.float64)
        if fallback.shape != (len(self.unresolved_channel_ids),) or not np.isfinite(fallback).all():
            raise ValueError(f"{self.box_id}: invalid unresolved terminal vector")
        contact_values = np.column_stack(
            (contact_state.contact_found, contact_state.forces, contact_state.torques)
        )
        source_values = np.empty(len(self.parameter_ids), dtype=np.float64)
        source_values[self._contact_edges] = contact_values[
            self._contact_leg_indices, self._contact_observable_indices
        ]
        source_values[self._body_contact_edges] = local_contact_state.forces[
            self._body_contact_segment_indices, self._body_contact_observable_indices
        ]
        joint_values = joint_state.positions[self._joint_indices].copy()
        joint_values[self._joint_velocity_edges] = joint_state.velocities[
            self._joint_indices[self._joint_velocity_edges]
        ]
        source_values[self._joint_edges] = joint_values
        values = np.zeros(len(self.channel_ids), dtype=np.float64)
        np.add.at(values, self._target_indices, source_values * weights)
        values[self._unresolved_indices] = fallback
        return ChannelActivity(channel_ids=self.channel_ids, values=values)


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


@dataclass(frozen=True)
class PhysicalStep:
    """One observed FlyBody physics step after addressed actuator commands."""

    joint_state: JointState
    actuator_names: tuple[str, ...]
    applied_commands: np.ndarray
    actuator_forces: np.ndarray
    simulation_time: float

    def __post_init__(self) -> None:
        expected = (len(self.actuator_names),)
        if self.applied_commands.shape != expected or self.actuator_forces.shape != expected:
            raise ValueError("physical command and force vectors must match actuator_names")
        if not np.isfinite(self.applied_commands).all() or not np.isfinite(
            self.actuator_forces
        ).all():
            raise ValueError("physical command and force vectors must be finite")
        if not np.isfinite(self.simulation_time) or self.simulation_time < 0:
            raise ValueError("simulation_time must be finite and non-negative")


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


class FlyBodyPhysicsLoop:
    """Apply addressed commands to FlyGym and expose the resulting joint state.

    This class fixes only API and address plumbing.  It deliberately accepts the
    already-transduced command vector as-is; parameter choice remains upstream.
    """

    box_id = "body.flybody"

    def __init__(
        self,
        simulation: object,
        fly: object,
        actuator_interface: FlyBodyActuatorInterface,
        proprioception_sensor: FlyBodyProprioceptionSensor,
    ):
        from flygym.compose import ActuatorType

        self.simulation = simulation
        self.fly = fly
        self.actuator_interface = actuator_interface
        self.proprioception_sensor = proprioception_sensor
        self.actuator_type = ActuatorType.MOTOR
        self.joint_names = tuple(item.name for item in fly.get_jointdofs_order())
        actuated_joint_names = tuple(
            item.name for item in fly.get_actuated_jointdofs_order(self.actuator_type)
        )
        self.actuator_names = tuple(f"{name}-motor" for name in actuated_joint_names)
        if self.actuator_names != actuator_interface.actuator_names:
            raise ValueError("compiled FlyBody actuator order differs from the wiring manifest")
        if self.joint_names != proprioception_sensor.joint_names:
            raise ValueError("compiled FlyBody joint order differs from the wiring manifest")

    @classmethod
    def from_generated_wiring(cls) -> "FlyBodyPhysicsLoop":
        from flygym.compose import ActuatorType
        from flygym.compose.fly.flybody import FlyBody
        from flygym.compose.world import FlatGroundWorld
        from flygym.flybody.anatomy_flybody import (
            FlyBodyActuatedDOFPreset,
            FlyBodyAxisOrder,
            FlyBodyContactBodiesPreset,
            FlyBodyJointPreset,
            FlyBodySkeleton,
        )
        from flygym.simulation import Simulation
        from flygym.utils.math import Rotation3D

        fly = FlyBody()
        skeleton = FlyBodySkeleton(
            axis_order=FlyBodyAxisOrder.YAW_PITCH_ROLL,
            joint_preset=FlyBodyJointPreset.ALL_BIOLOGICAL,
        )
        fly.add_joints(skeleton)
        actuated = skeleton.get_actuated_dofs_from_preset(FlyBodyActuatedDOFPreset.ALL)
        fly.add_actuators(
            actuated,
            ActuatorType.MOTOR,
            forcelimited=True,
            forcerange=(-0.01, 0.01),
        )
        world = FlatGroundWorld()
        world.add_fly(
            fly,
            np.asarray([0.0, 0.0, 1.0]),
            Rotation3D("quat", (1, 0, 0, 0)),
            bodysegs_with_ground_contact=FlyBodyContactBodiesPreset.LEGS_THORAX_ABDOMEN_HEAD,
        )
        return cls(
            Simulation(world),
            fly,
            FlyBodyActuatorInterface.from_generated_wiring(),
            FlyBodyProprioceptionSensor.from_generated_wiring(),
        )

    def reset(self) -> None:
        self.simulation.reset()

    def read_joint_state(self) -> JointState:
        positions = np.asarray(
            self.simulation.get_joint_angles("flybody"), dtype=np.float64
        )
        velocities = np.asarray(
            self.simulation.get_joint_velocities("flybody"), dtype=np.float64
        )
        return self.proprioception_sensor.step(
            dict(zip(self.joint_names, positions)),
            dict(zip(self.joint_names, velocities)),
        )

    def step(self, commands: ActuatorCommands, substeps: int = 1) -> PhysicalStep:
        if commands.actuator_names != self.actuator_names:
            raise ValueError("addressed command names differ from compiled FlyBody actuators")
        if substeps < 1:
            raise ValueError("substeps must be at least one")
        self.simulation.set_actuator_inputs(
            "flybody", self.actuator_type, commands.values
        )
        for _ in range(substeps):
            self.simulation.step()
        return PhysicalStep(
            joint_state=self.read_joint_state(),
            actuator_names=self.actuator_names,
            applied_commands=commands.values.copy(),
            actuator_forces=np.asarray(
                self.simulation.get_actuator_forces("flybody", self.actuator_type),
                dtype=np.float64,
            ).copy(),
            simulation_time=float(self.simulation.mj_data.time),
        )

    def close(self) -> None:
        self.simulation.close()

    def __enter__(self) -> "FlyBodyPhysicsLoop":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()


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


class VisionTransductionBox:
    """Partially column-addressed, uncalibrated visual transduction adapter."""

    adapter_type = "B"
    box_id = "adapter.vision.transduction"

    def __init__(
        self,
        assignments: pd.DataFrame,
        columns: pd.DataFrame,
        receptor_channels: pd.DataFrame,
        remainder_channels: pd.DataFrame,
        physical_channels: pd.DataFrame,
    ):
        if (
            assignments.empty
            or columns.empty
            or receptor_channels.empty
            or remainder_channels.empty
            or physical_channels.empty
        ):
            raise ValueError("No generated visual column assignments found")
        self.assignments = assignments.sort_values(
            ["side", "column_id", "receptor_class"]
        ).reset_index(drop=True)
        self.columns = columns.sort_values(["side", "column_u", "column_v"]).reset_index(
            drop=True
        )
        self.remainder_channels = remainder_channels.sort_values(
            ["terminal_disposition", "side", "target_type", "target_channel_id"]
        ).reset_index(drop=True)
        self.receptor_channels = receptor_channels.reset_index(drop=True)
        self.physical_channels = physical_channels.sort_values(
            ["eye_index", "ommatidium_id"]
        ).reset_index(drop=True)
        if self.assignments["parameter_id"].duplicated().any():
            raise ValueError("Duplicate visual transduction parameter IDs")
        if self.assignments["target_channel_id"].duplicated().any():
            raise ValueError("Duplicate column-assigned visual targets")
        if self.columns["column_id"].duplicated().any():
            raise ValueError("Duplicate optic-column IDs")
        if self.remainder_channels["target_channel_id"].duplicated().any():
            raise ValueError("Duplicate remainder visual targets")
        self.published_parameter_ids = tuple(self.assignments["parameter_id"].astype(str))
        self.remainder_parameter_ids = tuple(
            self.remainder_channels["parameter_id"].astype(str)
        )
        self.parameter_ids = self.published_parameter_ids + self.remainder_parameter_ids
        self.column_ids = tuple(self.columns["column_id"].astype(str))
        self.channel_ids = tuple(self.receptor_channels["channel_id"].astype(str))
        self.physical_channel_ids = tuple(self.physical_channels["channel_id"].astype(str))
        target_index = {value: index for index, value in enumerate(self.channel_ids)}
        physical_index = {
            value: index for index, value in enumerate(self.physical_channel_ids)
        }
        unknown_targets = set(self.assignments["target_channel_id"].astype(str)) - set(
            target_index
        )
        if unknown_targets:
            raise ValueError("Visual column assignments reference unknown terminal channels")
        self._target_indices = np.asarray(
            [target_index[str(value)] for value in self.assignments["target_channel_id"]],
            dtype=np.int64,
        )
        unknown_remainder_targets = set(
            self.remainder_channels["target_channel_id"].astype(str)
        ) - set(target_index)
        if unknown_remainder_targets:
            raise ValueError("Visual remainder references unknown terminal channels")
        self.published_channel_ids = tuple(
            self.assignments["target_channel_id"].astype(str)
        )
        self._remainder_target_indices = np.asarray(
            [
                target_index[str(value)]
                for value in self.remainder_channels["target_channel_id"]
            ],
            dtype=np.int64,
        )
        registration_mask = self.remainder_channels["source_policy"].eq(
            "same_eye_discrete_ommatidium"
        ).to_numpy()
        proxy_mask = self.remainder_channels["source_policy"].eq(
            "same_eye_mean_retinal_proxy"
        ).to_numpy()
        if not np.all(registration_mask | proxy_mask):
            raise ValueError("Unknown visual remainder source policy")
        self._registration_remainder_indices = np.flatnonzero(registration_mask)
        self._proxy_remainder_indices = np.flatnonzero(proxy_mask)
        self.registration_channel_ids = tuple(
            self.remainder_channels.loc[registration_mask, "target_channel_id"].astype(str)
        )
        self.proxy_channel_ids = tuple(
            self.remainder_channels.loc[proxy_mask, "target_channel_id"].astype(str)
        )
        covered = (
            set(self.published_channel_ids)
            | set(self.registration_channel_ids)
            | set(self.proxy_channel_ids)
        )
        if covered != set(self.channel_ids):
            raise ValueError("Visual transduction does not partition every terminal channel")
        self.resolved_channel_ids = self.channel_ids
        self.unresolved_channel_ids: tuple[str, ...] = ()
        self._column_side = dict(
            zip(self.columns["column_id"].astype(str), self.columns["side"].astype(str))
        )
        self._column_sample_type = dict(
            zip(
                self.columns["column_id"].astype(str),
                self.columns["expected_flybody_sample_type"].astype(str),
            )
        )
        self._physical_index = physical_index
        self._physical_side = {
            str(row.channel_id): "L" if str(row.eye) == "left" else "R"
            for row in self.physical_channels.itertuples(index=False)
        }
        self._physical_sample_type = dict(
            zip(
                self.physical_channels["channel_id"].astype(str),
                self.physical_channels["ommatidium_type"].astype(str),
            )
        )
        self._assignment_column_ids = tuple(self.assignments["column_id"].astype(str))
        self._remainder_side = dict(
            zip(
                self.remainder_channels["target_channel_id"].astype(str),
                self.remainder_channels["side"].astype(str),
            )
        )
        self._physical_indices_by_side = {
            side: np.asarray(
                [
                    index
                    for index, channel_id in enumerate(self.physical_channel_ids)
                    if self._physical_side[channel_id] == side
                ],
                dtype=np.int64,
            )
            for side in ("L", "R")
        }
        if (len(self.column_ids), len(self.published_parameter_ids)) != (1332, 2628):
            raise ValueError("Unexpected published R7/R8 column coverage")
        if (len(self.registration_channel_ids), len(self.proxy_channel_ids)) != (3463, 7):
            raise ValueError("Unexpected visual terminal coverage")
        if len(self.parameter_ids) != 6098:
            raise ValueError("Unexpected visual parameter coverage")

    @classmethod
    def from_generated_wiring(
        cls,
        assignment_path: Path = VISION_COLUMN_RECEPTOR_PATH,
        column_path: Path = VISION_COLUMN_PATH,
        receptor_channel_path: Path = VISION_CHANNEL_PATH,
        remainder_channel_path: Path = VISION_REMAINDER_RECEPTOR_PATH,
        physical_channel_path: Path = FLYBODY_VISION_CHANNEL_PATH,
    ) -> "VisionTransductionBox":
        if not all(
            path.is_file()
            for path in (
                assignment_path,
                column_path,
                receptor_channel_path,
                remainder_channel_path,
                physical_channel_path,
            )
        ):
            raise FileNotFoundError(
                "Visual column wiring is absent; run the wiring builder first"
            )
        return cls(
            pd.read_parquet(assignment_path),
            pd.read_csv(column_path),
            pd.read_csv(receptor_channel_path),
            pd.read_parquet(remainder_channel_path),
            pd.read_csv(physical_channel_path),
        )

    def step(
        self,
        retinal_samples: ChannelActivity,
        registration: Mapping[str, str],
        remainder_registration: Mapping[str, str],
        parameters: Mapping[str, float] | np.ndarray,
    ) -> ChannelActivity:
        if retinal_samples.channel_ids != self.physical_channel_ids:
            raise ValueError(f"{self.box_id}: physical retinal channel order mismatch")
        missing = set(self.column_ids) - set(registration)
        extra = set(registration) - set(self.column_ids)
        if missing or extra:
            raise ValueError(
                f"{self.box_id}: registration mismatch; "
                f"missing={len(missing)}, extra={len(extra)}"
            )
        source_ids = tuple(str(registration[column_id]) for column_id in self.column_ids)
        if len(set(source_ids)) != len(source_ids):
            raise ValueError(f"{self.box_id}: optic-column registration must be injective")
        for column_id, source_id in zip(self.column_ids, source_ids):
            if source_id not in self._physical_index:
                raise ValueError(f"{self.box_id}: unknown physical retinal channel {source_id}")
            expected_side = self._column_side[column_id]
            expected_type = self._column_sample_type[column_id]
            if self._physical_side[source_id] != expected_side:
                raise ValueError(f"{self.box_id}: cross-eye retinal registration")
            if (
                expected_type != "any"
                and self._physical_sample_type[source_id] != expected_type
            ):
                raise ValueError(f"{self.box_id}: incompatible ommatidium palette")
        registered_source_index = {
            column_id: self._physical_index[source_id]
            for column_id, source_id in zip(self.column_ids, source_ids)
        }
        assignment_source_indices = np.asarray(
            [registered_source_index[column_id] for column_id in self._assignment_column_ids],
            dtype=np.int64,
        )
        missing = set(self.registration_channel_ids) - set(remainder_registration)
        extra = set(remainder_registration) - set(self.registration_channel_ids)
        if missing or extra:
            raise ValueError(
                f"{self.box_id}: remainder registration mismatch; "
                f"missing={len(missing)}, extra={len(extra)}"
            )
        remainder_source_indices: list[int] = []
        for channel_id in self.registration_channel_ids:
            source_id = str(remainder_registration[channel_id])
            if source_id not in self._physical_index:
                raise ValueError(f"{self.box_id}: unknown remainder retinal channel {source_id}")
            if self._physical_side[source_id] != self._remainder_side[channel_id]:
                raise ValueError(f"{self.box_id}: cross-eye remainder registration")
            remainder_source_indices.append(self._physical_index[source_id])
        remainder_source_indices_array = np.asarray(
            remainder_source_indices, dtype=np.int64
        )
        if isinstance(parameters, Mapping):
            missing = set(self.parameter_ids) - set(parameters)
            extra = set(parameters) - set(self.parameter_ids)
            if missing or extra:
                raise ValueError(
                    f"{self.box_id}: parameter mismatch; "
                    f"missing={len(missing)}, extra={len(extra)}"
                )
            weights = np.asarray(
                [parameters[value] for value in self.parameter_ids], dtype=np.float64
            )
        else:
            weights = np.asarray(parameters, dtype=np.float64)
        if weights.shape != (len(self.parameter_ids),) or not np.isfinite(weights).all():
            raise ValueError(f"{self.box_id}: invalid phototransduction parameter vector")
        published_weight_count = len(self.published_parameter_ids)
        published_weights = weights[:published_weight_count]
        remainder_weights = weights[published_weight_count:]
        values = np.zeros(len(self.channel_ids), dtype=np.float64)
        values[self._target_indices] = (
            retinal_samples.values[assignment_source_indices] * published_weights
        )
        registered_target_indices = self._remainder_target_indices[
            self._registration_remainder_indices
        ]
        values[registered_target_indices] = (
            retinal_samples.values[remainder_source_indices_array]
            * remainder_weights[self._registration_remainder_indices]
        )
        for remainder_index in self._proxy_remainder_indices:
            row = self.remainder_channels.iloc[int(remainder_index)]
            source_indices = self._physical_indices_by_side[str(row["side"])]
            values[self._remainder_target_indices[remainder_index]] = (
                float(np.mean(retinal_samples.values[source_indices]))
                * remainder_weights[remainder_index]
            )
        return ChannelActivity(channel_ids=self.channel_ids, values=values)


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
    """Sparse type-F candidate transform whose gains are supplied explicitly.

    Every one of the 815 motor channels is consumed.  Channels whose physical
    effector is absent from FlyBody are tracked as explicit no-output terminals.
    """

    adapter_type = "F"
    box_id = "adapter.motor.transduction"

    def __init__(
        self, candidates: pd.DataFrame, actuators: pd.DataFrame, motor_channels: pd.DataFrame
    ):
        if candidates.empty or actuators.empty or motor_channels.empty:
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
        all_motor_channel_ids = tuple(motor_channels["channel_id"].astype(str))
        if len(all_motor_channel_ids) != 815 or len(set(all_motor_channel_ids)) != 815:
            raise ValueError("Expected 815 unique generated motor channels")
        self.all_motor_channel_ids = all_motor_channel_ids
        self.unsupported_terminal_channel_ids = tuple(
            sorted(set(all_motor_channel_ids) - set(self.source_channel_ids))
        )
        if len(self.parameter_ids) != 7849:
            raise ValueError("Expected 7,849 constrained motor-to-actuator parameters")
        if len(self.source_channel_ids) != 804 or len(self.resolved_group_ids) != 431:
            raise ValueError("Unexpected resolved motor candidate coverage")
        if len(self.actuator_names) != 102:
            raise ValueError("Expected 102 FlyBody actuator outputs")
        if len(self.covered_actuator_ids) != 102 or self.uncovered_actuator_ids:
            raise ValueError("Unexpected FlyBody actuator candidate coverage")
        if len(self.unsupported_terminal_channel_ids) != 11:
            raise ValueError("Expected 11 explicit unsupported motor terminals")

    @classmethod
    def from_generated_wiring(
        cls,
        candidate_path: Path = MOTOR_ACTUATOR_CANDIDATE_PATH,
        actuator_path: Path = FLYBODY_ACTUATOR_CHANNEL_PATH,
        motor_channel_path: Path = MOTOR_CHANNEL_PATH,
    ) -> "MotorTransductionBox":
        if (
            not candidate_path.is_file()
            or not actuator_path.is_file()
            or not motor_channel_path.is_file()
        ):
            raise FileNotFoundError(
                "Motor transduction candidates are absent; run the wiring builder first"
            )
        return cls(
            pd.read_parquet(candidate_path),
            pd.read_csv(actuator_path),
            pd.read_csv(motor_channel_path),
        )

    def step(
        self,
        activity: GroupedChannelActivity,
        parameters: Mapping[str, float] | np.ndarray,
    ) -> ActuatorCommands:
        channel_index = {channel_id: index for index, channel_id in enumerate(activity.channel_ids)}
        missing_all = set(self.all_motor_channel_ids) - set(channel_index)
        extra_all = set(channel_index) - set(self.all_motor_channel_ids)
        if missing_all or extra_all:
            raise ValueError(
                f"{self.box_id}: full motor input mismatch; "
                f"missing={len(missing_all)}, extra={len(extra_all)}"
            )
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


class CentralConnectomeBox:
    """Stream the annotated-neuron subgraph as a sparse structural operator.

    This computes raw one-hop synaptic drive from published integer connection
    weights.  It deliberately does not implement time constants, thresholds,
    signs, nonlinearities or any other calibrated neuronal dynamics.
    """

    adapter_type = "D"
    box_id = "cns.malecns"

    def __init__(
        self,
        nodes: pd.DataFrame,
        weight_path: Path,
        expected_induced_edges: int | None = None,
    ):
        required = {"node_index", "body_id"}
        missing = required - set(nodes.columns)
        if missing:
            raise ValueError(f"Missing central node-index columns: {sorted(missing)}")
        self.nodes = nodes.sort_values("node_index").reset_index(drop=True)
        expected_indices = np.arange(len(self.nodes), dtype=np.int64)
        if not np.array_equal(self.nodes["node_index"].to_numpy(dtype=np.int64), expected_indices):
            raise ValueError("Central node indices must be contiguous and zero-based")
        self.body_ids = self.nodes["body_id"].to_numpy(dtype=np.int64)
        if len(np.unique(self.body_ids)) != len(self.body_ids):
            raise ValueError("Central node body IDs must be unique")
        if not np.all(self.body_ids[1:] > self.body_ids[:-1]):
            raise ValueError("Central node body IDs must be strictly increasing")
        self.weight_path = Path(weight_path)
        if not self.weight_path.is_file():
            raise FileNotFoundError(f"Central weight table is absent: {self.weight_path}")
        self.expected_induced_edges = expected_induced_edges

    @classmethod
    def from_generated_wiring(
        cls,
        node_path: Path = CENTRAL_NODE_INDEX_PATH,
        weight_path: Path = CENTRAL_WEIGHT_PATH,
        summary_path: Path = CENTRAL_GRAPH_SUMMARY_PATH,
    ) -> "CentralConnectomeBox":
        if not node_path.is_file() or not summary_path.is_file():
            raise FileNotFoundError("Central graph index is absent; run the wiring builder first")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        return cls(
            pd.read_parquet(node_path),
            weight_path,
            expected_induced_edges=int(summary["induced_edge_rows"]),
        )

    def _locate(self, body_ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        indices = np.searchsorted(self.body_ids, body_ids)
        clipped = np.minimum(indices, len(self.body_ids) - 1)
        valid = (indices < len(self.body_ids)) & (self.body_ids[clipped] == body_ids)
        return indices, valid

    def project_many(self, activities: tuple[SparseActivity, ...]) -> tuple[SparseActivity, ...]:
        """Project multiple inputs in one edge-table pass for deterministic replay."""
        if not activities:
            raise ValueError("At least one CNS input activity is required")
        dense_inputs = np.zeros((len(activities), len(self.body_ids)), dtype=np.float64)
        for row, activity in enumerate(activities):
            indices, valid = self._locate(activity.body_ids.astype(np.int64, copy=False))
            if not valid.all():
                unknown = activity.body_ids[~valid]
                raise ValueError(f"CNS input contains unknown body IDs: {unknown[:3].tolist()}")
            dense_inputs[row, indices] = activity.values

        outputs = np.zeros_like(dense_inputs)
        induced_edges = 0
        import pyarrow as pa

        with pa.memory_map(str(self.weight_path), "r") as mapped:
            reader = pa.ipc.open_file(mapped)
            for batch_index in range(reader.num_record_batches):
                batch = reader.get_batch(batch_index)
                pre = batch.column(0).to_numpy()
                post = batch.column(1).to_numpy()
                weights = batch.column(2).to_numpy().astype(np.float64, copy=False)
                pre_indices, pre_valid = self._locate(pre)
                post_indices, post_valid = self._locate(post)
                valid = pre_valid & post_valid
                if not valid.any():
                    continue
                source = pre_indices[valid]
                target = post_indices[valid]
                selected_weights = weights[valid]
                induced_edges += len(source)
                for row in range(len(activities)):
                    np.add.at(
                        outputs[row],
                        target,
                        dense_inputs[row, source] * selected_weights,
                    )
        if (
            self.expected_induced_edges is not None
            and induced_edges != self.expected_induced_edges
        ):
            raise RuntimeError(
                f"Central edge coverage mismatch: {induced_edges} != "
                f"{self.expected_induced_edges}"
            )
        return tuple(
            SparseActivity(body_ids=self.body_ids.copy(), values=values)
            for values in outputs
        )

    def project(self, activity: SparseActivity) -> SparseActivity:
        return self.project_many((activity,))[0]

    def select_values(self, activity: SparseActivity, body_ids: tuple[int, ...]) -> np.ndarray:
        requested = np.asarray(body_ids, dtype=np.int64)
        if np.array_equal(activity.body_ids, self.body_ids):
            indices, valid = self._locate(requested)
            if not valid.all():
                raise ValueError("Requested CNS output body ID is absent")
            return activity.values[indices]
        activity_order = np.argsort(activity.body_ids)
        sorted_ids = activity.body_ids[activity_order]
        indices = np.searchsorted(sorted_ids, requested)
        clipped = np.minimum(indices, len(sorted_ids) - 1)
        valid = (indices < len(sorted_ids)) & (sorted_ids[clipped] == requested)
        if not valid.all():
            raise ValueError("Requested CNS output body ID is absent from activity")
        return activity.values[activity_order[indices]]

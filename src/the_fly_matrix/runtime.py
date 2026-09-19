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

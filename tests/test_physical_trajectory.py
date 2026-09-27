from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from the_fly_matrix.physical_trajectory import (
    PhysicalTrajectory,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    TrajectoryError,
)


class PhysicalTrajectoryTests(unittest.TestCase):
    def _trajectory(self) -> PhysicalTrajectory:
        return PhysicalTrajectory(
            timestamps_s=np.asarray([0.005, 0.010]),
            qpos=np.arange(8, dtype=float).reshape(2, 4),
            qvel=np.arange(6, dtype=float).reshape(2, 3),
            actuator_commands=np.arange(4, dtype=float).reshape(2, 2),
            neural_summary=np.zeros((2, 6), dtype=float),
            sensory_observations={"retina": np.ones((2, 3), dtype=float)},
            metadata={
                "schema_name": SCHEMA_NAME,
                "schema_version": SCHEMA_VERSION,
                "model": {
                    "nq": 4,
                    "nv": 3,
                    "nu": 2,
                    "actuator_names": ["a", "b"],
                },
            },
        )

    def test_round_trip_is_controller_independent(self) -> None:
        trajectory = self._trajectory()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trajectory.npz"
            trajectory.save(path)
            loaded = PhysicalTrajectory.load(path)
        np.testing.assert_array_equal(loaded.qpos, trajectory.qpos)
        np.testing.assert_array_equal(loaded.actuator_commands, trajectory.actuator_commands)
        np.testing.assert_array_equal(
            loaded.sensory_observations["retina"], trajectory.sensory_observations["retina"]
        )
        self.assertEqual(loaded.metadata["schema_name"], SCHEMA_NAME)

    def test_non_monotonic_timestamps_are_rejected(self) -> None:
        trajectory = self._trajectory()
        with self.assertRaises(TrajectoryError):
            PhysicalTrajectory(
                timestamps_s=np.asarray([0.01, 0.005]),
                qpos=trajectory.qpos,
                qvel=trajectory.qvel,
                actuator_commands=trajectory.actuator_commands,
                neural_summary=trajectory.neural_summary,
                sensory_observations=trajectory.sensory_observations,
                metadata=trajectory.metadata,
            )


if __name__ == "__main__":
    unittest.main()

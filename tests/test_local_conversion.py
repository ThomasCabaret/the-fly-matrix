from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from the_fly_matrix.local_conversion import (
    ActuatorBridgeParameters,
    FeCOTransferParameters,
    LocalConversionError,
    MotorTwitchParameters,
    event_intensity_to_counts,
    feco_kinematics_to_native_output,
    force_uN_to_actuator_command,
    motor_events_to_force_uN,
    run_local_conversion_contract,
)


class LocalConversionTests(unittest.TestCase):
    def test_feco_modes_keep_their_declared_native_units(self) -> None:
        position = np.asarray([[0.0, 1.0], [1.0, 2.0]])
        velocity = np.asarray([[2.0, 3.0], [4.0, 5.0]])
        graded = feco_kinematics_to_native_output(
            position,
            velocity,
            FeCOTransferParameters(
                "graded_activity",
                np.asarray([2.0, 3.0]),
                np.asarray([0.5, 0.25]),
                np.asarray([1.0, -1.0]),
            ),
        )
        expected = position * np.asarray([2.0, 3.0]) + velocity * np.asarray(
            [0.5, 0.25]
        ) + np.asarray([1.0, -1.0])
        np.testing.assert_allclose(graded, expected)

        with self.assertRaisesRegex(LocalConversionError, "cannot be negative"):
            feco_kinematics_to_native_output(
                position,
                velocity,
                FeCOTransferParameters(
                    "event_intensity_hz",
                    np.asarray([-10.0, -10.0]),
                    np.zeros(2),
                    np.zeros(2),
                ),
            )

    def test_seeded_event_sampling_is_reproducible_and_nonnegative(self) -> None:
        intensity = np.full((100, 3), 1000.0)
        first = event_intensity_to_counts(intensity, timestep_s=0.001, seed=7)
        second = event_intensity_to_counts(intensity, timestep_s=0.001, seed=7)
        third = event_intensity_to_counts(intensity, timestep_s=0.001, seed=8)
        np.testing.assert_array_equal(first, second)
        self.assertFalse(np.array_equal(first, third))
        self.assertTrue(np.issubdtype(first.dtype, np.integer))
        self.assertTrue((first >= 0).all())

    def test_motor_kernel_is_causal_peak_normalized_and_superposes(self) -> None:
        events = np.zeros((200, 1), dtype=np.int64)
        events[10, 0] = 1
        parameters = MotorTwitchParameters(
            force_per_event_uN=np.asarray([3.0]),
            rise_time_s=np.asarray([0.003]),
            decay_time_s=np.asarray([0.012]),
        )
        single = motor_events_to_force_uN(events, parameters, timestep_s=0.001)
        self.assertTrue(np.all(single[:11] == 0.0))
        self.assertAlmostEqual(float(single[:, 0].max()), 3.0, delta=0.03)

        doubled = events.copy()
        doubled[10, 0] = 2
        double_force = motor_events_to_force_uN(doubled, parameters, timestep_s=0.001)
        np.testing.assert_allclose(double_force, 2.0 * single)

    def test_force_to_actuator_bridge_is_a_separate_stage(self) -> None:
        force = np.asarray([[0.0, 1.0], [2.0, 3.0]])
        commands = force_uN_to_actuator_command(
            force,
            ActuatorBridgeParameters(
                command_per_uN=np.asarray([0.1, -0.2]),
                command_offset=np.asarray([1.0, 2.0]),
            ),
        )
        np.testing.assert_allclose(
            commands, force * np.asarray([0.1, -0.2]) + np.asarray([1.0, 2.0])
        )

    def test_shape_units_and_kernel_misuse_fail_loudly(self) -> None:
        with self.assertRaisesRegex(LocalConversionError, "shapes must match"):
            feco_kinematics_to_native_output(
                np.zeros((2, 1)),
                np.zeros((3, 1)),
                FeCOTransferParameters(
                    "graded_activity", np.ones(1), np.ones(1), np.zeros(1)
                ),
            )
        with self.assertRaisesRegex(LocalConversionError, "integer-valued"):
            motor_events_to_force_uN(
                np.zeros((10, 1), dtype=float),
                MotorTwitchParameters(np.ones(1), np.ones(1), np.ones(1) * 2.0),
                timestep_s=0.001,
            )
        with self.assertRaisesRegex(LocalConversionError, "rise_time_s"):
            motor_events_to_force_uN(
                np.zeros((10, 1), dtype=np.int64),
                MotorTwitchParameters(np.ones(1), np.ones(1), np.ones(1) * 0.5),
                timestep_s=0.001,
            )

    def test_registered_contract_runs_without_promoting_values_or_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            result = run_local_conversion_contract(
                output_root=temporary / "artifacts",
                result_path=temporary / "runner.yaml",
            )
        self.assertEqual(result["status"], "pass_contract_only_values_unresolved")
        self.assertEqual(result["accounting"]["promoted_parameter_values"], 0)
        self.assertEqual(result["accounting"]["behavior_targets_exposed"], 0)
        self.assertEqual(result["accounting"]["topology_changes"], 0)
        self.assertEqual(result["behavior_targets"], [])


if __name__ == "__main__":
    unittest.main()

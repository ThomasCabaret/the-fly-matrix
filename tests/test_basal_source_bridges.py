from __future__ import annotations

import unittest

import numpy as np

from the_fly_matrix.basal_source_bridges import (
    BasalSourceBridgeError,
    build_arm_rates,
    event_probability,
    hz_to_graded,
    sample_event_presence,
)


class BasalSourceBridgeTests(unittest.TestCase):
    def test_poisson_presence_is_seed_reproducible_and_unit_bounded(self) -> None:
        rates = np.asarray([0.0, 10.0, 100.0, 500.0])
        probability = event_probability(rates, 0.1)
        self.assertEqual(probability[0], 0.0)
        self.assertTrue(np.all(np.diff(probability) > 0))
        self.assertTrue(np.all((probability >= 0) & (probability < 1)))
        self.assertAlmostEqual(float(probability[1]), float(1.0 - np.exp(-0.001)), places=15)
        left = sample_event_presence(rates, 0.1, np.random.default_rng(123))
        right = sample_event_presence(rates, 0.1, np.random.default_rng(123))
        np.testing.assert_array_equal(left, right)
        dense = np.full(1000, 1000.0)
        first = sample_event_presence(dense, 0.1, np.random.default_rng(1))
        second = sample_event_presence(dense, 0.1, np.random.default_rng(2))
        self.assertFalse(np.array_equal(first, second))

    def test_poisson_presence_rejects_invalid_units(self) -> None:
        with self.assertRaises(BasalSourceBridgeError):
            event_probability([-1.0], 0.1)
        with self.assertRaises(BasalSourceBridgeError):
            event_probability([1.0], 0.0)
        with self.assertRaises(BasalSourceBridgeError):
            event_probability([np.nan], 0.1)

    def test_hz_to_graded_is_zero_preserving_monotone_and_bounded(self) -> None:
        values = hz_to_graded([0.0, 10.0, 100.0, 1000.0], 100.0)
        self.assertEqual(values[0], 0.0)
        self.assertTrue(np.all(np.diff(values) > 0))
        self.assertTrue(np.all(values < 1.0))
        self.assertAlmostEqual(float(values[2]), 0.5)

    def test_hz_to_graded_rejects_hidden_or_invalid_scale(self) -> None:
        with self.assertRaises(BasalSourceBridgeError):
            hz_to_graded([1.0], 0.0)
        with self.assertRaises(BasalSourceBridgeError):
            hz_to_graded([-1.0], 100.0)

    def test_all_preregistered_shapes_preserve_terminal_accounting(self) -> None:
        families = ["a", "a", "b", "b", "b"]
        silence = build_arm_rates(
            families, "explicit_silence_control", uniform_rate_hz=20, equal_family_total_rate_hz=60
        )
        uniform = build_arm_rates(
            families, "uniform_per_terminal", uniform_rate_hz=20, equal_family_total_rate_hz=60
        )
        equal_mass = build_arm_rates(
            families, "equal_family_mass", uniform_rate_hz=20, equal_family_total_rate_hz=60
        )
        self.assertEqual(len(silence), len(families))
        self.assertEqual(len(uniform), len(families))
        self.assertEqual(len(equal_mass), len(families))
        self.assertTrue(np.all(silence == 0))
        self.assertTrue(np.all(uniform == 20))
        self.assertAlmostEqual(float(equal_mass[:2].sum()), 60.0)
        self.assertAlmostEqual(float(equal_mass[2:].sum()), 60.0)

    def test_unknown_shape_never_falls_back_silently(self) -> None:
        with self.assertRaises(BasalSourceBridgeError):
            build_arm_rates(
                ["a"], "unknown", uniform_rate_hz=20, equal_family_total_rate_hz=60
            )


if __name__ == "__main__":
    unittest.main()

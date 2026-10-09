from __future__ import annotations

import unittest

import numpy as np

from the_fly_matrix.motor_spike_force_parser import (
    _moving_mean,
    matlab_smooth,
    _position_from_tags,
    firing_rate,
    make_input_time,
)


class MotorSpikeForceParserTests(unittest.TestCase):
    def test_make_input_time_preserves_matlab_sampling_contract(self) -> None:
        params = {"durSweep": 1.0, "sampratein": 10, "preDurInSec": 0.2}
        np.testing.assert_allclose(
            make_input_time(params), np.arange(10, dtype=float) / 10 - 0.2
        )

    def test_tag_mapping_is_explicit_and_unknown_tags_are_not_zero(self) -> None:
        self.assertEqual(_position_from_tags(np.asarray([], dtype=object), {0.0}), 0.0)
        self.assertEqual(_position_from_tags("-100", {-100.0, 0.0}), -100.0)
        self.assertTrue(np.isnan(_position_from_tags("drug", {0.0})))

    def test_moving_mean_has_bounded_matlab_style_endpoints(self) -> None:
        observed = _moving_mean(np.asarray([1.0, 10.0, 3.0, 4.0, 20.0]), 5)
        np.testing.assert_allclose(observed, [1.0, 14.0 / 3.0, 7.6, 9.0, 20.0])

    def test_nan_trace_uses_local_linear_smoothing_and_fills_boundary(self) -> None:
        observed = matlab_smooth(np.asarray([np.nan, np.nan, 2.0, 3.0, 4.0, 5.0]), 5)
        self.assertTrue(np.isfinite(observed).all())
        np.testing.assert_allclose(observed, np.arange(6, dtype=float), atol=1e-10)

    def test_parser_contract_accounts_for_every_declared_trial(self) -> None:
        import yaml

        from the_fly_matrix.motor_spike_force_parser import PARSER_CONTRACT

        contract = yaml.safe_load(PARSER_CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(sum(item["trial_count"] for item in contract["class_specs"].values()), 194)
        self.assertEqual(contract["scientific_boundary"]["parameter_values_promoted"], 0)
        self.assertFalse(contract["scientific_boundary"]["temporal_twitch_kernel_identified"])

    def test_firing_rate_is_finite_and_scales_over_repeated_trials(self) -> None:
        time = np.arange(1000, dtype=float) / 1000 - 0.5
        single = np.zeros((1000, 1), dtype=float)
        single[[100, 300, 500, 700, 900], 0] = 1
        repeated = np.repeat(single, 3, axis=1)
        first = firing_rate(time, single, 10 / 300)
        second = firing_rate(time, repeated, 10 / 300)
        self.assertTrue(np.isfinite(first).all())
        np.testing.assert_allclose(first, second)


if __name__ == "__main__":
    unittest.main()

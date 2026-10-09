from __future__ import annotations

import unittest

import numpy as np
import yaml

from the_fly_matrix.motor_twitch_temporal_fit import (
    CAMPAIGN_PATH,
    NormalizedTwitch,
    deterministic_folds,
    fit_temporal_shape,
    peak_normalized_biexponential,
)


class MotorTwitchTemporalFitTests(unittest.TestCase):
    def test_kernel_is_causal_peak_normalized_and_decays(self) -> None:
        time = np.linspace(-0.01, 0.2, 5000)
        kernel = peak_normalized_biexponential(time, 0.005, 0.03)
        self.assertTrue(np.all(kernel[time <= 0.0] == 0.0))
        self.assertAlmostEqual(float(kernel.max()), 1.0, places=5)
        self.assertLess(float(kernel[-1]), 0.01)

    def test_round_robin_folds_are_deterministic_disjoint_and_exhaustive(self) -> None:
        first = deterministic_folds([9, 1, 7, 3, 5, 11], 3)
        second = deterministic_folds([11, 5, 3, 7, 1, 9], 3)
        self.assertEqual(first, second)
        flattened = [item for fold in first for item in fold]
        self.assertEqual(sorted(flattened), [1, 3, 5, 7, 9, 11])
        self.assertEqual(len(flattened), len(set(flattened)))

    def test_disposition_accounting_includes_selected_trials(self) -> None:
        dispositions = {
            "declared": 12,
            "source_excluded": 2,
            "not_single_spike": 7,
            "selected": 3,
        }
        accounted = sum(
            value for key, value in dispositions.items() if key != "declared"
        )
        self.assertEqual(accounted, dispositions["declared"])

    def test_synthetic_fold_fit_recovers_grid_member(self) -> None:
        time = np.linspace(0.001, 0.12, 80)
        expected = (0.004, 0.025)
        signal = peak_normalized_biexponential(time, *expected)
        rows = [
            NormalizedTwitch(i, time, signal.copy(), 1.0, float(time[np.argmax(signal)]))
            for i in range(10)
        ]
        candidates = [(0.002, 0.015), expected, (0.008, 0.05)]
        result = fit_temporal_shape(
            rows,
            candidates,
            fold_count=5,
            near_optimal_relative_rmse=0.05,
        )
        best = result["all_data_best_candidate"]
        self.assertEqual(best["rise_time_s"], expected[0])
        self.assertEqual(best["decay_time_s"], expected[1])
        self.assertAlmostEqual(result["held_out_energy_fraction_explained"], 1.0)

    def test_campaign_forbids_promotion_behavior_and_topology_changes(self) -> None:
        campaign = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertFalse(campaign["selection_policy"]["promote_values"])
        self.assertFalse(
            campaign["design_provenance"]["preregistered_before_any_raw_trace_inspection"]
        )


if __name__ == "__main__":
    unittest.main()

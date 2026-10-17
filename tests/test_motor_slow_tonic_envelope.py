from __future__ import annotations

import unittest

import numpy as np
import yaml

from the_fly_matrix.local_conversion import (
    MotorTonicParameters,
    motor_events_to_tonic_force_uN,
)
from the_fly_matrix.motor_slow_tonic_envelope import (
    CAMPAIGN_PATH,
    SlowTrial,
    first_order_event_rate,
    fit_slow_tonic_envelope,
    stratified_trial_folds,
)


class MotorSlowTonicEnvelopeTests(unittest.TestCase):
    def test_event_filter_is_causal_finite_and_decays(self) -> None:
        time = np.linspace(-0.2, 0.8, 1001)
        result = first_order_event_rate(
            time, np.asarray([0.0]), tau_s=0.1, delay_s=0.02, initial_rate_hz=0.0
        )
        self.assertTrue(np.all(result[time < 0.02] == 0.0))
        self.assertTrue(np.isfinite(result).all())
        self.assertGreater(float(result[np.searchsorted(time, 0.02)]), 0.0)
        self.assertLess(float(result[-1]), float(result[np.searchsorted(time, 0.02)]))

    def test_stratified_folds_are_disjoint_exhaustive_and_cover_each_step(self) -> None:
        mapping = {
            index: step
            for step, start in [(-1.0, 0), (1.0, 10), (2.0, 20)]
            for index in range(start, start + 6)
        }
        folds = stratified_trial_folds(mapping, 3)
        flattened = [trial for fold in folds for trial in fold]
        self.assertEqual(sorted(flattened), sorted(mapping))
        self.assertEqual(len(flattened), len(set(flattened)))
        for fold in folds:
            self.assertEqual({mapping[trial] for trial in fold}, {-1.0, 1.0, 2.0})

    def test_runtime_recurrence_matches_fitted_continuous_impulse_samples(self) -> None:
        timestep_s = 0.001
        time = np.arange(100, dtype=np.float64) * timestep_s
        event_indexes = np.asarray([0, 7, 21, 22, 60])
        events = np.zeros((len(time), 1), dtype=np.int64)
        events[event_indexes, 0] = 1
        expected = first_order_event_rate(
            time,
            event_indexes * timestep_s,
            tau_s=0.037,
            delay_s=0.002,
            initial_rate_hz=4.0,
        )
        observed = motor_events_to_tonic_force_uN(
            events,
            MotorTonicParameters(
                force_per_rate_uN_per_hz=np.asarray([1.0]),
                time_constant_s=np.asarray([0.037]),
                delay_s=np.asarray([0.002]),
            ),
            timestep_s=timestep_s,
            initial_filtered_rate_hz=np.asarray([4.0]),
        )
        np.testing.assert_allclose(observed[:, 0], expected, rtol=1e-12, atol=1e-12)

    def test_synthetic_fit_recovers_candidate_and_positive_held_out_score(self) -> None:
        time = np.linspace(-0.2, 0.6, 161)
        candidates = [(0.05, 0.0), (0.12, 0.02), (0.3, 0.04)]
        rows: list[SlowTrial] = []
        for trial in range(15):
            step = [-1.0, 1.0, 2.0][trial % 3]
            baseline_spikes = np.arange(-0.19, 0.0, 0.05)
            active_interval = 0.1 if step < 0 else (0.035 if step == 1.0 else 0.02)
            active_spikes = np.arange(0.0, 0.5, active_interval)
            spikes = np.concatenate([baseline_spikes, active_spikes])
            predictor = first_order_event_rate(
                time,
                spikes,
                tau_s=0.12,
                delay_s=0.02,
                initial_rate_hz=20.0,
            )
            baseline = (time >= -0.2) & (time < 0.0)
            predictor -= float(np.mean(predictor[baseline]))
            rows.append(
                SlowTrial(
                    trial=trial,
                    step_pA=step,
                    frame_time_s=time,
                    force_delta_uN=0.04 * predictor,
                    spike_time_s=spikes,
                    rest_rate_hz=20.0,
                    fit_mask=(time >= 0.0) & (time <= 0.6),
                )
            )
        result = fit_slow_tonic_envelope(
            rows,
            candidates,
            fold_count=5,
            baseline_window_s=[-0.2, 0.0],
            near_optimal_relative_rmse=0.01,
        )
        best = result["all_data_best_candidate"]
        self.assertEqual((best["tau_s"], best["delay_s"]), (0.12, 0.02))
        self.assertAlmostEqual(best["gain_uN_per_hz"], 0.04, places=8)
        self.assertGreater(result["held_out_energy_fraction_explained"], 0.999)

    def test_campaign_forbids_promotion_body_motion_and_topology_changes(self) -> None:
        campaign = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertFalse(campaign["selection_policy"]["promote_values"])
        self.assertFalse(campaign["selection_policy"]["choose_body_class_assignment"])
        self.assertFalse(campaign["selection_policy"]["body_motion_allowed_for_selection"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

import numpy as np
import yaml

from the_fly_matrix.local_conversion import MotorTwitchParameters, motor_events_to_force_uN
from the_fly_matrix.neutral_embodied_declared_closed_loop_sentinel import (
    CAMPAIGN_PATH,
    EVALUATION_PATH,
    RESULT_PATH,
    _MotorTwitch,
    _TypedPopulation,
    _load_campaign,
    geometry_oracle,
)
from the_fly_matrix.neutral_embodied_declared_neural_sentinel import _typed_population


class NeutralEmbodiedDeclaredClosedLoopSentinelTests(unittest.TestCase):
    def test_campaign_is_fixed_zero_fit_and_behavior_naive(self) -> None:
        campaign = _load_campaign(CAMPAIGN_PATH)
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertFalse(campaign["sentinel_selection"]["selected_from_body_motion"])
        self.assertFalse(campaign["acceptance"]["allow_physical_magnitude_to_select_candidate"])
        self.assertEqual(campaign["scientific_boundary"]["optimized_parameters"], 0)
        self.assertEqual(campaign["scientific_boundary"]["selected_candidates"], 0)

    def test_stateful_population_matches_batch_reference_exactly(self) -> None:
        generator = np.random.default_rng(42)
        drive = generator.uniform(0.0, 2.0, size=(300, 7))
        event_mask = np.asarray([True, False, True, False, False, True, True])
        common = dict(
            timestep_s=0.0001,
            graded_tau_s=0.01,
            event_tau_s=0.02,
            synaptic_tau_s=0.005,
            refractory_s=0.0022,
            threshold_excursion_mV=7.0,
            dimensionless_input_scale=1.5,
        )
        expected_output, expected_spikes = _typed_population(drive, event_mask, **common)
        state = _TypedPopulation(event_mask, **common)
        observed = [state.step(value) for value in drive]
        observed_output = np.asarray([item[0] for item in observed])
        observed_spikes = np.asarray([item[1] for item in observed])
        np.testing.assert_array_equal(observed_output, expected_output)
        np.testing.assert_array_equal(observed_spikes, expected_spikes)

    def test_stateful_motor_twitch_matches_batch_reference(self) -> None:
        events = np.zeros(500, dtype=np.int64)
        events[[3, 19, 211]] = [1, 2, 1]
        force_per_event = 12.5
        rise = 0.002
        decay = 0.02
        timestep = 0.0001
        expected = motor_events_to_force_uN(
            events[:, None],
            MotorTwitchParameters(
                force_per_event_uN=np.asarray([force_per_event]),
                rise_time_s=np.asarray([rise]),
                decay_time_s=np.asarray([decay]),
            ),
            timestep_s=timestep,
        )[:, 0]
        state = _MotorTwitch(force_per_event, rise, decay, timestep, gain=0.25)
        observed = np.asarray([state.step(int(value))[0] for value in events])
        np.testing.assert_allclose(observed, expected, atol=0.0, rtol=1e-14)

    def test_bilateral_geometric_coordinate_is_monotonic(self) -> None:
        oracle = geometry_oracle()
        self.assertTrue(oracle["all_strictly_increasing"])
        self.assertGreater(oracle["minimum_covered_span_deg"], 120.0)
        self.assertEqual(set(oracle["sides"]), {"L", "R"})

    def test_committed_result_is_hash_linked_and_claim_bounded(self) -> None:
        if not RESULT_PATH.is_file() or not EVALUATION_PATH.is_file():
            self.skipTest("closed-loop sentinel has not been executed yet")
        result = yaml.safe_load(RESULT_PATH.read_text(encoding="utf-8"))
        evaluation = yaml.safe_load(EVALUATION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(result["accounting"]["optimized_parameters"], 0)
        self.assertEqual(result["accounting"]["selected_candidates"], 0)
        self.assertEqual(result["accounting"]["named_behavior_exposure"], 0)
        self.assertTrue(all(result["checks"].values()))
        self.assertGreater(
            sum(
                item["baseline_chain"]["peak_abs_command"] > 0.0
                for item in result["outcomes"]
            ),
            0,
        )
        self.assertEqual(result["semantic_result_sha256"], evaluation["runner_semantic_sha256"])
        self.assertFalse(evaluation["stability_accepted"])
        self.assertFalse(evaluation["candidate_selected"])


if __name__ == "__main__":
    unittest.main()

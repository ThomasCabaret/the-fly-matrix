from __future__ import annotations

import unittest

from the_fly_matrix.front_leg_neutral_neural_regime import (
    CAMPAIGN_PATH,
    _load_yaml,
    build_pairwise_profiles,
    classify_regime,
    pairwise_coverage,
)


class FrontLegNeutralNeuralRegimeTests(unittest.TestCase):
    def test_locked_design_has_complete_pairwise_coverage_and_budget(self) -> None:
        campaign = _load_yaml(CAMPAIGN_PATH)
        profiles = build_pairwise_profiles(campaign["technical_factor_levels"])
        coverage = pairwise_coverage(profiles, campaign["technical_factor_levels"])
        self.assertTrue(coverage["complete"])
        self.assertEqual(len(profiles), campaign["budget"]["expected_pairwise_profiles"])
        rows = (
            len(profiles)
            * campaign["budget"]["expected_population_anchors"]
            * len(campaign["source_native_mirrors"])
        )
        self.assertEqual(rows, campaign["budget"]["expected_paired_schedule_rows"])
        self.assertLessEqual(rows, campaign["budget"]["max_schedule_rows"])

    def test_classification_requires_response_bounds_and_recovery(self) -> None:
        campaign = _load_yaml(CAMPAIGN_PATH)
        passing = {
            "finite": True,
            "stimulus_generated_event_occupancy": 0.02,
            "sham_generated_event_occupancy": 0.01,
            "stimulus_motor_event_occupancy": 0.02,
            "sham_motor_event_occupancy": 0.01,
            "stimulus_motor_events": 3,
            "sham_motor_events": 1,
            "motor_state_delta_peak_l1": 0.1,
            "motor_state_post_pulse_ratio": 0.25,
        }
        self.assertTrue(classify_regime(passing, campaign["acceptance"])["accepted"])
        for field, value in (
            ("finite", False),
            ("stimulus_generated_event_occupancy", 0.2),
            ("stimulus_motor_event_occupancy", 0.2),
            ("stimulus_motor_events", 1),
            ("motor_state_delta_peak_l1", 0.0),
            ("motor_state_post_pulse_ratio", 0.9),
        ):
            failing = dict(passing)
            failing[field] = value
            self.assertFalse(classify_regime(failing, campaign["acceptance"])["accepted"])

    def test_campaign_is_behavior_naive_and_body_blind(self) -> None:
        campaign = _load_yaml(CAMPAIGN_PATH)
        self.assertEqual(campaign["primary_class"], "technical")
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertEqual(campaign["parameter_values_promoted"], 0)
        self.assertEqual(
            campaign["forbidden_observables"],
            ["body_pose", "body_trajectory", "named_action", "held_out_response"],
        )
        self.assertFalse(campaign["topology_changes_allowed"])


if __name__ == "__main__":
    unittest.main()

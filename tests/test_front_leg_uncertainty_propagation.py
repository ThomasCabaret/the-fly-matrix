from __future__ import annotations

import unittest

import yaml

from the_fly_matrix.front_leg_uncertainty_propagation import (
    CAMPAIGN_PATH,
    build_balanced_pairwise_panel,
)


class FrontLegUncertaintyPropagationTests(unittest.TestCase):
    def test_complemented_panel_balances_every_body(self) -> None:
        panel, summary = build_balanced_pairwise_panel(
            [101, 202, 303, 404], policy_id="fixture", complement_pairs=8
        )
        counts = panel.groupby(["body_id", "assignment"]).size().unstack(fill_value=0)
        self.assertTrue((counts["event_candidate"] == counts["graded_candidate"]).all())
        self.assertEqual(summary["diagnostic_profiles"], 18)
        self.assertEqual(summary["scientific_assignment_space"], "2^4")
        self.assertFalse(summary["higher_order_coverage_claimed"])
        self.assertFalse(summary["probability_prior_implied"])

    def test_complements_and_extremes_cover_all_pairwise_states(self) -> None:
        _panel, summary = build_balanced_pairwise_panel(
            list(range(20)), policy_id="fixture-pairwise", complement_pairs=24
        )
        self.assertEqual(summary["incomplete_pair_count"], 0)
        self.assertEqual(summary["pairs_with_all_four_states"], summary["body_pairs"])

    def test_campaign_forbids_selection_and_scientific_reduction(self) -> None:
        campaign = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertEqual(
            campaign["intermediate_propagation_policy"]["scientific_assignment_space"],
            "2^148",
        )
        self.assertIn(
            "exhaustive higher-order interactions",
            campaign["intermediate_propagation_policy"]["explicitly_not_covered"],
        )
        self.assertIn("Never borrow", campaign["interface_acceptance_policy"]["motor"])


if __name__ == "__main__":
    unittest.main()

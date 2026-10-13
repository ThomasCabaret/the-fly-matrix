from __future__ import annotations

import unittest

import yaml

from the_fly_matrix.neutral_embodied_declared_closed_loop_panel import (
    CAMPAIGN_PATH,
    EVALUATION_PATH,
    RESULT_PATH,
    _coverage,
    _load_campaign,
    _verified_panel_context,
)


class NeutralEmbodiedDeclaredClosedLoopPanelTests(unittest.TestCase):
    def test_campaign_is_exhaustive_zero_fit_and_behavior_naive(self) -> None:
        campaign = _load_campaign(CAMPAIGN_PATH)
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertEqual(campaign["coverage_contract"]["schedule_tuples"], 240)
        self.assertEqual(campaign["coverage_contract"]["paired_physical_episodes"], 480)
        self.assertFalse(campaign["acceptance"]["allow_neural_magnitude_to_select_candidate"])
        self.assertFalse(campaign["acceptance"]["allow_physical_magnitude_to_select_candidate"])
        self.assertEqual(campaign["scientific_boundary"]["optimized_parameters"], 0)
        self.assertEqual(campaign["scientific_boundary"]["selected_candidates"], 0)

    def test_exact_schedule_coverage_matches_preregistered_contract(self) -> None:
        campaign = _load_campaign(CAMPAIGN_PATH)
        context, sentinel_result, _hashes = _verified_panel_context(campaign)
        observed = _coverage(context["rows"])
        expected = {
            key: int(value)
            for key, value in campaign["coverage_contract"].items()
            if key in observed
        }
        self.assertEqual(observed, expected)
        self.assertEqual(sentinel_result["status"], "pass_causal_closed_loop_execution_no_fit_no_selection")

    def test_committed_negative_result_is_complete_hash_linked_and_not_clipped(self) -> None:
        if not RESULT_PATH.is_file() or not EVALUATION_PATH.is_file():
            self.skipTest("causal physical panel has not been executed yet")
        result = yaml.safe_load(RESULT_PATH.read_text(encoding="utf-8"))
        evaluation = yaml.safe_load(EVALUATION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(result["accounting"]["schedule_tuples"], 240)
        self.assertEqual(len(result["outcomes"]), 240)
        self.assertEqual(result["accounting"]["outcome_counts"], {"completed_contract": 237, "error": 3})
        failed = [item for item in result["outcomes"] if item["status"] == "error"]
        self.assertEqual(
            [item["tuple_id"] for item in failed],
            ["declared_tuple_029", "declared_tuple_041", "declared_tuple_149"],
        )
        self.assertTrue(all("exceeds MOTOR limit" in item["error"] for item in failed))
        self.assertTrue(result["checks"]["every_schedule_tuple_accounted_exactly_once"])
        self.assertTrue(result["checks"]["exact_schedule_axis_coverage"])
        self.assertTrue(result["checks"]["all_16_frozen_sentinel_traces_reproduced_after_model_reuse"])
        self.assertFalse(result["checks"]["all_480_paired_episodes_finite"])
        self.assertEqual(result["accounting"]["optimized_parameters"], 0)
        self.assertEqual(result["accounting"]["selected_candidates"], 0)
        self.assertEqual(result["semantic_result_sha256"], evaluation["runner_semantic_sha256"])
        self.assertEqual(evaluation["status"], "fail")
        self.assertFalse(evaluation["stability_accepted"])
        self.assertFalse(evaluation["candidate_selected"])


if __name__ == "__main__":
    unittest.main()

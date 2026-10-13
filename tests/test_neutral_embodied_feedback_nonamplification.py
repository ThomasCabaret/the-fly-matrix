from __future__ import annotations

import unittest

import yaml

from the_fly_matrix.neutral_embodied_feedback_nonamplification import (
    CAMPAIGN_PATH,
    EVALUATION_PATH,
    PARAMETER_SET_PATH,
    RESULT_PATH,
    _active_ids,
    _load_campaign,
    _verified_inputs,
    _within_paired_limit,
)


class NeutralEmbodiedFeedbackNonamplificationTests(unittest.TestCase):
    def test_campaign_is_technical_behavior_naive_and_not_global_stability(self) -> None:
        campaign = _load_campaign(CAMPAIGN_PATH)
        self.assertEqual(campaign["primary_class"], "technical")
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertFalse(campaign["campaign_acceptance"]["stability_acceptance_possible"])
        self.assertFalse(campaign["per_row_acceptance"]["allow_ranking_within_accepted_set"])
        self.assertEqual(len(campaign["physical_protocol"]["perturbations"]), 4)

    def test_parent_active_stratum_is_exhaustive_and_keeps_previous_exception(self) -> None:
        campaign = _load_campaign(CAMPAIGN_PATH)
        inputs, _hashes = _verified_inputs(campaign)
        active = _active_ids(campaign, inputs["feedback_result"])
        self.assertEqual(len(active), 65)
        self.assertIn("declared_tuple_028", active)

    def test_paired_limit_uses_only_locked_tolerances(self) -> None:
        tolerance = {
            "paired_comparison_absolute_tolerance": 1e-12,
            "paired_comparison_relative_tolerance": 1e-6,
        }
        self.assertTrue(_within_paired_limit(1.0000005, 1.0, tolerance))
        self.assertFalse(_within_paired_limit(1.00001, 1.0, tolerance))

    def test_committed_result_is_complete_and_claim_bounded(self) -> None:
        if not RESULT_PATH.is_file() or not EVALUATION_PATH.is_file() or not PARAMETER_SET_PATH.is_file():
            self.skipTest("non-amplification validation has not run yet")
        result = yaml.safe_load(RESULT_PATH.read_text(encoding="utf-8"))
        evaluation = yaml.safe_load(EVALUATION_PATH.read_text(encoding="utf-8"))
        parameter_set = yaml.safe_load(PARAMETER_SET_PATH.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "completed_locked_validation")
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["accounting"]["physical_episodes"], 650)
        self.assertEqual(len(result["outcomes"]), 65)
        self.assertTrue(all(len(row["perturbations"]) == 4 for row in result["outcomes"]))
        self.assertEqual(
            result["accounting"]["classification_counts"],
            {
                "accepted_local_nonamplifying": 3,
                "mixed_or_amplifying": 61,
                "not_identifiable_on_validation_perturbations": 1,
            },
        )
        self.assertEqual(
            result["accepted_tuple_ids"],
            ["declared_tuple_129", "declared_tuple_141", "declared_tuple_238"],
        )
        self.assertEqual(result["semantic_result_sha256"], evaluation["runner_semantic_sha256"])
        self.assertEqual(parameter_set["runner_semantic_sha256"], result["semantic_result_sha256"])
        self.assertEqual(parameter_set["ensemble"]["member_tuple_ids"], result["accepted_tuple_ids"])
        self.assertFalse(evaluation["whole_body_stability_accepted"])
        self.assertFalse(evaluation["candidate_ranking_used"])
        self.assertFalse(parameter_set["applicability"]["whole_body_stability"])


if __name__ == "__main__":
    unittest.main()

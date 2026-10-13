from __future__ import annotations

import unittest

import yaml

from the_fly_matrix.neutral_embodied_feedback_identifiability import (
    CAMPAIGN_PATH,
    EVALUATION_PATH,
    RESULT_PATH,
    _accounting_sets,
    _load_campaign,
    _verified_inputs,
)


class NeutralEmbodiedFeedbackIdentifiabilityTests(unittest.TestCase):
    def test_campaign_is_behavior_naive_and_nonselective(self) -> None:
        campaign = _load_campaign(CAMPAIGN_PATH)
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertFalse(campaign["acceptance"]["allow_activity_or_motion_magnitude_to_rank_candidate"])
        self.assertFalse(campaign["acceptance"]["allow_silent_row_rejection"])
        self.assertFalse(campaign["acceptance"]["stability_acceptance_possible"])
        self.assertEqual(campaign["scientific_boundary"]["optimized_parameters"], 0)

    def test_frozen_workload_partitions_every_exact_row(self) -> None:
        campaign = _load_campaign(CAMPAIGN_PATH)
        inputs, _hashes = _verified_inputs(campaign)
        active, silent, blocked = _accounting_sets(campaign, inputs)
        self.assertEqual((len(active), len(silent), len(blocked)), (65, 172, 3))
        self.assertEqual(len(set(active) | set(silent) | set(blocked)), 240)
        self.assertFalse(set(active) & set(silent))

    def test_committed_result_is_hash_linked_and_claim_bounded(self) -> None:
        if not RESULT_PATH.is_file() or not EVALUATION_PATH.is_file():
            self.skipTest("feedback-identifiability gate has not run yet")
        result = yaml.safe_load(RESULT_PATH.read_text(encoding="utf-8"))
        evaluation = yaml.safe_load(EVALUATION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "pass_feedback_identifiability_no_selection")
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["accounting"]["active_rows_probed"], 65)
        self.assertEqual(result["accounting"]["silent_noninformative_rows"], 172)
        self.assertEqual(result["accounting"]["blocked_command_contract_rows"], 3)
        self.assertEqual(result["accounting"]["physical_episodes"], 260)
        self.assertEqual(
            result["strata"]["active_probe_classification_counts"],
            {"feedback_not_identifiable": 1, "feedback_physically_identifiable": 64},
        )
        self.assertEqual(result["semantic_result_sha256"], evaluation["runner_semantic_sha256"])
        self.assertFalse(evaluation["stability_accepted"])
        self.assertFalse(evaluation["candidate_selected"])
        self.assertTrue(evaluation["silent_rows_remain_unresolved"])


if __name__ == "__main__":
    unittest.main()

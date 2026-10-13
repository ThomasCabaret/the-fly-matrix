from __future__ import annotations

import csv
import unittest

import yaml

from the_fly_matrix.neutral_embodied_command_pathology_policy import (
    CAMPAIGN_PATH,
    EVALUATION_PATH,
    RESULT_PATH,
    _load_campaign,
)


class NeutralEmbodiedCommandPathologyPolicyTests(unittest.TestCase):
    def test_campaign_preserves_negative_factor_result_and_fails_unseen_closed(self) -> None:
        campaign = _load_campaign(CAMPAIGN_PATH)
        self.assertEqual(campaign["policy_contract"]["scope"], "exact_immutable_240_row_schedule")
        self.assertEqual(campaign["policy_contract"]["unseen_combination_policy"], "execute_same_pre_application_guard_fail_closed")
        self.assertEqual(campaign["policy_contract"]["broad_gain_domains_rejected"], [])
        self.assertEqual(campaign["policy_contract"]["broad_numeric_domains_rejected"], [])
        self.assertFalse(campaign["acceptance"]["allow_candidate_ranking"])
        self.assertEqual(campaign["behavior_targets"], [])

    def test_result_closes_exact_schedule_only(self) -> None:
        if not RESULT_PATH.is_file() or not EVALUATION_PATH.is_file():
            self.skipTest("command pathology policy has not been compiled yet")
        result = yaml.safe_load(RESULT_PATH.read_text(encoding="utf-8"))
        evaluation = yaml.safe_load(EVALUATION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "pass_exact_schedule_command_policy_unseen_fail_closed")
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["factor_isolation"]["source_status"], "failed_factor_isolation_policy_open")
        self.assertEqual(result["factor_isolation"]["completed_probes"], 14)
        self.assertEqual(result["factor_isolation"]["crossing_probes"], 10)
        self.assertTrue(result["schedule_factor_identifiability"]["each_numeric_profile_has_exactly_one_gain"])
        self.assertEqual(result["accounting"]["rows_admitted_to_next_technical_gate"], 237)
        self.assertEqual(result["accounting"]["rows_blocked_at_command_contract"], 3)
        self.assertEqual(result["policy"]["broad_gain_domains_rejected"], [])
        self.assertEqual(result["policy"]["broad_numeric_domains_rejected"], [])
        self.assertEqual(result["semantic_result_sha256"], evaluation["runner_semantic_sha256"])
        self.assertFalse(evaluation["stability_accepted"])
        self.assertFalse(evaluation["candidate_selected"])

        policy_path = CAMPAIGN_PATH.parents[2] / result["policy"]["path"]
        with policy_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 240)
        blocked = [row["tuple_id"] for row in rows if row["disposition"].startswith("blocked_")]
        self.assertEqual(blocked, ["declared_tuple_029", "declared_tuple_041", "declared_tuple_149"])


if __name__ == "__main__":
    unittest.main()

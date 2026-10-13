from __future__ import annotations

import unittest

import yaml

from the_fly_matrix.neutral_embodied_command_limit_diagnostic import (
    CAMPAIGN_PATH,
    EVALUATION_PATH,
    RESULT_PATH,
    _load_campaign,
)


class NeutralEmbodiedCommandLimitDiagnosticTests(unittest.TestCase):
    def test_campaign_is_bounded_repeatable_and_nonselecting(self) -> None:
        campaign = _load_campaign(CAMPAIGN_PATH)
        self.assertEqual(
            campaign["diagnostic_scope"]["tuple_ids"],
            ["declared_tuple_029", "declared_tuple_041", "declared_tuple_149"],
        )
        self.assertEqual(campaign["diagnostic_scope"]["total_probe_episodes"], 12)
        self.assertFalse(campaign["acceptance"]["allow_clipping"])
        self.assertFalse(campaign["acceptance"]["allow_candidate_narrowing"])
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertEqual(campaign["scientific_boundary"]["selected_candidates"], 0)

    def test_result_localizes_every_branch_deterministically_without_application(self) -> None:
        if not RESULT_PATH.is_file() or not EVALUATION_PATH.is_file():
            self.skipTest("command-limit diagnostic has not been executed yet")
        result = yaml.safe_load(RESULT_PATH.read_text(encoding="utf-8"))
        evaluation = yaml.safe_load(EVALUATION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "pass_deterministic_command_limit_localization_no_selection")
        self.assertEqual(result["accounting"]["probe_episodes"], 12)
        self.assertEqual(result["accounting"]["first_limit_crossing_probes"], 12)
        self.assertTrue(all(result["checks"].values()))
        for item in result["outcomes"]:
            for branch in ("baseline", "perturbed"):
                record = item["branches"][branch]
                self.assertTrue(record["repeat_signatures_identical"])
                for probe in record["repeats"]:
                    self.assertEqual(probe["status"], "first_command_limit_crossing")
                    self.assertGreater(probe["absolute_attempted_command"], 0.01)
                    self.assertFalse(probe["offending_command_applied"])
        self.assertEqual(result["accounting"]["selected_candidates"], 0)
        self.assertEqual(result["semantic_result_sha256"], evaluation["runner_semantic_sha256"])
        self.assertFalse(evaluation["stability_accepted"])
        self.assertFalse(evaluation["candidate_selected"])


if __name__ == "__main__":
    unittest.main()

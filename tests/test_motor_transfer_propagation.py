from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from the_fly_matrix.motor_transfer_propagation import CAMPAIGN_PATH, run


class MotorTransferPropagationTests(unittest.TestCase):
    def test_campaign_has_no_behavior_or_reference_selection(self) -> None:
        campaign = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertEqual(campaign["propagation_policy"]["reference_selection"], "forbidden")
        self.assertFalse(campaign["propagation_policy"]["body_motion_may_select_member"])

    def test_full_factorized_motor_space_becomes_executable_without_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = run(
                parameter_set_path=root / "parameters.yaml",
                evaluation_path=root / "evaluation.yaml",
                runner_path=root / "runner.yaml",
            )
            parameter_set = yaml.safe_load((root / "parameters.yaml").read_text(encoding="utf-8"))
        self.assertEqual(result["accounting"]["body_class_assignments"], 59_049)
        self.assertEqual(result["accounting"]["newly_executable_slow_containing_assignments"], 58_025)
        self.assertEqual(result["accounting"]["remaining_blocked_assignments"], 0)
        self.assertEqual(result["accounting"]["slow_candidates_propagated"], 338)
        self.assertEqual(result["selected_body_class_assignments"], 0)
        self.assertEqual(result["promoted_parameter_values"], 0)
        self.assertIsNone(parameter_set["reference_selection"])
        self.assertEqual(len(parameter_set["slow_candidate_source"]["retained_grid_indexes"]), 338)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from the_fly_matrix.actuator_semantics import _load_campaign, homolog_key


class ActuatorSemanticsTests(unittest.TestCase):
    def test_campaign_is_behavior_naive_and_diagnostic_only(self) -> None:
        campaign = _load_campaign()
        self.assertEqual(campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertEqual(campaign["probe"]["actuator_scope"], "all_102_channels_individually")
        self.assertEqual(campaign["budgets"]["optimized_parameters"], 0)

    def test_homolog_keys_preserve_leg_position_and_remove_only_side(self) -> None:
        left, left_side = homolog_key("lf_trochanterfemur-lf_tibia-pitch-motor")
        right, right_side = homolog_key("rf_trochanterfemur-rf_tibia-pitch-motor")
        self.assertEqual(left, right)
        self.assertEqual((left_side, right_side), ("l", "r"))
        self.assertIn("{side}f_", left)
        midline, side = homolog_key("c_thorax-c_head-yaw-motor")
        self.assertEqual(midline, "c_thorax-c_head-yaw-motor")
        self.assertIsNone(side)

    def test_v0_local_result_does_not_close_gate_by_itself(self) -> None:
        path = Path("calibration/runner/actuator-semantics-gate-v0.yaml")
        result = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(result["behavior_targets"], [])
        self.assertEqual(result["inventory_summary"]["actuator_count"], 102)
        self.assertEqual(result["response_summary"]["actuators_probed"], 102)
        self.assertTrue(result["accepted_local_open_loop_mechanics"])
        self.assertFalse(result["scientific_gate_closed"])
        self.assertEqual(
            result["unrun_required_metric"], "open_loop_closed_loop_response_gap"
        )


if __name__ == "__main__":
    unittest.main()

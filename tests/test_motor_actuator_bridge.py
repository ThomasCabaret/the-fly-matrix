from __future__ import annotations

import unittest

import yaml

from the_fly_matrix.motor_actuator_bridge import (
    CAMPAIGN_PATH,
    MotorActuatorBridgeError,
    derive_conditional_gain_envelope,
)


class MotorActuatorBridgeTests(unittest.TestCase):
    def test_conditional_gain_interval_preserves_detectability_and_guard(self) -> None:
        forces = {"fast": 5.0, "intermediate": 1.0, "slow": 0.02}
        result = derive_conditional_gain_envelope(
            force_candidates_uN=forces,
            worst_detectable_command=1e-6,
            command_guard=0.005,
            candidate_count=3,
        )
        self.assertTrue(result["feasible"])
        gains = result["candidate_gains_command_per_uN"]
        self.assertEqual(len(gains), 3)
        self.assertAlmostEqual(result["projected_commands"]["slow"][0], 1e-6)
        self.assertAlmostEqual(result["projected_commands"]["fast"][-1], 0.005)
        self.assertLess(gains[0], gains[1])
        self.assertLess(gains[1], gains[2])

    def test_infeasible_interval_is_reported_without_candidates(self) -> None:
        result = derive_conditional_gain_envelope(
            force_candidates_uN={"strong": 10.0, "weak": 0.001},
            worst_detectable_command=1e-3,
            command_guard=0.005,
            candidate_count=3,
        )
        self.assertFalse(result["feasible"])
        self.assertEqual(result["candidate_gains_command_per_uN"], [])

    def test_invalid_force_candidate_fails_closed(self) -> None:
        with self.assertRaises(MotorActuatorBridgeError):
            derive_conditional_gain_envelope(
                force_candidates_uN={"bad": 0.0},
                worst_detectable_command=1e-6,
                command_guard=0.005,
                candidate_count=3,
            )

    def test_campaign_cannot_select_gain_route_class_or_behavior(self) -> None:
        campaign = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        policy = campaign["selection_policy"]
        self.assertFalse(policy["promote_reference_gain"])
        self.assertFalse(policy["select_route"])
        self.assertFalse(policy["select_body_class"])
        self.assertEqual(policy["command_offset"], "fixed_zero")


if __name__ == "__main__":
    unittest.main()

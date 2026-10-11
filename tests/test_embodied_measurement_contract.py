from __future__ import annotations

import unittest

import numpy as np
import yaml

from the_fly_matrix.embodied_measurement_contract import (
    CAMPAIGN_PATH,
    _load_campaign,
    joint_limit_metrics,
    paired_recovery_metrics,
    physical_kinematics,
)


class EmbodiedMeasurementContractTests(unittest.TestCase):
    def test_joint_limit_metrics_count_real_violations_and_margins(self) -> None:
        positions = np.asarray([[0.0, 0.0], [0.5, 2.0], [1.1, -2.0]])
        metrics = joint_limit_metrics(
            positions,
            np.asarray([-1.0, -1.0]),
            np.asarray([1.0, 1.0]),
            np.asarray([True, False]),
        )
        self.assertEqual(metrics["limited_channels"], 1)
        self.assertEqual(metrics["violation_samples"], 1)
        self.assertEqual(metrics["violating_frames"], 1)
        self.assertAlmostEqual(metrics["minimum_margin_rad"], -0.1)

    def test_physical_jerk_is_derived_from_com_not_commands(self) -> None:
        time = np.linspace(0.0, 0.4, 9)
        com = np.column_stack((time**3, np.zeros_like(time), np.ones_like(time)))
        metrics = physical_kinematics(com, time)
        self.assertGreater(metrics["jerk_l2_peak"], 0.0)
        self.assertIn("mass_weighted_flybody_com", metrics["method"])

    def test_paired_recovery_reports_peak_and_final_without_acceptance(self) -> None:
        baseline = {
            "center_of_mass": np.zeros((5, 3)),
            "qpos": np.zeros((5, 4)),
            "qvel": np.zeros((5, 3)),
        }
        perturbed = {key: value.copy() for key, value in baseline.items()}
        perturbed["center_of_mass"][:, 0] = [0.0, 0.0, 1.0, 0.4, 0.2]
        perturbed["qpos"][:, 0] = [0.0, 0.0, 2.0, 0.8, 0.2]
        perturbed["qvel"][:, 0] = [0.0, 0.0, 3.0, 1.0, 0.1]
        metrics = paired_recovery_metrics(baseline, perturbed, 2)
        self.assertEqual(metrics["center_of_mass"]["peak_l2"], 1.0)
        self.assertEqual(metrics["center_of_mass"]["final_over_peak"], 0.2)
        self.assertEqual(
            metrics["center_of_mass"]["stable_half_recovery_frame_after_perturbation"],
            1,
        )

    def test_campaign_is_behavior_naive_threshold_free_and_zero_fit(self) -> None:
        campaign = _load_campaign()
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertEqual(campaign["budgets"]["optimized_parameters"], 0)
        self.assertEqual(campaign["acceptance"]["stability_thresholds"], "unresolved")
        self.assertFalse(campaign["acceptance"]["stability_acceptance_possible"])
        text = str(yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="utf-8"))).lower()
        self.assertNotIn("groom", text)
        self.assertNotIn("walking", text)
        self.assertEqual(
            campaign["acceptance"]["expected_ground_contact_channels"], 6
        )
        self.assertEqual(campaign["paired_protocol"]["expected_frame_dt_s"], 0.005)


if __name__ == "__main__":
    unittest.main()

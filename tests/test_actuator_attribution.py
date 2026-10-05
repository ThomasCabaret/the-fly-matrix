from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import yaml

from the_fly_matrix.actuator_attribution import _deviation_metrics, _load_campaign


ROOT = Path(__file__).resolve().parents[1]


class ActuatorAttributionTests(unittest.TestCase):
    def test_campaign_is_preregistered_behavior_naive_and_zero_fit(self) -> None:
        campaign = _load_campaign()
        self.assertEqual(campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertEqual(campaign["budgets"]["optimized_parameters"], 0)
        self.assertEqual(
            campaign["closed_loop_probe"]["branches"],
            [
                "passive_zero_command",
                "frozen_baseline_commands_open_loop",
                "live_malecns_closed_feedback",
            ],
        )

    def test_compact_result_closes_only_the_bounded_surrogate_gate(self) -> None:
        result = yaml.safe_load(
            (ROOT / "calibration" / "runner" / "actuator-causal-attribution-v1.yaml")
            .read_text(encoding="utf-8")
        )
        self.assertTrue(result["passed"])
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["optimized_parameters"], 0)
        self.assertEqual(result["behavior_targets"], [])
        self.assertEqual(result["unloaded_symmetry"]["actuators_probed"], 102)
        self.assertEqual(result["unloaded_symmetry"]["nonzero_local_responses"], 102)
        self.assertEqual(result["unloaded_symmetry"]["homolog_pairs_accounted"], 41)
        exclusions = " ".join(result["decision"]["does_not_support"])
        self.assertIn("muscle", exclusions)
        self.assertIn("behavior", exclusions)

    def test_deviation_metrics_reports_peak_final_and_recovery(self) -> None:
        reference = {
            "qpos": np.zeros((3, 9)),
            "qvel": np.zeros((3, 8)),
        }
        perturbed = {
            "qpos": np.asarray(
                [
                    np.zeros(9),
                    [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    [0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                ]
            ),
            "qvel": np.zeros((3, 8)),
        }
        metrics = _deviation_metrics(perturbed, reference, 1)
        self.assertEqual(metrics["qpos_l2_peak"], 1.0)
        self.assertEqual(metrics["qpos_l2_final"], 0.5)
        self.assertEqual(metrics["qpos_recovery_fraction"], 0.5)


if __name__ == "__main__":
    unittest.main()

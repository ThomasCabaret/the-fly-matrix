from __future__ import annotations

import unittest

import numpy as np
import yaml

from the_fly_matrix.first_held_out_execution import (
    _analyse,
    _member_side_summary,
    _pair_outcomes,
    _step_without_diagnostic_metrics,
    ramp_fraction,
    worker_group_indices,
)
from the_fly_matrix.ledger import ROOT
from the_fly_matrix.typed_hybrid_runtime import (
    DiagnosticConstants,
    TorchTypedHybridRuntime,
    _micro_graph,
)


class FirstHeldOutExecutionTests(unittest.TestCase):
    def test_worker_partitions_are_disjoint_and_exhaustive(self) -> None:
        partitions = [worker_group_indices(96, index, 8) for index in range(8)]
        flattened = [value for partition in partitions for value in partition]
        self.assertEqual(sorted(flattened), list(range(96)))
        self.assertEqual(len(flattened), len(set(flattened)))

    def test_metrics_free_step_is_state_identical_to_canonical_runtime(self) -> None:
        campaign = yaml.safe_load(
            (ROOT / "calibration/campaigns/basal-reached-typed-hybrid-runtime-sentinel-v0.yaml")
            .read_text(encoding="utf-8")
        )
        constants = DiagnosticConstants.from_campaign(campaign)
        graph, assignment = _micro_graph()
        canonical = TorchTypedHybridRuntime(graph, assignment, constants, "cpu")
        held_out = TorchTypedHybridRuntime(graph, assignment, constants, "cpu")
        external = np.zeros(4, dtype=np.float32)
        external[2] = constants.external_graded_probe

        canonical.step(forced_event_indices=[0], external_graded=external)
        _step_without_diagnostic_metrics(
            held_out,
            forced_event_indices=[0],
            external_graded=external,
        )

        self.assertEqual(canonical.step_index, held_out.step_index)
        for name, expected in canonical.state_arrays().items():
            np.testing.assert_array_equal(held_out.state_arrays()[name], expected)

    def test_ramp_fraction_is_exact_and_releases(self) -> None:
        self.assertIsNone(ramp_fraction(999, 1000, 650))
        self.assertAlmostEqual(ramp_fraction(1000, 1000, 650), 1 / 650)
        self.assertEqual(ramp_fraction(1649, 1000, 650), 1.0)
        self.assertIsNone(ramp_fraction(1650, 1000, 650))

    def test_pairing_keeps_native_measures_separate(self) -> None:
        common = {
            "topology_variant": "canonical",
            "member_id": "member-a",
            "side": "left",
            "trial_seed": 1,
            "event_motor_bodies": 2,
            "graded_motor_bodies": 1,
            "finite": True,
            "failure_masks": {"joint_limit_violation_frames": 0},
        }
        rows = [
            {
                **common,
                "condition": "stimulus",
                "event_motor_count": 3,
                "graded_motor_integral": 2.0,
                "release_opposition_deg": 1.0,
            },
            {
                **common,
                "condition": "sham",
                "event_motor_count": 1,
                "graded_motor_integral": 1.0,
                "release_opposition_deg": 0.0,
            },
        ]
        paired = _pair_outcomes(rows)
        self.assertEqual(paired[0]["event_count_effect"], 2)
        self.assertEqual(paired[0]["graded_integral_effect"], 1.0)
        self.assertTrue(paired[0]["neural_expected_direction"])
        self.assertTrue(paired[0]["physical_expected_direction"])

    def test_seven_of_eight_rule_is_exact(self) -> None:
        rows = []
        for seed in range(8):
            rows.append(
                {
                    "topology_variant": "canonical",
                    "member_id": "member-a",
                    "side": "left",
                    "trial_seed": seed,
                    "neural_expected_direction": seed < 7,
                    "physical_expected_direction": seed < 7,
                    "bounded": True,
                }
            )
        summary = _member_side_summary(rows, 7)
        self.assertTrue(summary[0]["primary_neural_pass"])
        self.assertTrue(summary[0]["secondary_physical_support"])

    def test_unpaired_outcome_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "unpaired"):
            _pair_outcomes(
                [
                    {
                        "topology_variant": "canonical",
                        "member_id": "a",
                        "side": "left",
                        "trial_seed": 1,
                        "condition": "stimulus",
                    }
                ]
            )


if __name__ == "__main__":
    unittest.main()

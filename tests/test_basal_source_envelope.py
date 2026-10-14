from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from the_fly_matrix.basal_source_envelope import (
    _semantic_float_quantization,
    compile_envelope_members,
)


ROOT = Path(__file__).resolve().parents[1]


class BasalSourceEnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.campaign = {
            "technical_envelope": {
                "assignment_profiles": [
                    "exact_event_plus_all_dual_as_graded",
                    "all_reached_as_event_candidate",
                ],
                "uniform_per_terminal_scales": [
                    {"id": "low", "rate_hz": 5.0},
                    {"id": "reference", "rate_hz": 20.0},
                    {"id": "high", "rate_hz": 80.0},
                ],
                "equal_family_mass_scales": [
                    {"id": "low", "family_total_rate_hz": 1250.0},
                    {"id": "reference", "family_total_rate_hz": 2500.0},
                    {"id": "high", "family_total_rate_hz": 5000.0},
                ],
                "graded_half_saturation_hz": [25.0, 100.0, 400.0],
                "ablation_family_ids": [f"family.{index}" for index in range(6)],
                "ablation_reference_uniform_rate_hz": 20.0,
                "ablation_reference_graded_half_saturation_hz": 100.0,
                "long_horizon_event_reference": {"uniform_rate_hz": 80.0, "steps": 960},
            }
        }

    def test_grid_is_complete_and_retains_both_profiles(self) -> None:
        members = compile_envelope_members(self.campaign)
        # Mixed: silence + 2 shapes * 3 rates * 3 conversion scales + 6 ablations.
        # Event: silence + 2 shapes * 3 rates * 1 irrelevant fixed scale + 6 ablations.
        self.assertEqual(len(members), 39)
        self.assertEqual(len({row["member_id"] for row in members}), 39)
        self.assertEqual(
            {row["assignment_profile_id"] for row in members},
            set(self.campaign["technical_envelope"]["assignment_profiles"]),
        )

    def test_each_family_is_ablated_once_per_profile(self) -> None:
        members = compile_envelope_members(self.campaign)
        ablations = [row for row in members if row["ablated_family_id"] is not None]
        self.assertEqual(len(ablations), 12)
        for profile in self.campaign["technical_envelope"]["assignment_profiles"]:
            observed = {
                row["ablated_family_id"]
                for row in ablations
                if row["assignment_profile_id"] == profile
            }
            self.assertEqual(observed, set(self.campaign["technical_envelope"]["ablation_family_ids"]))

    def test_event_profile_does_not_multiply_irrelevant_graded_scale(self) -> None:
        members = compile_envelope_members(self.campaign)
        event_members = [
            row for row in members if row["assignment_profile_id"] == "all_reached_as_event_candidate"
        ]
        non_ablation_non_silence = [
            row
            for row in event_members
            if row["ablated_family_id"] is None
            and row["shape_id"] != "explicit_silence_control"
            and "steps_override" not in row
        ]
        self.assertEqual(len(non_ablation_non_silence), 6)
        self.assertEqual(
            {row["graded_half_saturation_hz"] for row in non_ablation_non_silence}, {100.0}
        )

    def test_one_long_horizon_event_discriminant_is_explicit(self) -> None:
        members = compile_envelope_members(self.campaign)
        long_horizon = [row for row in members if "steps_override" in row]
        self.assertEqual(len(long_horizon), 1)
        self.assertEqual(long_horizon[0]["assignment_profile_id"], "all_reached_as_event_candidate")
        self.assertEqual(long_horizon[0]["steps_override"], 960)

    def test_committed_result_is_complete_and_promotes_nothing(self) -> None:
        result = yaml.safe_load(
            (ROOT / "calibration" / "runner" / "basal-source-envelope-propagation-v0.yaml")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(result["accounting"]["members"], 39)
        self.assertEqual(result["accounting"]["family_ablation_runs"], 12)
        self.assertEqual(result["accounting"]["local_probe_neurons"], 196)
        self.assertTrue(all(result["checks"].values()) is False)
        positive = {
            key: value
            for key, value in result["checks"].items()
            if key not in {
                "parameter_values_promoted",
                "population_assignments_promoted",
                "members_ranked_or_selected",
                "named_behavior_exposed",
            }
        }
        self.assertTrue(all(positive.values()))
        self.assertFalse(result["checks"]["parameter_values_promoted"])
        self.assertFalse(result["checks"]["population_assignments_promoted"])
        self.assertFalse(result["checks"]["members_ranked_or_selected"])
        self.assertFalse(result["checks"]["named_behavior_exposed"])

    def test_committed_findings_keep_scale_risk_visible(self) -> None:
        result = yaml.safe_load(
            (ROOT / "calibration" / "runner" / "basal-source-envelope-propagation-v0.yaml")
            .read_text(encoding="utf-8")
        )
        findings = result["diagnostic_findings"]
        self.assertGreater(
            findings[
                "mixed_reference_unknown_family_ablation_motor_state_max_absolute_fraction"
            ],
            0.8,
        )
        self.assertTrue(findings["short_horizon_all_event_reference_motor_probe_is_zero"])
        self.assertTrue(all(findings["long_horizon_all_event_probe_nonzero_by_group"].values()))
        self.assertEqual(findings["long_horizon_all_event_generated_internal_events"], 0)

    def test_semantic_quantization_removes_only_trailing_float_noise(self) -> None:
        left = {"metric": 0.0123456781, "count": 39, "gate": True}
        right = {"metric": 0.0123456789, "count": 39, "gate": True}
        self.assertEqual(
            _semantic_float_quantization(left, 6),
            _semantic_float_quantization(right, 6),
        )
        self.assertEqual(_semantic_float_quantization(left, 6)["count"], 39)
        self.assertIs(_semantic_float_quantization(left, 6)["gate"], True)


if __name__ == "__main__":
    unittest.main()

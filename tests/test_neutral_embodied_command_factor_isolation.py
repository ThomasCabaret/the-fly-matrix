from __future__ import annotations

import csv
import unittest

import yaml

from the_fly_matrix.neutral_embodied_command_factor_isolation import (
    CAMPAIGN_PATH,
    EVALUATION_PATH,
    RESULT_PATH,
    _load_campaign,
    _variant_row,
)


class NeutralEmbodiedCommandFactorIsolationTests(unittest.TestCase):
    def test_campaign_locks_minimal_nonselecting_policy(self) -> None:
        campaign = _load_campaign(CAMPAIGN_PATH)
        scope = campaign["factor_isolation"]
        self.assertEqual(scope["expected_variants"], 12)
        self.assertEqual(scope["expected_probe_episodes"], 24)
        self.assertEqual(
            [item["changed_axis"] for item in scope["ablations"]],
            [
                "bridge_gain",
                "unresolved_event_intensity_ceiling_hz",
                "dimensionless_input_scale",
                "graded_membrane_tau_s",
            ],
        )
        self.assertEqual(campaign["policy_contract"]["pass_scope"], "exact_observed_composite_rows_only")
        self.assertFalse(campaign["acceptance"]["allow_broad_factor_rejection"])
        self.assertFalse(campaign["acceptance"]["allow_clipping"])
        self.assertEqual(campaign["behavior_targets"], [])

    def test_variant_builder_changes_one_conceptual_axis(self) -> None:
        reference = {
            "bridge_gain_index": "2",
            "bridge_gain_command_per_uN": "0.0010470505009783303",
            "numeric_profile_id": "numeric_05",
            "graded_membrane_tau_s": "0.01",
            "dimensionless_input_scale": "2.0",
            "unresolved_event_intensity_ceiling_hz": "200.0",
            "seed": "7",
        }
        numeric = {
            "numeric_03": {
                "graded_membrane_tau_s": 0.01,
                "dimensionless_input_scale": 1.0,
                "unresolved_event_intensity_ceiling_hz": 200.0,
            }
        }
        ablation = {
            "id": "input_scale_1",
            "changed_axis": "dimensionless_input_scale",
            "numeric_profile_id": "numeric_03",
            "graded_membrane_tau_s": 0.01,
            "dimensionless_input_scale": 1.0,
            "unresolved_event_intensity_ceiling_hz": 200.0,
        }
        variant, fields = _variant_row(reference, ablation, numeric)
        self.assertEqual(variant["numeric_profile_id"], "numeric_03")
        self.assertEqual(float(variant["dimensionless_input_scale"]), 1.0)
        self.assertEqual(variant["seed"], "7")
        self.assertEqual(set(fields), {"numeric_profile_id", "dimensionless_input_scale"})

    def test_committed_result_preserves_failed_generalization_without_promotion(self) -> None:
        if not RESULT_PATH.is_file() or not EVALUATION_PATH.is_file():
            self.skipTest("factor-isolation campaign has not been executed yet")
        result = yaml.safe_load(RESULT_PATH.read_text(encoding="utf-8"))
        evaluation = yaml.safe_load(EVALUATION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "failed_factor_isolation_policy_open")
        self.assertFalse(result["checks"]["every_single_factor_ablation_completed_within_limit"])
        self.assertTrue(all(
            value for key, value in result["checks"].items()
            if key != "every_single_factor_ablation_completed_within_limit"
        ))
        self.assertEqual(result["accounting"]["probe_episodes"], 24)
        self.assertEqual(result["accounting"]["completed_within_limit_probes"], 14)
        self.assertEqual(result["accounting"]["first_limit_crossing_probes"], 10)
        self.assertEqual(result["accounting"]["declared_policy_rows"], 240)
        self.assertEqual(result["accounting"]["within_contract_rows"], 237)
        self.assertEqual(result["accounting"]["blocked_exact_composite_rows"], 3)
        self.assertEqual(result["policy"]["broad_factor_domains_rejected"], [])
        self.assertEqual(result["scientific_boundary"]["selected_candidates"], 0)
        self.assertEqual(result["semantic_result_sha256"], evaluation["runner_semantic_sha256"])
        self.assertEqual(evaluation["status"], "fail")
        self.assertFalse(evaluation["stability_accepted"])
        self.assertFalse(evaluation["parameter_promoted"])

        policy_path = CAMPAIGN_PATH.parents[2] / result["policy"]["path"]
        with policy_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 240)
        blocked = [row["tuple_id"] for row in rows if row["disposition"].startswith("blocked_")]
        self.assertEqual(blocked, ["declared_tuple_029", "declared_tuple_041", "declared_tuple_149"])
        self.assertTrue(all(row["selected_or_promoted"] == "false" for row in rows))


if __name__ == "__main__":
    unittest.main()

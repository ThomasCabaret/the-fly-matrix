from __future__ import annotations

import unittest

from the_fly_matrix.front_leg_integrated_lineage import (
    CAMPAIGN_PATH,
    _lineage_manifest,
    _load_yaml,
    _verify_inputs,
    conditional_motor_member_count,
)


class FrontLegIntegratedLineageTests(unittest.TestCase):
    def test_conditional_motor_count_preserves_class_shared_candidates(self) -> None:
        result = conditional_motor_member_count(
            fast_candidates=19,
            intermediate_candidates=139,
            slow_candidates=338,
            body_count=10,
            route_count=110,
            gain_count=3,
        )
        self.assertEqual(result["ten_body_class_assignments"], 59049)
        self.assertEqual(result["assignments_per_exact_two_class_support"], 1022)
        self.assertEqual(result["assignments_using_all_three_classes"], 55980)
        self.assertGreater(result["with_route_and_gain"], result["ten_body_class_assignments"])

    def test_lineage_is_factorized_hash_locked_and_behavior_naive(self) -> None:
        campaign = _load_yaml(CAMPAIGN_PATH)
        verified = _verify_inputs(campaign)
        manifest = _lineage_manifest(campaign, verified)
        self.assertEqual(
            manifest["representation"],
            "exact_factorized_conditional_product_not_materialized",
        )
        self.assertEqual(manifest["axes"]["sensory"]["discrete_members"], 1728)
        self.assertEqual(manifest["axes"]["central_basal"]["conditioned_branches"], 162)
        self.assertEqual(manifest["axes"]["motor"]["ten_body_class_assignments"], 59049)
        self.assertEqual(manifest["member_ids_materialized"], 0)
        self.assertIsNone(manifest["selected_reference_member_id"])
        self.assertFalse(manifest["members_ranked"])
        self.assertEqual(manifest["behavior_targets_exposed"], [])
        self.assertEqual(len(manifest["semantic_sha256"]), 64)

    def test_witness_rule_does_not_depend_on_body_outcome(self) -> None:
        campaign = _load_yaml(CAMPAIGN_PATH)
        witness = campaign["execution_witness"]
        self.assertEqual(
            witness["selection_rule"],
            "lexicographically_first_compatible_address_before_execution",
        )
        self.assertFalse(witness["require_motor_spike_or_command"])
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertEqual(campaign["parameter_values_promoted"], 0)


if __name__ == "__main__":
    unittest.main()

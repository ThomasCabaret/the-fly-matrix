from __future__ import annotations

import unittest

import yaml

from the_fly_matrix.front_leg_member_conditioned_freeze_boundary import (
    CAMPAIGN_PATH,
    EVALUATION_PATH,
    PARAMETER_SET_PATH,
    RESULT_PATH,
    _compile_bundles,
    _load_campaign,
    _verify_frozen_inputs,
)


class FrontLegMemberConditionedFreezeBoundaryTests(unittest.TestCase):
    def test_campaign_forbids_optimization_behavior_and_independent_freeze(self) -> None:
        campaign = _load_campaign(CAMPAIGN_PATH)
        self.assertEqual(campaign["primary_class"], "technical")
        self.assertEqual(campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertEqual(campaign["acceptance"]["independent_family_freezes_expected"], 0)
        self.assertTrue(campaign["human_checkpoint"]["required_before_post_global_visual_tuning"])

    def test_frozen_inputs_and_exact_members_are_reconstructible(self) -> None:
        campaign = _load_campaign(CAMPAIGN_PATH)
        artifacts = _verify_frozen_inputs(campaign)
        bundles = _compile_bundles(campaign, artifacts)
        self.assertEqual(
            [item["member_id"] for item in bundles],
            ["declared_tuple_129", "declared_tuple_141", "declared_tuple_238"],
        )
        self.assertEqual(len({item["bundle_semantic_sha256"] for item in bundles}), 3)
        for bundle in bundles:
            self.assertEqual(set(bundle["factors"]), {"sensory", "central", "motor"})
            self.assertTrue(all(part["values"] for part in bundle["factors"].values()))
            self.assertTrue(
                all(
                    part["freeze_disposition"] == "member_conditioned_only_not_independently_frozen"
                    for part in bundle["factors"].values()
                )
            )

    def test_committed_outputs_keep_every_boundary_explicit(self) -> None:
        if not all(path.is_file() for path in (RESULT_PATH, EVALUATION_PATH, PARAMETER_SET_PATH)):
            self.skipTest("member-conditioned compilation has not run yet")
        result = yaml.safe_load(RESULT_PATH.read_text(encoding="utf-8"))
        evaluation = yaml.safe_load(EVALUATION_PATH.read_text(encoding="utf-8"))
        parameter_set = yaml.safe_load(PARAMETER_SET_PATH.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "completed_member_conditioned_compilation")
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result["accounting"]["compiled_bundles"], 3)
        self.assertEqual(result["accounting"]["independent_family_freezes"], 0)
        self.assertEqual(result["accounting"]["basal_families_not_exercised"], 6)
        self.assertEqual(result["semantic_result_sha256"], evaluation["runner_semantic_sha256"])
        self.assertEqual(result["semantic_result_sha256"], parameter_set["runner_semantic_sha256"])
        self.assertEqual(parameter_set["independent_family_freezes"], [])
        self.assertIsNone(parameter_set["ensemble"]["selected_reference_member_id"])
        self.assertFalse(parameter_set["applicability"]["whole_body_stability"])
        self.assertTrue(parameter_set["human_checkpoint"]["required_before_post_global_visual_tuning"])
        basal = [value for value in result["family_dispositions"].values() if value == "not_exercised_no_freeze"]
        self.assertEqual(len(basal), 6)


if __name__ == "__main__":
    unittest.main()

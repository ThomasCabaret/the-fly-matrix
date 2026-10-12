from __future__ import annotations

import unittest

import yaml

from the_fly_matrix.neutral_embodied_declared_envelope import (
    CAMPAIGN_PATH,
    EVALUATION_PATH,
    RESULT_PATH,
    SCHEDULE_PATH,
    _load_campaign,
    _pairwise_coverage,
    _profile_panel,
    compile_declared_envelope,
)


class NeutralEmbodiedDeclaredEnvelopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = compile_declared_envelope()
        cls.campaign = _load_campaign(CAMPAIGN_PATH)

    def test_campaign_is_nonselecting_and_behavior_naive(self) -> None:
        self.assertEqual(self.campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(self.campaign["behavior_targets"], [])
        self.assertFalse(self.campaign["topology_changes_allowed"])
        self.assertEqual(self.campaign["capacity_policy"]["optimized_parameters"], 0)
        self.assertEqual(self.campaign["capacity_policy"]["selected_candidates"], 0)
        self.assertFalse(
            self.campaign["schedule_policy"]["candidate_selection_from_body_motion"]
        )

    def test_ternary_panel_is_balanced_and_pairwise_complete(self) -> None:
        ids = [f"group-{index}" for index in range(17)]
        profiles, directions = _profile_panel(ids, base=3, dimension=4)
        self.assertEqual(len(profiles), 81)
        self.assertEqual(len(directions), 17)
        for object_id in ids:
            counts = {level: sum(p[object_id] == level for p in profiles) for level in range(3)}
            self.assertEqual(counts, {0: 27, 1: 27, 2: 27})
        coverage = _pairwise_coverage(profiles, ids, 3)
        self.assertEqual(coverage["pairs_missing_a_state"], 0)
        self.assertEqual(coverage["minimum_state_repetitions"], 9)
        self.assertEqual(coverage["maximum_state_repetitions"], 9)

    def test_binary_sign_panel_is_balanced_and_pairwise_complete(self) -> None:
        ids = [f"body-{index}" for index in range(32)]
        profiles, directions = _profile_panel(ids, base=2, dimension=6)
        self.assertEqual(len(profiles), 64)
        self.assertEqual(len(directions), 32)
        for object_id in ids:
            counts = {level: sum(p[object_id] == level for p in profiles) for level in range(2)}
            self.assertEqual(counts, {0: 32, 1: 32})
        coverage = _pairwise_coverage(profiles, ids, 2)
        self.assertEqual(coverage["pairs_missing_a_state"], 0)
        self.assertEqual(coverage["minimum_state_repetitions"], 16)
        self.assertEqual(coverage["maximum_state_repetitions"], 16)

    def test_compiled_schedule_covers_every_declared_axis_without_defaults(self) -> None:
        coverage = self.result["coverage"]
        self.assertEqual(coverage["schedule_tuples"], 240)
        self.assertEqual(coverage["base_schedule"]["unique"], 120)
        self.assertEqual(coverage["base_schedule"]["minimum_repetitions"], 2)
        self.assertEqual(coverage["feco_routing_profiles"]["unique"], 81)
        self.assertEqual(coverage["unknown_sign_profiles"]["unique"], 64)
        self.assertEqual(coverage["numeric_profiles"]["unique"], 12)
        self.assertEqual(coverage["intermediate_profiles"]["unique"], 50)
        self.assertEqual(coverage["feco_alternatives"]["unique"], 24)
        self.assertEqual(coverage["motor_assignments"]["unique"], 120)
        self.assertEqual(coverage["route_basis_edges"]["unique"], 110)
        self.assertEqual(coverage["bridge_gains"]["unique"], 3)
        self.assertTrue(self.result["checks"]["no_round_robin_field"])
        self.assertTrue(self.result["checks"]["no_fixed_unknown_sign_field"])

    def test_registered_result_is_schedule_only_and_hash_linked(self) -> None:
        runner = yaml.safe_load(RESULT_PATH.read_text(encoding="utf-8"))
        evaluation = yaml.safe_load(EVALUATION_PATH.read_text(encoding="utf-8"))
        self.assertTrue(SCHEDULE_PATH.exists())
        self.assertEqual(
            runner["status"], "pass_declared_envelope_schedule_no_fit_no_execution"
        )
        self.assertEqual(runner["scientific_boundary"]["optimized_parameters"], 0)
        self.assertEqual(runner["scientific_boundary"]["selected_candidates"], 0)
        self.assertEqual(runner["scientific_boundary"]["physical_episodes"], 0)
        self.assertFalse(runner["scientific_boundary"]["stability_evaluated"])
        self.assertEqual(
            runner["semantic_result_sha256"],
            evaluation["reproducibility"]["runner_semantic_sha256"],
        )
        self.assertEqual(
            evaluation["acceptance_result"],
            "pass_schedule_contract_execution_not_started",
        )


if __name__ == "__main__":
    unittest.main()

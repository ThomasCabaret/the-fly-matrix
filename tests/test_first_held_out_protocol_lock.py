from __future__ import annotations

import math
import unittest

import yaml

from the_fly_matrix.first_held_out_protocol_lock import (
    CAMPAIGN_PATH,
    EVALUATION_PATH,
    RESULT_PATH,
    ProtocolLockError,
    _load_yaml,
    _sign_test_tail,
    compile_lock,
)


class FirstHeldOutProtocolLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.campaign = _load_yaml(CAMPAIGN_PATH)

    def test_compilation_is_outcome_blind_complete_and_reproducible(self) -> None:
        first = compile_lock(self.campaign)
        second = compile_lock(self.campaign)
        self.assertEqual(first["semantic_result_sha256"], second["semantic_result_sha256"])
        self.assertEqual(first["checks"]["held_out_outcomes_consumed"], 0)
        self.assertTrue(first["checks"]["all_11_members_exact_and_unranked"])
        self.assertIsNone(first["checks"]["selected_reference_member_id"])
        self.assertEqual(first["schedule"]["canonical_episodes"], 352)
        self.assertEqual(first["schedule"]["topology_control_episodes"], 2816)
        self.assertEqual(first["schedule"]["total_episodes"], 3168)

    def test_locked_sign_threshold_is_exact_and_prefixed(self) -> None:
        self.assertTrue(math.isclose(_sign_test_tail(7, 8), 0.03515625, abs_tol=1e-15))
        result = compile_lock(self.campaign)
        self.assertEqual(result["minimum_directionally_consistent_pairs"], 7)
        self.assertEqual(result["exact_one_sided_sign_test_p_at_threshold"], 0.03515625)

    def test_both_topology_control_families_are_mandatory(self) -> None:
        changed = yaml.safe_load(yaml.safe_dump(self.campaign))
        protocol_path = CAMPAIGN_PATH.parents[2] / changed["frozen_inputs"]["protocol"]["path"]
        protocol = _load_yaml(protocol_path)
        self.assertEqual(
            set(protocol["topology_controls"]["variants_per_seed"]),
            {"frozen_parameter_rewire", "same_recipe_recalibrated_rewire"},
        )
        self.assertTrue(protocol["topology_controls"]["recipe"]["no_fallback"])

    def test_protocol_has_no_magnitude_fit_or_outcome_payload(self) -> None:
        protocol_path = CAMPAIGN_PATH.parents[2] / self.campaign["frozen_inputs"]["protocol"]["path"]
        protocol = _load_yaml(protocol_path)
        self.assertEqual(protocol["execution_gate"]["outcome_rows_present"], 0)
        self.assertIsNone(protocol["measurements"]["primary_neural"]["magnitude_threshold"])
        self.assertIsNone(protocol["measurements"]["secondary_physical"]["magnitude_threshold"])
        self.assertFalse(protocol["lock_assertions"]["simulated_held_out_outcomes_inspected"])
        self.assertFalse(protocol["lock_assertions"]["behavior_used_for_parameter_or_member_selection"])

    def test_committed_outputs_match_compiler(self) -> None:
        compiled = compile_lock(self.campaign)
        committed = _load_yaml(RESULT_PATH)
        evaluation = _load_yaml(EVALUATION_PATH)
        self.assertEqual(committed["semantic_result_sha256"], compiled["semantic_result_sha256"])
        self.assertEqual(evaluation["semantic_result_sha256"], compiled["semantic_result_sha256"])
        self.assertTrue(evaluation["protocol_locked"])
        self.assertFalse(evaluation["protocol_executed"])

    def test_member_or_outcome_selection_would_fail(self) -> None:
        changed = yaml.safe_load(yaml.safe_dump(self.campaign))
        changed["frozen_inputs"]["protocol"]["sha256"] = "0" * 64
        with self.assertRaises(ProtocolLockError):
            compile_lock(changed)

    def test_v1_supersedes_unexecuted_v0_and_locks_exact_timebase(self) -> None:
        root = CAMPAIGN_PATH.parents[2]
        campaign = _load_yaml(
            root / "calibration/campaigns/first-held-out-protocol-lock-v1.yaml"
        )
        result = compile_lock(campaign)
        protocol = _load_yaml(root / campaign["frozen_inputs"]["protocol"]["path"])
        self.assertEqual(protocol["supersession"]["predecessor_outcome_rows"], 0)
        self.assertFalse(protocol["supersession"]["predecessor_executed"])
        self.assertEqual(protocol["stimulus"]["ramp_physics_steps"], 650)
        self.assertEqual(protocol["stimulus"]["total_physics_steps"], 3650)
        self.assertTrue(result["checks"]["frozen_timebase_representability_checked"])
        self.assertTrue(result["timebase_contract"]["all_required_durations_representable"])
        self.assertEqual(result["schedule"]["total_episodes"], 3168)
        self.assertEqual(result["checks"]["held_out_outcomes_consumed"], 0)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

import yaml

from the_fly_matrix.neutral_embodied_full_chain_panel import (
    CAMPAIGN_PATH,
    EVALUATION_PATH,
    RESULT_PATH,
    _load_campaign,
    compile_full_chain_panel,
)


class NeutralEmbodiedFullChainPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        (
            cls.campaign,
            cls.full_chain_campaign,
            cls.compiled,
            cls.context,
        ) = compile_full_chain_panel()

    def test_campaign_is_zero_fit_nonselecting_and_hash_frozen(self) -> None:
        campaign, full_chain, schedule_result = _load_campaign(CAMPAIGN_PATH)
        self.assertEqual(campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertFalse(
            campaign["schedule_contract"]["candidate_selection_from_body_motion"]
        )
        self.assertFalse(
            campaign["acceptance"]["allow_physical_magnitude_to_select_candidate"]
        )
        self.assertEqual(campaign["scientific_boundary"]["optimized_parameters"], 0)
        self.assertEqual(
            campaign["scientific_boundary"]["promoted_parameter_values"], 0
        )
        self.assertEqual(
            full_chain["id"], "campaign.neutral_embodied_full_chain_sentinel.v0"
        )
        self.assertEqual(
            schedule_result["semantic_result_sha256"],
            campaign["frozen_inputs"]["schedule_result_semantic_sha256"],
        )

    def test_all_120_tuples_compile_and_cover_every_declared_axis(self) -> None:
        self.assertEqual(len(self.compiled), 120)
        coverage = self.context["coverage"]
        self.assertEqual(coverage["scheduled_tuples"], 120)
        self.assertEqual(coverage["intermediate_profiles"]["unique"], 50)
        self.assertEqual(coverage["feco_alternatives"]["unique"], 24)
        self.assertEqual(coverage["motor_assignments"]["unique"], 120)
        self.assertEqual(coverage["route_basis_edges"]["unique"], 110)
        self.assertEqual(coverage["bridge_gains"]["unique"], 3)
        self.assertEqual(coverage["bridge_gains"]["counts"], {"0": 40, "1": 40, "2": 40})

    def test_every_compiled_tuple_executes_each_local_boundary(self) -> None:
        representations = set()
        for item in self.compiled:
            trace = item["local_chain"]
            representations.add(trace["feco_representation"])
            self.assertGreater(trace["feco_nonzero_drive_samples"], 0)
            self.assertEqual(
                trace["intermediate_event_candidates"]
                + trace["intermediate_graded_candidates"],
                150,
            )
            self.assertGreater(trace["intermediate_nonzero_state_samples"], 0)
            self.assertGreater(trace["motor_spike_count_all_bodies"], 0)
            self.assertIn(
                item["route"]["active_actuator_ids"],
                ([], [item["route"]["target_actuator_id"]]),
            )
            self.assertTrue(item["non_scoped_actuators_zero"])
            self.assertEqual(item["command_trace"].shape, (40, 102))
        self.assertEqual(representations, {"graded_candidate", "event_candidate"})

    def test_registered_result_is_exhaustive_and_claim_bounded(self) -> None:
        runner = yaml.safe_load(RESULT_PATH.read_text(encoding="utf-8"))
        evaluation = yaml.safe_load(EVALUATION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            runner["status"], "pass_full_local_chain_panel_execution_no_calibration"
        )
        self.assertEqual(runner["accounting"]["scheduled_tuples"], 120)
        self.assertEqual(runner["accounting"]["outcome_counts"]["completed_contract"], 120)
        self.assertTrue(runner["accounting"]["all_tuples_accounted"])
        self.assertEqual(len(runner["tuple_accounting"]), 120)
        self.assertFalse(runner["robustness"]["body_motion_used_for_selection"])
        self.assertEqual(runner["execution_boundary"]["promoted_parameter_values"], 0)
        self.assertFalse(runner["execution_boundary"]["stability_evaluated"])
        self.assertEqual(
            runner["semantic_result_sha256"], evaluation["runner_semantic_sha256"]
        )
        self.assertFalse(evaluation["stability_accepted"])


if __name__ == "__main__":
    unittest.main()

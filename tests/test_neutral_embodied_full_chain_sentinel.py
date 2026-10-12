from __future__ import annotations

import unittest

import numpy as np
import yaml

from the_fly_matrix.neutral_embodied_full_chain_sentinel import (
    EVALUATION_PATH,
    RESULT_PATH,
    _delay,
    _load_campaign,
    _mixed_population,
    compile_full_chain_sentinel,
)


class NeutralEmbodiedFullChainSentinelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.campaign, cls.compiled, cls.context = compile_full_chain_sentinel()

    def test_campaign_is_diagnostic_zero_fit_and_behavior_naive(self) -> None:
        self.assertEqual(self.campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(self.campaign["behavior_targets"], [])
        self.assertFalse(self.campaign["topology_changes_allowed"])
        self.assertFalse(
            self.campaign["sentinel_selection"]["selected_from_body_motion"]
        )
        self.assertEqual(
            self.campaign["scientific_boundary"]["promoted_parameter_values"], 0
        )
        self.assertFalse(
            self.campaign["acceptance"]["allow_physical_magnitude_to_select_candidate"]
        )

    def test_fixed_delay_is_exact_and_causal(self) -> None:
        values = np.arange(12, dtype=np.float64).reshape(6, 2)
        delayed = _delay(values, 2)
        np.testing.assert_array_equal(delayed[:2], np.zeros((2, 2)))
        np.testing.assert_array_equal(delayed[2:], values[:-2])

    def test_mixed_population_preserves_distinct_event_and_graded_semantics(self) -> None:
        drive = np.ones((200, 2), dtype=np.float64)
        output, spikes = _mixed_population(
            drive,
            np.asarray([True, False]),
            timestep_s=0.001,
            membrane_tau_s=0.01,
            synaptic_tau_s=0.005,
            refractory_s=0.005,
            threshold=1.0,
            input_gain=3.0,
        )
        self.assertGreater(int(spikes[:, 0].sum()), 0)
        self.assertEqual(int(spikes[:, 1].sum()), 0)
        self.assertGreater(float(output[:, 0].max()), 0.0)
        self.assertGreater(float(output[:, 1].max()), 0.0)

    def test_all_four_tuples_execute_every_local_axis(self) -> None:
        self.assertEqual(self.context["scheduled_tuple_count"], 120)
        self.assertEqual(len(self.compiled), 4)
        self.assertEqual(
            {item["local_chain"]["feco_representation"] for item in self.compiled},
            {"event_candidate", "graded_candidate"},
        )
        for item in self.compiled:
            trace = item["local_chain"]
            self.assertEqual(sum(trace["feco_projection_class_counts"].values()), 36)
            self.assertEqual(set(trace["feco_projection_class_counts"].values()), {12})
            self.assertGreater(trace["feco_nonzero_drive_samples"], 0)
            self.assertEqual(
                trace["intermediate_event_candidates"]
                + trace["intermediate_graded_candidates"],
                150,
            )
            self.assertGreater(trace["intermediate_nonzero_state_samples"], 0)
            self.assertGreater(trace["motor_spike_count_all_bodies"], 0)
            self.assertGreater(trace["route_motor_event_count"], 0)
            self.assertEqual(
                item["route"]["active_actuator_ids"],
                [item["route"]["target_actuator_id"]],
            )
            self.assertEqual(item["command_trace"].shape, (40, 102))

    def test_profiles_change_the_executed_neural_trace(self) -> None:
        hashes = {
            item["local_chain"]["neural_trace_sha256"] for item in self.compiled
        }
        self.assertEqual(len(hashes), len(self.compiled))

    def test_registered_pass_is_hash_linked_and_claim_bounded(self) -> None:
        runner = yaml.safe_load(RESULT_PATH.read_text(encoding="utf-8"))
        evaluation = yaml.safe_load(EVALUATION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            runner["status"], "pass_full_local_chain_execution_sentinel_no_calibration"
        )
        self.assertEqual(runner["accounting"]["completed_tuples"], 4)
        self.assertTrue(runner["accounting"]["all_axes_active"])
        self.assertEqual(runner["execution_boundary"]["promoted_parameter_values"], 0)
        self.assertFalse(runner["execution_boundary"]["stability_evaluated"])
        self.assertEqual(
            runner["semantic_result_sha256"],
            evaluation["runner_semantic_sha256"],
        )
        self.assertFalse(evaluation["stability_accepted"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import unittest

from the_fly_matrix.neutral_embodied_adapter_sentinel import (
    CAMPAIGN_PATH,
    NeutralAdapterSentinelError,
    _load_campaign,
    _read_schedule,
    compile_sentinel,
)


class NeutralEmbodiedAdapterSentinelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.campaign, cls.compiled, cls.context = compile_sentinel()

    def test_campaign_is_fixed_zero_fit_and_behavior_naive(self) -> None:
        self.assertEqual(self.campaign["behavior_targets"], [])
        self.assertEqual(self.campaign["scientific_boundary"]["optimized_parameters"], 0)
        self.assertEqual(
            self.campaign["scientific_boundary"]["promoted_parameter_values"], 0
        )
        self.assertFalse(
            self.campaign["sentinel_selection"]["selected_from_body_motion"]
        )
        self.assertEqual(
            self.campaign["sentinel_selection"]["tuple_ids"],
            [
                "neutral_tuple_000",
                "neutral_tuple_001",
                "neutral_tuple_002",
                "neutral_tuple_119",
            ],
        )

    def test_frozen_schedule_and_every_sentinel_tuple_are_accounted(self) -> None:
        self.assertEqual(self.context["scheduled_tuple_count"], 120)
        self.assertEqual(len(self.compiled), 4)
        self.assertEqual(len({item["tuple_id"] for item in self.compiled}), 4)
        self.assertEqual(
            self.context["schedule_result"]["semantic_result_sha256"],
            self.campaign["frozen_inputs"]["schedule_result_semantic_sha256"],
        )

    def test_compiler_exercises_motor_axes_without_command_leakage(self) -> None:
        self.assertEqual(
            {item["route"]["bridge_gain_index"] for item in self.compiled},
            {0, 1, 2},
        )
        self.assertEqual(
            {item["motor"]["route_body_class"] for item in self.compiled},
            {"fast_81A07", "intermediate_22A08"},
        )
        for item in self.compiled:
            target = item["route"]["target_actuator_id"]
            self.assertEqual(item["command_trace"].shape, (40, 102))
            self.assertEqual(
                item["command_contract"]["active_actuator_ids"], [target]
            )
            self.assertTrue(item["command_contract"]["non_scoped_actuators_zero"])
            self.assertGreater(item["command_contract"]["peak_abs_command"], 0.0)
            self.assertLessEqual(item["command_contract"]["peak_abs_command"], 0.01)

    def test_nonexecuted_axes_are_explicit_not_silently_defaulted(self) -> None:
        for item in self.compiled:
            self.assertEqual(item["intermediate_profile"]["assignments"], 148)
            self.assertFalse(item["intermediate_profile"]["applied_to_cns"])
            self.assertFalse(item["feco"]["transduction_executed"])
            self.assertFalse(item["full_sensor_cns_motor_chain_executed"])

    def test_schedule_hash_drift_fails_closed(self) -> None:
        campaign = copy.deepcopy(_load_campaign(CAMPAIGN_PATH))
        campaign["frozen_inputs"]["schedule_sha256"] = "0" * 64
        with self.assertRaisesRegex(NeutralAdapterSentinelError, "schedule file drift"):
            _read_schedule(campaign)


if __name__ == "__main__":
    unittest.main()

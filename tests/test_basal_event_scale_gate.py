from __future__ import annotations

import unittest
from copy import deepcopy

import yaml

from the_fly_matrix.basal_event_scale_gate import (
    CAMPAIGN_PATH,
    BasalEventScaleGateError,
    _verify_frozen_inputs,
    compile_members,
)


class BasalEventScaleGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.campaign = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="utf-8"))

    def test_grid_is_complete_unique_and_fixed(self) -> None:
        members = compile_members(self.campaign)
        self.assertEqual(len(members), 13)
        self.assertEqual(len({row["member_id"] for row in members}), 13)
        self.assertEqual({row["uniform_rate_hz"] for row in members[1:]}, {20.0, 80.0, 320.0})
        self.assertEqual({row["event_to_event_mV"] for row in members[1:]}, {0.05, 0.2, 0.8, 3.2})

    def test_event_draws_are_paired_across_scales(self) -> None:
        members = compile_members(self.campaign)[1:]
        for rate in (20.0, 80.0, 320.0):
            seeds = {row["seed"] for row in members if row["uniform_rate_hz"] == rate}
            self.assertEqual(len(seeds), 1)

    def test_campaign_is_behavior_naive_and_non_promoting(self) -> None:
        self.assertEqual(self.campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(self.campaign["behavior_targets"], [])
        self.assertFalse(self.campaign["topology_changes_allowed"])
        self.assertEqual(self.campaign["parameter_values_promoted"], 0)
        self.assertFalse(self.campaign["technical_grid"]["members_may_be_ranked"])
        self.assertFalse(self.campaign["technical_grid"]["post_hoc_extension_allowed"])

    def test_frozen_inputs_are_current(self) -> None:
        paths = _verify_frozen_inputs(self.campaign)
        self.assertIn("incoming_graph", paths)
        self.assertIn("source_terminals", paths)

    def test_behavior_exposure_is_rejected(self) -> None:
        changed = deepcopy(self.campaign)
        changed["behavior_targets"] = ["forbidden"]
        with self.assertRaises(BasalEventScaleGateError):
            _verify_frozen_inputs(changed)


if __name__ == "__main__":
    unittest.main()

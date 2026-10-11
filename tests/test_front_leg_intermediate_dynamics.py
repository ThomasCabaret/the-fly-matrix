from __future__ import annotations

import unittest

import pandas as pd
import yaml

from the_fly_matrix.front_leg_intermediate_dynamics import (
    CAMPAIGN_PATH,
    IntermediateDynamicsError,
    classify_intermediates,
)


def _rules() -> dict:
    return {
        "rules": [
            {
                "id": "event",
                "priority": 20,
                "selector": {"all": [{"field": "type", "op": "equals", "value": "ext"}]},
                "assignment": "event_required",
                "assignment_confidence": "test",
                "evidence_ids": ["source"],
                "expected_count": 1,
                "rationale": "fixture",
            },
            {
                "id": "typed_unresolved",
                "priority": 10,
                "selector": {"all": [{"field": "type", "op": "not_missing"}]},
                "assignment": "dual_unresolved",
                "assignment_confidence": "test",
                "evidence_ids": ["source"],
                "expected_count": 1,
                "rationale": "fixture",
            },
            {
                "id": "missing_unresolved",
                "priority": 5,
                "selector": {"all": [{"field": "type", "op": "is_missing"}]},
                "assignment": "dual_unresolved",
                "assignment_confidence": "test",
                "evidence_ids": ["source"],
                "expected_count": 1,
                "rationale": "fixture",
            },
        ]
    }


def _fixtures() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    inventory = pd.DataFrame(
        [
            {"body_id": 1, "superclass": "vnc_motor", "subclass": "fl", "type": "ext", "somaSide": "L", "chain_assignment": "dual_unresolved", "parameter_values_emitted": False},
            {"body_id": 2, "superclass": "vnc_intrinsic", "subclass": "IR", "type": "inter", "somaSide": "L", "chain_assignment": "dual_unresolved", "parameter_values_emitted": False},
            {"body_id": 3, "superclass": "vnc_intrinsic", "subclass": None, "type": None, "somaSide": None, "chain_assignment": "dual_unresolved", "parameter_values_emitted": False},
        ]
    )
    paths = pd.DataFrame(
        [
            {"source_body_id": 10, "intermediate_body_id": 1, "target_body_id": 20, "first_edge_weight": 2, "second_edge_weight": 3},
            {"source_body_id": 10, "intermediate_body_id": 2, "target_body_id": 20, "first_edge_weight": 4, "second_edge_weight": 5},
            {"source_body_id": 11, "intermediate_body_id": 3, "target_body_id": 20, "first_edge_weight": 6, "second_edge_weight": 7},
        ]
    )
    prior = pd.DataFrame(
        [
            {"body_id": body_id, "effective_transmitter": "acetylcholine", "sign_code": 1, "sign_interpretation": "typed"}
            for body_id in (1, 2, 3)
        ]
    )
    return inventory, paths, prior


class FrontLegIntermediateDynamicsTests(unittest.TestCase):
    def test_highest_priority_rule_promotes_only_supported_event_requirement(self) -> None:
        classified, summary, exceptions = classify_intermediates(*_fixtures(), _rules())
        assignments = classified.set_index("body_id")["assignment"].to_dict()
        self.assertEqual(assignments, {1: "event_required", 2: "dual_unresolved", 3: "dual_unresolved"})
        self.assertEqual(summary["assignment_counts"], {"dual_unresolved": 2, "event_required": 1})
        self.assertEqual(summary["parameter_values_emitted"], 0)
        self.assertEqual(exceptions[1]["body_ids"], [3])

    def test_transmitter_label_never_selects_native_dynamics(self) -> None:
        classified, _summary, _exceptions = classify_intermediates(*_fixtures(), _rules())
        unresolved = classified.loc[classified["body_id"].eq(2)].iloc[0]
        self.assertEqual(unresolved["effective_transmitter"], "acetylcholine")
        self.assertEqual(unresolved["assignment"], "dual_unresolved")

    def test_missing_path_or_prior_is_a_hard_error(self) -> None:
        inventory, paths, prior = _fixtures()
        with self.assertRaises(IntermediateDynamicsError):
            classify_intermediates(inventory, paths.loc[paths["intermediate_body_id"].ne(3)], prior, _rules())
        with self.assertRaises(IntermediateDynamicsError):
            classify_intermediates(inventory, paths, prior.loc[prior["body_id"].ne(3)], _rules())

    def test_campaign_forbids_topology_behavior_and_values(self) -> None:
        campaign = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertEqual(campaign["assignment_policy"]["parameter_values_emitted"], 0)
        self.assertFalse(campaign["priority_report"]["inspect_body_trajectory"])
        self.assertFalse(campaign["priority_report"]["selection_allowed"])


if __name__ == "__main__":
    unittest.main()

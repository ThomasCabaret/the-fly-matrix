from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from the_fly_matrix.ledger import ROOT
from the_fly_matrix.wiring_revalidation import apply_rules, matches, validate_ruleset


class WiringRevalidationRuleTests(unittest.TestCase):
    def test_nested_selectors(self) -> None:
        record = {"entryNerve": "MetaLN", "rootSide": "L", "subclass": "leg"}
        selector = {
            "all": [
                {"field": "entryNerve", "op": "in", "value": ["MesoLN", "MetaLN"]},
                {"field": "rootSide", "op": "equals", "value": "L"},
                {"not": {"field": "subclass", "op": "equals", "value": "notum"}},
            ]
        }
        self.assertTrue(matches(record, selector))

    def test_priority_resolves_compatible_overlap(self) -> None:
        rules = [
            {
                "id": "general",
                "priority": 10,
                "selector": {"field": "subclass", "op": "in", "value": ["rm", "xm"]},
                "outcome": "applied",
                "relation_class": "exact",
                "terminal_disposition": "sink",
            },
            {
                "id": "specific",
                "priority": 20,
                "selector": {"field": "type", "op": "equals", "value": "PS349"},
                "outcome": "applied",
                "relation_class": "source_supported_candidate",
                "terminal_disposition": "parameterized",
            },
        ]
        selected, matched, error = apply_rules({"subclass": "rm", "type": "PS349"}, rules)
        self.assertIsNone(error)
        self.assertEqual(selected["id"], "specific")
        self.assertEqual(set(matched), {"general", "specific"})

    def test_equal_priority_conflict_is_exception(self) -> None:
        rules = [
            {
                "id": "a",
                "priority": 10,
                "selector": {"field": "class", "op": "equals", "value": "visual"},
                "outcome": "applied",
                "relation_class": "exact",
                "terminal_disposition": "parameterized",
            },
            {
                "id": "b",
                "priority": 10,
                "selector": {"field": "class", "op": "equals", "value": "visual"},
                "outcome": "applied",
                "relation_class": "proxy",
                "terminal_disposition": "proxy",
            },
        ]
        selected, matched, error = apply_rules({"class": "visual"}, rules)
        self.assertIsNone(selected)
        self.assertEqual(set(matched), {"a", "b"})
        self.assertEqual(error, "conflicting_top_priority_rules")

    def test_versioned_ruleset_declares_both_directions(self) -> None:
        path = Path(ROOT) / "wiring" / "revalidation" / "rules-v1.yaml"
        ruleset = yaml.safe_load(path.read_text(encoding="utf-8"))
        directions = {item["direction"] for item in ruleset["workstreams"].values()}
        self.assertEqual(directions, {"input", "output"})
        self.assertEqual(
            set(ruleset["workstreams"]),
            {"vision", "proprioception", "mechanosensation", "motor_output"},
        )
        validate_ruleset(ruleset)


if __name__ == "__main__":
    unittest.main()

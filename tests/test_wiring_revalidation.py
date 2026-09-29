from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

import yaml

from the_fly_matrix.ledger import ROOT
from the_fly_matrix.mechanosensation_revalidation import (
    build_mechanosensation_envelope,
    compare_mechanosensation_with_prewiring,
)
from the_fly_matrix.proprioception_revalidation import (
    build_proprioception_envelope,
    compare_proprioception_with_prewiring,
)
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

    def test_mechanosensation_clean_build_matches_frozen_prewiring(self) -> None:
        with TemporaryDirectory(prefix="flymatrix-test-mechanosensation-") as temporary:
            output = Path(temporary) / "clean-build"
            built = build_mechanosensation_envelope(output)
            self.assertEqual(built["terminal_count"], 4_291)
            self.assertEqual(built["group_count"], 323)
            self.assertEqual(built["candidate_edge_count"], 2_108)
            self.assertEqual(built["expanded_terminal_observable_relations"], 28_514)
            self.assertEqual(
                built["semantic_topology_sha256"],
                "70e71d9a5c36edcc8ce5f01e367c7a5349f8d1942ea3b1a72e0e0a9868cc9fd2",
            )
            compared = compare_mechanosensation_with_prewiring(output)
            self.assertTrue(compared["clean_rebuild_repeat"]["pass"])
            self.assertTrue(compared["prewiring_comparison"]["pass"])
            self.assertTrue(compared["topology_independently_validated"])

    def test_proprioception_clean_build_matches_frozen_prewiring(self) -> None:
        with TemporaryDirectory(prefix="flymatrix-test-proprioception-") as temporary:
            output = Path(temporary) / "clean-build"
            built = build_proprioception_envelope(output)
            self.assertEqual(built["terminal_count"], 1_454)
            self.assertEqual(built["group_count"], 262)
            self.assertEqual(built["candidate_edge_count"], 1_992)
            self.assertEqual(built["expanded_terminal_observable_relations"], 10_518)
            self.assertEqual(built["disposition_counts"], {"proxy": 91, "parameterized": 171})
            self.assertEqual(
                built["semantic_topology_sha256"],
                "782b98d147b5ecd15861dca0241d7fabf2995b1b9b6ef5b9c50d8e94ea5dd665",
            )
            compared = compare_proprioception_with_prewiring(output)
            self.assertTrue(compared["clean_rebuild_repeat"]["pass"])
            self.assertTrue(compared["prewiring_comparison"]["pass"])
            self.assertTrue(compared["topology_independently_validated"])


if __name__ == "__main__":
    unittest.main()

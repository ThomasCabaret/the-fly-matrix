from __future__ import annotations

import json
import unittest
from pathlib import Path

from the_fly_matrix.ledger import build_summary, load_ledger, validate_ledger


class LedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = load_ledger()

    def test_all_references_and_statuses_are_valid(self) -> None:
        checks = validate_ledger(self.ledger)
        self.assertEqual(len(checks), 5)

    def test_top_level_interface_is_exhaustively_represented(self) -> None:
        self.assertEqual(len(self.ledger["boxes"]), 18)
        self.assertEqual(len(self.ledger["groups"]), 15)
        self.assertEqual(len(self.ledger["wires"]), 21)
        adapter_types = {
            box.get("adapter_type") for box in self.ledger["boxes"] if box.get("adapter_type")
        }
        self.assertEqual(adapter_types, set("ABCDEF"))

    def test_every_box_has_a_next_action_and_completion_criteria(self) -> None:
        for box in self.ledger["boxes"]:
            self.assertTrue(box.get("next_action"), box["id"])
            self.assertTrue(box.get("completion_criteria"), box["id"])

    def test_summary_has_bounded_progress_for_every_sector(self) -> None:
        summary = build_summary(self.ledger)
        self.assertGreater(len(summary["sectors"]), 1)
        self.assertGreaterEqual(summary["overall_progress"], 0)
        self.assertLessEqual(summary["overall_progress"], 100)
        self.assertGreaterEqual(summary["wiring_progress"], 0)
        self.assertLessEqual(summary["wiring_progress"], 100)
        self.assertEqual(
            set(summary["wiring_components"]),
            {
                "box_inventory",
                "box_execution",
                "group_decomposition",
                "group_routing",
                "wire_inventory",
                "wire_routing",
                "wire_execution",
            },
        )
        for sector in summary["sectors"]:
            self.assertGreaterEqual(sector["progress"], 0)
            self.assertLessEqual(sector["progress"], 100)
            self.assertGreaterEqual(sector["wiring_progress"], 0)
            self.assertLessEqual(sector["wiring_progress"], 100)

    def test_basal_clamp_wiring_is_exact_when_generated(self) -> None:
        path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "derived"
            / "wiring"
            / "basal-clamp-routing.json"
        )
        if not path.is_file():
            self.skipTest("derived basal clamp wiring is absent")
        wiring = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(wiring["totals"]["modalities"], 3)
        self.assertEqual(wiring["totals"]["generated_box_instances"], 147 + 166 + 16)
        self.assertEqual(wiring["totals"]["exact_routes"], 2639 + 1428 + 91)
        self.assertEqual(wiring["totals"]["duplicate_routes"], 0)
        self.assertEqual(wiring["totals"]["unassigned_neurons"], 0)
        self.assertTrue(all(item["coverage_percent"] == 100 for item in wiring["modalities"]))

    def test_group_counts_match_local_inventory_when_available(self) -> None:
        path = Path(__file__).resolve().parents[1] / "data" / "derived" / "inventory" / "inventory.json"
        if not path.is_file():
            self.skipTest("local derived inventory is absent")
        inventory = json.loads(path.read_text(encoding="utf-8"))
        audited = {f"group.{item['id']}": item for item in inventory["interface_groups"]}
        for group in self.ledger["groups"]:
            self.assertIn(group["id"], audited)
            self.assertEqual(group["member_count"], audited[group["id"]]["neurons"])
            self.assertEqual(group["named_type_count"], audited[group["id"]]["named_types"])

    def test_interface_validation_owns_every_top_level_group(self) -> None:
        validation = next(
            item
            for item in self.ledger["validations"]
            if item["id"] == "validation.interface_group_inventory"
        )
        self.assertEqual(
            set(validation["owner_ids"]),
            {group["id"] for group in self.ledger["groups"]},
        )


if __name__ == "__main__":
    unittest.main()

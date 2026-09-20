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
        self.assertEqual(len(self.ledger["boxes"]), 19)
        self.assertEqual(len(self.ledger["groups"]), 17)
        self.assertEqual(len(self.ledger["wires"]), 22)
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

        proprio_path = path.with_name("proprioception-routing.json")
        self.assertTrue(proprio_path.is_file())
        proprio = json.loads(proprio_path.read_text(encoding="utf-8"))
        self.assertEqual(proprio["generated_box_instances"], 262)
        self.assertEqual(proprio["exact_routes"], 1454)
        self.assertEqual(proprio["duplicate_routes"], 0)
        self.assertEqual(proprio["unassigned_neurons"], 0)

        physical_proprio_path = path.with_name("flybody-proprioception.json")
        self.assertTrue(physical_proprio_path.is_file())
        physical_proprio = json.loads(physical_proprio_path.read_text(encoding="utf-8"))
        self.assertEqual(physical_proprio["joint_channels"], 102)
        self.assertEqual(physical_proprio["scalar_observables"], 204)
        self.assertEqual(physical_proprio["qpos_addressing"], "exact")
        self.assertEqual(physical_proprio["qvel_addressing"], "exact")
        self.assertEqual(physical_proprio["biological_receptor_mapping"], "deferred")

        physical_touch_path = path.with_name("flybody-touch.json")
        self.assertTrue(physical_touch_path.is_file())
        physical_touch = json.loads(physical_touch_path.read_text(encoding="utf-8"))
        self.assertEqual(physical_touch["collision_enabled_segments"], 57)
        self.assertEqual(physical_touch["explicit_ground_contact_pairs"], 69)
        self.assertEqual(physical_touch["aggregate_leg_channels"], 6)
        self.assertEqual(physical_touch["scalar_observables"], 96)
        self.assertEqual(physical_touch["non_leg_local_load_mapping"], "deferred")
        self.assertEqual(physical_touch["biological_receptor_mapping"], "deferred")

        mechano_path = path.with_name("mechanosensation-routing.json")
        self.assertTrue(mechano_path.is_file())
        mechano = json.loads(mechano_path.read_text(encoding="utf-8"))
        self.assertEqual(mechano["generated_box_instances"], 323)
        self.assertEqual(mechano["exact_routes"], 2558 + 1733)
        self.assertEqual(mechano["duplicate_routes"], 0)
        self.assertEqual(mechano["unassigned_neurons"], 0)
        self.assertEqual(
            {item["group_id"]: item["terminal_channels"] for item in mechano["groups"]},
            {"sensory.tactile": 213, "sensory.mechanosensory_other": 110},
        )

        vision_path = path.with_name("vision-routing.json")
        self.assertTrue(vision_path.is_file())
        vision = json.loads(vision_path.read_text(encoding="utf-8"))
        self.assertEqual(vision["generated_box_instances"], 6098)
        self.assertEqual(vision["exact_routes"], 6098)
        self.assertEqual(vision["subpopulation_counts"], {"photoreceptor": 6091, "HBeyelet": 7})
        self.assertEqual(vision["hex_assignment_audit"]["all_annotated_rows"], 23720)
        self.assertEqual(vision["hex_assignment_audit"]["rows_with_both_coordinates"], 23720)
        self.assertEqual(vision["hex_assignment_audit"]["sensory_input_rows"], 0)
        self.assertFalse(vision["hex_assignment_audit"]["used_as_input_coordinates"])

        motor_path = path.with_name("motor-routing.json")
        self.assertTrue(motor_path.is_file())
        motor = json.loads(motor_path.read_text(encoding="utf-8"))
        self.assertEqual(motor["generated_box_instances"], 815)
        self.assertEqual(motor["exact_routes"], 815)
        self.assertEqual(motor["group_counts"], {"motor.vnc": 708, "motor.central_brain": 107})
        self.assertEqual(motor["exit_nerve_inventory"]["non_motor_deferred"], 191)
        self.assertEqual(motor["exit_nerve_inventory"]["motor_without_exit_nerve"], 1)

        residual_path = path.with_name("unclassified-sensory-routing.json")
        self.assertTrue(residual_path.is_file())
        residual = json.loads(residual_path.read_text(encoding="utf-8"))
        self.assertEqual(residual["generated_box_instances"], 1883)
        self.assertEqual(residual["exact_routes"], 1883)
        self.assertEqual(
            residual["class_counts"],
            {
                "unknown_sensory": 1712,
                "(unknown)": 103,
                "chemosensory": 57,
                "mechanosensory_tbc": 11,
            },
        )
        self.assertEqual(residual["sensory_coverage"]["total_routed_unique_body_ids"], 17884)
        self.assertEqual(residual["sensory_coverage"]["coverage_percent"], 100.0)

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

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from the_fly_matrix.ledger import build_summary, load_ledger, validate_ledger


class LedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = load_ledger()

    def test_all_references_and_statuses_are_valid(self) -> None:
        checks = validate_ledger(self.ledger)
        self.assertEqual(len(checks), 5)

    def test_top_level_interface_is_exhaustively_represented(self) -> None:
        self.assertEqual(len(self.ledger["boxes"]), 22)
        self.assertEqual(len(self.ledger["groups"]), 17)
        self.assertEqual(len(self.ledger["wires"]), 27)
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

        proprio_transduction_path = path.with_name(
            "proprioception-transduction-candidates.json"
        )
        self.assertTrue(proprio_transduction_path.is_file())
        proprio_transduction = json.loads(
            proprio_transduction_path.read_text(encoding="utf-8")
        )
        self.assertEqual(proprio_transduction["source_joint_channels"], 102)
        self.assertEqual(proprio_transduction["target_terminal_channels"], 262)
        self.assertEqual(proprio_transduction["target_neurons"], 1454)
        self.assertEqual(proprio_transduction["candidate_edges"], 1992)
        self.assertEqual(proprio_transduction["direct_candidate_edges"], 1439)
        self.assertEqual(proprio_transduction["proxy_candidate_edges"], 553)
        self.assertEqual(proprio_transduction["resolved_terminal_channels"], 262)
        self.assertEqual(proprio_transduction["resolved_neurons"], 1454)
        self.assertEqual(proprio_transduction["parameterized_terminal_channels"], 171)
        self.assertEqual(proprio_transduction["proxy_terminal_channels"], 91)
        self.assertEqual(proprio_transduction["proxy_neurons"], 468)
        self.assertEqual(proprio_transduction["unresolved_terminal_channels"], 0)
        self.assertEqual(proprio_transduction["unresolved_neurons"], 0)
        self.assertEqual(
            proprio_transduction["former_missing_reason_channel_counts"],
            {
                "notum_strain_observable_missing": 4,
                "strain_observable_missing": 82,
                "vibration_observable_missing": 5,
            },
        )
        self.assertEqual(
            proprio_transduction["terminal_disposition_counts"],
            {"parameterized": 171, "proxy": 91},
        )
        self.assertEqual(
            sum(proprio_transduction["proxy_basis_edge_counts"].values()), 553
        )
        proprio_proxy_path = path.with_name("proprioception-proxy-candidates.parquet")
        self.assertTrue(proprio_proxy_path.is_file())
        proprio_proxies = pd.read_parquet(proprio_proxy_path)
        self.assertEqual(len(proprio_proxies), 553)
        self.assertEqual(proprio_proxies["target_channel_id"].nunique(), 91)
        self.assertEqual(set(proprio_proxies["terminal_disposition"]), {"proxy"})
        self.assertFalse(proprio_transduction["scientific_parameter_values_selected"])

        physical_touch_path = path.with_name("flybody-touch.json")
        self.assertTrue(physical_touch_path.is_file())
        physical_touch = json.loads(physical_touch_path.read_text(encoding="utf-8"))
        self.assertEqual(physical_touch["collision_enabled_segments"], 57)
        self.assertEqual(physical_touch["explicit_ground_contact_pairs"], 69)
        self.assertEqual(physical_touch["aggregate_leg_channels"], 6)
        self.assertEqual(physical_touch["scalar_observables"], 96)
        self.assertEqual(physical_touch["local_body_contact_channels"], 2)
        self.assertEqual(physical_touch["local_body_contact_scalar_observables"], 6)
        self.assertEqual(
            physical_touch["non_leg_local_load_mapping"],
            "exact_for_head_and_thorax_net_force",
        )
        self.assertEqual(physical_touch["biological_receptor_mapping"], "deferred")

        physical_motor_path = path.with_name("flybody-actuators.json")
        self.assertTrue(physical_motor_path.is_file())
        physical_motor = json.loads(physical_motor_path.read_text(encoding="utf-8"))
        self.assertEqual(physical_motor["actuator_channels"], 102)
        self.assertEqual(physical_motor["unique_control_addresses"], 102)
        self.assertEqual(physical_motor["unique_target_joints"], 102)
        self.assertEqual(
            physical_motor["actuator_config_status_counts"],
            {"configured": 100, "missing": 2},
        )
        self.assertEqual(len(physical_motor["missing_actuator_config_joints"]), 2)
        self.assertEqual(physical_motor["control_addressing"], "exact")
        self.assertEqual(physical_motor["motor_neuron_to_actuator_mapping"], "deferred")

        physical_vision_path = path.with_name("flybody-vision.json")
        self.assertTrue(physical_vision_path.is_file())
        physical_vision = json.loads(physical_vision_path.read_text(encoding="utf-8"))
        self.assertEqual(physical_vision["eye_cameras"], 2)
        self.assertEqual(physical_vision["ommatidia_per_eye"], 721)
        self.assertEqual(physical_vision["active_sample_channels"], 1442)
        self.assertEqual(physical_vision["raw_readout_scalar_slots"], 2884)
        self.assertEqual(physical_vision["raw_frame_shape"], [2, 512, 450, 3])
        self.assertEqual(physical_vision["readout_shape"], [2, 721, 2])
        self.assertEqual(
            sum(physical_vision["ommatidium_type_counts_per_eye"].values()), 721
        )
        self.assertEqual(physical_vision["physical_channel_mapping"], "exact")
        self.assertEqual(physical_vision["malecns_retinotopic_mapping"], "deferred")

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

        mechano_transduction_path = path.with_name(
            "mechanosensation-transduction-candidates.json"
        )
        self.assertTrue(mechano_transduction_path.is_file())
        mechano_transduction = json.loads(
            mechano_transduction_path.read_text(encoding="utf-8")
        )
        self.assertEqual(mechano_transduction["source_contact_channels"], 6)
        self.assertEqual(mechano_transduction["target_terminal_channels"], 323)
        self.assertEqual(mechano_transduction["target_neurons"], 4291)
        self.assertEqual(mechano_transduction["source_joint_channels_used"], 19)
        self.assertEqual(mechano_transduction["source_local_body_contact_channels"], 2)
        self.assertEqual(mechano_transduction["candidate_edges"], 2108)
        self.assertEqual(mechano_transduction["resolved_terminal_channels"], 323)
        self.assertEqual(mechano_transduction["resolved_neurons"], 4291)
        self.assertEqual(mechano_transduction["unresolved_terminal_channels"], 0)
        self.assertEqual(mechano_transduction["unresolved_neurons"], 0)
        self.assertEqual(
            mechano_transduction["source_kind_edge_counts"],
            {"body_contact": 60, "contact_load": 1246, "joint_state": 802},
        )
        self.assertEqual(
            mechano_transduction["candidate_basis_edge_counts"],
            {
                "annotated_leg_entry_nerve_and_side": 1246,
                "antennal_nerve_side_antenna_motion": 456,
                "anterior_dorsal_mesothoracic_nerve_side_wing_motion": 102,
                "dorsal_metathoracic_nerve_side_haltere_motion": 4,
                "mouthpart_nerve_side_proboscis_motion": 240,
                "optic_nerve_head_contact": 12,
                "posterior_dorsal_mesothoracic_nerve_thorax_contact": 48,
            },
        )
        self.assertEqual(
            sum(mechano_transduction["unresolved_reason_channel_counts"].values()),
            0,
        )
        self.assertFalse(mechano_transduction["scientific_parameter_values_selected"])
        mechano_audit = pd.read_csv(
            path.with_name("mechanosensation-transduction-channel-audit.csv")
        )
        self.assertEqual(len(mechano_audit), 323)
        self.assertEqual(mechano_audit["channel_id"].nunique(), 323)
        self.assertEqual(
            mechano_audit["status"].value_counts().to_dict(),
            {"candidates_known": 323},
        )
        self.assertFalse(mechano_audit["reason"].isna().any())

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

        column_path = path.with_name("vision-optic-column-assignments.json")
        self.assertTrue(column_path.is_file())
        columns = json.loads(column_path.read_text(encoding="utf-8"))
        self.assertEqual(columns["published_optic_columns"], 1332)
        self.assertEqual(columns["published_receptor_assignments"], 2628)
        self.assertEqual(columns["assigned_target_channels"], 2628)
        self.assertEqual(columns["unassigned_target_channels"], 3470)
        self.assertEqual(columns["parameterized_remainder_photoreceptors"], 3463)
        self.assertEqual(columns["proxy_hbeyelet_channels"], 7)
        self.assertEqual(columns["structurally_covered_target_channels"], 6098)
        self.assertEqual(columns["blocked_target_channels"], 0)
        self.assertEqual(
            columns["terminal_disposition_counts"],
            {"parameterized": 6091, "proxy": 7},
        )
        self.assertEqual(columns["column_side_counts"], {"L": 627, "R": 705})
        self.assertEqual(columns["receptor_class_counts"], {"R7": 1299, "R8": 1329})
        self.assertEqual(columns["free_discrete_registration_parameters"], 4795)
        self.assertEqual(columns["free_continuous_parameters"], 6098)
        self.assertEqual(columns["flybody_registration_status"], "externally_parameterized")
        self.assertEqual(columns["structural_wiring_status"], "parameterized_complete")
        self.assertFalse(columns["scientific_parameter_values_selected"])
        remainder = pd.read_parquet(path.with_name("vision-remainder-transduction.parquet"))
        self.assertEqual(len(remainder), 3470)
        self.assertEqual(remainder["target_channel_id"].nunique(), 3470)
        self.assertEqual(remainder["candidate_source_count"].unique().tolist(), [721])
        self.assertEqual(remainder["terminal_disposition"].value_counts().to_dict(), {"parameterized": 3463, "proxy": 7})

        motor_path = path.with_name("motor-routing.json")
        self.assertTrue(motor_path.is_file())
        motor = json.loads(motor_path.read_text(encoding="utf-8"))
        self.assertEqual(motor["generated_box_instances"], 815)
        self.assertEqual(motor["exact_routes"], 815)
        self.assertEqual(motor["group_counts"], {"motor.vnc": 708, "motor.central_brain": 107})
        self.assertEqual(motor["exit_nerve_inventory"]["non_motor_deferred"], 191)
        self.assertEqual(motor["exit_nerve_inventory"]["motor_without_exit_nerve"], 1)
        muscle_groups = motor["muscle_group_inventory"]
        self.assertEqual(muscle_groups["groups"], 441)
        self.assertEqual(muscle_groups["exact_member_routes"], 815)
        self.assertEqual(muscle_groups["unknown_type_neurons_preserved_as_singletons"], 10)
        self.assertEqual(muscle_groups["value_transformation"], "none_preserve_members")
        self.assertEqual(muscle_groups["membership_status"], "fixed")
        self.assertEqual(muscle_groups["flybody_actuator_mapping"], "deferred")

        transduction_path = path.with_name("motor-transduction-candidates.json")
        self.assertTrue(transduction_path.is_file())
        transduction = json.loads(transduction_path.read_text(encoding="utf-8"))
        self.assertEqual(transduction["candidate_edges"], 7849)
        self.assertEqual(transduction["free_continuous_parameters"], 7849)
        self.assertEqual(transduction["resolved_motor_groups"], 431)
        self.assertEqual(transduction["unresolved_motor_groups"], 10)
        self.assertEqual(transduction["resolved_motor_neurons"], 804)
        self.assertEqual(transduction["unresolved_motor_neurons"], 11)
        self.assertEqual(transduction["unresolved_subclass_neuron_counts"], {"rm": 5, "xm": 6})
        self.assertEqual(
            transduction["unresolved_exit_nerve_counts"], {"DMetaN": 4, "ON": 5, "PDMNa": 2}
        )
        self.assertEqual(transduction["covered_actuators"], 102)
        self.assertEqual(transduction["uncovered_actuators"], 0)
        self.assertFalse(transduction["scientific_parameter_values_selected"])

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
        self.assertEqual(
            residual["source_model_counts"],
            {
                "source.sensory.residual.chemosensory": 57,
                "source.sensory.residual.mechanosensory_tbc": 11,
                "source.sensory.residual.unknown": 1815,
            },
        )
        self.assertEqual(residual["terminal_disposition_counts"], {"basal": 1883})
        self.assertEqual(residual["source_parameter_count"], 1883)
        self.assertEqual(residual["upstream_mapping_status"], "explicit_nominal_sources_complete")
        self.assertFalse(residual["scientific_parameter_values_selected"])

        central_path = path.with_name("central-connectome.json")
        self.assertTrue(central_path.is_file())
        central = json.loads(central_path.read_text(encoding="utf-8"))
        self.assertEqual(central["annotated_nodes"], 211577)
        self.assertEqual(central["annotated_body_rows"], 211577)
        self.assertEqual(central["canonical_neurons"], 166700)
        self.assertEqual(central["noncanonical_annotated_bodies"], 44877)
        self.assertEqual(central["population_classification"]["scope_counts"], {
            "canonical_neuron": 166700,
            "unresolved_or_non_neuronal_body": 33013,
            "non_neuronal_glia": 11864,
        })
        self.assertEqual(central["raw_edge_rows"], 151856684)
        self.assertEqual(central["induced_edge_rows"], 26028386)
        self.assertEqual(central["runtime_induced_edge_rows"], 25582938)
        self.assertEqual(central["runtime_excluded_annotated_body_edge_rows"], 445448)
        self.assertEqual(central["excluded_fragment_edge_rows"], 125828298)
        self.assertEqual(sum(central["edge_scope_counts"].values()), 151856684)
        self.assertEqual(central["raw_synapse_weight"], 311833243)
        self.assertEqual(central["induced_synapse_weight"], 125365933)
        self.assertEqual(central["runtime_induced_synapse_weight"], 124177617)
        self.assertFalse(central["scientific_parameter_values_selected"])

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

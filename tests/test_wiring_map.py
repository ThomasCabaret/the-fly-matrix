from __future__ import annotations

import unittest
from pathlib import Path

from the_fly_matrix.wiring_map import DERIVED_WIRING, WiringMapError, build_wiring_map


class WiringMapTests(unittest.TestCase):
    def test_missing_derived_inventory_is_reported(self) -> None:
        with self.assertRaisesRegex(WiringMapError, "run_analysis.bat"):
            build_wiring_map(Path("does-not-exist"))

    def test_real_map_is_exhaustive_when_derived_data_exist(self) -> None:
        if not (DERIVED_WIRING / "vision-routes.parquet").is_file():
            self.skipTest("derived wiring data are absent")
        payload = build_wiring_map()
        counts = payload["meta"]["counts"]
        self.assertEqual(counts["cns_inputs"], 17_884)
        self.assertEqual(counts["input_boxes"], 8_895)
        self.assertEqual(counts["physical_observables"], 1_552)
        self.assertEqual(counts["optic_columns"], 1_332)
        self.assertEqual(counts["cns_outputs"], 815)
        self.assertEqual(counts["motor_groups"], 441)
        self.assertEqual(counts["actuators"], 102)
        self.assertGreater(counts["nodes"], 30_000)
        self.assertGreater(counts["edges"], 25_000)
        self.assertEqual(
            sum(payload["meta"]["input_box_states"].values()),
            counts["input_boxes"],
        )
        self.assertNotIn("blocked", payload["meta"]["input_box_states"])
        self.assertEqual(payload["meta"]["input_box_states"]["basal"], 2_212)
        self.assertEqual(payload["meta"]["input_box_states"]["proxy"], 98)
        self.assertEqual(
            payload["meta"]["motor_group_states"],
            {"parameterized": 431, "sink": 10},
        )

        nodes = payload["elements"]["nodes"]
        edges = payload["elements"]["edges"]
        node_ids = {node["data"]["id"] for node in nodes}
        self.assertEqual(len(node_ids), len(nodes))
        self.assertEqual(len({edge["data"]["id"] for edge in edges}), len(edges))
        self.assertTrue(
            all(
                edge["data"]["source"] in node_ids and edge["data"]["target"] in node_ids
                for edge in edges
            )
        )
        self.assertEqual(
            sum(
                edge["data"]["kind"] == "cns_interface"
                for edge in edges
            ),
            counts["cns_inputs"] + counts["cns_outputs"],
        )
        self.assertFalse(
            any(
                node["data"]["kind"] == "input_adapter_channel"
                and node["data"]["state"] == "blocked"
                for node in nodes
            )
        )
        residual_sources = [
            node
            for node in nodes
            if node["data"]["kind"] == "nominal_source"
            and node["data"]["sector"] == "unclassified_sensory"
        ]
        self.assertEqual(len(residual_sources), 3)
        self.assertTrue(all(node["data"]["state"] == "basal" for node in residual_sources))
        proprio_nodes = [
            node
            for node in nodes
            if node["data"]["kind"] == "input_adapter_channel"
            and node["data"]["sector"] == "proprioception"
        ]
        self.assertEqual(len(proprio_nodes), 262)
        self.assertEqual(
            sum(node["data"]["state"] == "proxy" for node in proprio_nodes), 91
        )
        self.assertFalse(any(node["data"]["state"] == "blocked" for node in proprio_nodes))


if __name__ == "__main__":
    unittest.main()

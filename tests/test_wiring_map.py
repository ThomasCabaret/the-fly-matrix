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
        self.assertTrue(
            any(
                node["data"]["kind"] == "input_adapter_channel"
                and node["data"]["state"] == "blocked"
                for node in nodes
            )
        )


if __name__ == "__main__":
    unittest.main()

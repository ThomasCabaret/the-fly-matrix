from __future__ import annotations

import unittest

import numpy as np
import scipy.sparse as sparse
import yaml

from the_fly_matrix.front_leg_chain import (
    CAMPAIGN_PATH,
    compile_central_corridor,
    compile_feco_source_path_product,
)


class FrontLegChainTests(unittest.TestCase):
    def test_feco_product_preserves_each_functional_class(self) -> None:
        campaign = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="utf-8"))
        source = yaml.safe_load(
            (CAMPAIGN_PATH.parent / "feco-calcium-held-out-fit-v0.yaml").read_text(
                encoding="utf-8"
            )
        )
        product = compile_feco_source_path_product(source)
        self.assertEqual(len(product), 12)
        self.assertTrue(
            all(
                set(item)
                == {
                    "claw_position",
                    "club_vibration_and_speed",
                    "hook_flexion_direction",
                }
                for item in product
            )
        )
        self.assertEqual(campaign["acceptance"]["expected_feco_boundary_alternatives"], 24)

    def test_small_corridor_accounts_direct_and_two_hop_paths(self) -> None:
        # 10->30 direct; both sources also reach both targets through node 20.
        body_ids = np.asarray([10, 11, 20, 30, 40], dtype=np.int64)
        rows = np.asarray([0, 0, 1, 2, 2], dtype=np.int32)
        cols = np.asarray([2, 3, 2, 3, 4], dtype=np.int32)
        graph = sparse.coo_matrix(
            (np.asarray([2, 3, 5, 6, 7], dtype=np.float32), (rows, cols)),
            shape=(5, 5),
        ).tocsr()
        summary, paths, intermediates = compile_central_corridor(
            graph,
            body_ids,
            np.asarray([10, 11], dtype=np.int64),
            np.asarray([30, 40], dtype=np.int64),
            maximum_pair_distance=3,
        )
        self.assertEqual(summary["endpoint_pairs"], 4)
        self.assertEqual(summary["direct_edges"], 1)
        self.assertEqual(summary["two_hop_paths"], 4)
        self.assertEqual(intermediates.tolist(), [2])
        self.assertEqual(set(paths["hops"]), {1, 2})
        self.assertFalse(summary["path_selected"])

    def test_campaign_forbids_selection_behavior_and_motion(self) -> None:
        campaign = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="utf-8"))
        self.assertEqual(campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertFalse(campaign["diagnostic_probe"]["inspect_body_trajectory"])
        self.assertFalse(campaign["diagnostic_probe"]["run_mujoco"])
        self.assertTrue(all(value == 0 for value in campaign["capacity_policy"].values()))

    def test_recurrent_path_does_not_reclassify_terminal_as_intermediate(self) -> None:
        # 10->20->30 reaches the target; 10->30->30 is also a two-hop path
        # through the target itself and must not create a new intermediate.
        body_ids = np.asarray([10, 20, 30], dtype=np.int64)
        graph = sparse.coo_matrix(
            (
                np.ones(4, dtype=np.float32),
                (
                    np.asarray([0, 0, 1, 2]),
                    np.asarray([1, 2, 2, 2]),
                ),
            ),
            shape=(3, 3),
        ).tocsr()
        summary, _paths, intermediates = compile_central_corridor(
            graph,
            body_ids,
            np.asarray([10], dtype=np.int64),
            np.asarray([30], dtype=np.int64),
            maximum_pair_distance=2,
        )
        self.assertEqual(intermediates.tolist(), [1])
        self.assertEqual(summary["unique_intermediate_neurons"], 1)


if __name__ == "__main__":
    unittest.main()

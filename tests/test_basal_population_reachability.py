from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

from the_fly_matrix.basal_population_reachability import (
    compile_family_sources,
    compile_internal_boundary_counts,
    compile_population_dispositions,
    compile_reachability,
    run_accounting,
)


class BasalPopulationReachabilityTests(unittest.TestCase):
    def test_small_graph_reachability_and_boundary_partition(self) -> None:
        # 0 -> 1 -> 2 -> 3 -> 4, with one local return 2 -> 1.
        outgoing = sparse.csr_matrix(
            (
                np.ones(5, dtype=np.float32),
                (np.asarray([0, 1, 2, 2, 3]), np.asarray([1, 2, 1, 3, 4])),
            ),
            shape=(5, 5),
        )
        body_ids = np.asarray([10, 20, 30, 40, 50], dtype=np.int64)
        depths, summary = compile_reachability(
            outgoing, body_ids, {"family.a": np.asarray([10], dtype=np.int64)}
        )
        self.assertEqual(summary["union"]["reachable_neurons"], 5)
        self.assertEqual(summary["union"]["maximum_depth"], 4)

        reached = depths["union"] >= 0
        event = np.asarray([False, False, True, False, False])
        counts, leakage = compile_internal_boundary_counts(
            outgoing, outgoing.transpose().tocsr(), reached, event
        )
        self.assertEqual(leakage, 0)
        self.assertEqual(
            counts,
            {
                "event_required_to_event_required": 0,
                "event_required_to_dual_unresolved": 2,
                "dual_unresolved_to_event_required": 1,
                "dual_unresolved_to_dual_unresolved": 2,
                "total_reached_scope_edges": 5,
            },
        )

    def test_dispositions_never_infer_a_class_from_annotation(self) -> None:
        nodes = pd.DataFrame(
            {
                "body_id": [10, 20, 30],
                "superclass": ["sensory", "central", "motor"],
                "class": ["known", "known", "known"],
                "type": ["same", "same", "same"],
                "instance": ["a", "b", "c"],
            }
        )
        depths = {"family.a": np.asarray([0, 1, 2]), "union": np.asarray([0, 1, 2])}
        source_members = pd.DataFrame(
            {"family_id": ["family.a"], "channel_id": ["channel.a"], "body_id": [10]}
        )
        reached, sources, _ = compile_population_dispositions(
            nodes, depths, np.asarray([20], dtype=np.int64), source_members
        )
        self.assertEqual(
            reached.set_index("body_id")["assignment"].to_dict(),
            {10: "dual_unresolved", 20: "event_required", 30: "dual_unresolved"},
        )
        self.assertEqual(
            sources.iloc[0]["bridge_disposition"],
            "dual_event_or_graded_bridge_unresolved",
        )
        self.assertFalse(bool(sources.iloc[0]["bridge_executable"]))

    def test_real_campaign_accounts_scope_without_emitting_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = run_accounting(
                result_path=root / "result.yaml",
                evaluation_path=root / "evaluation.yaml",
                output_root=root / "derived",
            )
        self.assertEqual(result["source_accounting"], {
            "families": 6,
            "channels": 2212,
            "unique_terminal_bodies": 6041,
        })
        self.assertEqual(result["union_reachability"]["reachable_neurons"], 166431)
        self.assertEqual(result["union_reachability"]["unreachable_neurons"], 269)
        self.assertEqual(result["population_assignment_counts"]["event_required"], 12)
        self.assertEqual(result["population_assignment_counts"]["dual_unresolved"], 166419)
        self.assertEqual(result["parameter_values_emitted"], 0)
        self.assertFalse(result["gates"]["executable_source_unit_bridges_available"])
        self.assertFalse(result["gates"]["accepted_global_typed_hybrid_runtime_available"])


if __name__ == "__main__":
    unittest.main()

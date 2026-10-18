from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy import sparse

from the_fly_matrix.first_held_out_execution_preflight import (
    HeldOutPreflightError,
    _timebase_report,
    build_execution_schedule,
    deterministic_stratified_rewire,
    graph_semantic_hash,
    native_response_effect,
    write_jsonl_exclusive,
)


class FirstHeldOutExecutionPreflightTests(unittest.TestCase):
    def test_stratified_rewire_preserves_degree_weight_and_changes_topology(self) -> None:
        sources = np.array([0, 0, 1, 1, 2, 2, 3, 3])
        targets = np.array([1, 2, 2, 3, 0, 3, 0, 1])
        graph = sparse.csr_matrix((np.ones(8), (targets, sources)), shape=(4, 4))
        body_ids = np.array([10, 11, 12, 13])
        transmitters = np.array(["ach", "ach", "ach", "ach"], dtype=object)
        rewired, summary = deterministic_stratified_rewire(
            graph,
            body_ids=body_ids,
            source_transmitters=transmitters,
            seed=81701,
            accepted_swap_target=2,
            maximum_attempts=10000,
        )
        self.assertNotEqual(graph_semantic_hash(graph, body_ids), graph_semantic_hash(rewired, body_ids))
        self.assertTrue(summary["exact_in_degree_preserved"])
        self.assertTrue(summary["exact_out_degree_preserved"])
        self.assertTrue(summary["exact_weight_multiset_preserved"])
        self.assertEqual(summary["new_self_loops"], 0)
        self.assertEqual(summary["duplicate_edges"], 0)

    def test_schedule_is_exact_cartesian_accounting(self) -> None:
        protocol = {
            "topology_controls": {"rewire_seeds": [1, 2, 3, 4]},
            "frozen_lineage": {"member_ids": [f"m{i}" for i in range(11)]},
            "stimulus": {"sides": ["left", "right"]},
            "replication": {"paired_trial_seeds": list(range(8))},
        }
        schedule = build_execution_schedule(protocol)
        self.assertEqual(len(schedule), 3168)
        self.assertEqual(schedule["scenario_id"].nunique(), 3168)
        self.assertEqual(schedule["topology_variant"].nunique(), 9)
        self.assertEqual(schedule["condition"].value_counts().to_dict(), {"stimulus": 1584, "sham": 1584})

    def test_native_measurement_never_mixes_event_and_graded_units(self) -> None:
        stimulus = np.arange(20, dtype=float).reshape(5, 4)
        sham = np.ones_like(stimulus)
        result = native_response_effect(
            stimulus, sham, event_mask=np.array([True, False, True, False])
        )
        np.testing.assert_array_equal(
            result["event_count_delta"], (stimulus - sham)[:, [0, 2]].sum(axis=0)
        )
        np.testing.assert_array_equal(
            result["graded_state_integral_delta"], (stimulus - sham)[:, [1, 3]].sum(axis=0)
        )

    def test_append_only_writer_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.jsonl"
            write_jsonl_exclusive(path, [{"id": 1}])
            with self.assertRaises(FileExistsError):
                write_jsonl_exclusive(path, [{"id": 2}])

    def test_locked_ramp_is_not_representable_at_frozen_timebase(self) -> None:
        protocol = {
            "stimulus": {
                "baseline_duration_s": 0.1,
                "ramp_duration_s": 0.06504065040650407,
                "post_release_observation_s": 0.2,
                "total_duration_s": 0.3650406504065041,
                "implementation_tolerance": {"duration_abs_s": 1.0e-6},
            }
        }
        report = _timebase_report(protocol, 0.0001)
        self.assertFalse(report["all_locked_durations_representable"])
        self.assertTrue(report["baseline_duration_s"]["within_locked_tolerance"])
        self.assertFalse(report["ramp_duration_s"]["within_locked_tolerance"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

import numpy as np
from scipy import sparse

from the_fly_matrix.front_leg_coupled_identifiability_execution import (
    _factor_ratio,
    build_boundary_graph,
    deterministic_event_presence,
    summarize_factor_observability,
)


class FrontLegCoupledIdentifiabilityExecutionTests(unittest.TestCase):
    def test_boundary_graph_retains_only_source_to_cone_and_cone_recurrence(self) -> None:
        full = sparse.csr_matrix(
            np.asarray(
                [
                    [0, 0, 0, 0],
                    [9, 0, 0, 0],
                    [2, 3, 0, 5],
                    [7, 0, 11, 0],
                ],
                dtype=np.float32,
            )
        )
        graph, summary = build_boundary_graph(full, np.asarray([0, 1]), np.asarray([2, 3]))
        self.assertEqual(graph.shape, (4, 4))
        self.assertEqual(summary["direct_source_to_cone_edges"], 3)
        self.assertEqual(summary["cone_recurrent_edges"], 2)
        self.assertEqual(graph[:2].nnz, 0)
        self.assertEqual(float(graph[2, 0]), 2.0)
        self.assertEqual(float(graph[3, 2]), 11.0)

    def test_regular_event_schedule_is_deterministic_and_rate_sensitive(self) -> None:
        rates = np.asarray([10.0, 100.0])
        phases = np.asarray([0.0, 0.5])
        first = deterministic_event_presence(rates, 0.1, 1000, phases)
        second = deterministic_event_presence(rates, 0.1, 1000, phases)
        self.assertTrue(np.array_equal(first, second))
        self.assertEqual(first.sum(axis=0).tolist(), [0, 10])

    def test_factor_ratio_rejects_undeclared_coordinates(self) -> None:
        self.assertEqual(_factor_ratio("ratio_0p75"), 0.75)
        with self.assertRaisesRegex(RuntimeError, "unknown engineering coordinate"):
            _factor_ratio("physiology_default")

    def test_observability_reports_without_ranking(self) -> None:
        rows = []
        for left in ("low", "mid", "high"):
            for right in ("a", "b", "c"):
                scale = {"low": 0.0, "mid": 1.0, "high": 2.0}[left]
                rows.append(
                    {
                        "left": left,
                        "right": right,
                        "sensory_delta_peak_l1": scale,
                        "intermediate_delta_peak_l1": scale,
                        "motor_delta_peak_l1": scale,
                        "motor_delta_integral_l1": scale,
                        "generated_event_delta": scale,
                    }
                )
        summary = summarize_factor_observability(rows, ["left", "right"])
        self.assertTrue(summary["factors"]["left"]["dynamically_observable_in_declared_metrics"])
        self.assertFalse(summary["factors"]["right"]["dynamically_observable_in_declared_metrics"])
        self.assertNotIn("selected", summary)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

import numpy as np
import yaml

from the_fly_matrix.ledger import ROOT
from the_fly_matrix.typed_hybrid_runtime import (
    DiagnosticConstants,
    EVENT,
    GRADED,
    INACTIVE,
    TorchTypedHybridRuntime,
    TypedHybridRuntimeError,
    _micro_graph,
    boundary_edge_counts,
    run_micro_oracle,
)


class TypedHybridRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        campaign = yaml.safe_load(
            (
                ROOT
                / "calibration"
                / "campaigns"
                / "basal-reached-typed-hybrid-runtime-sentinel-v0.yaml"
            ).read_text(encoding="utf-8")
        )
        cls.constants = DiagnosticConstants.from_campaign(campaign)

    def test_micro_graph_has_exactly_the_four_boundary_classes(self) -> None:
        graph, assignment = _micro_graph()
        self.assertEqual(
            boundary_edge_counts(graph, assignment),
            {
                "event_to_event": 1,
                "event_to_graded": 1,
                "graded_to_event": 1,
                "graded_to_graded": 1,
                "total_active_edges": 4,
            },
        )

    def test_cpu_micro_oracle_preserves_delay_and_exercises_boundaries(self) -> None:
        result = run_micro_oracle(self.constants, "cpu")
        self.assertTrue(result["accepted"])
        self.assertTrue(result["event_projection_zero_before_delay"])
        self.assertTrue(result["event_projection_nonzero_at_delay"])
        self.assertTrue(result["graded_boundaries_nonzero"])

    def test_runtime_rejects_unresolved_assignment_codes(self) -> None:
        graph, _ = _micro_graph()
        with self.assertRaises(TypedHybridRuntimeError):
            TorchTypedHybridRuntime(
                graph,
                np.asarray([EVENT, 3, GRADED, INACTIVE], dtype=np.int8),
                self.constants,
                "cpu",
            )

    def test_runtime_rejects_cross_type_external_ports(self) -> None:
        graph, assignment = _micro_graph()
        runtime = TorchTypedHybridRuntime(graph, assignment, self.constants, "cpu")
        external = np.zeros(4, dtype=np.float32)
        external[0] = 1.0
        with self.assertRaises(TypedHybridRuntimeError):
            runtime.step(external_graded=external)
        with self.assertRaises(TypedHybridRuntimeError):
            runtime.step(forced_event_indices=[2])


if __name__ == "__main__":
    unittest.main()

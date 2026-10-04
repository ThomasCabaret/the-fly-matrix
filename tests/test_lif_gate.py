from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import yaml

from the_fly_matrix.lif_gate import (
    LifGateError,
    LifGateProfile,
    _small_graph,
    run_numpy_event_reference,
    run_torch_event_reference,
    validate_edge_sweep,
    validate_small_graph,
)


class LifGateTests(unittest.TestCase):
    def test_profile_keeps_model_class_claim_boundary(self) -> None:
        profile = LifGateProfile.load()
        self.assertEqual(profile.raw["claim_label"], "MODEL CLASS GATE / UNCALIBRATED / NO BEHAVIOR")
        self.assertEqual(profile.dt_ms, 0.1)
        self.assertEqual(profile.constants.fixed_delay_ms, 1.8)
        self.assertEqual(profile.constants.refractory_ms, 2.2)

    def test_small_graph_reference_is_recurrent_and_exact(self) -> None:
        result = validate_small_graph("cpu")
        self.assertTrue(result["accepted"])
        self.assertTrue(result["recurrent_spike_observed"])
        self.assertEqual(result["numpy_delivered_edge_events"], result["torch_cpu_delivered_edge_events"])

    def test_numpy_and_torch_preserve_delay_semantics(self) -> None:
        graph, forced, constants, dt_ms = _small_graph()
        numpy_result = run_numpy_event_reference(graph, forced, constants, dt_ms, 10)
        torch_result = run_torch_event_reference(graph, forced, constants, dt_ms, 10, "cpu")
        np.testing.assert_allclose(numpy_result["states"], torch_result["states"], atol=1e-6)
        self.assertEqual(numpy_result["spike_raster"], torch_result["spike_raster"])
        self.assertEqual(numpy_result["spike_raster"][2], [1])
        self.assertEqual(numpy_result["spike_raster"][4], [2])

    def test_edge_sweep_counts_every_row_and_edge(self) -> None:
        graph, _, _, _ = _small_graph()
        result = validate_edge_sweep(graph, 2)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["source_rows_visited"], 4)
        self.assertEqual(result["counted_edges"], 4)

    def test_behavior_targets_are_rejected(self) -> None:
        campaign = yaml.safe_load(Path("calibration/campaigns/neural-model-class-lif-feasibility-v0.yaml").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.yaml"
            campaign["behavior_targets"] = ["grooming"]
            path.write_text(yaml.safe_dump(campaign), encoding="utf-8")
            with self.assertRaisesRegex(LifGateError, "behavior targets"):
                LifGateProfile.load(campaign_path=path)


if __name__ == "__main__":
    unittest.main()

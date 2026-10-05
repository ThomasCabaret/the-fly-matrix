from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from the_fly_matrix.temporal_model_probes import _pathology_probes, collision_probe


ROOT = Path(__file__).resolve().parents[1]


class TemporalModelProbeTests(unittest.TestCase):
    def test_within_bin_events_collide_only_in_rate_representation(self) -> None:
        result = collision_probe(
            [(0, 0.5), (0, 4.5)], [(0, 1.5), (0, 3.5)], 1, 5.0, 0.1, 10.0
        )
        self.assertEqual(result["rate_max_abs_error"], 0.0)
        self.assertTrue(result["rate_representation_collision"])
        self.assertTrue(result["event_representation_distinguishes"])
        self.assertGreater(result["event_trace_l1_distance"], 0.0)

    def test_pathology_probe_respects_event_refractory(self) -> None:
        result = _pathology_probes(0.1)
        self.assertTrue(result["all_states_finite"])
        self.assertEqual(result["lif_quiescent_max_abs_deviation"], 0.0)
        self.assertGreaterEqual(result["event_minimum_inter_spike_interval_ms"], 2.2)

    def test_tracked_result_keeps_scientific_gate_open(self) -> None:
        result = yaml.safe_load(
            (ROOT / "calibration/runner/neural-model-class-temporal-probes-v1.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(all(result["checks"].values()))
        self.assertFalse(result["scientific_gate_closed"])


if __name__ == "__main__":
    unittest.main()

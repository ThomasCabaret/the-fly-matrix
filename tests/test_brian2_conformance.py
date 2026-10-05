from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import yaml
from scipy import sparse

from the_fly_matrix.lif_gate import LifConstants
from the_fly_matrix.lif_source_fidelity import run_numpy_source_aligned


ROOT = Path(__file__).resolve().parents[1]


class Brian2ConformanceTests(unittest.TestCase):
    def test_tracked_result_passes_every_preregistered_check(self) -> None:
        result = yaml.safe_load(
            (ROOT / "calibration/runner/neural-model-class-brian2-conformance-v1.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(result["comparison"]["accepted"])
        self.assertTrue(all(result["comparison"]["checks"].values()))
        self.assertLessEqual(result["comparison"]["maximum_state_error_mV"], 1e-9)
        self.assertFalse(result["scientific_gate_closed"])

    def test_delivery_is_visible_after_target_state_update(self) -> None:
        constants = LifConstants(-52.0, -52.0, -45.0, 20.0, 5.0, 2.2, 1.8)
        graph = sparse.csr_matrix(
            (np.asarray([5.0]), (np.asarray([0]), np.asarray([1]))), shape=(2, 2)
        )
        result = run_numpy_source_aligned(
            graph, {0: np.asarray([0], dtype=np.int64)}, constants, 0.1, 20
        )
        self.assertEqual(result["states"][17, 3], 0.0)
        self.assertEqual(result["states"][18, 1], -52.0)
        self.assertEqual(result["states"][18, 3], 5.0)
        self.assertGreater(result["states"][19, 1], -52.0)

    def test_refractory_release_is_not_one_step_late(self) -> None:
        constants = LifConstants(-52.0, -52.0, -45.0, 20.0, 5.0, 2.2, 1.8)
        graph = sparse.csr_matrix((1, 1), dtype=np.float64)
        result = run_numpy_source_aligned(
            graph,
            {},
            constants,
            0.1,
            23,
            initial_v_mV=np.asarray([-44.0]),
            initial_g_mV=np.asarray([3.0]),
        )
        self.assertEqual(result["spike_raster"][0], [0])
        self.assertGreater(result["states"][21, 2], 0.0)
        self.assertEqual(result["states"][22, 2], 0.0)


if __name__ == "__main__":
    unittest.main()

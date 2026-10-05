from __future__ import annotations

import math
import unittest

import numpy as np

from the_fly_matrix.lif_source_fidelity import (
    SourceAlignedProfile,
    _linear_factors,
    _small_graph,
    audit_pinned_source,
    run_numpy_source_aligned,
    run_torch_source_aligned,
    scaled_torch_weights,
    validate_small_graph,
)


class LifSourceFidelityTests(unittest.TestCase):
    def test_source_lock_and_semantics_are_present(self) -> None:
        result = audit_pinned_source(SourceAlignedProfile.load())
        self.assertTrue(result["accepted"])
        self.assertTrue(all(result["required_semantics_present"].values()))
        self.assertTrue(all(result["source_environment_present"].values()))
        self.assertEqual(result["commit"], "91bdd1e7dcf193f3e7ca5a8933497fcef63b7960")

    def test_exact_linear_factors_match_small_dt_limit(self) -> None:
        constants = _small_graph()[2]
        membrane, synaptic, coupling = _linear_factors(constants, 1e-7)
        self.assertAlmostEqual(membrane, 1.0, places=6)
        self.assertAlmostEqual(synaptic, 1.0, places=6)
        self.assertAlmostEqual(coupling / 1e-7, 1.0 / constants.tau_membrane_ms, places=5)

    def test_numpy_and_torch_match_with_reset_g(self) -> None:
        graph, forced, constants, dt_ms = _small_graph()
        numpy_result = run_numpy_source_aligned(graph, forced, constants, dt_ms, 10)
        torch_result = run_torch_source_aligned(graph, forced, constants, dt_ms, 10, "cpu")
        np.testing.assert_allclose(numpy_result["states"], torch_result["states"], atol=1e-6)
        self.assertEqual(numpy_result["spike_raster"], torch_result["spike_raster"])
        for step, row in enumerate(numpy_result["spike_raster"]):
            for neuron in row:
                self.assertTrue(math.isclose(numpy_result["states"][step, 4 + neuron], 0.0))

    def test_small_graph_is_recurrent_and_accepted(self) -> None:
        result = validate_small_graph("cpu")
        self.assertTrue(result["accepted"])
        self.assertTrue(result["recurrent_spike_observed"])
        self.assertTrue(result["reset_g_observed"])

    def test_weight_scaling_does_not_mutate_shared_numpy_buffer(self) -> None:
        values = np.asarray([1.0, 2.0], dtype=np.float32)
        before = values.copy()
        scaled = scaled_torch_weights(values, 0.275, "cpu")
        np.testing.assert_array_equal(values, before)
        np.testing.assert_allclose(scaled.numpy(), before * 0.275)


if __name__ == "__main__":
    unittest.main()

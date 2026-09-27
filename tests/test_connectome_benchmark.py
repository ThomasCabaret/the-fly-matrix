from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy import sparse

from the_fly_matrix.connectome_benchmark import DynamicsProfile, numpy_step


class ConnectomeBenchmarkTests(unittest.TestCase):
    def test_profile_is_explicitly_uncalibrated(self) -> None:
        profile = DynamicsProfile.load()
        self.assertEqual(profile.claim_label, "BENCHMARK ONLY / UNCALIBRATED")
        self.assertEqual(profile.raw["dynamics"]["rule"], "leaky_tanh_v0")
        self.assertEqual(profile.raw["dynamics"]["edge_weight_normalization"], "incoming_l1")

    def test_numpy_rule_is_deterministic_bounded_and_uses_input(self) -> None:
        profile = DynamicsProfile.load()
        matrix = sparse.csr_matrix(
            np.asarray([[0.0, 2.0], [1.0, 0.0]], dtype=np.float32)
        )
        incoming_inverse = np.asarray([0.5, 1.0], dtype=np.float32)
        state = np.asarray([0.1, -0.2], dtype=np.float32)
        input_vector = np.asarray([0.0, 1.0], dtype=np.float32)
        first = numpy_step(matrix, incoming_inverse, state, input_vector, profile)
        second = numpy_step(matrix, incoming_inverse, state, input_vector, profile)
        without_input = numpy_step(
            matrix, incoming_inverse, state, np.zeros(2, dtype=np.float32), profile
        )
        np.testing.assert_array_equal(first, second)
        self.assertTrue(np.isfinite(first).all())
        self.assertTrue(np.all(np.abs(first) <= 1.0))
        self.assertFalse(np.array_equal(first, without_input))

    def test_invalid_claim_label_is_rejected(self) -> None:
        source = Path("benchmarks/profiles/malecns-benchmark-v0.yaml").read_text(
            encoding="utf-8"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.yaml"
            path.write_text(
                source.replace("BENCHMARK ONLY / UNCALIBRATED", "CALIBRATED", 1),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "uncalibrated claim label"):
                DynamicsProfile.load(path)


if __name__ == "__main__":
    unittest.main()

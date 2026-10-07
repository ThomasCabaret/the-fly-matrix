from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np

from the_fly_matrix.feco_observation import (
    FeCOObservationError,
    gcamp_kernel,
    predict_calcium,
    run,
    source_activation,
)


class FeCOObservationTests(unittest.TestCase):
    def test_gcamp_kernel_is_causal_finite_and_normalized(self) -> None:
        kernel = gcamp_kernel(460, 8.01)
        self.assertEqual(kernel.shape, (460,))
        self.assertTrue(np.isfinite(kernel).all())
        self.assertTrue((kernel >= 0).all())
        self.assertEqual(kernel[0], 0.0)
        self.assertAlmostEqual(float(kernel.sum()), 1.0, places=14)

    def test_hook_and_club_never_get_silent_thresholds(self) -> None:
        position = np.linspace(0.0, 180.0, 100)
        for model_type in ("hook_flex", "club"):
            with self.subTest(model_type=model_type):
                with self.assertRaises(FeCOObservationError):
                    source_activation(position, sampling_hz=8.01, model_type=model_type)

    def test_source_activation_rules_have_expected_directionality(self) -> None:
        flexing = np.asarray([90.0, 80.0, 70.0])
        hook = source_activation(
            flexing,
            sampling_hz=1.0,
            model_type="hook_flex",
            threshold_deg_s=-5.0,
        )
        self.assertTrue(np.array_equal(hook, np.ones(3)))
        oscillating = np.asarray([90.0, 100.0, 90.0])
        club = source_activation(
            oscillating,
            sampling_hz=1.0,
            model_type="club",
            threshold_deg_s=5.0,
        )
        self.assertTrue(np.array_equal(club, np.ones(3)))

    def test_claw_source_paths_are_kept_distinct(self) -> None:
        position = np.linspace(0.0, 180.0, 460)
        predictor = predict_calcium(
            position, sampling_hz=8.01, model_type="claw", claw_center_deg=80.0
        )
        fit_recipe = predict_calcium(
            position,
            sampling_hz=8.01,
            model_type="claw",
            claw_center_deg=90.0,
            pad_first_sample=1000,
        )
        self.assertFalse(np.array_equal(predictor, fit_recipe))
        self.assertGreater(float(np.max(np.abs(predictor - fit_recipe))), 0.0)

    def test_runner_is_reproducible_apart_from_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = run(runner_path=root / "one.yaml", output_root=root / "out-one")
            second = run(runner_path=root / "two.yaml", output_root=root / "out-two")
        self.assertEqual(first["semantic_result_sha256"], second["semantic_result_sha256"])
        self.assertEqual(first["accounting"]["optimized_parameters"], 0)
        self.assertFalse(first["accounting"]["native_representation_selected"])
        self.assertEqual(first["accounting"]["behavior_targets_exposed"], 0)


if __name__ == "__main__":
    unittest.main()

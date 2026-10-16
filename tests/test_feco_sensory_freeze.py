from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import yaml

from the_fly_matrix.feco_sensory_freeze import ROOT, run


class FeCOSensoryFreezeTests(unittest.TestCase):
    def test_materialized_registry_artifacts_keep_uncertainty_and_behavior_boundary(self) -> None:
        parameter_set = yaml.safe_load(
            (ROOT / "calibration/parameter_sets/front-leg-feco-sensory-ensemble-v0.yaml").read_text(encoding="utf-8")
        )
        evaluation = yaml.safe_load(
            (ROOT / "calibration/evaluations/feco-sensory-ensemble-freeze-v0.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(parameter_set["factorization"]["factorized_members"], 432)
        self.assertEqual(parameter_set["factorization"]["routing_profiles"], 27)
        self.assertEqual(parameter_set["factorization"]["joint_source_paths"], 8)
        self.assertEqual(parameter_set["factorization"]["native_representations"], 2)
        self.assertEqual(parameter_set["routing"]["mapped_body_counts_by_class"], {"claw": 5, "club": 11, "hook": 10})
        self.assertEqual(parameter_set["routing"]["unknown_types"], ["SApp23", "SNpp43", "SNpp59"])
        self.assertFalse(parameter_set["native_boundary"]["representation_selected"])
        self.assertFalse(parameter_set["native_boundary"]["runtime_amplitude_identified"])
        self.assertFalse(parameter_set["selection"]["reference_member_selected"])
        self.assertEqual(parameter_set["behavior_targets"], [])
        self.assertFalse(evaluation["scientific_boundary"]["fh03_complete"])

    def test_runner_reconstructs_same_semantic_ensemble_in_an_empty_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = run(
                parameter_set_path=root / "parameter-set.yaml",
                runner_path=root / "runner.yaml",
                evaluation_path=root / "evaluation.yaml",
                output_path=root / "summary.json",
            )
            self.assertEqual(result["status"], "completed_scoped_shapes_frozen_native_scale_open")
            self.assertEqual(result["accounting"]["mapped_bodies"], 26)
            self.assertEqual(result["accounting"]["unresolved_bodies"], 10)
            self.assertEqual(result["accounting"]["factorized_members"], 432)
            rebuilt = yaml.safe_load((root / "parameter-set.yaml").read_text(encoding="utf-8"))
            canonical = yaml.safe_load(
                (ROOT / "calibration/parameter_sets/front-leg-feco-sensory-ensemble-v0.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(rebuilt["semantic_parameter_set_sha256"], canonical["semantic_parameter_set_sha256"])


if __name__ == "__main__":
    unittest.main()

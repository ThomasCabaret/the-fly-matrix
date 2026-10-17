from __future__ import annotations

import unittest

import yaml

from the_fly_matrix.feco_native_bridge import ROOT, run


class FeCONativeBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = run()
        cls.parameter_set = yaml.safe_load(
            (ROOT / "calibration/parameter_sets/front-leg-feco-sensory-ensemble-v1.yaml").read_text(
                encoding="utf-8"
            )
        )
        cls.evaluation = yaml.safe_load(
            (ROOT / "calibration/evaluations/feco-native-bridge-factorization-v0.yaml").read_text(
                encoding="utf-8"
            )
        )

    def test_fh03_closes_without_native_value_selection(self) -> None:
        self.assertTrue(self.evaluation["fh03_complete"])
        self.assertTrue(self.evaluation["fh05_native_amplitude_dependency_open"])
        self.assertEqual(self.evaluation["parameter_values_promoted"], 0)
        self.assertEqual(self.result["accounting"]["native_amplitude_values_selected"], 0)

    def test_class_shared_native_capacity_is_exhaustive(self) -> None:
        capacity = self.parameter_set["native_boundary_capacity"]
        self.assertEqual(len(capacity["profiles"]), 8)
        observed = {
            tuple(profile["representation_by_class"][name] for name in ("claw", "club", "hook"))
            for profile in capacity["profiles"]
        }
        self.assertEqual(len(observed), 8)
        self.assertFalse(capacity["profile_selected"])
        self.assertFalse(capacity["runtime_ready_without_FH05_values"])

    def test_every_activation_coordinate_is_bounded_on_admitted_support(self) -> None:
        coordinates = self.parameter_set["transfer_shape"]["activation_coordinates"]
        self.assertEqual(len(coordinates), 6)
        self.assertEqual({item["functional_class"] for item in coordinates}, {"claw", "club", "hook"})
        for item in coordinates:
            quotient = item["affine_quotient"]
            self.assertGreater(quotient["raw_activation_range"], 0.0)
            self.assertGreaterEqual(quotient["normalized_minimum"], -1e-12)
            self.assertLessEqual(quotient["normalized_maximum"], 1.0 + 1e-12)
            self.assertFalse(item["native_units_identified"])
            self.assertFalse(item["outside_support_scientific_claim_allowed"])

    def test_factorization_and_exposure_accounting(self) -> None:
        factorization = self.parameter_set["factorization"]
        self.assertEqual(factorization["routing_profiles"], 27)
        self.assertEqual(factorization["joint_source_paths"], 8)
        self.assertEqual(factorization["class_shared_native_profiles"], 8)
        self.assertEqual(factorization["factorized_members"], 1728)
        self.assertEqual(self.parameter_set["behavior_targets"], [])
        self.assertFalse(self.parameter_set["selection"]["future_held_out_outcome_inspected"])


if __name__ == "__main__":
    unittest.main()

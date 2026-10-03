from __future__ import annotations

import unittest

import numpy as np
from scipy import sparse

from the_fly_matrix.signed_dynamics import (
    SignedDynamicsContract,
    SignedDynamicsError,
    compile_signed_matrix,
    generate_pilot_candidate,
    load_diagnostic_probe,
    load_fit_campaign,
    numpy_signed_step,
)


class SignedDynamicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = SignedDynamicsContract.load()

    def test_contract_is_minimal_explicit_and_unfitted(self) -> None:
        self.assertEqual(len(self.contract.class_ids), 9)
        self.assertEqual(
            self.contract.raw["parameterization"]["fitted_degrees_of_freedom"], 12
        )
        self.assertEqual(
            self.contract.raw["parameterization"]["synaptic_parameters"]["unknown_policy"],
            "explicit_parameter_required_never_implicit_zero",
        )
        self.assertEqual(
            self.contract.raw["validation_probe"]["claim_label"],
            "STRUCTURAL TEST VALUES ONLY / NOT CALIBRATION",
        )

    def test_compiler_scales_columns_by_presynaptic_class(self) -> None:
        matrix = sparse.csr_matrix(
            np.asarray([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32)
        )
        class_indices = np.asarray(
            [
                self.contract.class_ids.index("acetylcholine"),
                self.contract.class_ids.index("gaba"),
                self.contract.class_ids.index("missing"),
            ],
            dtype=np.uint8,
        )
        values = dict(self.contract.probe_efficacies)
        values["acetylcholine"] = 2.0
        values["gaba"] = -3.0
        values["missing"] = 0.5
        compiled = compile_signed_matrix(matrix, class_indices, self.contract, values)
        np.testing.assert_allclose(
            compiled.toarray(),
            np.asarray([[2.0, -6.0, 1.5], [8.0, -15.0, 3.0]], dtype=np.float32),
        )

    def test_missing_class_and_typed_sign_violation_are_rejected(self) -> None:
        matrix = sparse.eye(3, format="csr", dtype=np.float32)
        classes = np.zeros(3, dtype=np.uint8)
        incomplete = dict(self.contract.probe_efficacies)
        incomplete.pop("unclear")
        with self.assertRaisesRegex(SignedDynamicsError, "missing=.*unclear"):
            compile_signed_matrix(matrix, classes, self.contract, incomplete)
        wrong_sign = dict(self.contract.probe_efficacies)
        wrong_sign["gaba"] = 1.0
        with self.assertRaisesRegex(SignedDynamicsError, "negative typed prior"):
            compile_signed_matrix(matrix, classes, self.contract, wrong_sign)

    def test_step_is_deterministic_bounded_and_uses_input(self) -> None:
        matrix = sparse.csr_matrix(
            np.asarray([[0.0, -0.5], [0.25, 0.0]], dtype=np.float32)
        )
        inverse = np.ones(2, dtype=np.float32)
        state = np.asarray([0.2, -0.1], dtype=np.float32)
        input_vector = np.asarray([0.0, 0.4], dtype=np.float32)
        kwargs = {
            "dt_ms": 5.0,
            "time_constant_ms": 20.0,
            "input_gain": 1.0,
            "bias": 0.0,
        }
        first = numpy_signed_step(matrix, inverse, state, input_vector, **kwargs)
        second = numpy_signed_step(matrix, inverse, state, input_vector, **kwargs)
        no_input = numpy_signed_step(
            matrix, inverse, state, np.zeros_like(input_vector), **kwargs
        )
        self.assertTrue(np.array_equal(first, second))
        self.assertTrue(np.isfinite(first).all())
        self.assertTrue(np.all(np.abs(first) <= 1.0))
        self.assertFalse(np.array_equal(first, no_input))

    def test_unfitted_diagnostic_is_preregistered_and_not_calibration(self) -> None:
        raw, probe = load_diagnostic_probe("nominal_signed_terminal_input")
        self.assertEqual(
            raw["claim_label"], "UNFITTED BASELINE / DIAGNOSTIC ONLY / NOT CALIBRATION"
        )
        self.assertFalse(raw["gate_policy"]["diagnostic_values_used_for_acceptance"])
        self.assertEqual(len(raw["probes"]), 7)
        self.assertEqual(set(probe["class_efficacies"]), set(self.contract.class_ids))

    def test_unknown_unfitted_probe_is_rejected(self) -> None:
        with self.assertRaisesRegex(SignedDynamicsError, "Unknown unfitted diagnostic probe"):
            load_diagnostic_probe("not-a-probe")

    def test_pilot_candidates_are_reconstructible_bounded_and_sign_safe(self) -> None:
        campaign = load_fit_campaign()
        first = generate_pilot_candidate(0)
        repeated = generate_pilot_candidate(0)
        last = generate_pilot_candidate(31)
        self.assertEqual(first, repeated)
        self.assertNotEqual(first, last)
        self.assertEqual(set(first), set(campaign["method"]["parameter_order"]))
        self.assertGreater(first["acetylcholine"], 0)
        self.assertLess(first["gaba"], 0)
        for name, value in first.items():
            bounds = campaign["method"]["bounds"][name]
            if "lower" in bounds:
                self.assertGreaterEqual(value, float(bounds["lower"]))
                self.assertLessEqual(value, float(bounds["upper"]))
            else:
                self.assertGreaterEqual(abs(value), float(bounds["lower_abs"]))
                self.assertLessEqual(abs(value), float(bounds["upper_abs"]))

    def test_pilot_fit_does_not_reuse_diagnostic_or_held_out_scenarios(self) -> None:
        campaign = load_fit_campaign()
        self.assertEqual(campaign["scenario_splits"]["diagnostic"], [])
        self.assertEqual(campaign["scenario_splits"]["held_out"], [])
        diagnostic, _ = load_diagnostic_probe("nominal_signed_terminal_input")
        fit_ids = {
            item["id"]
            for split in ("train", "validation")
            for item in campaign["scenario_splits"][split]
        }
        self.assertTrue(fit_ids.isdisjoint(diagnostic["probes"]))

    def test_pilot_candidate_index_is_bounded(self) -> None:
        with self.assertRaisesRegex(SignedDynamicsError, "outside the declared"):
            generate_pilot_candidate(32)


if __name__ == "__main__":
    unittest.main()

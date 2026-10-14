from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

import numpy as np
import yaml

from the_fly_matrix.neutral_embodied_declared_neural_sentinel import (
    CAMPAIGN_PATH,
    EVALUATION_PATH,
    RESULT_PATH,
    _load_campaign,
    _typed_population,
    run_sentinel,
)


class NeutralEmbodiedDeclaredNeuralSentinelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parents[1] / "runs"
        )
        output_root = Path(cls._temporary_directory.name)
        cls.result = run_sentinel(
            result_path=output_root / "result.yaml",
            evaluation_path=output_root / "evaluation.yaml",
        )
        cls.campaign = _load_campaign(CAMPAIGN_PATH)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary_directory.cleanup()

    def test_campaign_is_zero_fit_nonselecting_and_has_no_physics(self) -> None:
        self.assertEqual(self.campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(self.campaign["behavior_targets"], [])
        self.assertFalse(self.campaign["topology_changes_allowed"])
        self.assertFalse(self.campaign["acceptance"]["allow_neural_magnitude_to_select_candidate"])
        self.assertEqual(self.campaign["scientific_boundary"]["optimized_parameters"], 0)
        self.assertEqual(self.campaign["scientific_boundary"]["physical_episodes"], 0)

    def test_typed_population_distinguishes_graded_tau_and_input_scale(self) -> None:
        drive = np.ones((400, 1), dtype=np.float64)
        common = dict(timestep_s=0.0001, event_tau_s=0.02, synaptic_tau_s=0.005, refractory_s=0.0022, threshold_excursion_mV=7.0)
        fast, _ = _typed_population(drive, np.asarray([False]), graded_tau_s=0.01, dimensionless_input_scale=1.0, **common)
        slow, _ = _typed_population(drive, np.asarray([False]), graded_tau_s=0.02, dimensionless_input_scale=1.0, **common)
        scaled, _ = _typed_population(drive, np.asarray([False]), graded_tau_s=0.01, dimensionless_input_scale=2.0, **common)
        self.assertFalse(np.array_equal(fast, slow))
        self.assertFalse(np.array_equal(fast, scaled))

    def test_exact_envelope_executes_and_all_consumption_oracles_pass(self) -> None:
        self.assertEqual(self.result["accounting"]["scheduled_tuples"], 240)
        self.assertEqual(self.result["accounting"]["outcome_counts"], {"completed_contract": 240})
        self.assertEqual(self.result["coverage"]["feco_routing_profiles"], 81)
        self.assertEqual(self.result["coverage"]["unknown_sign_profiles"], 64)
        self.assertEqual(self.result["coverage"]["numeric_profiles"], 12)
        self.assertTrue(all(self.result["checks"].values()))
        self.assertTrue(self.result["structural_coupling_audit"]["all_nonzero_columns_exact"])
        self.assertEqual(self.result["isolated_oracles"]["unknown_sign_flip"]["nonzero_antisymmetric"], 32)
        self.assertTrue(all(item["changes_probe"] for item in self.result["isolated_oracles"]["numeric_axes"].values()))

    def test_result_is_hash_linked_and_claim_bounded(self) -> None:
        runner = yaml.safe_load(RESULT_PATH.read_text(encoding="utf-8"))
        evaluation = yaml.safe_load(EVALUATION_PATH.read_text(encoding="utf-8"))
        self.assertEqual(runner["status"], "pass_declared_neural_execution_no_fit_no_selection")
        self.assertEqual(runner["accounting"]["physical_episodes"], 0)
        self.assertEqual(runner["accounting"]["selected_candidates"], 0)
        self.assertEqual(runner["semantic_result_sha256"], evaluation["runner_semantic_sha256"])
        self.assertFalse(evaluation["stability_accepted"])


if __name__ == "__main__":
    unittest.main()

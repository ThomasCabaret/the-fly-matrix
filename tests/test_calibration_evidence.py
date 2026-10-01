from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
import pandas as pd
import yaml

from the_fly_matrix.calibration_evidence import (
    EvidenceCompilationError,
    compile_neuron_priors,
)


ROOT = Path(__file__).resolve().parents[1]


class CalibrationEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        recipe = yaml.safe_load(
            (ROOT / "calibration" / "evidence" / "transmitter-sign-prior-v0.yaml").read_text(
                encoding="utf-8"
            )
        )
        cls.sign_rules = recipe["typed_sign_prior"]["mappings"]

    def test_ground_truth_precedence_and_unknown_masks(self) -> None:
        annotations = pd.DataFrame(
            {
                "bodyId": [40, 10, 30, 20, 50],
                "superclass": ["central", "central", "central", "central", None],
                "status": ["Traced", "Traced", "Traced", "Traced", "Traced"],
            }
        )
        transmitters = pd.DataFrame(
            {
                "body": [10, 20, 30],
                "cell_type": ["a", "b", "c"],
                "total_nt_predictions": [100, 100, 100],
                "predicted_nt_confidence": [0.8, 0.9, 0.7],
                "predicted_nt": ["gaba", "acetylcholine", "glutamate"],
                "ground_truth": ["acetylcholine", None, None],
                "celltype_total_nt_predictions": [200, 200, 200],
                "celltype_predicted_nt": ["gaba", "acetylcholine", "glutamate"],
                "celltype_predicted_nt_confidence": [0.7, 0.85, 0.6],
                "consensus_nt": ["acetylcholine", "acetylcholine", "glutamate"],
            }
        )

        result = compile_neuron_priors(annotations, transmitters, self.sign_rules)
        self.assertEqual(result["body_id"].tolist(), [10, 20, 30, 40])

        ground_truth = result.loc[result["body_id"].eq(10)].iloc[0]
        self.assertEqual(ground_truth["effective_transmitter"], "acetylcholine")
        self.assertEqual(ground_truth["evidence_origin"], "source_curated_ground_truth")
        self.assertEqual(ground_truth["sign_code"], 1)
        self.assertTrue(np.isnan(ground_truth["support_confidence"]))

        agreeing = result.loc[result["body_id"].eq(20)].iloc[0]
        self.assertEqual(agreeing["evidence_origin"], "neuron_and_cell_type_prediction")
        self.assertAlmostEqual(agreeing["support_confidence"], 0.85)

        contextual = result.loc[result["body_id"].eq(30)].iloc[0]
        self.assertEqual(contextual["sign_interpretation"], "context_dependent")
        self.assertEqual(contextual["sign_code"], 0)
        self.assertFalse(contextual["sign_asserted"])

        missing = result.loc[result["body_id"].eq(40)].iloc[0]
        self.assertEqual(missing["effective_transmitter"], "missing")
        self.assertEqual(missing["evidence_origin"], "missing_record")
        self.assertEqual(missing["sign_interpretation"], "unresolved")

    def test_duplicate_transmitter_body_is_rejected(self) -> None:
        annotations = pd.DataFrame(
            {"bodyId": [10], "superclass": ["central"], "status": ["Traced"]}
        )
        row = {
            "body": 10,
            "cell_type": "a",
            "total_nt_predictions": 100,
            "predicted_nt_confidence": 0.8,
            "predicted_nt": "gaba",
            "ground_truth": None,
            "celltype_total_nt_predictions": 100,
            "celltype_predicted_nt": "gaba",
            "celltype_predicted_nt_confidence": 0.8,
            "consensus_nt": "gaba",
        }
        with self.assertRaises(EvidenceCompilationError):
            compile_neuron_priors(
                annotations, pd.DataFrame([row, row]), self.sign_rules
            )

    def test_recipe_zero_code_never_means_zero_effect(self) -> None:
        recipe = yaml.safe_load(
            (ROOT / "calibration" / "evidence" / "transmitter-sign-prior-v0.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            recipe["typed_sign_prior"]["zero_code_semantics"],
            "no_sign_assertion_not_zero_synaptic_effect",
        )
        self.assertEqual(recipe["typed_sign_prior"]["mappings"]["glutamate"]["code"], 0)


if __name__ == "__main__":
    unittest.main()

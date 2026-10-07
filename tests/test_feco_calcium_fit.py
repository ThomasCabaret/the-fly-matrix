from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import yaml

from the_fly_matrix.feco_calcium_fit import (
    FeCOCalciumFitError,
    add_candidate_prediction,
    candidates_for,
    fit_dataset,
    prepare_frame,
    run,
)


def dataset() -> dict:
    return {
        "dataset_id": "fixture",
        "functional_class": "hook_flexion_direction",
        "roi_contains": "L1_medial",
        "candidates": [
            {"id": "hook_minus_5", "fit_kind": "affine_on_fixed_prediction", "model_type": "hook_flex", "sampling_policy": "source_ceil_second_time_sample", "threshold_deg_s": -5},
            {"id": "hook_minus_50", "fit_kind": "affine_on_fixed_prediction", "model_type": "hook_flex", "sampling_policy": "source_ceil_second_time_sample", "threshold_deg_s": -50},
        ],
    }


def synthetic_frame() -> pd.DataFrame:
    rows: list[dict] = []
    for animal_index, animal in enumerate(("a", "b", "c")):
        for trial in ("one", "two"):
            base = np.asarray(
                [100, 99, 90, 90, 89, 80, 80, 79, 70, 70, 69, 60], dtype=float
            )
            position = base - animal_index * 0.25
            for sample, value in enumerate(position):
                rows.append(
                    {
                        "animal_id": animal,
                        "trial": trial,
                        "roi": "L1_medial",
                        "analyze": 1,
                        "time": sample * 0.1,
                        "calcium": 0.25 + 1.5 * float(sample in {2, 5, 8, 11}),
                        "L1C_flex": value,
                        "stimulus_type": "forbidden_but_ignored",
                    }
                )
    rows.append(
        {
            "animal_id": "excluded",
            "trial": "one",
            "roi": "other",
            "analyze": 1,
            "time": 0.0,
            "calcium": 999.0,
            "L1C_flex": 999.0,
            "stimulus_type": "must_not_be_read",
        }
    )
    return pd.DataFrame(rows)


class FeCOCalciumFitTests(unittest.TestCase):
    def test_row_and_fold_accounting_is_exhaustive(self) -> None:
        result = fit_dataset(synthetic_frame(), dataset())
        self.assertEqual(result["accounting"]["rows_total"], 73)
        self.assertEqual(result["accounting"]["rows_retained"], 72)
        self.assertEqual(result["accounting"]["rows_excluded_analyze_or_roi"], 1)
        self.assertEqual(len(result["candidates"]), 2)
        self.assertFalse(result["candidate_winner_selected"])
        for candidate in result["candidates"]:
            self.assertEqual(candidate["aggregate"]["folds_total"], 3)
            self.assertEqual(candidate["aggregate"]["folds_evaluated"], 3)
            self.assertEqual(
                {fold["held_out_animal"] for fold in candidate["folds"]}, {"a", "b", "c"}
            )

    def test_prediction_resets_at_every_trial_boundary(self) -> None:
        prepared = prepare_frame(synthetic_frame(), dataset()).frame
        candidate = candidates_for(dataset())[0]
        combined = add_candidate_prediction(prepared, candidate)
        for _, group in prepared.groupby(["animal_id", "trial", "roi"], sort=False):
            local = add_candidate_prediction(group.reset_index(drop=True), candidate)
            self.assertTrue(np.allclose(combined[group.index], local))

    def test_padded_claw_recipe_exposes_five_fitted_coefficients(self) -> None:
        claw_dataset = {
            "dataset_id": "claw-fixture",
            "functional_class": "claw_position",
            "roi_contains": "L1_medial",
            "candidates": [
                {
                    "id": "padded_quartic",
                    "fit_kind": "quartic_gcamp_padded",
                    "model_type": "claw",
                    "sampling_policy": "fixed_8_01_hz_from_imaging_poly_fun",
                    "grouping_policy": "per_animal_trial_roi",
                    "claw_center_deg": 90,
                    "pad_first_sample": 1000,
                }
            ],
        }
        result = fit_dataset(synthetic_frame(), claw_dataset)["candidates"][0]
        self.assertEqual(result["parameters_per_fold"], 5)
        self.assertEqual(result["aggregate"]["folds_evaluated"], 3)
        self.assertEqual(
            set(result["folds"][0]["fit"]),
            {"degree_4", "degree_3", "degree_2", "degree_1", "offset"},
        )

    def test_fewer_than_two_animals_is_blocked(self) -> None:
        frame = synthetic_frame()
        frame = frame.loc[frame["animal_id"].isin(["a", "excluded"])]
        with self.assertRaisesRegex(FeCOCalciumFitError, "at least two animals"):
            prepare_frame(frame, dataset())

    def test_missing_tables_produce_versionable_blocked_result(self) -> None:
        campaign = {
            "schema_version": 1,
            "id": "campaign.fixture",
            "primary_class": "local_interface",
            "optimization_exposure": "allowed",
            "behavior_targets": [],
            "topology_changes_allowed": False,
            "selection_policy": {"choose_winner": False},
            "fit": {"maximum_parameters_per_fold_candidate": 5},
            "inputs": {
                "datasets": [
                    {
                        "dataset_id": "missing",
                        "path": "data/raw/does-not-exist.parquet",
                        "sha256": "0" * 64,
                    }
                ]
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign_path = root / "campaign.yaml"
            campaign_path.write_text(yaml.safe_dump(campaign), encoding="utf-8")
            result = run(
                campaign_path=campaign_path,
                runner_path=root / "runner.yaml",
                output_root=root / "output",
            )
            self.assertEqual(result["status"], "blocked_missing_authenticated_tables")
            self.assertFalse(result["interpretation"]["biological_fit_completed"])
            self.assertFalse(result["accounting"]["candidate_winner_selected"])
            self.assertTrue((root / "runner.yaml").is_file())
            self.assertFalse((root / "output").exists())


if __name__ == "__main__":
    unittest.main()

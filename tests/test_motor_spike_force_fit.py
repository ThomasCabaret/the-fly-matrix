from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import yaml

from the_fly_matrix.motor_spike_force_fit import (
    MotorSpikeForceFitError,
    fit_line_through_origin,
    fit_prepared,
    load_campaign,
    prepare_class,
    run,
)


def frame(functional_class: str) -> pd.DataFrame:
    rows = []
    for index in range(1, 7):
        row = {
            "cell_id": "one-cell",
            "trial_id": f"trial-{index}",
            "functional_class": functional_class,
            "peak_displacement_um": float(index * 2),
            "peak_error_source_unit": 1.0,
            "probe_position_source_value": 0.0,
            "num_spikes": float(index),
            "firing_rate_hz": 30.0 + 2.0 * index,
            "rest_rate_hz": 30.0,
            "step_index": 14.0 + index,
        }
        rows.append(row)
    return pd.DataFrame(rows)


class MotorSpikeForceFitTests(unittest.TestCase):
    def test_line_through_origin_recovers_exact_slope(self) -> None:
        x = np.asarray([1.0, 2.0, 4.0, 8.0])
        self.assertAlmostEqual(fit_line_through_origin(x, 3.25 * x), 3.25)

    def test_fast_filter_and_force_units_are_explicit(self) -> None:
        campaign = load_campaign()
        source = frame("fast_81A07")
        excluded = source.iloc[[0]].copy()
        excluded["trial_id"] = "excluded"
        excluded["num_spikes"] = 31
        prepared = prepare_class(
            pd.concat([source, excluded], ignore_index=True), "fast_81A07", campaign
        )
        self.assertEqual(prepared.accounting["rows_total"], 7)
        self.assertEqual(prepared.accounting["rows_retained"], 6)
        self.assertEqual(
            prepared.fit_status, "derived_line_through_origin_diagnostic_extension"
        )
        np.testing.assert_allclose(
            prepared.frame["peak_force_uN"], source["peak_displacement_um"] * 0.2234
        )

    def test_slow_source_proxy_and_bootstrap_are_reproducible(self) -> None:
        campaign = load_campaign()
        prepared = prepare_class(frame("slow_35C09"), "slow_35C09", campaign)
        np.testing.assert_allclose(
            prepared.frame["spike_count_for_fit"], np.arange(1.0, 7.0)
        )
        first = fit_prepared(prepared, campaign)
        second = fit_prepared(prepared, campaign)
        self.assertEqual(first, second)
        self.assertEqual(first["fit_status"], "source_reproduction_line_through_origin")
        self.assertEqual(first["promoted_parameter_values"], 0)
        self.assertIn(
            "not_trial_or_population_uncertainty",
            first["aggregate_row_bootstrap"]["interpretation"],
        )

    def test_schema_and_one_cell_boundary_fail_loudly(self) -> None:
        campaign = load_campaign()
        with self.assertRaisesRegex(MotorSpikeForceFitError, "missing columns"):
            prepare_class(frame("fast_81A07").drop(columns=["peak_displacement_um"]), "fast_81A07", campaign)
        mixed = frame("fast_81A07")
        mixed.loc[0, "cell_id"] = "second-cell"
        with self.assertRaisesRegex(MotorSpikeForceFitError, "exactly one"):
            prepare_class(mixed, "fast_81A07", campaign)

    def test_missing_parser_manifest_produces_versionable_blocked_result(self) -> None:
        campaign = load_campaign()
        campaign["inputs"]["normalized_manifest"] = "data/derived/definitely-absent.yaml"
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            campaign_path = root / "campaign.yaml"
            campaign_path.write_text(yaml.safe_dump(campaign), encoding="utf-8")
            result = run(
                campaign_path=campaign_path,
                runner_path=root / "runner.yaml",
                output_root=root / "output",
            )
            self.assertEqual(result["status"], "blocked_missing_versioned_parser_manifest")
            self.assertEqual(result["accounting"]["parameter_values_promoted"], 0)
            self.assertFalse(result["interpretation"]["twitch_kernel_identified"])
            self.assertTrue((root / "runner.yaml").is_file())
            self.assertFalse((root / "output").exists())


if __name__ == "__main__":
    unittest.main()

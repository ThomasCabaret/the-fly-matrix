from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import yaml

from the_fly_matrix.motor_source_contract import (
    MotorSourceContractError,
    inspect_force_rules,
    load_campaign,
    parse_cohort,
    run,
    verify_sources,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "data" / "raw" / "calibration" / "front-leg-local-v0" / "motor-source"


class MotorSourceContractTests(unittest.TestCase):
    def test_exact_source_snapshots_and_campaign_boundaries(self) -> None:
        campaign = load_campaign()
        verified = verify_sources(campaign)
        self.assertEqual(len(verified), 5)
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertEqual(campaign["capacity_policy"]["optimized_parameters"], 0)

    def test_source_cohort_and_selected_pilot_trials_are_exhaustive(self) -> None:
        source = (SOURCE_ROOT / "Dataset3_SlowInterFast_ForcePerSpike.m").read_text(
            encoding="utf-8"
        )
        rows = parse_cohort(source)
        counts = {label: sum(row["cell_label"] == label for row in rows) for label in ("fast", "intermediate", "slow")}
        self.assertEqual(counts, {"fast": 7, "intermediate": 7, "slow": 9})
        by_id = {row["cell_id"]: row for row in rows}
        self.assertEqual(by_id["171102_F2_C1"]["trial_count"], 127)
        self.assertEqual(by_id["180222_F1_C1"]["trial_count"], 29)
        self.assertEqual(by_id["180111_F2_C1"]["trial_count"], 38)
        self.assertEqual(sum(by_id[cell]["trial_count"] for cell in ("171102_F2_C1", "180222_F1_C1", "180111_F2_C1")), 194)

    def test_force_rules_preserve_units_and_limitations(self) -> None:
        rules = inspect_force_rules(
            (SOURCE_ROOT / "Script_forcePerSpike.m").read_text(encoding="utf-8"),
            (SOURCE_ROOT / "Script_forcePerSpikeAndFiringRate.m").read_text(encoding="utf-8"),
            (SOURCE_ROOT / "Methods_ForceProbeCalibration.m").read_text(encoding="utf-8"),
            (SOURCE_ROOT / "README.txt").read_text(encoding="utf-8"),
        )
        self.assertEqual(rules["force_probe_spring_constant_N_per_m"], 0.2234)
        self.assertEqual(rules["slow_count_proxy"]["stimulus_duration_s"], 0.5)
        self.assertEqual(rules["probe_calibration"]["displacement_input_scale_to_m"], 1e-6)
        self.assertFalse(rules["twitch_time_course_fit_defined_by_these_five_files"])

    def test_source_hash_drift_is_rejected(self) -> None:
        campaign = load_campaign()
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            source = root / "source.m"
            source.write_text("drift", encoding="utf-8")
            mutated = dict(campaign)
            mutated["inputs"] = dict(campaign["inputs"])
            mutated["inputs"]["source_files"] = [
                {"path": str(source), "sha256": "0" * 64, "role": "fixture"}
            ]
            with self.assertRaisesRegex(MotorSourceContractError, "source hash drift"):
                verify_sources(mutated)

    def test_repository_contract_runs_without_raw_archives_or_promotion(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            result = run(runner_path=root / "runner.yaml", output_root=root / "output")
            self.assertEqual(result["status"], "accepted_source_contract_raw_fit_blocked")
            self.assertEqual(result["accounting"]["cohort_cells"], 23)
            self.assertEqual(result["accounting"]["selected_pilot_trials"], 194)
            self.assertEqual(result["accounting"]["promoted_parameter_values"], 0)
            self.assertFalse(result["interpretation"]["raw_variable_schema_identified"])
            self.assertTrue((root / "runner.yaml").is_file())
            self.assertTrue((root / "output" / "source-cohort.csv").is_file())


if __name__ == "__main__":
    unittest.main()

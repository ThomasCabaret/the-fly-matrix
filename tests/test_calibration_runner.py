from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

import yaml

from the_fly_matrix.calibration_runner import (
    CalibrationRunnerError,
    run_job,
    validate_job,
)
from the_fly_matrix.ledger import ROOT


class CalibrationRunnerTests(unittest.TestCase):
    def _base_job(self, evaluator_id: str = "test.evaluator") -> dict:
        input_path = ROOT / "calibration" / "README.md"
        return {
            "schema_version": 1,
            "id": "runner_validation.test.v0",
            "record_kind": "runner_validation",
            "status": "runnable",
            "claim_label": "TEST ONLY / NOT CALIBRATION",
            "mode": "validation",
            "primary_class": "technical",
            "optimization_exposure": "diagnostic_only",
            "behavior_targeted": False,
            "target_ids": [],
            "parameter_family_ids": [],
            "parent_parameter_set_ids": [],
            "output_parameter_set_id": None,
            "topology_boundary": {"semantic_topology_hashes": {}},
            "input_files": [
                {
                    "path": "calibration/README.md",
                    "sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
                }
            ],
            "evaluator_id": evaluator_id,
            "repeat_each": 1,
            "trials": [
                {
                    "case_id": "case-a",
                    "seed": 1,
                    "args": {"outcome": "pass"},
                    "gates": {"score": {"operator": "eq", "value": 1}},
                },
                {
                    "case_id": "case-b",
                    "seed": 2,
                    "args": {"outcome": "reject"},
                    "gates": {"score": {"operator": "eq", "value": 1}},
                },
                {
                    "case_id": "case-c",
                    "seed": 3,
                    "args": {"outcome": "error"},
                    "gates": {"score": {"operator": "eq", "value": 1}},
                },
            ],
            "budget": {"max_trials": 3, "max_wall_seconds": 10},
            "scenario_splits": {
                "train": [],
                "validation": [],
                "diagnostic": [],
                "held_out": [],
                "behavior_held_out": [],
            },
            "acceptance": {"criteria_locked_before_run": True},
        }

    @staticmethod
    def _evaluator(trial: dict) -> dict:
        outcome = trial["args"]["outcome"]
        if outcome == "error":
            raise RuntimeError("deliberate test failure")
        return {"score": 1 if outcome == "pass" else 0}

    def test_runner_accounts_for_acceptance_rejection_and_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_path = root / "job.yaml"
            job_path.write_text(yaml.safe_dump(self._base_job()), encoding="utf-8")
            summary = run_job(
                job_path,
                root / "runs",
                evaluators={"test.evaluator": self._evaluator},
            )
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["trial_accounting"]["scheduled"], 3)
            self.assertEqual(summary["trial_accounting"]["accounted"], 3)
            self.assertEqual(summary["trial_accounting"]["unaccounted"], 0)
            self.assertEqual(
                summary["trial_accounting"]["by_status"],
                {"accepted": 1, "error": 1, "rejected": 1},
            )

    def test_non_evaluation_job_cannot_access_held_out_scenarios(self) -> None:
        job = self._base_job()
        job["scenario_splits"]["held_out"] = ["forbidden-scenario"]
        with self.assertRaisesRegex(CalibrationRunnerError, "cannot access held-out"):
            validate_job(job, Path("test-job.yaml"))

    def test_real_runner_validation_is_reproducible(self) -> None:
        job_path = ROOT / "calibration" / "runner" / "peripheral-compiler-validation-v0.yaml"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = run_job(job_path, root / "first")
            second = run_job(job_path, root / "second")
            self.assertEqual(first["status"], "passed")
            self.assertEqual(second["status"], "passed")
            self.assertEqual(first["trial_accounting"]["scheduled"], 6)
            self.assertEqual(first["trial_accounting"]["unaccounted"], 0)
            self.assertEqual(
                first["semantic_result_sha256"], second["semantic_result_sha256"]
            )

    def test_infrastructure_evaluator_cannot_be_reused_for_fitting(self) -> None:
        source = ROOT / "calibration" / "runner" / "peripheral-compiler-validation-v0.yaml"
        job = yaml.safe_load(source.read_text(encoding="utf-8"))
        job["record_kind"] = "calibration_campaign"
        job["mode"] = "fit"
        job["output_parameter_set_id"] = "parameters.forbidden.test.v0"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_path = root / "job.yaml"
            job_path.write_text(yaml.safe_dump(job), encoding="utf-8")
            with self.assertRaisesRegex(CalibrationRunnerError, "not permitted"):
                run_job(job_path, root / "runs")

    def test_unfitted_characterizer_cannot_be_reused_for_fitting(self) -> None:
        source = (
            ROOT
            / "calibration"
            / "runner"
            / "central-unfitted-characterization-v0.yaml"
        )
        job = yaml.safe_load(source.read_text(encoding="utf-8"))
        job["mode"] = "fit"
        job["output_parameter_set_id"] = "parameters.forbidden.diagnostic.v0"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_path = root / "job.yaml"
            job_path.write_text(yaml.safe_dump(job), encoding="utf-8")
            with self.assertRaisesRegex(CalibrationRunnerError, "not permitted"):
                run_job(job_path, root / "runs")

    def test_runtime_metrics_can_be_retained_but_excluded_from_semantic_hash(self) -> None:
        counter = {"value": 0}

        def evaluator(trial: dict) -> dict:
            counter["value"] += 1
            return {"score": 1, "runtime_seconds": float(counter["value"])}

        job = self._base_job()
        job["trials"] = [job["trials"][0]]
        job["budget"]["max_trials"] = 1
        job["semantic_metric_exclusions"] = ["runtime_seconds"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_path = root / "job.yaml"
            job_path.write_text(yaml.safe_dump(job), encoding="utf-8")
            first = run_job(
                job_path, root / "first", evaluators={"test.evaluator": evaluator}
            )
            second = run_job(
                job_path, root / "second", evaluators={"test.evaluator": evaluator}
            )
            self.assertEqual(first["semantic_result_sha256"], second["semantic_result_sha256"])
            self.assertNotEqual(
                first["trials"][0]["metrics"]["runtime_seconds"],
                second["trials"][0]["metrics"]["runtime_seconds"],
            )

    def test_gated_metric_cannot_be_semantically_excluded(self) -> None:
        job = self._base_job()
        job["semantic_metric_exclusions"] = ["score"]
        with self.assertRaisesRegex(CalibrationRunnerError, "Gated metrics cannot"):
            validate_job(job, Path("test-job.yaml"))

    def test_float_semantics_can_use_declared_significant_digits(self) -> None:
        counter = {"value": 0}

        def evaluator(trial: dict) -> dict:
            counter["value"] += 1
            jitter = 0.0000002 * counter["value"]
            return {"score": 1, "diagnostic": 1.2344 + jitter}

        job = self._base_job()
        job["trials"] = [job["trials"][0]]
        job["budget"]["max_trials"] = 1
        job["semantic_float_significant_digits"] = 4
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_path = root / "job.yaml"
            job_path.write_text(yaml.safe_dump(job), encoding="utf-8")
            first = run_job(
                job_path, root / "first", evaluators={"test.evaluator": evaluator}
            )
            second = run_job(
                job_path, root / "second", evaluators={"test.evaluator": evaluator}
            )
            self.assertEqual(first["semantic_result_sha256"], second["semantic_result_sha256"])
            self.assertNotEqual(
                first["trials"][0]["metrics"]["diagnostic"],
                second["trials"][0]["metrics"]["diagnostic"],
            )


if __name__ == "__main__":
    unittest.main()

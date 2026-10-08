from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

import yaml

from the_fly_matrix.motor_pilot_inventory import (
    MotorPilotInventoryError,
    inspect_zip,
    load_campaign,
    load_class_ensemble,
    run,
)


def _campaign(archives: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "id": "campaign.fixture",
        "primary_class": "local_interface",
        "optimization_exposure": "diagnostic_only",
        "behavior_targets": [],
        "topology_changes_allowed": False,
        "capacity_policy": {"optimized_parameters": 0},
        "inputs": {"archives": archives},
    }


class MotorPilotInventoryTests(unittest.TestCase):
    def test_repository_campaign_and_factorized_ensemble_are_exhaustive(self) -> None:
        campaign = load_campaign()
        ensemble = load_class_ensemble()
        self.assertEqual(len(campaign["inputs"]["archives"]), 3)
        self.assertEqual(len(ensemble["members"]), 10)
        self.assertEqual(ensemble["factorized_assignment_upper_bound"], 59_049)
        self.assertTrue(all(item["selected_class"] is None for item in ensemble["members"]))

    def test_zip_inventory_reads_headers_without_extracting(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "fixture.zip"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("cell/trial.mat", b"MATLAB 5.0 MAT-file" + b"\0" * 200)
                archive.writestr("cell/trace.abf", b"ABF2" + b"\0" * 200)
                archive.writestr("README.txt", b"fixture")
            result = inspect_zip(path)
            self.assertEqual(result["members_total"], 3)
            self.assertEqual(result["data_like_members"], 2)
            self.assertEqual(result["format_counts"]["matlab_v5"], 1)
            self.assertEqual(result["format_counts"]["axon_abf"], 1)
            self.assertEqual(result["extracted_files"], 0)
            self.assertLessEqual(max(item["header_bytes_read"] for item in result["members"]), 128)

    def test_zip_slip_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "unsafe.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("../outside.mat", b"MATLAB 5.0 MAT-file")
            with self.assertRaisesRegex(MotorPilotInventoryError, "unsafe ZIP member"):
                inspect_zip(path)

    def test_missing_archives_produce_versionable_blocked_result(self) -> None:
        classes = ("fast_81A07", "intermediate_22A08", "slow_35C09")
        archives = [
            {
                "functional_class": class_name,
                "path": f"missing/{index}.zip",
                "expected_bytes": 1,
                "sha256": hashlib.sha256(b"x").hexdigest(),
            }
            for index, class_name in enumerate(classes)
        ]
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            campaign_path = root / "campaign.yaml"
            campaign_path.write_text(yaml.safe_dump(_campaign(archives)), encoding="utf-8")
            result = run(
                campaign_path=campaign_path,
                runner_path=root / "runner.yaml",
                output_root=root / "output",
            )
            self.assertEqual(result["status"], "blocked_missing_authenticated_archives")
            self.assertEqual(len(result["accounting"]["archives_blocked"]), 3)
            self.assertEqual(result["accounting"]["parameter_values_promoted"], 0)
            self.assertFalse(result["interpretation"]["body_level_crosswalk_resolved"])
            self.assertTrue((root / "runner.yaml").is_file())
            self.assertFalse((root / "output").exists())


if __name__ == "__main__":
    unittest.main()

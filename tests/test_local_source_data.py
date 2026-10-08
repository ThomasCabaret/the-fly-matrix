from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

import yaml

from the_fly_matrix.local_source_data import (
    SourceFile,
    build_source_plan,
    verify_source_file,
)


class LocalSourceDataTests(unittest.TestCase):
    def test_repository_manifest_is_exhaustive_and_byte_accounted(self) -> None:
        plan = build_source_plan()
        self.assertEqual(len(plan), 12)
        feco = [item for item in plan if item.group == "feco"]
        motor = [item for item in plan if item.group == "motor"]
        self.assertEqual(len(feco), 7)
        self.assertEqual(len(motor), 5)
        self.assertEqual(sum(item.expected_bytes for item in feco), 2_025_899)
        self.assertEqual(sum(item.expected_bytes for item in motor), 860_450_999)
        self.assertEqual(sum(item.optional_large for item in motor), 3)
        self.assertFalse(any(item.optional_large for item in feco))

    def test_exact_size_and_hash_are_both_required(self) -> None:
        payload = b"calcium-observation-not-spikes"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.bin"
            path.write_bytes(payload)
            source = SourceFile(
                dataset_id="fixture",
                functional_class="fixture",
                path=path,
                url="https://invalid.example/fixture",
                expected_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                group="feco",
                optional_large=False,
            )
            self.assertEqual(verify_source_file(source), (True, "verified"))
            path.write_bytes(payload + b"x")
            verified, status = verify_source_file(source)
            self.assertFalse(verified)
            self.assertTrue(status.startswith("size_mismatch:"))

    def test_missing_file_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = SourceFile(
                dataset_id="missing",
                functional_class="fixture",
                path=Path(directory) / "missing.bin",
                url="https://invalid.example/missing",
                expected_bytes=1,
                sha256="0" * 64,
                group="motor",
                optional_large=True,
            )
            self.assertEqual(verify_source_file(source), (False, "missing"))

    def test_tracked_acquisition_result_records_no_credential(self) -> None:
        result_path = Path("calibration/runner/front-leg-local-source-data-v0.yaml")
        result_text = result_path.read_text(encoding="utf-8")
        result = yaml.safe_load(result_text)
        self.assertEqual(result["accounting"]["files_verified"], 9)
        self.assertEqual(result["accounting"]["feco_tables_verified"], 3)
        self.assertEqual(result["accounting"]["feco_rows_inspected"], 64_300)
        self.assertEqual(result["accounting"]["motor_large_archives_downloaded"], 0)
        self.assertFalse(result["authentication"]["credential_recorded_in_result"])
        self.assertNotIn("DRYAD_BEARER_TOKEN=", result_text)
        self.assertNotIn("Authorization: Bearer", result_text)


if __name__ == "__main__":
    unittest.main()

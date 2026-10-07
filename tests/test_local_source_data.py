from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()

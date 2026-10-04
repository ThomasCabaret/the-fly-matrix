from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from the_fly_matrix.basal_evidence import RECIPE_PATH, compile_basal_evidence


class BasalEvidenceTests(unittest.TestCase):
    def test_compiler_accounts_every_channel_without_emitting_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            summary = compile_basal_evidence(RECIPE_PATH, output)
            self.assertEqual(summary["totals"]["families"], 6)
            self.assertEqual(summary["totals"]["channels"], 2_212)
            self.assertEqual(summary["totals"]["terminals"], 6_041)
            self.assertEqual(summary["totals"]["numeric_transfer_ready_channels"], 0)
            self.assertEqual(summary["totals"]["numeric_parameter_values_emitted"], 0)
            self.assertEqual(summary["runtime_unit_contract"]["bridge_status"], "missing")

            with (output / "channel-evidence-coverage.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2_212)
            self.assertTrue(
                all(row["numeric_parameter_value_emitted"] == "False" for row in rows)
            )
            self.assertEqual(len({row["channel_id"] for row in rows}), 2_212)

    def test_compiler_is_semantically_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = compile_basal_evidence(RECIPE_PATH, Path(first_dir))
            second = compile_basal_evidence(RECIPE_PATH, Path(second_dir))
            self.assertEqual(
                first["semantic_result_sha256"], second["semantic_result_sha256"]
            )


if __name__ == "__main__":
    unittest.main()

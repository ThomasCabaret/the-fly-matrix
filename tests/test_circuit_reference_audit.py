from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from the_fly_matrix.circuit_reference_audit import (
    RECIPE_PATH,
    audit_circuit_reference,
)


class CircuitReferenceAuditTests(unittest.TestCase):
    def test_identity_audit_is_partial_and_selects_no_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = Path(directory) / "result.yaml"
            summary = audit_circuit_reference(
                RECIPE_PATH,
                Path(directory) / "derived",
                result,
                scan_connectivity=False,
            )
            self.assertEqual(summary["status"], "partial_mapping_abn2_unresolved")
            self.assertEqual(summary["malecns"]["missing_abn2_types"], ["CB3129"])
            self.assertEqual(summary["malecns"]["group_counts"]["aBN1"], 2)
            self.assertEqual(summary["malecns"]["group_counts"]["aBN2_resolved_subset"], 4)
            self.assertFalse(summary["behavior_exposure"]["behavior_targeted"])
            self.assertFalse(summary["behavior_exposure"]["currently_contaminated"])
            self.assertTrue(result.is_file())

    def test_identity_audit_is_semantically_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            one = audit_circuit_reference(
                RECIPE_PATH,
                Path(first) / "derived",
                Path(first) / "result.yaml",
                scan_connectivity=False,
            )
            two = audit_circuit_reference(
                RECIPE_PATH,
                Path(second) / "derived",
                Path(second) / "result.yaml",
                scan_connectivity=False,
            )
            self.assertEqual(one["semantic_result_sha256"], two["semantic_result_sha256"])


if __name__ == "__main__":
    unittest.main()

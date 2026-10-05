from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from the_fly_matrix.abn1_reference_lock import audit_lock


class Abn1ReferenceLockTests(unittest.TestCase):
    def test_locked_scope_excludes_unresolved_abn2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = audit_lock(
                scan_connectivity=False,
                output_root=Path(directory) / "derived",
                result_path=Path(directory) / "result.yaml",
            )
        self.assertEqual(result["status"], "protocol_locked_execution_pending")
        self.assertEqual(result["mapping"]["group_counts"]["JO_CE"], 335)
        self.assertEqual(result["mapping"]["group_counts"]["JO_F"], 78)
        self.assertEqual(result["mapping"]["group_counts"]["aBN1"], 2)
        self.assertIn("aBN2", result["excluded"])
        self.assertEqual(result["direction"], "JO_CE_above_JO_F")
        self.assertFalse(result["scientific_model_class_gate_closed"])


if __name__ == "__main__":
    unittest.main()

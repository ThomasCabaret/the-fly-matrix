from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import yaml
from scipy import sparse

from the_fly_matrix.first_held_out_control_recalibration import (
    HeldOutControlRecalibrationError,
    replace_cone_recurrence,
)


class FirstHeldOutControlRecalibrationTests(unittest.TestCase):
    def test_replacement_preserves_source_boundary_and_changes_only_recurrence(self) -> None:
        source_to_cone = sparse.csr_matrix(np.array([[1.0, 0.0], [0.0, 2.0]]))
        canonical = sparse.csr_matrix(np.array([[0.0, 3.0], [4.0, 0.0]]))
        replacement = sparse.csr_matrix(np.array([[0.0, 4.0], [3.0, 0.0]]))
        graph = sparse.bmat(
            [
                [sparse.csr_matrix((2, 2)), sparse.csr_matrix((2, 2))],
                [source_to_cone, canonical],
            ],
            format="csr",
        )
        result = replace_cone_recurrence(
            graph,
            source_count=2,
            canonical_cone=canonical,
            replacement_cone=replacement,
        )
        np.testing.assert_array_equal(result[2:, :2].toarray(), source_to_cone.toarray())
        np.testing.assert_array_equal(result[2:, 2:].toarray(), replacement.toarray())
        self.assertEqual(result[:2, :].nnz, 0)

    def test_replacement_rejects_canonical_context_drift(self) -> None:
        canonical = sparse.eye(2, format="csr")
        graph = sparse.csr_matrix((4, 4))
        with self.assertRaises(HeldOutControlRecalibrationError):
            replace_cone_recurrence(
                graph,
                source_count=2,
                canonical_cone=canonical,
                replacement_cone=canonical,
            )

    def test_replacement_rejects_shape_drift(self) -> None:
        canonical = sparse.eye(2, format="csr")
        graph = sparse.block_diag((sparse.csr_matrix((1, 1)), canonical), format="csr")
        with self.assertRaises(HeldOutControlRecalibrationError):
            replace_cone_recurrence(
                graph,
                source_count=1,
                canonical_cone=canonical,
                replacement_cone=sparse.eye(3, format="csr"),
            )

    def test_committed_result_accounts_every_control_without_outcomes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = yaml.safe_load(
            (root / "calibration/runner/first-held-out-control-recalibration-v1.yaml").read_text(
                encoding="utf-8"
            )
        )
        controls = result["rewire_controls"]
        self.assertEqual([row["rewire_seed"] for row in controls], [81701, 81702, 81703, 81704])
        self.assertEqual([row["fh07b_accepted_members"] for row in controls], [14, 15, 4, 8])
        self.assertEqual(sum(row["fh07b_accepted_members"] for row in controls), 41)
        self.assertTrue(all(row["held_out_outcomes_consumed"] == 0 for row in controls))
        self.assertEqual(result["accounting"]["failed_control_calibrations"], 0)
        self.assertEqual(result["accounting"]["held_out_outcomes_consumed"], 0)
        self.assertFalse(result["members_ranked"])
        self.assertEqual(result["parameter_values_promoted"], 0)


if __name__ == "__main__":
    unittest.main()

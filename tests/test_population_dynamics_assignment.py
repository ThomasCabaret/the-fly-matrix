from __future__ import annotations

import csv
import hashlib
import tempfile
import unittest
from pathlib import Path

from the_fly_matrix.population_dynamics_assignment import (
    RECIPE_PATH,
    compile_population_dynamics_assignments,
)


class PopulationDynamicsAssignmentTests(unittest.TestCase):
    def test_front_leg_scope_is_exhaustive_without_values_or_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            summary = compile_population_dynamics_assignments(RECIPE_PATH, output)

            self.assertEqual(summary["totals"]["populations"], 2)
            self.assertEqual(summary["totals"]["neurons"], 46)
            self.assertEqual(summary["totals"]["event_required_neurons"], 10)
            self.assertEqual(summary["totals"]["dual_unresolved_neurons"], 36)
            self.assertEqual(summary["totals"]["graded_required_neurons"], 0)
            self.assertEqual(summary["totals"]["parameter_values_emitted"], 0)
            self.assertEqual(summary["totals"]["unmatched_neurons"], 0)
            self.assertFalse(summary["behavior_exposure"]["behavior_targeted"])

            with (output / "population-members.csv").open(
                encoding="utf-8", newline=""
            ) as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 46)
            self.assertEqual(len({row["body_id"] for row in rows}), 46)
            self.assertTrue(all(row["parameter_value_emitted"] == "False" for row in rows))

    def test_front_leg_assignment_is_semantically_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_summary = compile_population_dynamics_assignments(
                RECIPE_PATH, Path(first)
            )
            second_summary = compile_population_dynamics_assignments(
                RECIPE_PATH, Path(second)
            )
            self.assertEqual(
                first_summary["semantic_result_sha256"],
                second_summary["semantic_result_sha256"],
            )

    def test_recipe_hash_is_the_registered_execution_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = compile_population_dynamics_assignments(
                RECIPE_PATH, Path(directory)
            )
        self.assertEqual(
            summary["recipe_sha256"],
            hashlib.sha256(RECIPE_PATH.read_bytes()).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()

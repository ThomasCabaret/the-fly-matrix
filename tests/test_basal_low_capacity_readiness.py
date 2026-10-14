from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from the_fly_matrix.basal_low_capacity_readiness import run_readiness


class BasalLowCapacityReadinessTests(unittest.TestCase):
    def test_compiler_accounts_for_every_family_without_emitting_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result_path = root / "result.yaml"
            evaluation_path = root / "evaluation.yaml"
            design_path = root / "design.yaml"
            result = run_readiness(
                result_path=result_path,
                evaluation_path=evaluation_path,
                design_path=design_path,
            )
            design = yaml.safe_load(design_path.read_text(encoding="utf-8"))

        self.assertEqual(result["accounting"]["basal_families"], 6)
        self.assertEqual(result["accounting"]["basal_channels"], 2212)
        self.assertEqual(result["accounting"]["basal_terminals"], 6041)
        self.assertEqual(result["accounting"]["currently_accounted_local_population_neurons"], 196)
        self.assertEqual(result["accounting"]["currently_event_required_local_neurons"], 12)
        self.assertEqual(result["accounting"]["currently_dual_unresolved_local_neurons"], 184)
        self.assertEqual(result["accounting"]["basal_reached_population_neurons"], 166431)
        self.assertEqual(result["accounting"]["basal_reached_event_required_neurons"], 12)
        self.assertEqual(result["accounting"]["basal_reached_dual_unresolved_neurons"], 166419)
        self.assertEqual(result["numerical_basal_values_emitted"], 0)
        self.assertEqual(design["absolute_numeric_values"], [])
        self.assertTrue(design["applicability"]["whole_MaleCNS_mechanics_executable"])
        self.assertFalse(design["applicability"]["basal_arms_executable"])
        self.assertEqual(
            [arm["id"] for arm in design["arms"]],
            ["explicit_silence_control", "uniform_per_terminal", "equal_family_mass"],
        )

    def test_whole_graph_execution_is_blocked_for_explicit_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = run_readiness(
                result_path=root / "result.yaml",
                evaluation_path=root / "evaluation.yaml",
                design_path=root / "design.yaml",
            )

        self.assertEqual(
            result["whole_MaleCNS_execution_disposition"],
            "mechanics_executed_basal_inputs_not_executed",
        )
        self.assertEqual(
            set(result["blocker_ids"]),
            {
                "explicit_event_or_graded_unit_bridge_per_consumed_population",
            },
        )
        self.assertGreater(result["population_assignment_scope_fraction"], 0.998)


if __name__ == "__main__":
    unittest.main()

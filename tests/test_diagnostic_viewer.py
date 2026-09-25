from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from the_fly_matrix.diagnostics.viewer_demo import (
    DiagnosticDemoConfig,
    DiagnosticToyCNS,
    run_diagnostic_demo,
)
from the_fly_matrix.runtime import JointState


class DiagnosticToyCNSTests(unittest.TestCase):
    @staticmethod
    def joint_state(count: int = 6) -> JointState:
        return JointState(
            joint_names=tuple(f"joint-{index}" for index in range(count)),
            positions=np.linspace(-0.2, 0.2, count, dtype=np.float64),
            velocities=np.linspace(0.1, -0.1, count, dtype=np.float64),
        )

    def test_same_seed_replays_identically_and_remains_bounded(self) -> None:
        first = DiagnosticToyCNS(6, 8, seed=42, hidden_size=16)
        second = DiagnosticToyCNS(6, 8, seed=42, hidden_size=16)
        state = self.joint_state()
        for _ in range(50):
            first_output = first.step(state, 0.002)
            second_output = second.step(state, 0.002)
            self.assertTrue(np.array_equal(first_output, second_output))
            self.assertTrue(np.isfinite(first_output).all())
            self.assertLessEqual(float(np.abs(first_output).max()), 1.0)
        self.assertGreater(float(np.abs(first_output).max()), 0.0)

    def test_different_seeds_produce_different_signal(self) -> None:
        first = DiagnosticToyCNS(6, 8, seed=1, hidden_size=16)
        second = DiagnosticToyCNS(6, 8, seed=2, hidden_size=16)
        state = self.joint_state()
        self.assertFalse(np.array_equal(first.step(state, 0.002), second.step(state, 0.002)))

    def test_headless_demo_exercises_physics_without_scientific_claim(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "summary.json"
            result = run_diagnostic_demo(
                DiagnosticDemoConfig(
                    seed=7,
                    duration_seconds=0.01,
                    amplitude=0.001,
                    realtime_speed=0.0,
                    control_substeps=10,
                    hidden_size=16,
                    headless=True,
                    output=output,
                )
            )
            self.assertTrue(output.is_file())
        self.assertEqual(
            result["scientific_status"],
            "diagnostic_only_not_malecns_not_calibration",
        )
        self.assertIn("cns.malecns", result["bypassed_components"])
        self.assertGreaterEqual(result["result"]["simulation_seconds"], 0.01)
        self.assertTrue(result["result"]["finite_physics_state"])
        self.assertGreater(result["result"]["max_abs_command"], 0.0)
        self.assertGreater(result["result"]["max_abs_joint_delta"], 0.0)


if __name__ == "__main__":
    unittest.main()

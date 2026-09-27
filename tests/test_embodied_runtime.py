from __future__ import annotations

import unittest

from the_fly_matrix.embodied_runtime import ClosedLoopConfig


class ClosedLoopConfigTests(unittest.TestCase):
    def test_headless_run_requires_a_finite_duration(self) -> None:
        with self.assertRaises(ValueError):
            ClosedLoopConfig(duration_s=0, live_viewer=False)

    def test_live_run_can_be_unbounded_and_unrecorded(self) -> None:
        config = ClosedLoopConfig(duration_s=0, live_viewer=True, record=False)
        self.assertFalse(config.record)
        self.assertTrue(config.live_viewer)

    def test_command_envelope_is_bounded(self) -> None:
        with self.assertRaises(ValueError):
            ClosedLoopConfig(command_scale=0.1)


if __name__ == "__main__":
    unittest.main()

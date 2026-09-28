from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from the_fly_matrix.motor_output_revalidation import (
    _actuator_side,
    _leg_position,
    _select_actuators,
    build_motor_output_envelope,
    compare_motor_output_with_prewiring,
)


class MotorOutputRevalidationTests(unittest.TestCase):
    def test_actuator_anatomy_parser(self) -> None:
        self.assertEqual(_actuator_side("c_thorax-lf_coxa-yaw-motor"), "L")
        self.assertEqual(_actuator_side("c_thorax-r_wing-roll-motor"), "R")
        self.assertEqual(_actuator_side("c_thorax-c_head-yaw-motor"), "neutral")
        self.assertEqual(_leg_position("rf_tibia-rf_tarsus1-pitch-motor"), "front")
        self.assertEqual(_leg_position("c_thorax-lm_coxa-yaw-motor"), "middle")
        self.assertEqual(_leg_position("lh_coxa-lh_trochanterfemur-pitch-motor"), "hind")

    def test_local_selector_rejects_other_legs_and_sides(self) -> None:
        frame = pd.DataFrame(
            [
                {"actuator_id": 1, "actuator_name": "c_thorax-lf_coxa-yaw-motor", "body_group": "legs", "control_address": 1},
                {"actuator_id": 2, "actuator_name": "c_thorax-rf_coxa-yaw-motor", "body_group": "legs", "control_address": 2},
                {"actuator_id": 3, "actuator_name": "c_thorax-lm_coxa-yaw-motor", "body_group": "legs", "control_address": 3},
            ]
        )
        selected = _select_actuators(
            frame,
            {"body_group": "legs", "leg_position": "front", "side_policy": "same"},
            "L",
        )
        self.assertEqual(selected["actuator_id"].tolist(), [1])

    def test_real_clean_build_is_deterministic_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            one = build_motor_output_envelope(Path(first))
            two = build_motor_output_envelope(Path(second))
        self.assertEqual(one["terminal_count"], 815)
        self.assertEqual(one["group_count"], 441)
        self.assertEqual(one["covered_actuator_count"], 102)
        self.assertEqual(one["degrees_of_freedom"]["continuous_transfer_parameters"], 7849)
        self.assertEqual(one["semantic_topology_sha256"], two["semantic_topology_sha256"])
        self.assertTrue(one["negative_constraints"]["pass"])
        self.assertTrue(one["symmetry"]["pass"])
        self.assertFalse(one["accepted_for_calibration"])

    def test_current_prewiring_is_opened_only_after_clean_hash_and_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "clean"
            build_motor_output_envelope(output)
            result = compare_motor_output_with_prewiring(output)
        self.assertEqual(result["status"], "independently_validated")
        self.assertTrue(result["clean_rebuild_repeat"]["pass"])
        self.assertEqual(result["prewiring_comparison"]["confirmed_relations"], 7849)
        self.assertEqual(result["prewiring_comparison"]["missing_from_current"], 0)
        self.assertEqual(result["prewiring_comparison"]["extra_in_current"], 0)
        self.assertFalse(result["accepted_for_calibration"])


if __name__ == "__main__":
    unittest.main()

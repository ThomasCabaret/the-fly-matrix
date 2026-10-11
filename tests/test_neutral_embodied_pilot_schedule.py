from __future__ import annotations

import unittest

from the_fly_matrix.neutral_embodied_pilot_schedule import (
    CAMPAIGN_PATH,
    _load_axes,
    _load_yaml,
    _validate,
    build_schedule,
    evenly_spaced_indices,
)


class NeutralEmbodiedPilotScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.campaign = _load_yaml(CAMPAIGN_PATH)
        cls.axes = _load_axes(cls.campaign)
        cls.rows, cls.coverage = build_schedule(cls.campaign, cls.axes)

    def test_evenly_spaced_motor_sample_is_unique_and_includes_extremes(self) -> None:
        values = evenly_spaced_indices(1024, 120)
        self.assertEqual(len(values), len(set(values)))
        self.assertEqual((values[0], values[-1]), (0, 1023))

    def test_schedule_is_exact_bounded_and_paired(self) -> None:
        self.assertEqual(len(self.rows), 120)
        self.assertEqual(len({row["tuple_id"] for row in self.rows}), 120)
        self.assertEqual(len({row["seed"] for row in self.rows}), 120)
        self.assertEqual(self.coverage["paired_physical_episodes"], 240)
        self.assertEqual(
            self.coverage["full_executable_cartesian_product"], 405_504_000
        )

    def test_all_small_axes_are_covered_without_selecting_them(self) -> None:
        self.assertEqual(self.coverage["intermediate_profiles"]["unscheduled"], 0)
        self.assertEqual(self.coverage["feco_alternatives"]["unscheduled"], 0)
        self.assertEqual(self.coverage["route_basis_edges"]["unscheduled"], 0)
        self.assertEqual(self.coverage["bridge_gains"]["unscheduled"], 0)
        self.assertEqual(
            self.coverage["motor_assignments"]["kernel_executable_unscheduled"],
            904,
        )
        self.assertEqual(
            self.coverage["motor_assignments"]["blocked_slow_containing"],
            58_025,
        )

    def test_motor_panel_is_balanced_and_pairwise_complete(self) -> None:
        for counts in self.coverage["motor_assignments"]["per_body_class_counts"].values():
            self.assertEqual(counts, {"fast_81A07": 60, "intermediate_22A08": 60})
        self.assertEqual(
            self.coverage["motor_assignments"][
                "body_pairs_with_all_four_fast_intermediate_states"
            ],
            self.coverage["motor_assignments"]["body_pairs_total"],
        )

    def test_campaign_is_behavior_naive_zero_fit_and_valid(self) -> None:
        self.assertEqual(self.campaign["behavior_targets"], [])
        self.assertEqual(self.campaign["parameter_policy"]["optimized_parameters"], 0)
        self.assertFalse(
            self.campaign["schedule_policy"]["candidate_selection_from_body_motion"]
        )
        _validate(self.campaign, self.coverage)


if __name__ == "__main__":
    unittest.main()

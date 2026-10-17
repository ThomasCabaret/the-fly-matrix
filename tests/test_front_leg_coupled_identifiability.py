from __future__ import annotations

import itertools
import unittest

from the_fly_matrix.front_leg_coupled_identifiability import (
    build_owner_orthogonal_array,
    build_structural_schedule,
)


LEVELS = {
    "feco_native_amplitude": ["low", "mid", "high"],
    "basal_source_intensity": ["low", "mid", "high"],
    "same_native_efficacy": ["low", "mid", "high"],
    "cross_native_conversion": ["low", "mid", "high"],
    "threshold_distance": ["low", "mid", "high"],
    "unknown_afferent_policy": ["zero", "tonic", "stochastic"],
}


class FrontLegCoupledIdentifiabilityTests(unittest.TestCase):
    def test_owner_array_covers_every_pair_without_a_full_product(self) -> None:
        frame, summary = build_owner_orthogonal_array(LEVELS)
        self.assertEqual(len(frame), 27)
        self.assertEqual(summary["factor_pairs"], 15)
        self.assertTrue(summary["all_factor_pairs_cover_nine_combinations"])
        self.assertTrue(summary["all_pair_combinations_repeated_three_times"])
        for left, right in itertools.combinations(LEVELS, 2):
            counts = frame.groupby([left, right]).size()
            self.assertEqual(len(counts), 9)
            self.assertEqual(set(counts), {3})

    def test_structural_schedule_covers_both_required_pair_spaces(self) -> None:
        frame = build_structural_schedule(
            [f"routing_{index}" for index in range(27)],
            [f"native_{index}" for index in range(8)],
            [f"assignment_{index}" for index in range(50)],
        )
        self.assertEqual(
            len(frame[["routing_profile_id", "native_profile_id"]].drop_duplicates()),
            216,
        )
        self.assertEqual(
            len(frame[["intermediate_profile_id", "native_profile_id"]].drop_duplicates()),
            400,
        )
        self.assertLess(len(frame), 27 * 8 * 50)


if __name__ == "__main__":
    unittest.main()

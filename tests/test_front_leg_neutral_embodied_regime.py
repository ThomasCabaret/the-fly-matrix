from __future__ import annotations

import unittest

import numpy as np

from the_fly_matrix.front_leg_integrated_lineage import _load_yaml
from the_fly_matrix.front_leg_neutral_embodied_regime import (
    CAMPAIGN_PATH,
    RESULT_PATH,
    _MotorTonic,
)
from the_fly_matrix.front_leg_neutral_neural_regime import (
    build_pairwise_profiles,
    pairwise_coverage,
)
from the_fly_matrix.local_conversion import MotorTonicParameters, motor_events_to_tonic_force_uN


class FrontLegNeutralEmbodiedRegimeTests(unittest.TestCase):
    def test_locked_physical_design_is_pairwise_complete_and_covers_all_parents(self) -> None:
        campaign = _load_yaml(CAMPAIGN_PATH)
        result = _load_yaml(RESULT_PATH)
        profiles = build_pairwise_profiles(campaign["physical_factor_levels"])
        self.assertEqual(len(profiles), campaign["budget"]["expected_pairwise_profiles"])
        self.assertTrue(pairwise_coverage(profiles, campaign["physical_factor_levels"])["complete"])
        self.assertTrue(result["checks"]["all_neural_parent_rows_executed"])
        self.assertEqual(result["design"]["physical_composites"], len(profiles))
        self.assertEqual(len(result["rows"]), len(profiles))

    def test_streaming_slow_filter_matches_owned_batch_conversion(self) -> None:
        dt = 0.0001
        events = np.zeros((800, 1), dtype=np.int64)
        events[[0, 17, 251, 799], 0] = 1
        tau = 0.18
        delay = 0.005
        gain = 0.014
        bridge = 0.0002
        expected = motor_events_to_tonic_force_uN(
            events,
            MotorTonicParameters(
                np.asarray([gain]), np.asarray([tau]), np.asarray([delay])
            ),
            timestep_s=dt,
        )[:, 0]
        streaming = _MotorTonic(tau, delay, gain, dt, bridge)
        observed = np.asarray([streaming.step(int(value))[0] for value in events[:, 0]])
        np.testing.assert_allclose(observed, expected, rtol=0.0, atol=1e-12)

    def test_result_is_nonempty_unranked_and_accounts_guard_blocks(self) -> None:
        campaign = _load_yaml(CAMPAIGN_PATH)
        result = _load_yaml(RESULT_PATH)
        self.assertEqual(campaign["primary_class"], "technical")
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertGreater(result["accepted_rows"], 0)
        self.assertFalse(result["members_ranked"])
        self.assertFalse(result["reference_member_selected"])
        self.assertGreater(result["failure_counts"].get("direct_motor_guard", 0), 0)
        dispositions = {row["disposition"] for row in result["rows"]}
        self.assertEqual(
            dispositions,
            {"completed_four_branch_physical_probe", "blocked_preapplication_direct_motor_guard"},
        )
        self.assertTrue(all(row["classification"]["accepted"] is False for row in result["rows"] if row["disposition"].startswith("blocked")))


if __name__ == "__main__":
    unittest.main()

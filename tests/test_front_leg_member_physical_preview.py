from __future__ import annotations

import unittest

import numpy as np

from the_fly_matrix.front_leg_member_physical_preview import (
    _jsonable,
    _load_campaign,
    _trajectory_from_episode,
    _trajectory_semantic_hash,
)


class FrontLegMemberPhysicalPreviewTests(unittest.TestCase):
    def test_campaign_keeps_local_scope_and_human_checkpoint_explicit(self) -> None:
        campaign = _load_campaign()
        self.assertFalse(campaign["acceptance"]["whole_MaleCNS_claim_possible"])
        self.assertFalse(campaign["acceptance"]["whole_body_stability_claim_possible"])
        self.assertTrue(campaign["human_checkpoint"]["required_after_generation"])
        self.assertFalse(campaign["execution"]["default_is_scientific_selection"])

    def test_episode_conversion_preserves_physical_state_without_fake_neural_trace(self) -> None:
        episode = {
            "timestamps_s": np.asarray([0.005, 0.010]),
            "qpos": np.zeros((2, 4)),
            "qvel": np.zeros((2, 3)),
            "applied_commands": np.zeros((2, 2)),
            "joint_positions": np.zeros((2, 2)),
            "joint_velocities": np.zeros((2, 2)),
            "actuator_forces": np.zeros((2, 2)),
            "center_of_mass": np.zeros((2, 3)),
            "root_up_z": np.ones(2),
        }
        trajectory = _trajectory_from_episode(
            episode,
            model={
                "nq": 4,
                "nv": 3,
                "nu": 2,
                "actuator_names": ["a", "b"],
                "contract_sha256": "fixture",
            },
            metadata={"claim_label": "LOCAL TEST"},
        )
        self.assertEqual(trajectory.frame_count, 2)
        self.assertEqual(trajectory.neural_summary.shape, (2, 0))
        self.assertEqual(trajectory.sensory_observations["root_up_z"].shape, (2, 1))
        self.assertEqual(
            _trajectory_semantic_hash(trajectory, "member-a"),
            _trajectory_semantic_hash(trajectory, "member-a"),
        )

    def test_measurement_metadata_is_converted_to_strict_json_values(self) -> None:
        converted = _jsonable({"vector": np.asarray([1, 2]), "scalar": np.float64(3.0)})
        self.assertEqual(converted, {"vector": [1, 2], "scalar": 3.0})


if __name__ == "__main__":
    unittest.main()

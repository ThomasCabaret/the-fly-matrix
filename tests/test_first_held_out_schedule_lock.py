from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from the_fly_matrix.first_held_out_schedule_lock import (
    CAMPAIGN_PATH,
    HeldOutScheduleLockError,
    _control_members,
    _load_yaml,
    build_v2_schedule,
    compile_schedule_lock,
)


class FirstHeldOutScheduleLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = CAMPAIGN_PATH.parents[2]
        self.campaign = _load_yaml(CAMPAIGN_PATH)
        self.protocol = _load_yaml(
            self.root / self.campaign["frozen_inputs"]["protocol_v2"]["path"]
        )
        self.base_protocol = _load_yaml(
            self.root / self.campaign["frozen_inputs"]["base_protocol_v1"]["path"]
        )
        self.preflight = _load_yaml(
            self.root / self.campaign["frozen_inputs"]["preflight_v1"]["path"]
        )
        self.control_result = _load_yaml(
            self.root / self.campaign["frozen_inputs"]["control_recalibration"]["path"]
        )
        self.control_parameters = _load_yaml(
            self.root / self.campaign["frozen_inputs"]["control_parameter_set"]["path"]
        )
        canonical = _load_yaml(
            self.root / self.campaign["frozen_inputs"]["canonical_parameter_set"]["path"]
        )
        self.canonical_members = list(map(str, canonical["exact_member_ids"]))

    def _artifacts(self):
        return {
            (int(row["rewire_seed"]), str(row["control_family"])): row
            for row in self.preflight["topology_controls"]
        }

    def test_schedule_accounts_native_cardinalities_exactly(self) -> None:
        controls = _control_members(self.control_result, self.control_parameters)
        schedule = build_v2_schedule(
            self.base_protocol,
            self.protocol,
            self.canonical_members,
            controls,
            self._artifacts(),
        )
        self.assertEqual(len(schedule), 3072)
        self.assertEqual(schedule["scenario_id"].nunique(), 3072)
        self.assertEqual(
            schedule["topology_family"].value_counts().to_dict(),
            {
                "frozen_parameter_rewire": 1408,
                "same_recipe_recalibrated_rewire": 1312,
                "canonical": 352,
            },
        )
        recalibrated = schedule.loc[
            schedule["topology_family"].eq("same_recipe_recalibrated_rewire")
        ]
        self.assertEqual(
            recalibrated.groupby("rewire_seed")["member_id"].nunique().to_dict(),
            {81701: 14, 81702: 15, 81703: 4, 81704: 8},
        )
        self.assertTrue(schedule["outcome_status"].str.startswith("not_executed").all())

    def test_control_result_and_parameter_set_must_match(self) -> None:
        changed = yaml.safe_load(yaml.safe_dump(self.control_parameters))
        changed["ensembles_by_rewire_seed"][0]["member_ids"] = ["fabricated"]
        with self.assertRaises(HeldOutScheduleLockError):
            _control_members(self.control_result, changed)

    def test_v2_changes_no_stimulus_or_canonical_member(self) -> None:
        self.assertEqual(self.protocol["base_protocol"]["sha256"], self.campaign["frozen_inputs"]["base_protocol_v1"]["sha256"])
        self.assertEqual(self.protocol["supersession"]["predecessor_outcome_rows"], 0)
        self.assertFalse(self.protocol["supersession"]["decision_informed_by_held_out_outcomes"])
        self.assertEqual(self.protocol["schedule"]["canonical_members"], 11)
        self.assertEqual(self.protocol["schedule"]["total_episodes"], 3072)

    def test_compiler_writes_zero_outcome_reproducible_schedule(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd(), prefix=".test-fh09-v2-") as directory:
            root = Path(directory)
            first = compile_schedule_lock(
                CAMPAIGN_PATH,
                root / "result-a.yaml",
                root / "evaluation-a.yaml",
                root / "derived-a",
            )
            second = compile_schedule_lock(
                CAMPAIGN_PATH,
                root / "result-b.yaml",
                root / "evaluation-b.yaml",
                root / "derived-b",
            )
            self.assertEqual(first["semantic_result_sha256"], second["semantic_result_sha256"])
            self.assertEqual(first["held_out_outcomes_consumed"], 0)
            self.assertFalse(first["members_ranked"])
            self.assertEqual(first["schedule"]["rows"], 3072)


if __name__ == "__main__":
    unittest.main()

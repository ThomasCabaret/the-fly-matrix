from __future__ import annotations

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
CALIBRATION_ROOT = ROOT / "calibration"


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a YAML mapping")
    return value


class CalibrationRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.state = load_yaml(CALIBRATION_ROOT / "state.yaml")
        cls.targets = {
            target["id"]: target
            for target in (
                load_yaml(path)
                for path in sorted((CALIBRATION_ROOT / "targets").glob("*.yaml"))
            )
        }

    def test_state_references_existing_targets(self) -> None:
        referenced = self.state["active_target_ids"] + self.state["evaluation_target_ids"]
        self.assertEqual(len(referenced), len(set(referenced)))
        self.assertEqual(set(referenced), set(self.targets))

    def test_target_class_and_exposure_are_compatible(self) -> None:
        allowed_classes = {
            "evidence_transfer",
            "technical",
            "local_interface",
            "behavior_targeted",
            "evaluation_only",
        }
        allowed_exposures = {"allowed", "diagnostic_only", "evaluation_only"}

        for target_id, target in self.targets.items():
            with self.subTest(target=target_id):
                self.assertIn(target["primary_class"], allowed_classes)
                self.assertIn(target["optimization_exposure"], allowed_exposures)
                if target["primary_class"] == "evaluation_only":
                    self.assertEqual(target["optimization_exposure"], "evaluation_only")

    def test_technical_targets_do_not_name_behaviors(self) -> None:
        for target_id, target in self.targets.items():
            if target["primary_class"] != "technical":
                continue
            with self.subTest(target=target_id):
                self.assertEqual(target.get("behavior_targets"), [])
                self.assertNotEqual(target.get("claim_label"), "emergent_behavior")

    def test_ledger_behavior_index_matches_registry(self) -> None:
        behavior_index = load_yaml(ROOT / "ledger" / "behaviors.yaml")
        self.assertEqual(behavior_index["behavior_targeted_calibrations"], [])
        self.assertEqual(
            set(behavior_index["technical_targets"]),
            {
                target_id
                for target_id, target in self.targets.items()
                if target["primary_class"] == "technical"
            },
        )
        self.assertEqual(
            set(behavior_index["evaluation_only_targets"]),
            {
                target_id
                for target_id, target in self.targets.items()
                if target["primary_class"] == "evaluation_only"
            },
        )


if __name__ == "__main__":
    unittest.main()

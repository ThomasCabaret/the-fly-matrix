from __future__ import annotations

from pathlib import Path
import unittest

import yaml

from the_fly_matrix.calibration_registry import load_calibration_inventory


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
        cls.inventory = load_calibration_inventory(CALIBRATION_ROOT)
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

    def test_parameter_family_inventory_is_exhaustive_and_acyclic(self) -> None:
        self.assertEqual(len(self.inventory.families), 19)
        self.assertEqual(len(self.inventory.topological_order), 19)
        self.assertEqual(
            set(self.inventory.topological_order), set(self.inventory.families)
        )

    def test_routing_families_freeze_accepted_topology_hashes(self) -> None:
        expected = {
            "parameter.vision.routing.v0": "130b45c285aa86f97886648a607de29617422e9c8c94aed51be711ae5a836152",
            "parameter.proprioception.routing.v0": "782b98d147b5ecd15861dca0241d7fabf2995b1b9b6ef5b9c50d8e94ea5dd665",
            "parameter.mechanosensation.routing.v0": "70e71d9a5c36edcc8ce5f01e367c7a5349f8d1942ea3b1a72e0e0a9868cc9fd2",
            "parameter.motor.routing.v0": "0cd753e02283e42f3bf963e3fe223b7728b1a343da5b2db78e6414d4de8c5ca3",
        }
        for family_id, semantic_hash in expected.items():
            with self.subTest(family=family_id):
                snapshot = self.inventory.families[family_id]["scope"]["topology_snapshot"]
                self.assertEqual(snapshot["semantic_topology_sha256"], semantic_hash)
                self.assertEqual(snapshot["candidate_envelope_sha256"], semantic_hash)

    def test_inventory_does_not_claim_fitted_values(self) -> None:
        self.assertEqual(
            self.inventory.index["accounting"]["accepted_parameter_sets"], 0
        )
        self.assertEqual(self.inventory.index["accounting"]["fitted_families"], 0)
        externally_frozen = {
            family_id
            for family_id, family in self.inventory.families.items()
            if family["freeze"]["status"] == "externally_frozen"
        }
        self.assertEqual(
            externally_frozen, {"parameter.body.flybody_mechanics.v0"}
        )

    def test_state_references_inventory_and_dag(self) -> None:
        self.assertEqual(
            self.state["parameter_family_inventory_id"], self.inventory.index["id"]
        )
        self.assertEqual(
            self.state["parameter_dependency_dag_id"], self.inventory.dag["id"]
        )


if __name__ == "__main__":
    unittest.main()

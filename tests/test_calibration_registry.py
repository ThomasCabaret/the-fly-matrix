from __future__ import annotations

from pathlib import Path
import unittest

import yaml

from the_fly_matrix.calibration_registry import (
    load_calibration_inventory,
    validate_model_risk_references,
)


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
        referenced = (
            self.state["active_target_ids"]
            + self.state["evaluation_target_ids"]
            + self.state["completed_target_ids"]
        )
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

    def test_prospective_behavior_catalog_is_not_a_locked_protocol(self) -> None:
        catalog = load_yaml(
            CALIBRATION_ROOT
            / "evaluation_candidates"
            / "emergent-behavior-catalog-v0.yaml"
        )
        held_out_target = self.targets["target.held_out_stimulus_response.v0"]
        behavior_index = load_yaml(ROOT / "ledger" / "behaviors.yaml")

        self.assertEqual(catalog["status"], "prospective_only_not_locked_not_run")
        self.assertEqual(catalog["optimization_exposure"], "forbidden")
        self.assertEqual(len(catalog["candidates"]), 7)
        self.assertFalse(
            catalog["catalog_exposure_policy"][
                "catalog_registration_is_protocol_lock"
            ]
        )
        self.assertEqual(held_out_target["protocol_lock_status"], "not_locked")
        self.assertEqual(behavior_index["held_out_behaviors"], [])
        self.assertEqual(
            behavior_index["prospective_evaluation_candidates"]["status"],
            "catalog_only_not_locked_not_run",
        )
        self.assertFalse(self.state["readiness"]["held_out_protocol_locked"])

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
            self.inventory.index["accounting"]["accepted_parameter_sets"], 1
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

    def test_transmitter_prior_is_frozen_but_not_a_complete_signed_graph(self) -> None:
        family = self.inventory.families["parameter.central.transmitter_sign_prior.v0"]
        self.assertEqual(family["freeze"]["status"], "frozen")
        self.assertEqual(
            family["freeze"]["parameter_set_id"],
            "parameters.central_transmitter_sign_prior.v0",
        )
        self.assertEqual(
            family["scope"]["dimension"]["unknown_or_context_dependent_neurons"],
            40911,
        )

    def test_first_evidence_campaign_lineage_is_closed(self) -> None:
        campaign = load_yaml(
            CALIBRATION_ROOT / "campaigns" / "evidence-transmitter-sign-prior-v0.yaml"
        )
        parameter_set = load_yaml(
            CALIBRATION_ROOT
            / "parameter_sets"
            / "central-transmitter-sign-prior-v0.yaml"
        )
        evaluation = load_yaml(
            CALIBRATION_ROOT
            / "evaluations"
            / "evidence-transmitter-sign-prior-v0.yaml"
        )
        self.assertEqual(campaign["result"]["status"], "accepted")
        self.assertEqual(campaign["output_parameter_set_id"], parameter_set["id"])
        self.assertEqual(parameter_set["campaign_id"], campaign["id"])
        self.assertIn(evaluation["id"], parameter_set["validation"]["evaluation_ids"])
        self.assertEqual(evaluation["parameter_set_id"], parameter_set["id"])
        self.assertEqual(evaluation["acceptance_result"], "pass")
        self.assertFalse(parameter_set["behavior_exposure"]["behavior_targeted"])

    def test_state_references_inventory_and_dag(self) -> None:
        self.assertEqual(
            self.state["parameter_family_inventory_id"], self.inventory.index["id"]
        )
        self.assertEqual(
            self.state["parameter_dependency_dag_id"], self.inventory.dag["id"]
        )

    def test_neural_model_class_gate_closes_as_typed_hybrid_revision(self) -> None:
        risks = load_yaml(CALIBRATION_ROOT / "model-risks.yaml")
        risk_by_id = {risk["id"]: risk for risk in risks["risks"]}
        rate_risk = risk_by_id["risk.central_rate_representation_fidelity.v0"]
        delay_risk = risk_by_id["risk.central_delay_fidelity.v0"]
        rate_model = load_yaml(
            CALIBRATION_ROOT / "models" / "malecns-typed-signed-rate-v0.yaml"
        )
        architecture = load_yaml(
            CALIBRATION_ROOT
            / "models"
            / "malecns-event-capable-typed-hybrid-v0.yaml"
        )
        evaluation = load_yaml(
            CALIBRATION_ROOT / "evaluations" / "neural-model-class-gate-v0.yaml"
        )
        gate = self.targets["target.neural_model_class_gate.v0"]
        assignment = self.targets["target.population_dynamics_assignment.v0"]

        self.assertEqual(
            rate_risk["status"],
            "resolved_reject_global_default_retained_scoped_comparator",
        )
        self.assertEqual(delay_risk["status"], "open_high_impact")
        self.assertEqual(
            gate["status"],
            "completed_revise_to_event_capable_typed_hybrid_architecture",
        )
        self.assertEqual(gate["optimization_exposure"], "diagnostic_only")
        self.assertEqual(gate["behavior_targets"], [])
        self.assertIn(gate["id"], self.state["completed_target_ids"])
        self.assertNotIn(gate["id"], self.state["active_target_ids"])
        self.assertIn(assignment["id"], self.state["active_target_ids"])
        self.assertNotIn("scientific_role", rate_model)
        self.assertEqual(
            self.state["readiness"]["central_model_class"],
            "global_gate_resolved_revise_event_capable_typed_hybrid_architecture_population_assignments_open",
        )
        self.assertTrue(gate["acceptance_policy"]["scientific_gate_closed"])
        self.assertEqual(gate["acceptance_policy"]["decision"], "revise")
        self.assertEqual(evaluation["decision"]["outcome"], "revise")
        self.assertEqual(
            architecture["assignment_contract"]["default_class"],
            "dual_unresolved",
        )
        assignment_coverage = architecture["scope"]["population_assignment_coverage"]
        self.assertEqual(assignment_coverage["event_required_neurons"], 10)
        self.assertEqual(assignment_coverage["dual_unresolved_scoped_neurons"], 36)
        self.assertEqual(architecture["scope"]["parameter_values_promoted"], 0)
        self.assertIn(
            "homogeneous_continuous_rate",
            evaluation["decision"]["rejected_global_defaults"],
        )
        self.assertIn(
            "homogeneous_point_neuron_lif",
            evaluation["decision"]["rejected_global_defaults"],
        )
        for artifact_ref in evaluation["reproducibility"]["artifact_refs"]:
            with self.subTest(artifact_ref=artifact_ref):
                self.assertTrue((ROOT / artifact_ref).is_file())

    def test_first_local_population_assignment_is_partial_and_value_free(self) -> None:
        campaign = load_yaml(
            CALIBRATION_ROOT
            / "campaigns"
            / "population-dynamics-front-leg-accounting-v0.yaml"
        )
        evaluation = load_yaml(
            CALIBRATION_ROOT
            / "evaluations"
            / "population-dynamics-front-leg-accounting-v0.yaml"
        )
        runner = load_yaml(
            CALIBRATION_ROOT
            / "runner"
            / "population-dynamics-front-leg-accounting-v0.yaml"
        )
        assignment = self.targets["target.population_dynamics_assignment.v0"]

        self.assertEqual(campaign["capacity_policy"]["degrees_of_freedom"], 0)
        self.assertEqual(campaign["result"]["parameter_values_emitted"], 0)
        self.assertEqual(evaluation["metrics"]["neurons_accounted"], 46)
        self.assertEqual(evaluation["metrics"]["event_required_neurons"], 10)
        self.assertEqual(evaluation["metrics"]["dual_unresolved_neurons"], 36)
        self.assertEqual(evaluation["metrics"]["behavior_targets_exposed"], 0)
        self.assertEqual(runner["semantic_result_sha256"], campaign["result"]["semantic_result_sha256"])
        self.assertIn("active_front_leg", assignment["status"])
        self.assertIn(assignment["id"], self.state["active_target_ids"])

    def test_first_local_conversion_contract_is_executable_and_value_free(self) -> None:
        campaign = load_yaml(
            CALIBRATION_ROOT / "campaigns" / "front-leg-local-conversion-contract-v0.yaml"
        )
        evaluation = load_yaml(
            CALIBRATION_ROOT / "evaluations" / "front-leg-local-conversion-contract-v0.yaml"
        )
        runner = load_yaml(
            CALIBRATION_ROOT / "runner" / "front-leg-local-conversion-contract-v0.yaml"
        )
        assignment = self.targets["target.population_dynamics_assignment.v0"]

        self.assertEqual(campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertEqual(campaign["capacity_policy"]["optimized_parameters"], 0)
        self.assertFalse(campaign["capacity_policy"]["representation_selected"])
        self.assertEqual(evaluation["metrics"]["parameter_values_promoted"], 0)
        self.assertEqual(evaluation["metrics"]["behavior_targets_exposed"], 0)
        self.assertEqual(runner["accounting"]["topology_changes"], 0)
        self.assertEqual(
            runner["semantic_result_sha256"],
            evaluation["reproducibility"]["semantic_result_sha256"],
        )
        self.assertIn("conversion_contracts_executable", assignment["status"])

    def test_feco_observation_source_contract_does_not_claim_native_spikes(self) -> None:
        campaign = load_yaml(
            CALIBRATION_ROOT / "campaigns" / "feco-calcium-observation-source-v0.yaml"
        )
        evaluation = load_yaml(
            CALIBRATION_ROOT / "evaluations" / "feco-calcium-observation-source-v0.yaml"
        )
        runner = load_yaml(
            CALIBRATION_ROOT / "runner" / "feco-calcium-observation-source-v0.yaml"
        )
        model = load_yaml(
            CALIBRATION_ROOT / "models" / "feco-calcium-observation-source-v0.yaml"
        )

        self.assertEqual(campaign["behavior_targets"], [])
        self.assertEqual(campaign["capacity_policy"]["optimized_parameters"], 0)
        self.assertFalse(campaign["capacity_policy"]["representation_selected"])
        self.assertEqual(evaluation["metrics"]["promoted_parameter_values"], 0)
        self.assertTrue(evaluation["metrics"]["source_path_discrepancy_detected"])
        self.assertFalse(
            evaluation["metrics"]["source_path_discrepancy_silently_reconciled"]
        )
        self.assertFalse(model["native_neural_representation_selected"])
        self.assertFalse(runner["interpretation"]["calcium_is_native_spiking_evidence"])
        self.assertEqual(
            runner["semantic_result_sha256"],
            evaluation["reproducibility"]["semantic_result_sha256"],
        )

    def test_feco_held_out_fit_is_preregistered_without_silent_selection(self) -> None:
        campaign = load_yaml(
            CALIBRATION_ROOT / "campaigns" / "feco-calcium-held-out-fit-v0.yaml"
        )
        evaluation = load_yaml(
            CALIBRATION_ROOT / "evaluations" / "feco-calcium-held-out-fit-v0.yaml"
        )
        runner = load_yaml(
            CALIBRATION_ROOT / "runner" / "feco-calcium-held-out-fit-v0.yaml"
        )

        self.assertEqual(campaign["split"]["method"], "leave_one_animal_out")
        self.assertFalse(campaign["selection_policy"]["choose_winner"])
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertEqual(
            sum(len(dataset["candidates"]) for dataset in campaign["inputs"]["datasets"]),
            7,
        )
        self.assertEqual(
            evaluation["acceptance_result"],
            "pass_procedure_candidate_ensemble_retained",
        )
        self.assertEqual(evaluation["procedure_readiness"]["source_tables_verified"], 3)
        self.assertEqual(evaluation["procedure_readiness"]["source_rows_inspected"], 64_300)
        self.assertEqual(
            runner["status"],
            "completed_candidate_ensemble_unpromoted",
        )
        self.assertEqual(runner["accounting"]["datasets_verified"], 3)
        self.assertEqual(runner["accounting"]["candidate_paths"], 7)
        self.assertEqual(runner["accounting"]["folds_total"], 86)
        self.assertEqual(runner["accounting"]["folds_blocked"], 0)
        self.assertEqual(
            runner["semantic_result_sha256"],
            evaluation["reproducibility"]["semantic_result_sha256"],
        )
        self.assertFalse(runner["accounting"]["candidate_winner_selected"])
        self.assertEqual(runner["accounting"]["parameter_values_promoted"], 0)

    def test_motor_pilot_inventory_preserves_class_uncertainty(self) -> None:
        campaign = load_yaml(
            CALIBRATION_ROOT / "campaigns" / "motor-spike-force-pilot-inventory-v0.yaml"
        )
        evaluation = load_yaml(
            CALIBRATION_ROOT / "evaluations" / "motor-spike-force-pilot-inventory-v0.yaml"
        )
        ensemble = load_yaml(
            CALIBRATION_ROOT / "evidence" / "front-leg-motor-class-ensemble-v0.yaml"
        )
        runner = load_yaml(
            CALIBRATION_ROOT / "runner" / "motor-spike-force-pilot-inventory-v0.yaml"
        )

        self.assertEqual(campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertEqual(len(campaign["inputs"]["archives"]), 3)
        self.assertEqual(len(ensemble["members"]), 10)
        self.assertEqual(ensemble["factorized_assignment_upper_bound"], 59_049)
        self.assertEqual(ensemble["selected_joint_assignments"], 0)
        self.assertTrue(all(item["selected_class"] is None for item in ensemble["members"]))
        self.assertEqual(evaluation["acceptance_result"], "pass_inventory_only")
        self.assertEqual(runner["status"], "completed_schema_inventory_fit_not_started")
        self.assertEqual(runner["accounting"]["archives_verified"], 3)
        self.assertEqual(len(runner["accounting"]["archives_blocked"]), 0)
        self.assertEqual(runner["accounting"]["body_class_assignments_selected"], 0)
        self.assertEqual(runner["accounting"]["parameter_values_promoted"], 0)

    def test_motor_source_contract_locks_scope_without_fitting_values(self) -> None:
        campaign = load_yaml(
            CALIBRATION_ROOT / "campaigns" / "motor-spike-force-source-contract-v0.yaml"
        )
        evaluation = load_yaml(
            CALIBRATION_ROOT / "evaluations" / "motor-spike-force-source-contract-v0.yaml"
        )
        runner = load_yaml(
            CALIBRATION_ROOT / "runner" / "motor-spike-force-source-contract-v0.yaml"
        )

        self.assertEqual(campaign["primary_class"], "evidence_transfer")
        self.assertEqual(campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertEqual(len(campaign["inputs"]["source_files"]), 5)
        self.assertEqual(evaluation["metrics"]["active_cells_accounted"], 23)
        self.assertEqual(evaluation["metrics"]["selected_pilot_trials"], 194)
        self.assertFalse(evaluation["metrics"]["raw_variable_schema_identified"])
        self.assertFalse(evaluation["metrics"]["twitch_kernel_identified"])
        self.assertEqual(evaluation["metrics"]["promoted_parameter_values"], 0)
        self.assertEqual(runner["accounting"]["body_class_assignments_selected"], 0)
        self.assertEqual(
            runner["semantic_result_sha256"],
            evaluation["reproducibility"]["semantic_result_sha256"],
        )

    def test_motor_pilot_fit_is_preregistered_but_unpromoted(self) -> None:
        campaign = load_yaml(
            CALIBRATION_ROOT / "campaigns" / "motor-spike-force-pilot-fit-v0.yaml"
        )
        evaluation = load_yaml(
            CALIBRATION_ROOT / "evaluations" / "motor-spike-force-pilot-fit-v0.yaml"
        )
        runner = load_yaml(
            CALIBRATION_ROOT / "runner" / "motor-spike-force-pilot-fit-v0.yaml"
        )

        self.assertEqual(campaign["primary_class"], "local_interface")
        self.assertEqual(campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertFalse(campaign["selection_policy"]["promote_values"])
        self.assertEqual(
            list(campaign["fit"]["class_policies"].values()).count(
                "source_reproduction_line_through_origin"
            ),
            1,
        )
        self.assertEqual(evaluation["procedure_readiness"]["fitted_parameters_if_run"], 3)
        self.assertEqual(evaluation["procedure_readiness"]["parameter_values_promoted"], 0)
        self.assertEqual(
            runner["status"], "completed_diagnostic_one_cell_per_class_unpromoted"
        )
        self.assertFalse(runner["interpretation"]["twitch_kernel_identified"])
        self.assertEqual(
            runner["semantic_result_sha256"],
            evaluation["reproducibility"]["semantic_result_sha256"],
        )

    def test_motor_twitch_temporal_diagnostic_preserves_identifiability_limits(self) -> None:
        campaign = load_yaml(
            CALIBRATION_ROOT / "campaigns" / "motor-twitch-temporal-diagnostic-v0.yaml"
        )
        evaluation = load_yaml(
            CALIBRATION_ROOT / "evaluations" / "motor-twitch-temporal-diagnostic-v0.yaml"
        )
        runner = load_yaml(
            CALIBRATION_ROOT / "runner" / "motor-twitch-temporal-diagnostic-v0.yaml"
        )

        self.assertFalse(
            campaign["design_provenance"]["preregistered_before_any_raw_trace_inspection"]
        )
        self.assertFalse(campaign["selection_policy"]["promote_values"])
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertEqual(runner["accounting"]["selected_single_spike_trials"], 33)
        self.assertEqual(runner["accounting"]["promoted_parameter_values"], 0)
        self.assertEqual(
            runner["class_results"]["slow_35C09"]["status"],
            "not_fit_no_isolated_single_spike_trials",
        )
        self.assertGreater(
            runner["class_results"]["fast_81A07"]["held_out_energy_fraction_explained"],
            runner["class_results"]["intermediate_22A08"]["held_out_energy_fraction_explained"],
        )
        self.assertEqual(
            runner["semantic_result_sha256"],
            evaluation["reproducibility"]["semantic_result_sha256"],
        )

    def test_model_risk_references_and_decisions_are_resolved(self) -> None:
        registry = validate_model_risk_references(CALIBRATION_ROOT)
        self.assertIn("risk.central_event_model_fidelity.v0", registry.risks)
        self.assertIn("risk.flybody_actuator_abstraction.v0", registry.risks)
        self.assertEqual(
            set(registry.model_references["model.malecns_lif_fixed_delay.v0"]),
            {
                "risk.central_delay_fidelity.v0",
                "risk.central_event_model_fidelity.v0",
            },
        )

    def test_actuator_gate_records_current_direct_motor_boundary(self) -> None:
        gate = self.targets["target.actuator_semantics_gate.v0"]
        self.assertEqual(gate["primary_class"], "technical")
        self.assertEqual(gate["optimization_exposure"], "diagnostic_only")
        self.assertEqual(gate["behavior_targets"], [])
        self.assertIn(gate["id"], self.state["completed_target_ids"])
        self.assertEqual(
            gate["status"],
            "accepted_bounded_direct_motor_surrogate_initial_short_horizon",
        )
        self.assertIsNone(gate["blocked_reason"])
        self.assertIn(
            "accepted_bounded_direct_motor_surrogate_initial_short_horizon",
            self.state["readiness"]["actuator_semantics"],
        )


if __name__ == "__main__":
    unittest.main()

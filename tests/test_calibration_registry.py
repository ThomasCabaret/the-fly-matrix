from __future__ import annotations

from pathlib import Path
import unittest

import yaml

from the_fly_matrix.calibration_registry import (
    load_calibration_inventory,
    validate_active_milestone_roadmap,
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

    def test_active_milestone_roadmap_is_itemized_and_accounted(self) -> None:
        roadmap = validate_active_milestone_roadmap(CALIBRATION_ROOT)
        self.assertEqual(roadmap["id"], self.state["active_roadmap_id"])
        self.assertIn(roadmap["status"], {"active", "complete"})

        items = roadmap["items"]
        item_ids = [item["id"] for item in items]
        open_items = [
            item for item in items if item["status"] not in {"complete", "superseded"}
        ]
        self.assertEqual(
            len(open_items), roadmap["estimate_contract"]["open_items"]
        )
        self.assertEqual(len(item_ids), len(set(item_ids)))
        self.assertEqual(item_ids, [f"FH-{index:02d}" for index in range(1, 10)])

        allowed_statuses = set(roadmap["replanning_policy"]["statuses"])
        known_ids: set[str] = set()
        for item in items:
            with self.subTest(item=item["id"]):
                self.assertIn(item["status"], allowed_statuses)
                self.assertTrue(item["exit_criteria"])
                self.assertLessEqual(
                    item["estimated_batches"]["min"],
                    item["estimated_batches"]["max"],
                )
                self.assertTrue(set(item["depends_on"]).issubset(known_ids))
                known_ids.add(item["id"])

        base = roadmap["estimate_contract"]["base_work_batches"]
        contingency = roadmap["estimate_contract"]["contingency_batches"]
        forecast = roadmap["estimate_contract"]["planning_forecast_batches"]
        self.assertEqual(
            base["min"],
            sum(item["estimated_batches"]["min"] for item in open_items),
        )
        self.assertEqual(
            base["max"],
            sum(item["estimated_batches"]["max"] for item in open_items),
        )
        self.assertEqual(forecast["min"], base["min"] + contingency["min"])
        self.assertEqual(forecast["max"], base["max"] + contingency["max"])

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

    def test_prospective_catalog_and_single_locked_protocol_are_distinct(self) -> None:
        catalog = load_yaml(
            CALIBRATION_ROOT
            / "evaluation_candidates"
            / "emergent-behavior-catalog-v0.yaml"
        )
        held_out_target = self.targets["target.held_out_stimulus_response.v0"]
        behavior_index = load_yaml(ROOT / "ledger" / "behaviors.yaml")

        self.assertEqual(
            catalog["status"],
            "prospective_catalog_one_candidate_executed_ambiguous_protocol_closed",
        )
        self.assertEqual(catalog["optimization_exposure"], "forbidden")
        self.assertEqual(len(catalog["candidates"]), 8)
        self.assertEqual(
            catalog["planning_priority"]["preferred_first_candidate"],
            "evaluation_candidate.front_leg_proprioceptive_resistance_reflex.v0",
        )
        self.assertFalse(
            catalog["catalog_exposure_policy"][
                "catalog_registration_is_protocol_lock"
            ]
        )
        self.assertEqual(
            held_out_target["protocol_lock_status"],
            "v2_executed_closed_after_inspection",
        )
        self.assertEqual(len(behavior_index["held_out_behaviors"]), 1)
        self.assertTrue(behavior_index["held_out_behaviors"][0]["outcomes_inspected"])
        self.assertFalse(behavior_index["held_out_behaviors"][0]["members_ranked"])
        self.assertEqual(
            behavior_index["prospective_evaluation_candidates"]["status"],
            "catalog_retained_one_protocol_executed_ambiguous_closed",
        )
        self.assertTrue(self.state["readiness"]["held_out_protocol_locked"])
        self.assertTrue(self.state["readiness"]["held_out_protocol_executed"])

    def test_first_held_out_channel_choice_is_evidence_based_and_unlocked(self) -> None:
        readiness = load_yaml(
            CALIBRATION_ROOT
            / "evaluations"
            / "first-held-out-channel-readiness-v0.yaml"
        )
        catalog = load_yaml(
            CALIBRATION_ROOT
            / "evaluation_candidates"
            / "emergent-behavior-catalog-v0.yaml"
        )
        roadmap = validate_active_milestone_roadmap(CALIBRATION_ROOT)

        self.assertFalse(readiness["selection_rules"]["simulated_outcomes_inspected"])
        self.assertFalse(readiness["selection_rules"]["protocol_locked"])
        self.assertEqual(readiness["selection_rules"]["parameter_values_promoted"], 0)
        self.assertEqual(
            readiness["tactile_audit"]["calibration_readiness"][
                "admitted_local_dataset_ids"
            ],
            [],
        )
        selected_id = readiness["decision"]["selected_candidate_id"]
        self.assertIn(selected_id, {item["id"] for item in catalog["candidates"]})
        self.assertEqual(roadmap["revision"], 6)
        self.assertEqual(roadmap["items"][0]["status"], "complete")
        self.assertEqual(roadmap["items"][1]["status"], "complete")
        self.assertEqual(roadmap["items"][2]["status"], "complete")
        self.assertFalse(roadmap["items"][2]["completion_record"]["simulated_outcomes_inspected"])
        self.assertEqual(roadmap["items"][3]["status"], "complete")
        self.assertFalse(roadmap["items"][3]["completion_record"]["simulated_body_outcomes_inspected"])
        self.assertEqual(roadmap["items"][4]["status"], "complete")
        self.assertFalse(roadmap["items"][4]["completion_record"]["simulated_body_outcomes_inspected"])
        self.assertEqual(roadmap["items"][5]["status"], "complete")
        self.assertEqual(roadmap["items"][5]["completion"]["motor_events"], 0)
        self.assertEqual(roadmap["items"][5]["completion"]["nonzero_commands"], 0)
        self.assertEqual(roadmap["items"][6]["status"], "complete")
        self.assertEqual(
            roadmap["items"][6]["completion_record"]["result"][
                "retained_unranked_exact_composites"
            ],
            11,
        )
        self.assertEqual(roadmap["items"][7]["status"], "complete")
        self.assertEqual(roadmap["items"][8]["status"], "complete")
        self.assertEqual(
            roadmap["items"][8]["blocking_substep"]["id"], "FH-09-timebase"
        )
        self.assertEqual(
            roadmap["items"][8]["blocking_substep"]["status"],
            "resolved_before_outcomes",
        )
        self.assertEqual(
            roadmap["items"][8]["preflight_record"]["held_out_outcomes_consumed"],
            0,
        )
        self.assertEqual(
            roadmap["items"][8]["preflight_record"]["schedule_rows"], 3168
        )
        self.assertFalse(
            roadmap["items"][8]["preflight_record"]["execution_ready"]
        )
        self.assertEqual(
            roadmap["items"][8]["control_recalibration_record"][
                "exact_same_recipe_survivor_counts_by_rewire_seed"
            ],
            {81701: 14, 81702: 15, 81703: 4, 81704: 8},
        )
        self.assertEqual(
            roadmap["items"][8]["control_recalibration_record"][
                "held_out_outcomes_consumed"
            ],
            0,
        )
        schedule = roadmap["items"][8]["execution_schedule_v2"]
        self.assertTrue(schedule["execution_ready"])
        self.assertEqual(schedule["schedule_rows"], 3072)
        self.assertEqual(schedule["canonical_rows"], 352)
        self.assertEqual(schedule["frozen_parameter_rewire_rows"], 1408)
        self.assertEqual(schedule["same_recipe_recalibrated_rewire_rows"], 1312)
        self.assertEqual(schedule["recalibrated_control_members"], 41)
        self.assertEqual(schedule["held_out_outcomes_consumed"], 0)
        self.assertFalse(schedule["members_ranked"])
        execution = roadmap["items"][8]["execution_record"]
        self.assertEqual(execution["outcome_rows"], 3072)
        self.assertEqual(execution["canonical_primary_pass_rows"], 0)
        self.assertFalse(execution["topology_specific"])
        self.assertEqual(roadmap["estimate_contract"]["open_items"], 0)

    def test_first_held_out_causal_cone_is_bounded_and_nonselecting(self) -> None:
        scope = load_yaml(
            CALIBRATION_ROOT
            / "scopes"
            / "first-held-out-proprioceptive-resistance-reflex-v0.yaml"
        )
        result = load_yaml(
            CALIBRATION_ROOT / "runner" / "first-held-out-causal-cone-v0.yaml"
        )
        evaluation = load_yaml(
            CALIBRATION_ROOT
            / "evaluations"
            / "first-held-out-causal-cone-v0.yaml"
        )

        accounting = scope["population_accounting"]
        self.assertEqual(accounting["unique_cone_neurons"], 196)
        self.assertEqual(accounting["event_required_neurons"], 12)
        self.assertEqual(accounting["dual_unresolved_neurons"], 184)
        self.assertEqual(accounting["canonical_neurons_outside_cone"], 166_504)
        self.assertFalse(scope["selection_policy"]["central_path_selected"])
        self.assertFalse(scope["selection_policy"]["simulated_outcome_inspected"])
        self.assertEqual(result["promoted_parameter_values"], 0)
        self.assertEqual(result["behavior_outcomes_consumed"], 0)
        self.assertEqual(result["semantic_result_sha256"], scope["semantic_scope_sha256"])
        self.assertEqual(evaluation["acceptance_result"], "pass")
        self.assertFalse(evaluation["protocol_locked"])

    def test_parameter_family_inventory_is_exhaustive_and_acyclic(self) -> None:
        self.assertEqual(len(self.inventory.families), 23)
        self.assertEqual(len(self.inventory.topological_order), 23)
        self.assertEqual(
            set(self.inventory.topological_order), set(self.inventory.families)
        )

    def test_internal_native_boundary_capacity_is_explicit_and_unfrozen(self) -> None:
        family = self.inventory.families[
            "parameter.central.native_boundary_conversion.v0"
        ]
        self.assertEqual(family["freeze"]["status"], "not_frozen")
        self.assertEqual(
            family["dependencies"]["upstream_family_ids"],
            ["parameter.central.neuron_dynamics.v0"],
        )
        central = self.inventory.families["parameter.central.neuron_dynamics.v0"]
        self.assertEqual(central["scope"]["dimension"]["event_required_neurons"], 12)
        self.assertEqual(
            central["scope"]["dimension"]["dual_unresolved_basal_reached_neurons"],
            166419,
        )

    def test_proprioception_native_bridge_is_separate_and_unfrozen(self) -> None:
        shape = self.inventory.families["parameter.proprioception.transfer.v0"]
        bridge = self.inventory.families["parameter.proprioception.native_bridge.v0"]
        self.assertEqual(
            shape["dependencies"]["downstream_family_ids"],
            ["parameter.proprioception.native_bridge.v0"],
        )
        self.assertEqual(bridge["freeze"]["status"], "not_frozen")
        self.assertEqual(bridge["scope"]["dimension"]["scoped_representation_profiles"], 8)
        self.assertIn(
            "parameter.central.synaptic_efficacy.v0",
            bridge["identifiability"]["jointly_identified_with"],
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
        self.assertEqual(assignment_coverage["basal_reached_neurons"], 166431)
        self.assertEqual(assignment_coverage["exact_event_required_neurons"], 12)
        self.assertEqual(assignment_coverage["dual_unresolved_reached_neurons"], 166419)
        self.assertEqual(assignment_coverage["canonical_neurons_outside_basal_reached_scope"], 269)
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

    def test_full_graph_typed_hybrid_runtime_is_mechanics_only(self) -> None:
        campaign = load_yaml(
            CALIBRATION_ROOT
            / "campaigns"
            / "basal-reached-typed-hybrid-runtime-sentinel-v0.yaml"
        )
        runner = load_yaml(
            CALIBRATION_ROOT
            / "runner"
            / "basal-reached-typed-hybrid-runtime-sentinel-v0.yaml"
        )
        evaluation = load_yaml(
            CALIBRATION_ROOT
            / "evaluations"
            / "basal-reached-typed-hybrid-runtime-sentinel-v0.yaml"
        )

        self.assertEqual(campaign["behavior_targets"], [])
        self.assertEqual(campaign["parameter_values_promoted"], 0)
        self.assertFalse(all(runner["checks"].values()))
        self.assertFalse(runner["checks"]["parameter_values_promoted"])
        self.assertFalse(runner["checks"]["named_behavior_exposed"])
        mixed = runner["profiles"]["exact_event_plus_all_dual_as_graded"]
        self.assertEqual(mixed["node_counts"], {"inactive": 269, "event": 12, "graded": 166419})
        self.assertTrue(all(value > 0 for value in mixed["boundary_projection_max_l1"].values()))
        self.assertEqual(runner["scientific_boundary"]["population_assignments_promoted"], 0)
        self.assertEqual(runner["scientific_boundary"]["source_bridges_executed"], 0)
        self.assertFalse(runner["scientific_boundary"]["higher_order_assignment_space_covered"])
        self.assertEqual(
            runner["semantic_result_sha256"],
            evaluation["reproducibility"]["runner_semantic_sha256"],
        )

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

    def test_front_leg_uncertainty_propagation_preserves_scientific_space(self) -> None:
        campaign = load_yaml(
            CALIBRATION_ROOT / "campaigns" / "front-leg-uncertainty-propagation-v0.yaml"
        )
        evaluation = load_yaml(
            CALIBRATION_ROOT / "evaluations" / "front-leg-uncertainty-propagation-v0.yaml"
        )
        runner = load_yaml(
            CALIBRATION_ROOT / "runner" / "front-leg-uncertainty-propagation-v0.yaml"
        )

        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertEqual(
            campaign["intermediate_propagation_policy"]["scientific_assignment_space"],
            "2^148",
        )
        self.assertEqual(runner["intermediate_panel"]["diagnostic_profiles"], 50)
        self.assertEqual(
            runner["intermediate_panel"]["pairs_with_all_four_states"], 10878
        )
        self.assertFalse(runner["intermediate_panel"]["higher_order_coverage_claimed"])
        self.assertEqual(
            runner["interface_decisions"]["motor"][
                "kernel_blocked_slow_containing_assignments"
            ],
            58025,
        )
        self.assertEqual(evaluation["scientific_boundary"]["parameter_values_promoted"], 0)
        self.assertEqual(
            runner["semantic_result_sha256"],
            evaluation["reproducibility"]["semantic_result_sha256"],
        )

    def test_front_leg_chain_envelope_preserves_factorized_uncertainty(self) -> None:
        campaign = load_yaml(
            CALIBRATION_ROOT / "campaigns" / "front-leg-sensor-cns-motor-chain-v0.yaml"
        )
        evaluation = load_yaml(
            CALIBRATION_ROOT / "evaluations" / "front-leg-sensor-cns-motor-chain-v0.yaml"
        )
        runner = load_yaml(
            CALIBRATION_ROOT / "runner" / "front-leg-sensor-cns-motor-chain-v0.yaml"
        )
        scope = load_yaml(
            CALIBRATION_ROOT / "scopes" / "front-leg-sensor-cns-motor-chain-v0.yaml"
        )

        self.assertEqual(campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertEqual(evaluation["procedure_result"]["central"]["reachable_endpoint_pairs"], 360)
        self.assertEqual(evaluation["procedure_result"]["central"]["unique_new_intermediate_neurons"], 150)
        self.assertEqual(
            scope["generated_intermediate_population"]["assignment"],
            "mixed_explicit_2_event_required_148_dual_unresolved",
        )
        self.assertEqual(
            scope["generated_intermediate_population"]["assignment_summary"],
            {"event_required": 2, "dual_unresolved": 148, "graded_required": 0},
        )
        self.assertEqual(runner["sensory_ensemble"]["boundary_alternatives"], 24)
        self.assertEqual(runner["motor_ensemble"]["factorized_class_assignment_upper_bound"], 59_049)
        self.assertEqual(runner["motor_ensemble"]["basis_probes_executed"], 660)
        self.assertEqual(runner["motor_ensemble"]["basis_probes_blocked"], 330)
        self.assertEqual(runner["accounting"]["promoted_parameter_values"], 0)
        self.assertEqual(runner["accounting"]["behavior_targets_exposed"], 0)
        self.assertEqual(
            runner["semantic_result_sha256"],
            evaluation["reproducibility"]["semantic_result_sha256"],
        )

    def test_front_leg_intermediate_rules_account_every_body_without_values(self) -> None:
        campaign = load_yaml(
            CALIBRATION_ROOT
            / "campaigns"
            / "front-leg-intermediate-dynamics-accounting-v0.yaml"
        )
        evaluation = load_yaml(
            CALIBRATION_ROOT
            / "evaluations"
            / "front-leg-intermediate-dynamics-accounting-v0.yaml"
        )
        runner = load_yaml(
            CALIBRATION_ROOT
            / "runner"
            / "front-leg-intermediate-dynamics-accounting-v0.yaml"
        )

        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertEqual(runner["summary"]["scoped_bodies"], 150)
        self.assertEqual(
            runner["summary"]["assignment_counts"],
            {"dual_unresolved": 148, "event_required": 2},
        )
        self.assertEqual(runner["summary"]["parameter_values_emitted"], 0)
        self.assertEqual(runner["summary"]["topology_changes"], 0)
        self.assertEqual(runner["summary"]["behavior_targets_exposed"], 0)
        self.assertEqual(
            runner["semantic_result_sha256"],
            evaluation["reproducibility"]["semantic_result_sha256"],
        )

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
        self.assertIn("risk.internal_native_boundary_conversion.v0", registry.risks)
        self.assertIn("risk.population_native_dynamics_assignment.v0", registry.risks)
        self.assertIn("risk.basal_source_synaptic_threshold_coupling.v0", registry.risks)
        self.assertIn("risk.motor_slow_kernel_and_bodyid_assignment.v0", registry.risks)
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

    def test_embodied_measurement_contract_closes_observability_not_stability(self) -> None:
        campaign = load_yaml(
            CALIBRATION_ROOT / "campaigns" / "embodied-measurement-contract-v1.yaml"
        )
        evaluation = load_yaml(
            CALIBRATION_ROOT / "evaluations" / "embodied-measurement-contract-v1.yaml"
        )
        runner = load_yaml(
            CALIBRATION_ROOT / "runner" / "embodied-measurement-contract-v1.yaml"
        )

        self.assertEqual(campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertEqual(campaign["budgets"]["optimized_parameters"], 0)
        self.assertEqual(campaign["acceptance"]["stability_thresholds"], "unresolved")
        self.assertEqual(
            evaluation["acceptance_result"],
            "pass_measurement_contract_stability_unresolved",
        )
        self.assertEqual(runner["status"], "measurement_contract_pass_stability_unresolved")
        self.assertTrue(all(runner["checks"].values()))
        self.assertFalse(runner["interpretation"]["stability_accepted"])
        self.assertEqual(runner["accounting"]["optimized_parameters"], 0)
        self.assertEqual(runner["uncertainty_axes"]["intermediate_profiles"], 50)
        self.assertEqual(runner["uncertainty_axes"]["feco_alternatives"], 24)
        self.assertEqual(
            runner["uncertainty_axes"]["motor_class_assignments_blocked_slow"],
            58_025,
        )
        self.assertEqual(
            runner["semantic_result_sha256"],
            evaluation["reproducibility"]["semantic_result_sha256"],
        )

    def test_neutral_embodied_pilot_schedule_is_bounded_and_nonselecting(self) -> None:
        campaign = load_yaml(
            CALIBRATION_ROOT / "campaigns" / "neutral-embodied-stability-pilot-v0.yaml"
        )
        evaluation = load_yaml(
            CALIBRATION_ROOT / "evaluations" / "neutral-embodied-stability-pilot-v0.yaml"
        )
        runner = load_yaml(
            CALIBRATION_ROOT
            / "runner"
            / "neutral-embodied-stability-pilot-schedule-v0.yaml"
        )

        self.assertEqual(campaign["behavior_targets"], [])
        self.assertEqual(campaign["parameter_policy"]["optimized_parameters"], 0)
        self.assertFalse(campaign["schedule_policy"]["candidate_selection_from_body_motion"])
        self.assertEqual(
            evaluation["acceptance_result"],
            "pass_full_local_panel_execution_stability_not_evaluated",
        )
        self.assertEqual(evaluation["execution_accounting"]["completed_tuples"], 120)
        self.assertFalse(evaluation["stability_accepted"])
        self.assertEqual(
            runner["status"],
            "schedule_complete_execution_not_started_stability_unresolved",
        )
        self.assertEqual(runner["coverage"]["scheduled_tuples"], 120)
        self.assertEqual(runner["coverage"]["paired_physical_episodes"], 240)
        self.assertEqual(runner["coverage"]["intermediate_profiles"]["unscheduled"], 0)
        self.assertEqual(runner["coverage"]["feco_alternatives"]["unscheduled"], 0)
        self.assertEqual(runner["coverage"]["route_basis_edges"]["unscheduled"], 0)
        self.assertEqual(runner["coverage"]["bridge_gains"]["unscheduled"], 0)
        self.assertEqual(
            runner["coverage"]["motor_assignments"]["kernel_executable_unscheduled"],
            904,
        )
        self.assertEqual(
            runner["coverage"]["motor_assignments"]["blocked_slow_containing"],
            58_025,
        )
        self.assertFalse(runner["interpretation"]["stability_accepted"])
        self.assertEqual(runner["interpretation"]["parameter_values_promoted"], 0)

    def test_declared_envelope_replaces_silent_fixtures_without_selection(self) -> None:
        campaign = load_yaml(
            CALIBRATION_ROOT / "campaigns" / "neutral-embodied-declared-envelope-v0.yaml"
        )
        evaluation = load_yaml(
            CALIBRATION_ROOT / "evaluations" / "neutral-embodied-declared-envelope-v0.yaml"
        )
        parameter_set = load_yaml(
            CALIBRATION_ROOT / "parameter_sets" / "neutral-embodied-declared-envelope-v0.yaml"
        )
        runner = load_yaml(
            CALIBRATION_ROOT / "runner" / "neutral-embodied-declared-envelope-v0.yaml"
        )

        self.assertEqual(campaign["optimization_exposure"], "diagnostic_only")
        self.assertEqual(campaign["behavior_targets"], [])
        self.assertFalse(campaign["topology_changes_allowed"])
        self.assertEqual(campaign["capacity_policy"]["optimized_parameters"], 0)
        self.assertEqual(campaign["capacity_policy"]["selected_candidates"], 0)
        self.assertFalse(
            campaign["schedule_policy"]["candidate_selection_from_body_motion"]
        )
        self.assertEqual(runner["factorized_panels"]["feco_routing"]["profiles"], 81)
        self.assertEqual(runner["factorized_panels"]["unknown_sign"]["profiles"], 64)
        self.assertEqual(len(runner["factorized_panels"]["numeric"]["profiles"]), 12)
        self.assertEqual(runner["coverage"]["schedule_tuples"], 240)
        self.assertEqual(runner["scientific_boundary"]["physical_episodes"], 0)
        self.assertEqual(runner["scientific_boundary"]["promoted_parameter_values"], 0)
        self.assertIsNone(parameter_set["solution_set"]["selected_reference_id"])
        self.assertEqual(
            runner["semantic_result_sha256"],
            evaluation["reproducibility"]["runner_semantic_sha256"],
        )


if __name__ == "__main__":
    unittest.main()

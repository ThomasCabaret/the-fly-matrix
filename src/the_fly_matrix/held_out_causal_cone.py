from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from .ledger import ROOT


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "first-held-out-causal-cone-v0.yaml"


class HeldOutCausalConeError(RuntimeError):
    """Raised when the held-out causal-scope contract is violated."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HeldOutCausalConeError(f"{path} must contain a YAML mapping")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _verify_file(ref: str, expected_sha256: str) -> tuple[Path, dict[str, Any]]:
    path = ROOT / ref
    observed = _sha256(path)
    if observed != expected_sha256:
        raise HeldOutCausalConeError(
            f"frozen input drift for {ref}: {observed} != {expected_sha256}"
        )
    return path, _load_yaml(path)


def _verify_campaign(campaign: Mapping[str, Any]) -> None:
    if campaign.get("primary_class") != "technical":
        raise HeldOutCausalConeError("causal-cone compilation must remain technical")
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise HeldOutCausalConeError("causal-cone compilation cannot optimize")
    if campaign.get("behavior_targets") != []:
        raise HeldOutCausalConeError("held-out outcomes cannot enter scope compilation")
    if campaign.get("topology_changes_allowed") is not False:
        raise HeldOutCausalConeError("scope compilation cannot change topology")
    if int(campaign.get("optimized_parameters", -1)) != 0:
        raise HeldOutCausalConeError("scope compilation cannot fit values")


def compile_held_out_causal_cone(
    campaign_path: Path = CAMPAIGN_PATH,
) -> dict[str, Any]:
    print("[1/6] Loading the preregistered held-out scope contract", flush=True)
    campaign = _load_yaml(campaign_path)
    _verify_campaign(campaign)

    selected = campaign["selected_candidate"]
    readiness_path, readiness = _verify_file(
        str(selected["readiness_ref"]), str(selected["readiness_sha256"])
    )
    if readiness["decision"]["selected_candidate_id"] != selected["id"]:
        raise HeldOutCausalConeError("selected candidate differs from FH-01 decision")
    if readiness["selection_rules"]["simulated_outcomes_inspected"]:
        raise HeldOutCausalConeError("FH-01 decision consumed a simulated outcome")
    if readiness["selection_rules"]["protocol_locked"]:
        raise HeldOutCausalConeError("scope compilation must precede protocol lock")

    print("[2/6] Verifying source scope and upstream semantic results", flush=True)
    loaded: dict[str, dict[str, Any]] = {}
    file_hashes: dict[str, str] = {}
    for key, record in campaign["frozen_inputs"].items():
        path, document = _verify_file(str(record["ref"]), str(record["sha256"]))
        loaded[key] = document
        file_hashes[key] = _sha256(path)
        expected_semantic = record.get("semantic_sha256")
        if expected_semantic is not None and document.get("semantic_result_sha256") != expected_semantic:
            raise HeldOutCausalConeError(f"semantic drift for {key}")

    source_scope = loaded["source_scope"]
    chain = loaded["chain_result"]
    intermediate = loaded["intermediate_result"]
    expected = campaign["expected_scope"]

    print("[3/6] Accounting every included and excluded population", flush=True)
    observed = {
        "sensory_neurons": int(source_scope["endpoint_populations"]["sensory"]["canonical_neurons"]),
        "intermediate_neurons": int(source_scope["generated_intermediate_population"]["canonical_neurons"]),
        "motor_neurons": int(source_scope["endpoint_populations"]["motor"]["canonical_neurons"]),
        "unique_cone_neurons": int(source_scope["accounting"]["unique_chain_neurons"]),
        "event_required_neurons": (
            int(source_scope["generated_intermediate_population"]["assignment_summary"]["event_required"])
            + int(source_scope["endpoint_populations"]["motor"]["canonical_neurons"])
        ),
        "dual_unresolved_neurons": (
            int(source_scope["endpoint_populations"]["sensory"]["canonical_neurons"])
            + int(source_scope["generated_intermediate_population"]["assignment_summary"]["dual_unresolved"])
        ),
        "graded_required_neurons": int(
            source_scope["generated_intermediate_population"]["assignment_summary"]["graded_required"]
        ),
        "reachable_endpoint_pairs": int(chain["central_corridor"]["reachable_endpoint_pairs"]),
        "direct_edges": int(chain["central_corridor"]["direct_edges"]),
        "bounded_path_records": int(chain["central_corridor"]["local_path_records"]),
    }
    for key, value in observed.items():
        if value != int(expected[key]):
            raise HeldOutCausalConeError(f"scope drift for {key}: {value} != {expected[key]}")

    exclusions = {
        "canonical_neurons_outside_cone": int(expected["canonical_neurons_total"]) - observed["unique_cone_neurons"],
        "basal_reached_neurons_outside_cone": int(expected["basal_reached_neurons"]) - observed["unique_cone_neurons"],
        "dual_unresolved_basal_reached_neurons_outside_cone": 166419 - observed["dual_unresolved_neurons"],
        "canonical_neurons_outside_basal_reach": int(expected["canonical_neurons_outside_basal_reach"]),
    }
    if exclusions != {
        "canonical_neurons_outside_cone": 166504,
        "basal_reached_neurons_outside_cone": 166235,
        "dual_unresolved_basal_reached_neurons_outside_cone": 166235,
        "canonical_neurons_outside_basal_reach": 269,
    }:
        raise HeldOutCausalConeError(f"unexpected exclusion accounting: {exclusions}")

    print("[4/6] Freezing topology, boundary ownership and exception semantics", flush=True)
    boundary_ownership = campaign["boundary_ownership"]
    expected_boundary_keys = {
        "kinematics_to_feco",
        "central_event_to_event",
        "central_graded_to_graded",
        "central_event_to_graded",
        "central_graded_to_event",
        "motor_event_to_force",
        "force_to_direct_motor",
    }
    if set(boundary_ownership) != expected_boundary_keys:
        raise HeldOutCausalConeError("native-boundary ownership is incomplete")
    if any(not item.get("owner_family_ids") for item in boundary_ownership.values()):
        raise HeldOutCausalConeError("every boundary requires a parameter owner")

    topology = source_scope["topology_boundary"]
    exception_payload = {
        "intermediate_exceptions": intermediate["exceptions"],
        "chain_open_blockers": chain["open_blockers"],
        "selected_candidate_open_dependencies": readiness["selected_candidate"]["open_dependencies"],
    }
    exception_sha256 = _canonical_hash(exception_payload)
    frozen_source_sha256 = _canonical_hash(
        {
            "readiness": _sha256(readiness_path),
            "inputs": file_hashes,
            "upstream_semantics": {
                key: value.get("semantic_result_sha256")
                for key, value in loaded.items()
                if value.get("semantic_result_sha256") is not None
            },
        }
    )

    checks = {
        "FH_01_candidate_matches": True,
        "no_simulated_outcomes_consumed": True,
        "all_196_neurons_accounted": sum(
            observed[key]
            for key in ("sensory_neurons", "intermediate_neurons", "motor_neurons")
        )
        == observed["unique_cone_neurons"],
        "event_plus_dual_plus_graded_equals_cone": (
            observed["event_required_neurons"]
            + observed["dual_unresolved_neurons"]
            + observed["graded_required_neurons"]
            == observed["unique_cone_neurons"]
        ),
        "all_native_boundary_kinds_owned": set(boundary_ownership) == expected_boundary_keys,
        "outside_cone_accounted": sum(
            [observed["unique_cone_neurons"], exclusions["canonical_neurons_outside_cone"]]
        )
        == int(expected["canonical_neurons_total"]),
        "no_path_selected": not bool(chain["central_corridor"]["path_selected"]),
        "zero_parameter_values_promoted": True,
        "zero_topology_changes": True,
    }
    if not all(checks.values()):
        raise HeldOutCausalConeError(f"scope checks failed: {checks}")

    scope = {
        "schema_version": 1,
        "id": "scope.first_held_out_proprioceptive_resistance_reflex.v0",
        "title": "Bounded front-leg cone for the prospective proprioceptive resistance-reflex evaluation",
        "status": "compiled_196_neurons_topology_and_exceptions_frozen_values_open",
        "candidate_id": selected["id"],
        "protocol_lock_status": "not_locked",
        "source_scope_id": source_scope["id"],
        "population_accounting": {**observed, **exclusions},
        "assignment_space": {
            "event_required": observed["event_required_neurons"],
            "dual_unresolved": observed["dual_unresolved_neurons"],
            "graded_required": observed["graded_required_neurons"],
            "unresolved_assignment_upper_bound": "2^184",
            "enumerated_as_scientific_coverage": False,
        },
        "boundary_ownership": boundary_ownership,
        "topology_boundary": topology,
        "frozen_source_bundle_sha256": frozen_source_sha256,
        "exception_semantics_sha256": exception_sha256,
        "exceptions": exception_payload,
        "selection_policy": {
            "central_path_selected": False,
            "population_assignment_selected": False,
            "parameter_value_selected": False,
            "simulated_outcome_inspected": False,
        },
        "next_action": campaign["next_action"],
    }
    semantic_payload = {
        "candidate_id": selected["id"],
        "population_accounting": scope["population_accounting"],
        "assignment_space": scope["assignment_space"],
        "boundary_ownership": boundary_ownership,
        "topology_boundary": topology,
        "frozen_source_bundle_sha256": frozen_source_sha256,
        "exception_semantics_sha256": exception_sha256,
        "selection_policy": scope["selection_policy"],
    }
    semantic_sha256 = _canonical_hash(semantic_payload)
    scope["semantic_scope_sha256"] = semantic_sha256

    result = {
        "schema_version": 1,
        "id": "runner_result.first_held_out_causal_cone.v0",
        "campaign_id": campaign["id"],
        "status": "pass_bounded_cone_accounting_no_selection",
        "command": "first_held_out_causal_cone.bat",
        "claim_label": campaign["claim_label"],
        "scope_id": scope["id"],
        "population_accounting": scope["population_accounting"],
        "boundary_ownership": boundary_ownership,
        "topology_boundary": topology,
        "frozen_source_bundle_sha256": frozen_source_sha256,
        "exception_semantics_sha256": exception_sha256,
        "checks": checks,
        "optimized_parameters": 0,
        "promoted_parameter_values": 0,
        "behavior_outcomes_consumed": 0,
        "accepted_claims": [
            "The prospective first path has a bounded and reproducible 196-neuron cone.",
            "All scoped dynamics dispositions, native-boundary owners and outside-cone populations are explicit.",
            "No path, population assignment, parameter value or response outcome was selected.",
        ],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
        "semantic_result_sha256": semantic_sha256,
    }
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.first_held_out_causal_cone.v0",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "scope_id": scope["id"],
        "status": "accepted_scope_compilation_FH_02_complete",
        "acceptance_result": "pass",
        "checks": checks,
        "population_accounting": scope["population_accounting"],
        "semantic_scope_sha256": semantic_sha256,
        "protocol_locked": False,
        "behavior_outcomes_consumed": 0,
        "parameter_values_promoted": 0,
        "interpretation": (
            "FH-02 closes scope accounting only. The 184 dual-unresolved assignments, "
            "all conversion values and all local interface values remain open for FH-03 to FH-05."
        ),
        "next_action": campaign["next_action"],
    }

    print("[5/6] Writing scope, compact runner result and evaluation", flush=True)
    outputs = campaign["outputs"]
    (ROOT / outputs["scope_ref"]).write_text(
        yaml.safe_dump(scope, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    (ROOT / outputs["runner_ref"]).write_text(
        yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    (ROOT / outputs["evaluation_ref"]).write_text(
        yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

    print("[6/6] COMPLETE", flush=True)
    print("[SCOPE] 36 FeCO + 150 intermediate + 10 motor = 196 neurons", flush=True)
    print("[DYNAMICS] 12 event-required; 184 dual-unresolved; zero silent defaults", flush=True)
    print("[EXCLUDED] 166,504 canonical neurons remain outside this local claim", flush=True)
    print(f"[HASH] {semantic_sha256}", flush=True)
    return result


def main() -> int:
    compile_held_out_causal_cone()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

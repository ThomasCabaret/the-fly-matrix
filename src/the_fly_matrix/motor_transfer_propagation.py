from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml

from .ledger import ROOT
from .local_conversion import MotorTonicParameters, motor_events_to_tonic_force_uN


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "front-leg-motor-transfer-propagation-v1.yaml"
PARAMETER_SET_PATH = ROOT / "calibration" / "parameter_sets" / "front-leg-motor-transfer-ensemble-v1.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "front-leg-motor-transfer-propagation-v1.yaml"
RUNNER_PATH = ROOT / "calibration" / "runner" / "front-leg-motor-transfer-propagation-v1.yaml"


class MotorTransferPropagationError(RuntimeError):
    pass


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MotorTransferPropagationError(f"expected YAML mapping: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _verify_inputs(campaign: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for name, spec in campaign["inputs"].items():
        path = ROOT / str(spec["path"])
        observed = _sha256(path)
        if observed != str(spec["sha256"]):
            raise MotorTransferPropagationError(
                f"input drift for {name}: expected {spec['sha256']}, got {observed}"
            )
        loaded[name] = _load_yaml(path)
    return loaded


def _probe_slow_candidates(
    candidates: list[dict[str, Any]], probe: Mapping[str, Any]
) -> list[dict[str, Any]]:
    indexes = [0, len(candidates) // 2, len(candidates) - 1]
    samples = int(probe["samples"])
    timestep_s = float(probe["timestep_s"])
    period = int(probe["event_period_samples"])
    events = np.zeros((samples, 1), dtype=np.int64)
    events[: samples // 2 : period, 0] = 1
    results: list[dict[str, Any]] = []
    for index in indexes:
        candidate = candidates[index]
        force = motor_events_to_tonic_force_uN(
            events,
            MotorTonicParameters(
                force_per_rate_uN_per_hz=np.asarray([candidate["gain_uN_per_hz"]]),
                time_constant_s=np.asarray([candidate["tau_s"]]),
                delay_s=np.asarray([candidate["delay_s"]]),
            ),
            timestep_s=timestep_s,
        )
        delay_samples = int(round(float(candidate["delay_s"]) / timestep_s))
        if not np.isfinite(force).all() or (force < 0.0).any():
            raise MotorTransferPropagationError("slow runtime probe produced invalid force")
        if np.any(force[:delay_samples] != 0.0):
            raise MotorTransferPropagationError("slow runtime probe violated causality")
        if float(force[-1, 0]) >= float(force[samples // 2, 0]):
            raise MotorTransferPropagationError("slow runtime force did not decay")
        results.append(
            {
                "retained_index": index,
                "grid_index": int(candidate["grid_index"]),
                "peak_force_uN": float(force[:, 0].max()),
                "final_force_uN": float(force[-1, 0]),
                "finite": True,
            }
        )
    return results


def run(
    campaign_path: Path = CAMPAIGN_PATH,
    parameter_set_path: Path = PARAMETER_SET_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    runner_path: Path = RUNNER_PATH,
) -> dict[str, Any]:
    campaign = _load_yaml(campaign_path)
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise MotorTransferPropagationError("campaign must remain diagnostic_only")
    if campaign.get("behavior_targets") != [] or campaign.get("topology_changes_allowed") is not False:
        raise MotorTransferPropagationError("campaign cannot expose behavior or topology")

    print("[1/5] Verifying locked evidence and diagnostic inputs", flush=True)
    inputs = _verify_inputs(campaign)
    policy = campaign["propagation_policy"]
    motor = inputs["motor_class_ensemble"]
    twitch = inputs["fast_intermediate_temporal_diagnostic"]
    slow = inputs["slow_tonic_diagnostic"]
    actuator = inputs["actuator_bridge_diagnostic"]

    print("[2/5] Checking exhaustive factorized class accounting", flush=True)
    body_count = len(motor["members"])
    class_count = len(motor["admissible_classes"])
    total = class_count**body_count
    no_slow = (class_count - 1) ** body_count
    with_slow = total - no_slow
    expected = (
        int(policy["expected_body_class_assignments"]),
        int(policy["expected_assignments_without_slow"]),
        int(policy["expected_assignments_with_slow"]),
    )
    if (total, no_slow, with_slow) != expected:
        raise MotorTransferPropagationError("motor class-assignment accounting drift")
    if int(motor["selected_joint_assignments"]) != 0:
        raise MotorTransferPropagationError("a body-class assignment was selected")

    print("[3/5] Checking class-distinct temporal envelopes", flush=True)
    class_results = twitch["class_results"]
    if class_results["slow_35C09"]["status"] != "not_fit_no_isolated_single_spike_trials":
        raise MotorTransferPropagationError("historical slow-twitch limitation drift")
    for class_id in ("fast_81A07", "intermediate_22A08"):
        if int(class_results[class_id]["near_optimal_envelope"]["candidate_count"]) <= 0:
            raise MotorTransferPropagationError(f"empty temporal envelope for {class_id}")
    slow_envelope = slow["slow_result"]["near_optimal_envelope"]
    candidates = slow_envelope.get("retained_candidates", [])
    if len(candidates) != int(policy["expected_slow_candidates"]):
        raise MotorTransferPropagationError("slow retained-candidate accounting drift")
    if len({int(item["grid_index"]) for item in candidates}) != len(candidates):
        raise MotorTransferPropagationError("duplicate slow grid indexes")
    if slow["accounting"]["promoted_parameter_values"] != 0:
        raise MotorTransferPropagationError("slow diagnostic promoted a value")

    print("[4/5] Exercising first, middle and last slow candidates", flush=True)
    probes = _probe_slow_candidates(candidates, campaign["runtime_probe"])
    actuator_members = len(
        actuator["conditional_gain_envelope"]["candidate_gains_command_per_uN"]
    )

    parameter_set = {
        "schema_version": 1,
        "id": "parameters.front_leg_motor_transfer_ensemble.v1",
        "status": "accepted_factorized_diagnostic_envelope_no_reference",
        "classification": "evidence_transfer",
        "claim_label": campaign["claim_label"],
        "source_campaign_id": campaign["id"],
        "factorization": {
            "body_class_variables": body_count,
            "classes_per_body": class_count,
            "body_class_assignments": total,
            "assignments_without_slow": no_slow,
            "assignments_with_slow": with_slow,
            "fast_twitch_candidates": int(class_results["fast_81A07"]["near_optimal_envelope"]["candidate_count"]),
            "intermediate_twitch_candidates": int(class_results["intermediate_22A08"]["near_optimal_envelope"]["candidate_count"]),
            "slow_tonic_candidates": len(candidates),
            "actuator_bridge_candidates": actuator_members,
            "joint_cartesian_product_materialized": False,
            "probability_prior": None,
        },
        "representations": {
            "fast_81A07": "peak_normalized_biexponential_event_twitch",
            "intermediate_22A08": "peak_normalized_biexponential_event_twitch",
            "slow_35C09": "causal_delayed_first_order_event_rate_to_force",
            "force_to_actuator": "separate_direct_motor_surrogate_bridge",
        },
        "slow_candidate_source": {
            "runner_id": slow["id"],
            "semantic_result_sha256": slow["semantic_result_sha256"],
            "retained_grid_indexes": [int(item["grid_index"]) for item in candidates],
            "boundary_contact": slow["slow_result"]["grid_boundary_contact"],
        },
        "reference_selection": None,
        "promoted_parameter_values": 0,
        "selected_body_class_assignments": 0,
        "behavior_targets_exposed": [],
        "dependency_hashes": {name: spec["sha256"] for name, spec in campaign["inputs"].items()},
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    parameter_set["semantic_sha256"] = _canonical_hash(parameter_set)
    parameter_set_path.write_text(yaml.safe_dump(parameter_set, sort_keys=False), encoding="utf-8")

    evaluation = {
        "schema_version": 1,
        "id": "evaluation.front_leg_motor_transfer_propagation.v1",
        "campaign_id": campaign["id"],
        "parameter_set_id": parameter_set["id"],
        "acceptance_result": "pass_complete_factorized_execution_boundary_contact_no_reference",
        "runtime_probes": probes,
        "accounting": {
            "body_class_assignments": total,
            "previously_executable_assignments": no_slow,
            "newly_executable_slow_containing_assignments": with_slow,
            "remaining_blocked_assignments": 0,
            "slow_candidates_propagated": len(candidates),
            "selected_members": 0,
        },
        "limitations": [
            "The slow envelope is post-inspection, one-cell and touches the tau and delay grid boundaries.",
            "Fast and intermediate envelopes are also one-cell diagnostics and the intermediate fit is weak.",
            "No individual MaleCNS body has an experimental motor-class crosswalk.",
            "Execution completeness is not physiological validation or motor calibration.",
        ],
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    evaluation_path.write_text(yaml.safe_dump(evaluation, sort_keys=False), encoding="utf-8")

    runner = {
        "schema_version": 1,
        "id": "runner_result.front_leg_motor_transfer_propagation.v1",
        "campaign_id": campaign["id"],
        "target_id": campaign["target_id"],
        "status": evaluation["acceptance_result"],
        "claim_label": campaign["claim_label"],
        "command": "propagate_motor_transfer_ensemble.bat",
        "campaign_sha256": _sha256(campaign_path),
        "parameter_set_id": parameter_set["id"],
        "parameter_set_semantic_sha256": parameter_set["semantic_sha256"],
        "evaluation_id": evaluation["id"],
        "accounting": evaluation["accounting"],
        "runtime_probes": probes,
        "behavior_targets": [],
        "promoted_parameter_values": 0,
        "selected_body_class_assignments": 0,
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
        "generated_at": datetime.now(UTC).isoformat(),
    }
    runner["semantic_result_sha256"] = _canonical_hash(
        {key: value for key, value in runner.items() if key != "generated_at"}
    )
    runner_path.write_text(yaml.safe_dump(runner, sort_keys=False), encoding="utf-8")

    print("[5/5] Summary", flush=True)
    print(f"[OK] {total} / {total} body-class assignments executable", flush=True)
    print(f"[SLOW] {with_slow} assignments retain {len(candidates)} tonic candidates", flush=True)
    print("[BOUNDARY] 0 reference, 0 body assignment, 0 behavior, 0 topology change", flush=True)
    print(f"[HASH] {runner['semantic_result_sha256']}", flush=True)
    return runner


def main() -> int:
    parser = argparse.ArgumentParser(description="Propagate the factorized front-leg motor transfer ensemble")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    run(campaign_path=args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

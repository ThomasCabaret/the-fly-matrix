from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from .ledger import ROOT


CAMPAIGN_PATH = ROOT / "calibration/campaigns/first-held-out-protocol-lock-v0.yaml"
RESULT_PATH = ROOT / "calibration/runner/first-held-out-protocol-lock-v0.yaml"
EVALUATION_PATH = ROOT / "calibration/evaluations/first-held-out-protocol-lock-v0.yaml"


class ProtocolLockError(RuntimeError):
    pass


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ProtocolLockError(f"expected YAML mapping: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _verify_frozen_inputs(campaign: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
    hashes: dict[str, str] = {}
    documents: dict[str, Any] = {}
    for name, spec in campaign["frozen_inputs"].items():
        path = ROOT / str(spec["path"])
        if not path.is_file():
            raise ProtocolLockError(f"missing frozen input {name}: {path}")
        observed = _sha256(path)
        if observed != str(spec["sha256"]):
            raise ProtocolLockError(
                f"frozen input hash drift for {name}: {observed} != {spec['sha256']}"
            )
        hashes[str(name)] = observed
        documents[str(name)] = _load_yaml(path)
        expected_semantic = spec.get("semantic_sha256")
        if expected_semantic is not None:
            observed_semantic = documents[str(name)].get(
                "semantic_result_sha256",
                documents[str(name)].get("runner_semantic_sha256", documents[str(name)].get("semantic_scope_sha256")),
            )
            if observed_semantic != expected_semantic:
                raise ProtocolLockError(f"semantic hash drift for {name}")
    return hashes, documents


def _sign_test_tail(successes: int, trials: int) -> float:
    return sum(math.comb(trials, k) for k in range(successes, trials + 1)) / (2**trials)


def _timebase_contract(
    protocol: Mapping[str, Any], campaign: Mapping[str, Any]
) -> dict[str, Any] | None:
    contract = campaign.get("timebase_contract")
    if contract is None:
        return None
    timestep = float(contract["physics_timestep_s"])
    tolerance = float(contract["duration_tolerance_s"])
    durations: dict[str, Any] = {}
    all_representable = True
    for key in contract["required_duration_fields"]:
        requested = float(protocol["stimulus"][key])
        steps = int(round(requested / timestep))
        represented = steps * timestep
        error = abs(represented - requested)
        durations[str(key)] = {
            "requested_s": requested,
            "steps": steps,
            "represented_s": represented,
            "absolute_error_s": error,
            "within_tolerance": error <= tolerance,
        }
        all_representable &= error <= tolerance
    if not all_representable:
        raise ProtocolLockError(
            "protocol timing is not representable on the frozen physical timebase"
        )
    return {
        "physics_timestep_s": timestep,
        "duration_tolerance_s": tolerance,
        "all_required_durations_representable": True,
        "durations": durations,
    }


def compile_lock(campaign: Mapping[str, Any]) -> dict[str, Any]:
    frozen_hashes, docs = _verify_frozen_inputs(campaign)
    protocol = docs["protocol"]
    scope = docs["causal_scope"]
    fh07_result = docs["fh07_result"]
    parameter_set = docs["fh07_parameter_set"]
    checks = campaign["lock_checks"]

    if protocol.get("status") != "locked_execution_pending":
        raise ProtocolLockError("protocol is not locked_execution_pending")
    assertions = protocol["lock_assertions"]
    if assertions["simulated_held_out_outcomes_inspected"]:
        raise ProtocolLockError("held-out outcomes were inspected before lock")
    if assertions["behavior_used_for_parameter_or_member_selection"]:
        raise ProtocolLockError("held-out behavior contaminated member selection")
    if protocol["execution_gate"]["outcome_rows_present"] != 0:
        raise ProtocolLockError("protocol lock contains outcome rows")

    protocol_members = list(map(str, protocol["frozen_lineage"]["member_ids"]))
    parameter_members = list(map(str, parameter_set["exact_member_ids"]))
    result_members = list(map(str, fh07_result["accepted_row_ids"]))
    expected_members = int(checks["expected_members"])
    if not (protocol_members == parameter_members == result_members):
        raise ProtocolLockError("protocol does not preserve the exact ordered FH-07 ensemble")
    if len(protocol_members) != expected_members or len(set(protocol_members)) != expected_members:
        raise ProtocolLockError("FH-07 member accounting drift")
    if protocol["frozen_lineage"]["selected_reference_member_id"] is not None:
        raise ProtocolLockError("a reference member was selected")
    if protocol["frozen_lineage"]["members_ranked"]:
        raise ProtocolLockError("members were ranked")

    if scope["semantic_scope_sha256"] != campaign["frozen_inputs"]["causal_scope"]["semantic_sha256"]:
        raise ProtocolLockError("causal scope hash drift")
    if scope["population_accounting"]["unique_cone_neurons"] != 196:
        raise ProtocolLockError("causal cone population drift")

    seeds = protocol["replication"]["paired_trial_seeds"]
    rewire_seeds = protocol["topology_controls"]["rewire_seeds"]
    variants = protocol["topology_controls"]["variants_per_seed"]
    if len(seeds) != int(checks["expected_trial_seeds"]) or len(set(seeds)) != len(seeds):
        raise ProtocolLockError("trial-seed accounting drift")
    if len(rewire_seeds) != int(checks["expected_rewire_seeds"]) or len(set(rewire_seeds)) != len(rewire_seeds):
        raise ProtocolLockError("rewire-seed accounting drift")
    if set(variants) != {"frozen_parameter_rewire", "same_recipe_recalibrated_rewire"}:
        raise ProtocolLockError("both mandatory topology-control families are not scheduled")

    successes = int(protocol["replication"]["minimum_directionally_consistent_pairs"])
    sign_p = _sign_test_tail(successes, len(seeds))
    if not math.isclose(sign_p, float(checks["expected_sign_test_p"]), abs_tol=1e-15):
        raise ProtocolLockError("locked sign-test probability is inconsistent")

    schedule = protocol["schedule"]
    canonical = len(protocol_members) * 2 * 2 * len(seeds)
    control = canonical * len(rewire_seeds) * len(variants)
    total = canonical + control
    expected = {
        "canonical_episodes": canonical,
        "topology_control_episodes": control,
        "total_episodes": total,
        "total_topology_variants": 1 + len(rewire_seeds) * len(variants),
    }
    for key, value in expected.items():
        if int(schedule[key]) != value or int(checks[f"expected_{key}"]) != value:
            raise ProtocolLockError(f"schedule accounting drift for {key}")

    required_mechanism_keys = {"represented", "absent_or_surrogate", "interpretation_constraints"}
    if set(protocol["mechanism_coverage"]) != required_mechanism_keys:
        raise ProtocolLockError("mechanism coverage is incomplete or unreviewed")
    if not protocol["contamination"]["forbidden_after_first_outcome_inspection"]:
        raise ProtocolLockError("contamination policy is empty")
    if protocol["measurements"]["primary_neural"]["magnitude_threshold"] is not None:
        raise ProtocolLockError("an unsupported neural magnitude threshold was introduced")
    if protocol["measurements"]["secondary_physical"]["magnitude_threshold"] is not None:
        raise ProtocolLockError("an unsupported physical magnitude threshold was introduced")

    timebase = _timebase_contract(protocol, campaign)

    semantic = {
        "protocol_sha256": frozen_hashes["protocol"],
        "scope_semantic_sha256": scope["semantic_scope_sha256"],
        "fh07_semantic_sha256": fh07_result["semantic_result_sha256"],
        "member_ids": protocol_members,
        "stimulus": protocol["stimulus"],
        "sham": protocol["sham"],
        "replication": protocol["replication"],
        "measurements": protocol["measurements"],
        "decision_rule": protocol["decision_rule"],
        "topology_controls": protocol["topology_controls"],
        "schedule": schedule,
        "mechanism_coverage": protocol["mechanism_coverage"],
        "contamination": protocol["contamination"],
    }
    semantic_hash = _canonical_hash(semantic)
    result = {
        "schema_version": 1,
        "id": campaign.get("result_id", "runner_result.first_held_out_protocol_lock.v0"),
        "campaign_id": campaign["id"],
        "protocol_id": protocol["id"],
        "status": "accepted_immutable_protocol_lock_FH08_complete",
        "completed_at": campaign.get("completed_at", datetime.now(UTC).isoformat()),
        "command": campaign.get("command", "first_held_out_protocol_lock.bat"),
        "claim_label": campaign["claim_label"],
        "frozen_input_sha256": frozen_hashes,
        "checks": {
            "held_out_outcomes_consumed": 0,
            "all_11_members_exact_and_unranked": True,
            "selected_reference_member_id": None,
            "stimulus_sham_and_mirrors_locked": True,
            "eight_paired_trial_seeds_locked": True,
            "sign_test_threshold_locked": True,
            "frozen_parameter_rewires_scheduled": True,
            "same_recipe_recalibrated_rewires_scheduled": True,
            "mechanism_coverage_attached": True,
            "contamination_policy_attached": True,
        },
        "schedule": expected,
        "trial_seed_count": len(seeds),
        "rewire_seed_count": len(rewire_seeds),
        "minimum_directionally_consistent_pairs": successes,
        "exact_one_sided_sign_test_p_at_threshold": sign_p,
        "semantic_result_sha256": semantic_hash,
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    if timebase is not None:
        result["timebase_contract"] = timebase
        result["checks"]["frozen_timebase_representability_checked"] = True
    return result


def _evaluation(
    result: Mapping[str, Any], campaign: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    campaign = campaign or {}
    return {
        "schema_version": 1,
        "id": campaign.get("evaluation_id", "evaluation.first_held_out_protocol_lock.v0"),
        "campaign_id": result["campaign_id"],
        "runner_result_id": result["id"],
        "protocol_id": result["protocol_id"],
        "status": result["status"],
        "acceptance_result": "pass",
        "protocol_locked": True,
        "protocol_executed": False,
        "held_out_outcomes_consumed": 0,
        "member_count": 11,
        "members_ranked": False,
        "selected_reference_member_id": None,
        "scheduled_episodes": result["schedule"],
        "semantic_result_sha256": result["semantic_result_sha256"],
        "interpretation": (
            "FH-08 closes prospective design only. It locks a source-backed paired "
            "stimulus/sham evaluation over all 11 unranked FH-07 members and both "
            "topology-control families. It reports no held-out result and promotes no member."
        ),
        "next_action": result["next_action"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile the immutable FH-08 held-out protocol lock")
    parser.add_argument("--check", action="store_true", help="validate committed outputs without rewriting")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--result", type=Path, default=RESULT_PATH)
    parser.add_argument("--evaluation", type=Path, default=EVALUATION_PATH)
    args = parser.parse_args()
    campaign = _load_yaml(args.campaign)
    result = compile_lock(campaign)
    evaluation = _evaluation(result, campaign)
    if args.check:
        committed_result = _load_yaml(args.result)
        committed_evaluation = _load_yaml(args.evaluation)
        if committed_result.get("semantic_result_sha256") != result["semantic_result_sha256"]:
            raise ProtocolLockError("committed runner semantic hash drift")
        if committed_evaluation.get("semantic_result_sha256") != result["semantic_result_sha256"]:
            raise ProtocolLockError("committed evaluation semantic hash drift")
        print("[PASS] FH-08 lock and committed semantic hashes are current", flush=True)
        return 0
    args.result.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    args.evaluation.write_text(yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print("[PASS] FH-08 immutable protocol lock compiled", flush=True)
    print(f"[ACCOUNTING] 11 members / 8 trial seeds / 4 rewire seeds / {result['schedule']['total_episodes']} episodes scheduled", flush=True)
    print("[OUTCOMES] 0 held-out outcomes consumed; 0 members selected or ranked", flush=True)
    print(f"[HASH] {result['semantic_result_sha256']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

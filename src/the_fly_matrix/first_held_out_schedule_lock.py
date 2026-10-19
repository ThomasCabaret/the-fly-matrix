from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import yaml

from .ledger import ROOT


CAMPAIGN_PATH = ROOT / "calibration/campaigns/first-held-out-schedule-lock-v2.yaml"
RESULT_PATH = ROOT / "calibration/runner/first-held-out-schedule-lock-v2.yaml"
EVALUATION_PATH = ROOT / "calibration/evaluations/first-held-out-schedule-lock-v2.yaml"
OUTPUT_ROOT = ROOT / "data/derived/calibration/first-held-out-schedule-lock-v2"


class HeldOutScheduleLockError(RuntimeError):
    """Raised when the outcome-blind v2 schedule loses a frozen invariant."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HeldOutScheduleLockError(f"{path} must contain a YAML mapping")
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


def _verify_inputs(campaign: Mapping[str, Any]) -> tuple[dict[str, Path], dict[str, Any]]:
    if campaign.get("primary_class") != "evaluation_only":
        raise HeldOutScheduleLockError("schedule lock must remain evaluation_only")
    if campaign.get("optimization_exposure") != "forbidden":
        raise HeldOutScheduleLockError("schedule lock cannot expose optimization")
    if int(campaign.get("held_out_outcomes_consumed", -1)) != 0:
        raise HeldOutScheduleLockError("schedule lock must consume zero held-out outcomes")
    if campaign.get("members_ranked") is not False:
        raise HeldOutScheduleLockError("schedule lock cannot rank members")

    paths: dict[str, Path] = {}
    docs: dict[str, Any] = {}
    for name, record in campaign["frozen_inputs"].items():
        path = ROOT / str(record["path"])
        if not path.is_file():
            raise HeldOutScheduleLockError(f"missing frozen input {name}: {path}")
        observed = _sha256(path)
        if observed != str(record["sha256"]):
            raise HeldOutScheduleLockError(
                f"frozen input drift for {name}: {observed} != {record['sha256']}"
            )
        paths[str(name)] = path
        if path.suffix.lower() in {".yaml", ".yml"}:
            docs[str(name)] = _load_yaml(path)
    return paths, docs


def _control_members(
    control_result: Mapping[str, Any], control_parameters: Mapping[str, Any]
) -> dict[int, list[str]]:
    if int(control_result["accounting"]["held_out_outcomes_consumed"]) != 0:
        raise HeldOutScheduleLockError("control recalibration consumed held-out outcomes")
    if control_result.get("members_ranked") is not False:
        raise HeldOutScheduleLockError("control recalibration ranked members")
    result_by_seed = {
        int(row["rewire_seed"]): list(map(str, row["fh07b_member_ids"]))
        for row in control_result["rewire_controls"]
    }
    parameters_by_seed = {
        int(row["rewire_seed"]): list(map(str, row["member_ids"]))
        for row in control_parameters["ensembles_by_rewire_seed"]
    }
    if result_by_seed != parameters_by_seed:
        raise HeldOutScheduleLockError("control result and parameter-set membership differ")
    for seed, members in result_by_seed.items():
        if not members or len(members) != len(set(members)):
            raise HeldOutScheduleLockError(f"rewire {seed} has empty or duplicate members")
    return result_by_seed


def build_v2_schedule(
    base_protocol: Mapping[str, Any],
    v2_protocol: Mapping[str, Any],
    canonical_members: Sequence[str],
    recalibrated_members: Mapping[int, Sequence[str]],
    topology_artifacts: Mapping[tuple[int, str], Mapping[str, Any]],
    scenario_namespace: str = "heldout.proprio.resistance.v2",
) -> pd.DataFrame:
    sides = list(map(str, base_protocol["stimulus"]["sides"]))
    trial_seeds = list(map(int, base_protocol["replication"]["paired_trial_seeds"]))
    rewire_seeds = list(map(int, base_protocol["topology_controls"]["rewire_seeds"]))
    if sorted(recalibrated_members) != sorted(rewire_seeds):
        raise HeldOutScheduleLockError("recalibrated-control seed accounting drift")

    topology_sets: list[tuple[dict[str, Any], Sequence[str]]] = [
        (
            {
                "topology_variant": "canonical",
                "topology_family": "canonical",
                "rewire_seed": "",
                "parameter_disposition": "frozen_canonical_member",
                "topology_artifact": "canonical_cone_from_v1_preflight",
                "topology_artifact_sha256": "inherited_from_v1_preflight",
            },
            canonical_members,
        )
    ]
    for rewire_seed in rewire_seeds:
        frozen_artifact = topology_artifacts[(rewire_seed, "frozen_parameter_rewire")]
        recalibrated_artifact = topology_artifacts[
            (rewire_seed, "same_recipe_recalibrated_rewire")
        ]
        topology_sets.extend(
            [
                (
                    {
                        "topology_variant": f"rewire-{rewire_seed}-frozen",
                        "topology_family": "frozen_parameter_rewire",
                        "rewire_seed": rewire_seed,
                        "parameter_disposition": "canonical_values_frozen_on_rewire",
                        "topology_artifact": frozen_artifact["artifact"],
                        "topology_artifact_sha256": frozen_artifact["artifact_sha256"],
                    },
                    canonical_members,
                ),
                (
                    {
                        "topology_variant": f"rewire-{rewire_seed}-recalibrated",
                        "topology_family": "same_recipe_recalibrated_rewire",
                        "rewire_seed": rewire_seed,
                        "parameter_disposition": "native_same_recipe_control_member",
                        "topology_artifact": recalibrated_artifact["artifact"],
                        "topology_artifact_sha256": recalibrated_artifact["artifact_sha256"],
                    },
                    recalibrated_members[rewire_seed],
                ),
            ]
        )

    rows: list[dict[str, Any]] = []
    for topology, members in topology_sets:
        for member_id in members:
            for side in sides:
                for condition in ("stimulus", "sham"):
                    for trial_seed in trial_seeds:
                        scenario_id = (
                            f"{scenario_namespace}/{topology['topology_variant']}/"
                            f"{member_id}/{side}/{condition}/seed-{trial_seed}"
                        )
                        rows.append(
                            {
                                "scenario_id": scenario_id,
                                **topology,
                                "member_id": str(member_id),
                                "side": side,
                                "condition": condition,
                                "trial_seed": trial_seed,
                                "outcome_status": "not_executed_outcome_blind_schedule_lock",
                            }
                        )
    schedule = pd.DataFrame(rows)
    expected = int(v2_protocol["schedule"]["total_episodes"])
    if len(schedule) != expected or schedule["scenario_id"].nunique() != expected:
        raise HeldOutScheduleLockError("v2 schedule is not exactly unique and exhaustive")
    return schedule


def compile_schedule_lock(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    campaign_path = campaign_path if campaign_path.is_absolute() else ROOT / campaign_path
    result_path = result_path if result_path.is_absolute() else ROOT / result_path
    evaluation_path = evaluation_path if evaluation_path.is_absolute() else ROOT / evaluation_path
    output_root = output_root if output_root.is_absolute() else ROOT / output_root
    print("[1/6] Verifying v2, v1 lineage and zero-outcome frozen inputs", flush=True)
    campaign = _load_yaml(campaign_path)
    paths, docs = _verify_inputs(campaign)
    protocol = docs["protocol_v2"]
    base_protocol = docs["base_protocol_v1"]
    preflight = docs["preflight_v1"]
    control_result = docs["control_recalibration"]
    control_parameters = docs["control_parameter_set"]
    canonical_parameters = docs["canonical_parameter_set"]

    if protocol["base_protocol"]["sha256"] != _sha256(paths["base_protocol_v1"]):
        raise HeldOutScheduleLockError("v2 embedded base-protocol hash drift")
    if protocol["supersession"]["predecessor_outcome_rows"] != 0:
        raise HeldOutScheduleLockError("v1 was not outcome-free at supersession")
    if protocol["lock_assertions"]["simulated_held_out_outcomes_inspected"]:
        raise HeldOutScheduleLockError("held-out outcomes were inspected before v2 lock")
    if int(preflight["held_out_outcomes_consumed"]) != 0:
        raise HeldOutScheduleLockError("v1 preflight consumed outcomes")

    print("[2/6] Accounting canonical and native recalibrated-control ensembles", flush=True)
    canonical_members = list(map(str, canonical_parameters["exact_member_ids"]))
    base_members = list(map(str, base_protocol["frozen_lineage"]["member_ids"]))
    if canonical_members != base_members or len(canonical_members) != 11:
        raise HeldOutScheduleLockError("canonical eleven-member lineage drift")
    recalibrated_members = _control_members(control_result, control_parameters)
    counts = {seed: len(members) for seed, members in recalibrated_members.items()}
    expected_counts = {
        int(seed): int(count)
        for seed, count in protocol["schedule"]["recalibrated_control_members_by_seed"].items()
    }
    if counts != expected_counts or sum(counts.values()) != 41:
        raise HeldOutScheduleLockError("v2 native control cardinality drift")

    print("[3/6] Verifying all eight inherited topology artifacts", flush=True)
    topology_artifacts: dict[tuple[int, str], Mapping[str, Any]] = {}
    for row in preflight["topology_controls"]:
        key = (int(row["rewire_seed"]), str(row["control_family"]))
        artifact = ROOT / str(row["artifact"])
        if not artifact.is_file() or _sha256(artifact) != str(row["artifact_sha256"]):
            raise HeldOutScheduleLockError(f"topology artifact drift for {key}")
        topology_artifacts[key] = row
    if len(topology_artifacts) != 8:
        raise HeldOutScheduleLockError("eight topology-control artifacts are required")

    print("[4/6] Compiling the exact native-cardinality v2 schedule", flush=True)
    schedule = build_v2_schedule(
        base_protocol,
        protocol,
        canonical_members,
        recalibrated_members,
        topology_artifacts,
        str(campaign["scenario_namespace"]),
    )
    output_root.mkdir(parents=True, exist_ok=True)
    schedule_path = output_root / "execution-schedule.csv"
    schedule.to_csv(schedule_path, index=False, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    family_counts = {
        str(key): int(value)
        for key, value in schedule["topology_family"].value_counts().sort_index().items()
    }
    expected_family_counts = {
        "canonical": 352,
        "frozen_parameter_rewire": 1408,
        "same_recipe_recalibrated_rewire": 1312,
    }
    if family_counts != expected_family_counts:
        raise HeldOutScheduleLockError(f"v2 schedule family accounting drift: {family_counts}")

    print("[5/6] Checking comparison, contamination and no-selection contracts", flush=True)
    comparison = protocol["topology_comparison"]
    assertions = protocol["lock_assertions"]
    checks = {
        "held_out_outcomes_consumed_zero": True,
        "canonical_eleven_members_exact_and_unranked": assertions["canonical_members_ranked"] is False,
        "all_41_native_control_members_accounted": sum(counts.values()) == 41,
        "control_cardinality_equalization_forbidden": protocol["ensemble_membership"]["policy"]["equalize_cardinality"] == "forbidden",
        "frozen_rewires_remain_member_paired": comparison["frozen_parameter_rewires"]["pairing"] == "same_parameter_member_and_trial_seed",
        "recalibrated_controls_use_complete_ensemble_fraction": "fraction" in comparison["same_recipe_recalibrated_rewires"]["ensemble_statistic"],
        "native_measurements_remain_separate": bool(comparison["same_recipe_recalibrated_rewires"]["uncertainty_reporting"]),
        "schedule_exactly_3072_unique_rows": len(schedule) == schedule["scenario_id"].nunique() == 3072,
        "no_member_selected": assertions["selected_reference_member_id"] is None,
        "predecessor_outcomes_zero": protocol["supersession"]["predecessor_outcome_rows"] == 0,
    }
    if not all(checks.values()):
        raise HeldOutScheduleLockError(
            f"v2 schedule lock failed: {[key for key, value in checks.items() if not value]}"
        )

    semantic_payload = {
        "campaign_id": campaign["id"],
        "frozen_input_sha256": {key: _sha256(path) for key, path in paths.items()},
        "canonical_member_ids": canonical_members,
        "control_member_ids_by_seed": recalibrated_members,
        "topology_artifact_sha256": {
            f"{seed}:{family}": str(row["artifact_sha256"])
            for (seed, family), row in sorted(topology_artifacts.items())
        },
        "comparison": comparison,
        "schedule_semantic_sha256": _canonical_hash(schedule.to_dict(orient="records")),
        "checks": checks,
    }
    semantic_hash = _canonical_hash(semantic_payload)
    result = {
        "schema_version": 1,
        "id": "runner_result.first_held_out_schedule_lock.v2",
        "campaign_id": campaign["id"],
        "protocol_id": protocol["id"],
        "status": "accepted_outcome_blind_native_control_schedule_execution_ready",
        "completed_at": datetime.now(UTC).isoformat(),
        "command": "first_held_out_schedule_lock_v2.bat",
        "claim_label": campaign["claim_label"],
        "frozen_input_sha256": semantic_payload["frozen_input_sha256"],
        "held_out_outcomes_consumed": 0,
        "members_ranked": False,
        "selected_reference_member_id": None,
        "control_member_counts_by_seed": counts,
        "schedule": {
            "rows": len(schedule),
            "unique_scenarios": int(schedule["scenario_id"].nunique()),
            "topology_variants": int(schedule["topology_variant"].nunique()),
            "family_rows": family_counts,
            "artifact": schedule_path.relative_to(ROOT).as_posix(),
            "artifact_sha256": _sha256(schedule_path),
            "semantic_sha256": semantic_payload["schedule_semantic_sha256"],
        },
        "checks": checks,
        "semantic_result_sha256": semantic_hash,
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.first_held_out_schedule_lock.v2",
        "status": result["status"],
        "protocol_id": protocol["id"],
        "primary_class": "evaluation_only",
        "protocol_locked": True,
        "protocol_executed": False,
        "held_out_outcomes_consumed": 0,
        "members_ranked": False,
        "result_ref": result_path.relative_to(ROOT).as_posix(),
        "semantic_result_sha256": semantic_hash,
        "schedule": result["schedule"],
        "control_member_counts_by_seed": counts,
        "checks": checks,
        "interpretation": (
            "V2 accounts every native same-recipe control survivor without selecting, "
            "duplicating or dropping members. It locks execution mechanics and an "
            "unequal-ensemble comparison before any held-out response exists."
        ),
        "next_action": campaign["next_action"],
    }
    print("[6/6] Writing compact result and evaluation records", flush=True)
    result_path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    evaluation_path.write_text(yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(
        f"[COMPLETE] scenarios={len(schedule)} controls=41 outcomes=0 semantic={semantic_hash}",
        flush=True,
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lock the outcome-blind FH-09 v2 execution schedule")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--result", type=Path, default=RESULT_PATH)
    parser.add_argument("--evaluation", type=Path, default=EVALUATION_PATH)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    compile_schedule_lock(args.campaign, args.result, args.evaluation, args.output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

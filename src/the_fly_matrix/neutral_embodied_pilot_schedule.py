from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Any

import yaml

from .ledger import ROOT


CAMPAIGN_PATH = (
    ROOT / "calibration" / "campaigns" / "neutral-embodied-stability-pilot-v0.yaml"
)
SCHEDULE_PATH = (
    ROOT / "calibration" / "schedules" / "neutral-embodied-stability-pilot-v0.csv"
)
RESULT_PATH = (
    ROOT / "calibration" / "runner" / "neutral-embodied-stability-pilot-schedule-v0.yaml"
)


class NeutralPilotScheduleError(RuntimeError):
    """Raised when the bounded neutral-pilot schedule is incomplete or drifts."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise NeutralPilotScheduleError(f"{path} must contain a YAML mapping")
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


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def evenly_spaced_indices(total: int, selected: int) -> list[int]:
    if total < 1 or selected < 2 or selected > total:
        raise NeutralPilotScheduleError("invalid evenly-spaced selection dimensions")
    values = [round(index * (total - 1) / (selected - 1)) for index in range(selected)]
    if len(set(values)) != selected or values[0] != 0 or values[-1] != total - 1:
        raise NeutralPilotScheduleError("evenly-spaced selection is not unique or bounded")
    return values


def _ordered_unique(rows: list[dict[str, str]], key: str) -> list[str]:
    return list(dict.fromkeys(row[key] for row in rows))


def _load_axes(campaign: dict[str, Any]) -> dict[str, Any]:
    frozen = campaign["frozen_inputs"]
    uncertainty = _load_yaml(ROOT / frozen["uncertainty_result"])
    measurement = _load_yaml(ROOT / frozen["measurement_result"])
    actuator = _load_yaml(ROOT / frozen["actuator_attribution_result"])
    bridge = _load_yaml(ROOT / frozen["motor_bridge_result"])
    motor_ensemble = _load_yaml(ROOT / frozen["motor_class_ensemble"])

    expected_hashes = campaign["frozen_semantic_hashes"]
    if uncertainty["semantic_result_sha256"] != expected_hashes["uncertainty_result"]:
        raise NeutralPilotScheduleError("front-leg uncertainty result drift")
    if measurement["semantic_result_sha256"] != expected_hashes["measurement_result"]:
        raise NeutralPilotScheduleError("embodied measurement result drift")
    if bridge["semantic_result_sha256"] != expected_hashes["motor_bridge_result"]:
        raise NeutralPilotScheduleError("motor bridge result drift")
    if (
        measurement["model_contract"]["contract_sha256"]
        != frozen["physical_model_contract_sha256"]
    ):
        raise NeutralPilotScheduleError("physical model contract drift")
    if (
        actuator["frozen_inputs"]["actuator_contract_sha256"]
        != frozen["actuator_semantics_contract_sha256"]
    ):
        raise NeutralPilotScheduleError("actuator semantics contract drift")
    if actuator["status"] != "accepted_bounded_direct_motor_surrogate_initial_short_horizon":
        raise NeutralPilotScheduleError("direct-motor surrogate gate is not accepted")

    profile_path = ROOT / frozen["intermediate_profile_panel"]
    profiles = _ordered_unique(_read_csv(profile_path), "profile_id")

    feco_path = ROOT / frozen["feco_joint_source_paths"]
    feco_source_paths = json.loads(feco_path.read_text(encoding="utf-8"))
    if not isinstance(feco_source_paths, list):
        raise NeutralPilotScheduleError("FeCO source paths must be a list")
    feco_alternatives = []
    for path_index, source_path in enumerate(feco_source_paths):
        for representation in ("graded_candidate", "event_candidate"):
            feco_alternatives.append(
                {
                    "id": f"feco_{path_index:02d}_{representation}",
                    "source_path_index": path_index,
                    "native_representation": representation,
                    "source_path": source_path,
                }
            )

    members = sorted(
        (int(member["body_id"]) for member in motor_ensemble["members"])
    )
    classes = list(motor_ensemble["admissible_classes"])
    if classes[:2] != ["fast_81A07", "intermediate_22A08"]:
        raise NeutralPilotScheduleError("executable motor class ordering drift")

    route_path = ROOT / frozen["motor_basis_probes"]
    route_rows = _read_csv(route_path)
    route_keys = sorted(
        {
            (
                int(row["body_id"]),
                int(row["target_actuator_id"]),
                row["target_actuator_name"],
            )
            for row in route_rows
        }
    )
    gains = [
        float(value)
        for value in bridge["conditional_gain_envelope"][
            "candidate_gains_command_per_uN"
        ]
    ]
    return {
        "profiles": profiles,
        "feco_alternatives": feco_alternatives,
        "motor_body_ids": members,
        "motor_classes": classes,
        "routes": route_keys,
        "gains": gains,
        "input_hashes": {
            "intermediate_profile_panel": _sha256(profile_path),
            "feco_joint_source_paths": _sha256(feco_path),
            "motor_basis_probes": _sha256(route_path),
            "motor_class_ensemble": _sha256(ROOT / frozen["motor_class_ensemble"]),
        },
        "upstream": uncertainty,
    }


def build_schedule(
    campaign: dict[str, Any], axes: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    policy = campaign["schedule_policy"]
    tuple_count = int(policy["scheduled_tuples"])
    motor_contract = axes["upstream"]["interface_decisions"]["motor"]
    motor_total = int(motor_contract["kernel_executable_fast_or_intermediate_assignments"])
    motor_indices = evenly_spaced_indices(motor_total, tuple_count)
    profiles = axes["profiles"]
    feco = axes["feco_alternatives"]
    routes = axes["routes"]
    gains = axes["gains"]
    body_ids = axes["motor_body_ids"]
    seeds = range(int(policy["seed_base"]), int(policy["seed_base"]) + tuple_count)

    rows: list[dict[str, Any]] = []
    for tuple_index, (motor_index, seed) in enumerate(zip(motor_indices, seeds, strict=True)):
        alternative = feco[tuple_index % len(feco)]
        route_body, actuator_id, actuator_name = routes[tuple_index % len(routes)]
        signature = "".join(
            "I" if (motor_index >> bit_index) & 1 else "F"
            for bit_index in range(len(body_ids))
        )
        tuple_id = f"neutral_tuple_{tuple_index:03d}"
        rows.append(
            {
                "tuple_id": tuple_id,
                "seed": seed,
                "intermediate_profile_id": profiles[tuple_index % len(profiles)],
                "feco_alternative_id": alternative["id"],
                "feco_source_path_index": alternative["source_path_index"],
                "feco_native_representation": alternative["native_representation"],
                "motor_assignment_index": motor_index,
                "motor_assignment_signature": signature,
                "route_body_id": route_body,
                "route_target_actuator_id": actuator_id,
                "route_target_actuator_name": actuator_name,
                "bridge_gain_index": tuple_index % len(gains),
                "bridge_gain_command_per_uN": gains[tuple_index % len(gains)],
                "baseline_scenario_id": f"{tuple_id}.baseline",
                "perturbed_scenario_id": f"{tuple_id}.generic_qvel_impulse",
            }
        )

    motor_balance = {}
    for bit_index, body_id in enumerate(body_ids):
        intermediate_count = sum((index >> bit_index) & 1 for index in motor_indices)
        motor_balance[str(body_id)] = {
            "fast_81A07": tuple_count - intermediate_count,
            "intermediate_22A08": intermediate_count,
        }
    pairwise_states = {
        (left, right): len(
            {((index >> left) & 1, (index >> right) & 1) for index in motor_indices}
        )
        for left, right in combinations(range(len(body_ids)), 2)
    }
    coverage = {
        "scheduled_tuples": len(rows),
        "paired_physical_episodes": len(rows) * 2,
        "intermediate_profiles": _count_coverage(rows, "intermediate_profile_id", len(profiles)),
        "feco_alternatives": _count_coverage(rows, "feco_alternative_id", len(feco)),
        "motor_assignments": {
            "scientific_total": int(
                motor_contract["scientific_class_assignment_upper_bound"]
            ),
            "kernel_executable_total": motor_total,
            "scheduled_unique": len(set(motor_indices)),
            "kernel_executable_unscheduled": motor_total - len(set(motor_indices)),
            "blocked_slow_containing": int(
                motor_contract["kernel_blocked_slow_containing_assignments"]
            ),
            "selected_indices": motor_indices,
            "signature_body_order": body_ids,
            "per_body_class_counts": motor_balance,
            "body_pairs_with_all_four_fast_intermediate_states": sum(
                value == 4 for value in pairwise_states.values()
            ),
            "body_pairs_total": len(pairwise_states),
        },
        "route_basis_edges": _count_coverage(
            rows,
            "route_target_actuator_name",
            len(routes),
            compound_key=("route_body_id", "route_target_actuator_id"),
        ),
        "bridge_gains": _count_coverage(rows, "bridge_gain_index", len(gains)),
        "full_executable_cartesian_product": (
            len(profiles) * len(feco) * motor_total * len(routes) * len(gains)
        ),
        "full_scientific_cartesian_product": (
            len(profiles)
            * len(feco)
            * int(motor_contract["scientific_class_assignment_upper_bound"])
            * len(routes)
            * len(gains)
        ),
        "cartesian_product_materialized": False,
    }
    return rows, coverage


def _count_coverage(
    rows: list[dict[str, Any]],
    key: str,
    expected_unique: int,
    *,
    compound_key: tuple[str, str] | None = None,
) -> dict[str, int]:
    if compound_key is None:
        counts = Counter(row[key] for row in rows)
    else:
        counts = Counter((row[compound_key[0]], row[compound_key[1]]) for row in rows)
    return {
        "available": expected_unique,
        "scheduled_unique": len(counts),
        "unscheduled": expected_unique - len(counts),
        "minimum_repetitions": min(counts.values()),
        "maximum_repetitions": max(counts.values()),
    }


def _validate(campaign: dict[str, Any], coverage: dict[str, Any]) -> None:
    expected = campaign["acceptance"]
    if campaign["behavior_targets"]:
        raise NeutralPilotScheduleError("neutral pilot cannot expose behavior targets")
    if int(campaign["parameter_policy"]["optimized_parameters"]) != 0:
        raise NeutralPilotScheduleError("schedule-only pilot cannot optimize parameters")
    if campaign["schedule_policy"]["candidate_selection_from_body_motion"] is not False:
        raise NeutralPilotScheduleError("body motion cannot select schedule candidates")
    checks = {
        "tuple_count": coverage["scheduled_tuples"] == int(expected["scheduled_tuples"]),
        "paired_episodes": coverage["paired_physical_episodes"] == int(expected["paired_physical_episodes"]),
        "all_profiles": coverage["intermediate_profiles"]["unscheduled"] == 0,
        "all_feco": coverage["feco_alternatives"]["unscheduled"] == 0,
        "all_routes": coverage["route_basis_edges"]["unscheduled"] == 0,
        "all_gains": coverage["bridge_gains"]["unscheduled"] == 0,
        "motor_sample": coverage["motor_assignments"]["scheduled_unique"]
        == int(expected["scheduled_motor_assignments"]),
        "motor_balance": all(
            counts["fast_81A07"] == counts["intermediate_22A08"]
            for counts in coverage["motor_assignments"]["per_body_class_counts"].values()
        ),
        "motor_pairwise": coverage["motor_assignments"][
            "body_pairs_with_all_four_fast_intermediate_states"
        ]
        == coverage["motor_assignments"]["body_pairs_total"],
        "blocked_slow_visible": coverage["motor_assignments"][
            "blocked_slow_containing"
        ]
        == int(expected["blocked_slow_assignments"]),
        "profile_count": coverage["intermediate_profiles"]["available"]
        == int(expected["available_intermediate_profiles"]),
        "feco_count": coverage["feco_alternatives"]["available"]
        == int(expected["available_feco_alternatives"]),
        "motor_executable_count": coverage["motor_assignments"][
            "kernel_executable_total"
        ]
        == int(expected["available_motor_kernel_executable_assignments"]),
        "route_count": coverage["route_basis_edges"]["available"]
        == int(expected["available_route_basis_edges"]),
        "gain_count": coverage["bridge_gains"]["available"] == int(expected["available_bridge_gains"]),
    }
    if not all(checks.values()):
        raise NeutralPilotScheduleError(
            f"schedule acceptance failed: {[key for key, value in checks.items() if not value]}"
        )


def compile_schedule(
    campaign_path: Path = CAMPAIGN_PATH,
    schedule_path: Path = SCHEDULE_PATH,
    result_path: Path = RESULT_PATH,
) -> dict[str, Any]:
    campaign = _load_yaml(campaign_path)
    print("[1/5] Verifying frozen measurement and uncertainty contracts", flush=True)
    axes = _load_axes(campaign)
    print("[2/5] Building the deterministic factorized tuple panel", flush=True)
    rows, coverage = build_schedule(campaign, axes)
    print("[3/5] Checking coverage, balance, leakage and blockers", flush=True)
    _validate(campaign, coverage)

    print("[4/5] Writing the exact versioned schedule", flush=True)
    schedule_path.parent.mkdir(parents=True, exist_ok=True)
    with schedule_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    result = {
        "schema_version": 1,
        "id": "runner_result.neutral_embodied_stability_pilot_schedule.v0",
        "campaign_id": campaign["id"],
        "target_id": campaign["target_id"],
        "status": "schedule_complete_execution_not_started_stability_unresolved",
        "claim_label": campaign["claim_label"],
        "behavior_targets": [],
        "command": "neutral_embodied_pilot_schedule.bat",
        "campaign_sha256": _sha256(campaign_path),
        "implementation_sha256": _sha256(Path(__file__).resolve()),
        "input_hashes": axes["input_hashes"],
        "frozen_semantic_hashes": campaign["frozen_semantic_hashes"],
        "coverage": coverage,
        "threshold_contract": campaign["technical_thresholds"],
        "parameter_policy": campaign["parameter_policy"],
        "schedule": {
            "path": str(schedule_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": _sha256(schedule_path),
            "semantic_sha256": _canonical_hash(rows),
        },
        "interpretation": {
            "schedule_preregistered": True,
            "execution_started": False,
            "stability_accepted": False,
            "parameter_values_promoted": 0,
            "candidate_selected_from_body_motion": False,
            "global_whole_body_stability_claim_allowed": False,
        },
        "next_action": campaign["next_action"],
    }
    result["semantic_result_sha256"] = _canonical_hash(result)
    result_path.write_text(yaml.safe_dump(result, sort_keys=False), encoding="utf-8")

    print("[5/5] Summary", flush=True)
    print(
        f"[SCHEDULE] {coverage['scheduled_tuples']} tuples / "
        f"{coverage['paired_physical_episodes']} paired episodes",
        flush=True,
    )
    print(
        f"[MOTOR] {coverage['motor_assignments']['scheduled_unique']} scheduled, "
        f"{coverage['motor_assignments']['kernel_executable_unscheduled']} executable unscheduled, "
        f"{coverage['motor_assignments']['blocked_slow_containing']} slow blocked",
        flush=True,
    )
    print("[BOUNDARY] schedule only; 0 fit, 0 selection, 0 behavior", flush=True)
    print(f"[HASH] {result['semantic_result_sha256']}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile the bounded neutral embodied pilot schedule")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    compile_schedule(args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

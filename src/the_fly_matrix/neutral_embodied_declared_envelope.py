from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from itertools import combinations, product
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd
import yaml

from .ledger import ROOT


CAMPAIGN_PATH = (
    ROOT / "calibration" / "campaigns" / "neutral-embodied-declared-envelope-v0.yaml"
)
SCHEDULE_PATH = (
    ROOT / "calibration" / "schedules" / "neutral-embodied-declared-envelope-v0.csv"
)
RESULT_PATH = (
    ROOT / "calibration" / "runner" / "neutral-embodied-declared-envelope-v0.yaml"
)
EVALUATION_PATH = (
    ROOT / "calibration" / "evaluations" / "neutral-embodied-declared-envelope-v0.yaml"
)


class DeclaredEnvelopeError(RuntimeError):
    """Raised when the preregistered candidate-envelope contract drifts."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DeclaredEnvelopeError(f"{path} must contain a YAML mapping")
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


def _load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = _load_yaml(path)
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise DeclaredEnvelopeError("declared envelope must remain diagnostic_only")
    if campaign.get("behavior_targets"):
        raise DeclaredEnvelopeError("declared envelope cannot expose behavior targets")
    if campaign.get("topology_changes_allowed") is not False:
        raise DeclaredEnvelopeError("declared envelope cannot change topology")
    capacity = campaign["capacity_policy"]
    for key in ("optimized_parameters", "promoted_parameter_values", "selected_candidates"):
        if int(capacity.get(key, -1)) != 0:
            raise DeclaredEnvelopeError(f"declared envelope requires zero {key}")
    if campaign["schedule_policy"].get("candidate_selection_from_body_motion") is not False:
        raise DeclaredEnvelopeError("body motion cannot select an envelope member")
    return campaign


def _verify_frozen_inputs(campaign: Mapping[str, Any]) -> dict[str, Path]:
    frozen = campaign["frozen_inputs"]
    pairs = {
        "passed_panel_campaign": "passed_panel_campaign_sha256",
        "passed_panel_result": "passed_panel_result_sha256",
        "base_schedule": "base_schedule_sha256",
        "population_members": "population_members_sha256",
        "classified_intermediates": "classified_intermediates_sha256",
        "central_paths": "central_paths_sha256",
        "event_comparator_model": "event_comparator_model_sha256",
    }
    paths: dict[str, Path] = {}
    for key, hash_key in pairs.items():
        path = ROOT / str(frozen[key])
        observed = _sha256(path)
        expected = str(frozen[hash_key])
        if observed != expected:
            raise DeclaredEnvelopeError(
                f"frozen input drift for {key}: expected {expected}, observed {observed}"
            )
        paths[key] = path
    panel = _load_yaml(paths["passed_panel_result"])
    if panel.get("status") != "pass_full_local_chain_panel_execution_no_calibration":
        raise DeclaredEnvelopeError("passed full-chain panel is no longer accepted")
    return paths


def _projective_directions(base: int, dimension: int) -> list[tuple[int, ...]]:
    directions: list[tuple[int, ...]] = []
    for vector in product(range(base), repeat=dimension):
        if not any(vector):
            continue
        first = next(value for value in vector if value)
        if first != 1:
            continue
        directions.append(tuple(int(value) for value in vector))
    return directions


def _dot_mod(left: Sequence[int], right: Sequence[int], base: int) -> int:
    return sum(a * b for a, b in zip(left, right, strict=True)) % base


def _profile_panel(
    object_ids: Sequence[str],
    *,
    base: int,
    dimension: int,
) -> tuple[list[dict[str, int]], dict[str, tuple[int, ...]]]:
    directions = _projective_directions(base, dimension)
    if len(object_ids) > len(directions):
        raise DeclaredEnvelopeError("insufficient projective directions for panel")
    selected = dict(zip(object_ids, directions[: len(object_ids)], strict=True))
    profiles = []
    for index, point in enumerate(product(range(base), repeat=dimension)):
        profile = {object_id: _dot_mod(direction, point, base) for object_id, direction in selected.items()}
        profile["_index"] = index
        profiles.append(profile)
    return profiles, selected


def _pairwise_coverage(
    profiles: Sequence[Mapping[str, int]], object_ids: Sequence[str], levels: int
) -> dict[str, int]:
    missing_pairs = 0
    minimum = len(profiles)
    maximum = 0
    for left, right in combinations(object_ids, 2):
        counts = Counter((profile[left], profile[right]) for profile in profiles)
        if len(counts) != levels * levels:
            missing_pairs += 1
        if counts:
            minimum = min(minimum, min(counts.values()))
            maximum = max(maximum, max(counts.values()))
    return {
        "object_pairs": len(list(combinations(object_ids, 2))),
        "pairs_missing_a_state": missing_pairs,
        "minimum_state_repetitions": minimum,
        "maximum_state_repetitions": maximum,
    }


def _numeric_profiles(campaign: Mapping[str, Any]) -> list[dict[str, Any]]:
    axes = campaign["factorized_envelope"]["local_numeric_profiles"]["cartesian_axes"]
    values = []
    for index, (graded_tau, input_scale, intensity) in enumerate(
        product(
            axes["graded_membrane_tau_s"],
            axes["dimensionless_input_scale"],
            axes["unresolved_event_intensity_ceiling_hz"],
        )
    ):
        values.append(
            {
                "profile_id": f"numeric_{index:02d}",
                "graded_membrane_tau_s": float(graded_tau),
                "dimensionless_input_scale": float(input_scale),
                "unresolved_event_intensity_ceiling_hz": float(intensity),
            }
        )
    return values


def _axis_counts(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(row[key]) for row in rows)
    return {
        "unique": len(counts),
        "minimum_repetitions": min(counts.values()),
        "maximum_repetitions": max(counts.values()),
    }


def compile_declared_envelope(
    campaign_path: Path = CAMPAIGN_PATH,
    schedule_path: Path = SCHEDULE_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
) -> dict[str, Any]:
    campaign = _load_campaign(campaign_path)
    print("[1/6] Verifying the passed panel and frozen local-chain inputs", flush=True)
    paths = _verify_frozen_inputs(campaign)

    members = pd.read_csv(paths["population_members"])
    feco = members.loc[
        members["population_id"].eq("population.front_leg_feco.v0")
    ].copy()
    classified = pd.read_csv(paths["classified_intermediates"])
    central_paths = pd.read_csv(paths["central_paths"])
    event_model = _load_yaml(paths["event_comparator_model"])
    base_rows = _read_csv(paths["base_schedule"])

    feco_groups = sorted(feco["route_channel_id"].astype(str).unique())
    unknown_bodies = sorted(
        str(int(value))
        for value in classified.loc[classified["sign_code"].eq(0), "body_id"]
    )
    acceptance = campaign["acceptance"]
    observed = {
        "feco_bodies": len(feco),
        "feco_route_groups": len(feco_groups),
        "unknown_sign_bodies": len(unknown_bodies),
        "base_schedule_tuples": len(base_rows),
    }
    expected = {
        "feco_bodies": int(acceptance["expected_feco_bodies"]),
        "feco_route_groups": int(acceptance["expected_feco_route_groups"]),
        "unknown_sign_bodies": int(acceptance["expected_unknown_sign_bodies"]),
        "base_schedule_tuples": int(acceptance["expected_base_schedule_tuples"]),
    }
    if observed != expected:
        raise DeclaredEnvelopeError(f"local population accounting drift: {observed}")
    if not (central_paths["first_edge_weight"] > 0).all():
        raise DeclaredEnvelopeError("central structural weights must be positive counts")

    print("[2/6] Building balanced FeCO-routing and unknown-sign panels", flush=True)
    feco_profiles, feco_directions = _profile_panel(
        feco_groups, base=3, dimension=4
    )
    sign_profiles, sign_directions = _profile_panel(
        unknown_bodies, base=2, dimension=6
    )
    feco_pairwise = _pairwise_coverage(feco_profiles, feco_groups, 3)
    sign_pairwise = _pairwise_coverage(sign_profiles, unknown_bodies, 2)
    numeric_profiles = _numeric_profiles(campaign)

    functional_levels = campaign["factorized_envelope"]["feco_functional_routing"]["levels"]
    tuple_count = int(campaign["schedule_policy"]["tuples"])
    seed_base = int(campaign["schedule_policy"]["seed_base"])
    rows: list[dict[str, Any]] = []
    for index in range(tuple_count):
        base = base_rows[index % len(base_rows)]
        feco_profile = feco_profiles[index % len(feco_profiles)]
        sign_profile = sign_profiles[index % len(sign_profiles)]
        numeric = numeric_profiles[index % len(numeric_profiles)]
        rows.append(
            {
                "tuple_id": f"declared_tuple_{index:03d}",
                "seed": seed_base + index,
                "base_tuple_id": base["tuple_id"],
                "feco_routing_profile_id": f"feco_route_{int(feco_profile['_index']):02d}",
                "unknown_sign_profile_id": f"unknown_sign_{int(sign_profile['_index']):02d}",
                "numeric_profile_id": numeric["profile_id"],
                "intermediate_profile_id": base["intermediate_profile_id"],
                "feco_alternative_id": base["feco_alternative_id"],
                "feco_source_path_index": base["feco_source_path_index"],
                "feco_native_representation": base["feco_native_representation"],
                "motor_assignment_index": base["motor_assignment_index"],
                "motor_assignment_signature": base["motor_assignment_signature"],
                "route_body_id": base["route_body_id"],
                "route_target_actuator_id": base["route_target_actuator_id"],
                "route_target_actuator_name": base["route_target_actuator_name"],
                "bridge_gain_index": base["bridge_gain_index"],
                "bridge_gain_command_per_uN": base["bridge_gain_command_per_uN"],
                "graded_membrane_tau_s": numeric["graded_membrane_tau_s"],
                "dimensionless_input_scale": numeric["dimensionless_input_scale"],
                "unresolved_event_intensity_ceiling_hz": numeric[
                    "unresolved_event_intensity_ceiling_hz"
                ],
            }
        )

    print("[3/6] Checking exact coverage and absence of silent defaults", flush=True)
    coverage = {
        "schedule_tuples": len(rows),
        "base_schedule": _axis_counts(rows, "base_tuple_id"),
        "feco_routing_profiles": _axis_counts(rows, "feco_routing_profile_id"),
        "unknown_sign_profiles": _axis_counts(rows, "unknown_sign_profile_id"),
        "numeric_profiles": _axis_counts(rows, "numeric_profile_id"),
        "intermediate_profiles": _axis_counts(rows, "intermediate_profile_id"),
        "feco_alternatives": _axis_counts(rows, "feco_alternative_id"),
        "motor_assignments": _axis_counts(rows, "motor_assignment_index"),
        "route_basis_edges": {
            "unique": len(
                {
                    (row["route_body_id"], row["route_target_actuator_id"])
                    for row in rows
                }
            )
        },
        "bridge_gains": _axis_counts(rows, "bridge_gain_index"),
    }
    checks = {
        "schedule_size": len(rows) == int(acceptance["expected_schedule_tuples"]),
        "feco_profile_count": len(feco_profiles)
        == int(acceptance["expected_feco_routing_profiles"]),
        "sign_profile_count": len(sign_profiles)
        == int(acceptance["expected_sign_profiles"]),
        "numeric_profile_count": len(numeric_profiles)
        == int(acceptance["expected_numeric_profiles"]),
        "feco_pairwise_complete": feco_pairwise["pairs_missing_a_state"] == 0,
        "sign_pairwise_complete": sign_pairwise["pairs_missing_a_state"] == 0,
        "all_base_rows_present": coverage["base_schedule"]["unique"] == len(base_rows),
        "all_feco_profiles_present": coverage["feco_routing_profiles"]["unique"]
        == len(feco_profiles),
        "all_sign_profiles_present": coverage["unknown_sign_profiles"]["unique"]
        == len(sign_profiles),
        "all_numeric_profiles_present": coverage["numeric_profiles"]["unique"]
        == len(numeric_profiles),
        "no_round_robin_field": all(
            "round_robin" not in json.dumps(row) for row in rows
        ),
        "no_fixed_unknown_sign_field": all(
            "unknown_sign_diagnostic_candidate" not in row for row in rows
        ),
    }
    if not all(checks.values()):
        raise DeclaredEnvelopeError(
            f"declared envelope acceptance failed: {[key for key, value in checks.items() if not value]}"
        )

    print("[4/6] Writing the exact 240-tuple versioned schedule", flush=True)
    schedule_path.parent.mkdir(parents=True, exist_ok=True)
    with schedule_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    reference_constants = event_model["reference_constants"]
    event_constants = {
        key: reference_constants[key]["value"]
        for key in (
            "v_rest_mV",
            "reset_mV",
            "threshold_mV",
            "tau_membrane_ms",
            "tau_syn_ms",
            "refractory_ms",
            "fixed_delay_ms",
        )
    }
    completed_next_action = (
        "Implement and execute one bounded neural sentinel over this exact 240-tuple "
        "schedule. It must consume the declared FeCO-routing, unknown-sign and "
        "numeric profiles before any new physical panel, without ranking members "
        "from neural magnitude or body motion."
    )
    result: dict[str, Any] = {
        "schema_version": 1,
        "id": "runner_result.neutral_embodied_declared_envelope.v0",
        "campaign_id": campaign["id"],
        "target_ids": campaign["target_ids"],
        "status": "pass_declared_envelope_schedule_no_fit_no_execution",
        "claim_label": campaign["claim_label"],
        "behavior_targets": [],
        "command": "neutral_embodied_declared_envelope.bat",
        "campaign_sha256": _sha256(campaign_path),
        "implementation_sha256": _sha256(Path(__file__).resolve()),
        "input_hashes": {key: _sha256(path) for key, path in paths.items()},
        "accounting": observed,
        "factorized_panels": {
            "feco_routing": {
                "groups": len(feco_groups),
                "profiles": len(feco_profiles),
                "levels": functional_levels,
                "directions": {
                    key: list(value) for key, value in feco_directions.items()
                },
                "pairwise": feco_pairwise,
                "selected_profile": None,
            },
            "unknown_sign": {
                "bodies": len(unknown_bodies),
                "profiles": len(sign_profiles),
                "levels": [-1, 1],
                "level_encoding": "GF2_level_0_means_minus_1_level_1_means_plus_1",
                "directions": {
                    key: list(value) for key, value in sign_directions.items()
                },
                "pairwise": sign_pairwise,
                "selected_profile": None,
            },
            "numeric": {
                "profiles": numeric_profiles,
                "source_aligned_event_constants": event_constants,
                "selected_profile": None,
            },
            "structural_coupling": campaign["factorized_envelope"][
                "structural_coupling"
            ],
        },
        "coverage": coverage,
        "checks": checks,
        "schedule": {
            "path": str(schedule_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": _sha256(schedule_path),
            "semantic_sha256": _canonical_hash(rows),
        },
        "scientific_boundary": {
            "optimized_parameters": 0,
            "promoted_parameter_values": 0,
            "selected_candidates": 0,
            "physical_episodes": 0,
            "neural_execution_started": False,
            "stability_evaluated": False,
            "body_motion_used_for_selection": False,
        },
        "open_blocks": [
            "FeCO functional identity remains an overinclusive channel-group ensemble.",
            "FeCO native event-intensity amplitude remains technically bounded rather than biologically identified.",
            "Event comparator constants are source-traceable but not accepted population physiology.",
            "Incoming-L1 count normalization is a technical coordinate system, not synaptic efficacy.",
            "Slow motor assignments remain blocked by the absent slow temporal kernel.",
        ],
        "next_action": completed_next_action,
    }
    result["semantic_result_sha256"] = _canonical_hash(result)
    result_path.write_text(yaml.safe_dump(result, sort_keys=False), encoding="utf-8")

    evaluation = {
        "schema_version": 1,
        "id": "evaluation.neutral_embodied_declared_envelope.v0",
        "title": "Declared local-chain fixture-replacement envelope evaluation",
        "status": "completed_schedule_contract",
        "target_ids": campaign["target_ids"],
        "parameter_set_id": campaign["output_parameter_set_id"],
        "exposure_policy": "diagnostic_only_no_behavior_no_selection",
        "metrics": {
            "feco_bodies_accounted": len(feco),
            "feco_route_groups_accounted": len(feco_groups),
            "unknown_sign_bodies_accounted": len(unknown_bodies),
            "feco_routing_profiles": len(feco_profiles),
            "unknown_sign_profiles": len(sign_profiles),
            "numeric_profiles": len(numeric_profiles),
            "schedule_tuples": len(rows),
            "parameter_values_promoted": 0,
            "candidates_selected": 0,
            "behavior_targets_exposed": 0,
        },
        "acceptance_result": "pass_schedule_contract_execution_not_started",
        "reproducibility": {
            "command": "neutral_embodied_declared_envelope.bat",
            "runner_semantic_sha256": result["semantic_result_sha256"],
            "schedule_sha256": result["schedule"]["sha256"],
        },
        "contamination": {
            "body_motion_inspected": False,
            "used_for_model_selection": False,
            "used_for_manual_tuning": False,
        },
        "conclusion": (
            "Silent local-chain fixtures are replaced at the schedule boundary by "
            "named, reconstructible candidate families. No member is identified, "
            "executed, fitted or promoted by this result."
        ),
        "next_action": completed_next_action,
    }
    evaluation_path.write_text(
        yaml.safe_dump(evaluation, sort_keys=False), encoding="utf-8"
    )

    print("[5/6] Writing compact runner and evaluation records", flush=True)
    print("[6/6] Summary", flush=True)
    print(
        f"[ENVELOPE] {len(feco_profiles)} FeCO routing profiles, "
        f"{len(sign_profiles)} unknown-sign profiles, {len(numeric_profiles)} numeric profiles",
        flush=True,
    )
    print(
        f"[SCHEDULE] {len(rows)} tuples; all {len(base_rows)} previous tuples retained twice",
        flush=True,
    )
    print("[BOUNDARY] 0 fit, 0 selection, 0 physical episode, 0 behavior", flush=True)
    print(f"[HASH] {result['semantic_result_sha256']}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile the factorized declared local-chain parameter envelope"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    compile_declared_envelope(args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

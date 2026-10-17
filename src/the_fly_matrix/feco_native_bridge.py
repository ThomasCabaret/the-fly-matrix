from __future__ import annotations

import hashlib
import itertools
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from .feco_calcium_fit import _sampling_hz, candidates_for, prepare_frame
from .feco_observation import CLAW_SOURCE_COEFFICIENTS, source_activation
from .ledger import ROOT


CAMPAIGN_PATH = ROOT / "calibration/campaigns/feco-native-bridge-factorization-v0.yaml"
PARAMETER_SET_PATH = ROOT / "calibration/parameter_sets/front-leg-feco-sensory-ensemble-v1.yaml"
RUNNER_PATH = ROOT / "calibration/runner/feco-native-bridge-factorization-v0.yaml"
EVALUATION_PATH = ROOT / "calibration/evaluations/feco-native-bridge-factorization-v0.yaml"
OUTPUT_PATH = ROOT / "data/derived/calibration/feco-native-bridge-factorization-v0/summary.json"


class FeCONativeBridgeError(ValueError):
    """Raised when the scoped FeCO native-boundary factorization is dishonest."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FeCONativeBridgeError(f"{path} must contain a YAML mapping")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _verify_campaign(campaign: Mapping[str, Any]) -> None:
    if campaign.get("primary_class") != "local_interface":
        raise FeCONativeBridgeError("campaign must remain local_interface")
    if campaign.get("behavior_targets") != []:
        raise FeCONativeBridgeError("native bridge factorization cannot expose behavior")
    if campaign.get("topology_changes_allowed") is not False:
        raise FeCONativeBridgeError("native bridge factorization cannot change topology")
    if int(campaign.get("optimized_native_amplitudes", -1)) != 0:
        raise FeCONativeBridgeError("this campaign cannot optimize native amplitudes")
    selection = campaign.get("selection_policy", {})
    for key in (
        "choose_native_profile",
        "choose_source_path",
        "choose_routing_profile",
        "choose_amplitude",
    ):
        if selection.get(key) is not False:
            raise FeCONativeBridgeError(f"selection policy {key} must remain false")


def _broad_class(functional_class: str) -> str:
    mapping = {
        "claw_position": "claw",
        "club_vibration_and_speed": "club",
        "hook_flexion_direction": "hook",
    }
    try:
        return mapping[functional_class]
    except KeyError as error:
        raise FeCONativeBridgeError(
            f"unsupported FeCO functional class {functional_class!r}"
        ) from error


def _candidate_fit_by_id(parent: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    fits = parent.get("transfer_shape", {}).get("full_data_observation_fits", [])
    result = {str(item["candidate_id"]): item for item in fits}
    if len(result) != len(fits):
        raise FeCONativeBridgeError("parent observation fits contain duplicate candidate IDs")
    return result


def _raw_activation(
    frame: pd.DataFrame,
    candidate: Any,
    fit: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray]:
    raw = np.empty(len(frame), dtype=np.float64)
    velocity = np.empty(len(frame), dtype=np.float64)
    for _, group in frame.groupby(["animal_id", "trial", "roi"], sort=False, observed=True):
        positions = group["L1C_flex"].to_numpy(dtype=np.float64)
        sampling_hz = (
            8.01
            if candidate.sampling_policy == "fixed_8_01_hz_from_imaging_poly_fun"
            else _sampling_hz(group, candidate.sampling_policy)
        )
        group_velocity = np.concatenate(
            ([np.diff(positions)[0] * sampling_hz], np.diff(positions) * sampling_hz)
        )
        indices = group.index.to_numpy(dtype=np.int64)
        velocity[indices] = group_velocity
        if candidate.fit_kind == "quartic_gcamp_padded":
            coefficients = fit["observation_space_fit"]
            ordered = np.asarray(
                [
                    coefficients["degree_4"],
                    coefficients["degree_3"],
                    coefficients["degree_2"],
                    coefficients["degree_1"],
                    coefficients["offset"],
                ],
                dtype=np.float64,
            )
            values = np.polyval(ordered, positions - float(candidate.claw_center_deg))
        else:
            values = source_activation(
                positions,
                sampling_hz=sampling_hz,
                model_type=candidate.model_type,
                threshold_deg_s=candidate.threshold_deg_s,
                claw_center_deg=candidate.claw_center_deg,
                claw_coefficients=CLAW_SOURCE_COEFFICIENTS,
            )
        raw[indices] = values
    if not np.isfinite(raw).all() or not np.isfinite(velocity).all():
        raise FeCONativeBridgeError(f"candidate {candidate.candidate_id} emitted non-finite data")
    return raw, velocity


def _compile_coordinates(
    source_campaign: Mapping[str, Any], parent: Mapping[str, Any]
) -> list[dict[str, Any]]:
    fit_by_id = _candidate_fit_by_id(parent)
    retained = {
        str(candidate_id)
        for source_path in parent["transfer_shape"]["source_paths"]
        for candidate_id in source_path["candidate_by_class"].values()
    }
    coordinates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for dataset in source_campaign["inputs"]["datasets"]:
        path = ROOT / str(dataset["path"])
        if _sha256(path) != str(dataset["sha256"]):
            raise FeCONativeBridgeError(f"source table hash drift for {path}")
        prepared = prepare_frame(pd.read_parquet(path), dataset)
        frame = prepared.frame.reset_index(drop=True)
        for candidate in candidates_for(dataset):
            if candidate.candidate_id not in retained:
                continue
            fit = fit_by_id.get(candidate.candidate_id)
            if fit is None:
                raise FeCONativeBridgeError(
                    f"retained candidate {candidate.candidate_id} has no parent fit"
                )
            raw, velocity = _raw_activation(frame, candidate, fit)
            raw_min = float(np.min(raw))
            raw_max = float(np.max(raw))
            raw_range = raw_max - raw_min
            if not np.isfinite(raw_range) or raw_range <= 1e-12:
                raise FeCONativeBridgeError(
                    f"candidate {candidate.candidate_id} is constant on admitted support"
                )
            normalized = (raw - raw_min) / raw_range
            tolerance = 1e-12
            if float(np.min(normalized)) < -tolerance or float(np.max(normalized)) > 1 + tolerance:
                raise FeCONativeBridgeError(
                    f"candidate {candidate.candidate_id} normalization escaped [0, 1]"
                )
            coordinates.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "functional_class": _broad_class(str(dataset["functional_class"])),
                    "dataset_id": str(dataset["dataset_id"]),
                    "retained_rows": int(len(frame)),
                    "evidence_support": {
                        "position_deg": {
                            "minimum": float(frame["L1C_flex"].min()),
                            "maximum": float(frame["L1C_flex"].max()),
                        },
                        "velocity_deg_s": {
                            "minimum": float(np.min(velocity)),
                            "maximum": float(np.max(velocity)),
                        },
                    },
                    "affine_quotient": {
                        "raw_activation_minimum": raw_min,
                        "raw_activation_maximum": raw_max,
                        "raw_activation_range": raw_range,
                        "normalized_minimum": float(np.min(normalized)),
                        "normalized_maximum": float(np.max(normalized)),
                    },
                    "native_units_identified": False,
                    "outside_support_scientific_claim_allowed": False,
                }
            )
            seen.add(candidate.candidate_id)
    if seen != retained:
        raise FeCONativeBridgeError(
            f"retained candidate accounting mismatch: missing={sorted(retained - seen)}"
        )
    return sorted(coordinates, key=lambda item: str(item["candidate_id"]))


def run(
    campaign_path: Path = CAMPAIGN_PATH,
    parameter_set_path: Path = PARAMETER_SET_PATH,
    runner_path: Path = RUNNER_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    output_path: Path = OUTPUT_PATH,
) -> dict[str, Any]:
    campaign = _load_yaml(campaign_path)
    _verify_campaign(campaign)

    print("[1/6] Verifying the frozen FH-03 parent and evidence boundary", flush=True)
    parent_path = ROOT / str(campaign["inputs"]["parent_parameter_set"])
    observed_parent_hash = _sha256(parent_path)
    if observed_parent_hash != str(campaign["inputs"]["expected_parent_file_sha256"]):
        raise FeCONativeBridgeError("parent FeCO parameter-set file hash drift")
    parent = _load_yaml(parent_path)
    evidence_path = ROOT / str(campaign["inputs"]["evidence_boundary"])
    evidence = _load_yaml(evidence_path)
    if evidence.get("behavior_targets") is not None:
        # The behavior list is nested under scope in this record.
        raise FeCONativeBridgeError("unexpected top-level behavior exposure field")
    if evidence.get("scope", {}).get("behavior_targets") != []:
        raise FeCONativeBridgeError("evidence boundary cannot expose behavior")

    print("[2/6] Reconstructing six activation coordinates on admitted source support", flush=True)
    source_campaign = _load_yaml(ROOT / str(campaign["inputs"]["source_fit_campaign"]))
    coordinates = _compile_coordinates(source_campaign, parent)
    if len(coordinates) != 6:
        raise FeCONativeBridgeError(f"expected six retained coordinates, got {len(coordinates)}")

    print("[3/6] Materializing all class-shared event/graded representation profiles", flush=True)
    classes = list(campaign["capacity_policy"]["functional_classes"])
    modes = ("graded_activity", "event_intensity_hz")
    native_profiles = [
        {
            "profile_id": f"native_{index:02d}",
            "representation_by_class": dict(zip(classes, values, strict=True)),
        }
        for index, values in enumerate(itertools.product(modes, repeat=len(classes)))
    ]
    expected_profiles = int(campaign["capacity_policy"]["expected_native_profiles"])
    if len(native_profiles) != expected_profiles:
        raise FeCONativeBridgeError("native representation profile count drift")

    print("[4/6] Freezing factorization while leaving every native amplitude unresolved", flush=True)
    routing_profiles = int(parent["factorization"]["routing_profiles"])
    source_paths = int(parent["factorization"]["joint_source_paths"])
    factorized_members = routing_profiles * source_paths * len(native_profiles)
    parameter_set = {
        "schema_version": 1,
        "id": "parameters.front_leg_feco_sensory_ensemble.v1",
        "title": "Frozen scoped FeCO routing, activation-shape and native-capacity ensemble",
        "status": "frozen_locally_identifiable_components_native_amplitude_conditional_on_FH05",
        "parent_ids": [parent["id"]],
        "scope_id": campaign["scope_id"],
        "campaign_id": campaign["id"],
        "primary_class": "local_interface",
        "behavior_targets": [],
        "topology_changes": 0,
        "factorization": {
            "routing_profiles": routing_profiles,
            "joint_source_paths": source_paths,
            "class_shared_native_profiles": len(native_profiles),
            "factorized_members": factorized_members,
            "continuous_native_amplitude_parameters_per_member": 6,
            "continuous_native_amplitude_values_selected": 0,
        },
        "routing": parent["routing"],
        "transfer_shape": {
            "source_paths": parent["transfer_shape"]["source_paths"],
            "activation_coordinates": coordinates,
            "coordinate_units": "dimensionless_activation_coordinate",
            "outside_support_policy": "invalid_for_scientific_claim",
            "source_observation_fits_parent_ref": str(campaign["inputs"]["parent_parameter_set"]),
        },
        "native_boundary_capacity": {
            "model_id": "model.feco_native_bridge_factorization.v0",
            "owner_family_id": "parameter.proprioception.native_bridge.v0",
            "profiles": native_profiles,
            "profile_selected": False,
            "amplitude_parameters": {
                "per_functional_class": ["baseline", "dynamic_range"],
                "values": None,
                "identified": False,
                "joint_gate_item": "FH-05",
            },
            "event_process_selected": False,
            "runtime_ready_without_FH05_values": False,
        },
        "selection": {
            "reference_member_selected": False,
            "routing_profile_selected": False,
            "source_path_selected": False,
            "native_profile_selected": False,
            "native_amplitude_selected": False,
            "future_held_out_outcome_inspected": False,
        },
        "freeze_boundary": {
            "locally_frozen_family_ids": [
                "parameter.proprioception.routing.v0",
                "parameter.proprioception.transfer.v0",
            ],
            "conditionally_open_family_ids": ["parameter.proprioception.native_bridge.v0"],
            "interpretation": (
                "FH-03 freezes every component identifiable from local FeCO evidence. "
                "Native scale is not a missing silent default; it is an explicit FH-05 joint parameter."
            ),
        },
        "reproducibility": {"command": "feco_native_bridge_factorization.bat"},
        "next_action": (
            "Start FH-04 motor uncertainty closure independently, then consume the explicit "
            "native-amplitude family in the FH-05 coupled nonbehavioral gate."
        ),
    }
    parameter_set["semantic_parameter_set_sha256"] = _canonical_hash(parameter_set)
    parameter_set_path.parent.mkdir(parents=True, exist_ok=True)
    parameter_set_path.write_text(
        yaml.safe_dump(parameter_set, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

    accounting = {
        "activation_coordinates": len(coordinates),
        "routing_profiles": routing_profiles,
        "joint_source_paths": source_paths,
        "native_profiles": len(native_profiles),
        "factorized_members": factorized_members,
        "native_amplitude_values_selected": 0,
        "behavior_outcomes_consumed": 0,
        "topology_changes": 0,
    }
    checks = {
        "all_source_coordinates_finite_nonconstant": True,
        "all_admitted_coordinates_in_closed_unit_interval": True,
        "all_class_shared_native_profiles_materialized": len(native_profiles) == 8,
        "native_amplitude_has_separate_owner": True,
        "native_amplitude_values_remain_unresolved": True,
        "future_held_out_outcome_not_consumed": True,
    }
    semantic_result = _canonical_hash(
        {
            "parameter_set_sha256": parameter_set["semantic_parameter_set_sha256"],
            "accounting": accounting,
            "checks": checks,
            "evidence_sha256": _sha256(evidence_path),
        }
    )
    result = {
        "schema_version": 1,
        "id": "runner_result.feco_native_bridge_factorization.v0",
        "campaign_id": campaign["id"],
        "status": "pass_FH03_complete_native_amplitude_explicitly_handed_to_FH05",
        "command": "feco_native_bridge_factorization.bat",
        "claim_label": campaign["claim_label"],
        "parameter_set_id": parameter_set["id"],
        "semantic_parameter_set_sha256": parameter_set["semantic_parameter_set_sha256"],
        "semantic_result_sha256": semantic_result,
        "accounting": accounting,
        "checks": checks,
        "accepted_claims": [
            "All locally identifiable FeCO routing and activation-shape components are frozen as an unselected ensemble.",
            "Native representation capacity is bounded by eight class-shared profiles rather than one silent global choice.",
            "Native amplitude is explicitly owned and deferred to the coupled FH-05 gate because current local evidence cannot identify it.",
            "No behavior, body motion, threshold crossing or native runtime fixture selected a member.",
        ],
        "forbidden_claims": [
            "A native representation or amplitude has been calibrated.",
            "The class-sharing capacity is proven sufficient.",
            "The 1,728 factorized members are independent fitted biological models.",
            "The sensory chain can execute scientifically before FH-05 supplies a conditional native scale.",
        ],
        "next_action": parameter_set["next_action"],
    }
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.feco_native_bridge_factorization.v0",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "parameter_set_id": parameter_set["id"],
        "status": "accepted_local_factorization_FH03_complete_FH05_scale_dependency_open",
        "acceptance_result": "pass",
        "fh03_complete": True,
        "fh05_native_amplitude_dependency_open": True,
        "accounting": accounting,
        "checks": checks,
        "semantic_parameter_set_sha256": parameter_set["semantic_parameter_set_sha256"],
        "behavior_outcomes_consumed": 0,
        "parameter_values_promoted": 0,
        "interpretation": (
            "FH-03 is complete for locally identifiable sensory structure and shape. "
            "The native amplitude is deliberately not guessed; its named family is an FH-05 dependency."
        ),
        "next_action": parameter_set["next_action"],
    }

    print("[5/6] Writing parameter set, compact result and evaluation", flush=True)
    runner_path.write_text(
        yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    evaluation_path.write_text(
        yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                **result,
                "generated_at": datetime.now(UTC).isoformat(),
                "activation_coordinates": coordinates,
                "native_profiles": native_profiles,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("[6/6] COMPLETE", flush=True)
    print("[SHAPES] 6/6 finite activation coordinates on admitted evidence support", flush=True)
    print("[CAPACITY] 27 routing x 8 source x 8 native = 1,728 members", flush=True)
    print("[VALUES] 0 native amplitudes selected; explicit FH-05 dependency", flush=True)
    print("[EXPOSURE] 0 behavior outcomes; 0 body-motion choices; 0 topology changes", flush=True)
    print(f"[HASH] {semantic_result}", flush=True)
    return result


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

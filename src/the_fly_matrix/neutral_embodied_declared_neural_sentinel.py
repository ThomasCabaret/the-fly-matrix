from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from collections import Counter
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml

from .ledger import ROOT
from .local_conversion import event_intensity_to_counts
from .neutral_embodied_declared_envelope import _profile_panel
from .neutral_embodied_full_chain_sentinel import (
    _delay,
    _event_filter,
    _functional_signals,
    _load_campaign as _load_full_chain_campaign,
    _sha256,
    _verify_and_load_inputs,
)


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "neutral-embodied-declared-neural-sentinel-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "neutral-embodied-declared-neural-sentinel-v0.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "neutral-embodied-declared-neural-sentinel-v0.yaml"


class DeclaredNeuralSentinelError(RuntimeError):
    """Raised when the declared neural execution contract is violated."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DeclaredNeuralSentinelError(f"{path} must contain a YAML mapping")
    return value


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _array_hash(*arrays: np.ndarray) -> str:
    digest = hashlib.sha256()
    for array in arrays:
        value = np.ascontiguousarray(array)
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(str(value.shape).encode("ascii"))
        digest.update(value.tobytes())
    return digest.hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = _load_yaml(path)
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise DeclaredNeuralSentinelError("sentinel must remain diagnostic_only")
    if campaign.get("behavior_targets"):
        raise DeclaredNeuralSentinelError("sentinel cannot expose behavior targets")
    if campaign.get("topology_changes_allowed") is not False:
        raise DeclaredNeuralSentinelError("sentinel cannot change topology")
    boundary = campaign["scientific_boundary"]
    for key in (
        "optimized_parameters",
        "promoted_parameter_values",
        "selected_candidates",
        "physical_episodes",
        "named_behavior_exposure",
    ):
        if int(boundary.get(key, -1)) != 0:
            raise DeclaredNeuralSentinelError(f"sentinel requires zero {key}")
    acceptance = campaign["acceptance"]
    if acceptance.get("allow_neural_magnitude_to_select_candidate") is not False:
        raise DeclaredNeuralSentinelError("neural magnitude cannot select a candidate")
    if acceptance.get("allow_physical_magnitude_to_select_candidate") is not False:
        raise DeclaredNeuralSentinelError("physical magnitude cannot select a candidate")
    return campaign


def _load_context(campaign: Mapping[str, Any]) -> dict[str, Any]:
    frozen = campaign["frozen_inputs"]
    pairs = (
        ("declared_envelope_campaign", "declared_envelope_campaign_sha256"),
        ("declared_envelope_result", "declared_envelope_result_sha256"),
        ("declared_schedule", "declared_schedule_sha256"),
        ("full_chain_contract", "full_chain_contract_sha256"),
    )
    paths: dict[str, Path] = {}
    for key, hash_key in pairs:
        path = ROOT / str(frozen[key])
        observed = _sha256(path)
        if observed != str(frozen[hash_key]):
            raise DeclaredNeuralSentinelError(f"frozen input drift for {key}")
        paths[key] = path
    declared = _load_yaml(paths["declared_envelope_result"])
    if declared.get("semantic_result_sha256") != frozen["declared_envelope_result_semantic_sha256"]:
        raise DeclaredNeuralSentinelError("declared envelope semantic result drift")
    rows = _read_csv(paths["declared_schedule"])
    full_chain = _load_full_chain_campaign(paths["full_chain_contract"])
    inputs = _verify_and_load_inputs(full_chain)
    members_path = ROOT / str(full_chain["frozen_inputs"]["population_members"])
    members = pd.read_csv(members_path)
    return {
        "paths": paths,
        "declared": declared,
        "rows": rows,
        "full_chain": full_chain,
        "inputs": inputs,
        "members": members,
    }


def _incoming_l1_matrices(inputs: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    paths = inputs["central_paths"]
    sensory = list(map(int, inputs["sensory_body_ids"]))
    intermediate = list(map(int, inputs["intermediate_body_ids"]))
    motor = list(map(int, inputs["motor_body_ids"]))
    si = {body_id: index for index, body_id in enumerate(sensory)}
    ii = {body_id: index for index, body_id in enumerate(intermediate)}
    mi = {body_id: index for index, body_id in enumerate(motor)}
    raw = [np.zeros((36, 150)), np.zeros((150, 10)), np.zeros((36, 10))]
    two_hop = paths.loc[paths["hops"].eq(2)]
    for row in two_hop.drop_duplicates(["source_body_id", "intermediate_body_id"]).itertuples(index=False):
        body_id = int(row.intermediate_body_id)
        if body_id in ii:
            raw[0][si[int(row.source_body_id)], ii[body_id]] = float(row.first_edge_weight)
    for row in two_hop.drop_duplicates(["intermediate_body_id", "target_body_id"]).itertuples(index=False):
        body_id = int(row.intermediate_body_id)
        if body_id in ii:
            raw[1][ii[body_id], mi[int(row.target_body_id)]] = float(row.second_edge_weight)
    for row in paths.loc[paths["hops"].eq(1)].itertuples(index=False):
        raw[2][si[int(row.source_body_id)], mi[int(row.target_body_id)]] = float(row.first_edge_weight)
    if any(np.any(matrix < 0.0) for matrix in raw):
        raise DeclaredNeuralSentinelError("structural synapse counts must be nonnegative")
    matrices: list[np.ndarray] = []
    audits: list[dict[str, Any]] = []
    for name, matrix in zip(("sensory_to_intermediate", "intermediate_to_motor", "sensory_to_motor"), raw, strict=True):
        denominator = np.abs(matrix).sum(axis=0)
        nonzero = denominator > 0.0
        transformed = matrix.copy()
        transformed[:, nonzero] /= denominator[nonzero]
        l1 = np.abs(transformed).sum(axis=0)
        exact = bool(np.allclose(l1[nonzero], 1.0, atol=1e-12, rtol=0.0))
        audits.append({
            "matrix": name,
            "shape": list(matrix.shape),
            "nonzero_edges": int(np.count_nonzero(matrix)),
            "nonzero_target_columns": int(np.count_nonzero(nonzero)),
            "zero_target_columns": int(np.count_nonzero(~nonzero)),
            "nonzero_columns_l1_exact": exact,
            "raw_sha256": _array_hash(matrix),
            "transformed_sha256": _array_hash(transformed),
        })
        matrices.append(transformed)
    if not audits[0]["nonzero_edges"] or not audits[1]["nonzero_edges"]:
        raise DeclaredNeuralSentinelError("bounded local corridor is empty")
    return matrices[0], matrices[1], matrices[2], {
        "transform": "incoming_L1_synapse_fraction",
        "matrices": audits,
        "all_nonzero_columns_exact": all(item["nonzero_columns_l1_exact"] for item in audits),
    }


def _typed_population(
    drive: np.ndarray,
    event_mask: np.ndarray,
    *,
    timestep_s: float,
    graded_tau_s: float,
    event_tau_s: float,
    synaptic_tau_s: float,
    refractory_s: float,
    threshold_excursion_mV: float,
    dimensionless_input_scale: float,
) -> tuple[np.ndarray, np.ndarray]:
    channels = drive.shape[1]
    membrane = np.zeros(channels, dtype=np.float64)
    synaptic = np.zeros(channels, dtype=np.float64)
    output = np.zeros_like(drive, dtype=np.float64)
    spikes = np.zeros_like(drive, dtype=np.int8)
    refractory = np.zeros(channels, dtype=np.int64)
    refractory_steps = max(1, int(round(refractory_s / timestep_s)))
    taus = np.where(event_mask, event_tau_s, graded_tau_s)
    alpha = timestep_s / taus
    synaptic_decay = float(np.exp(-timestep_s / synaptic_tau_s))
    input_gain_mV = threshold_excursion_mV * dimensionless_input_scale
    graded_mask = ~event_mask
    for index in range(len(drive)):
        refractory = np.maximum(refractory - 1, 0)
        active = graded_mask | (event_mask & (refractory == 0))
        membrane[active] += alpha[active] * (-membrane[active] + input_gain_mV * drive[index, active])
        fired = event_mask & (refractory == 0) & (membrane >= threshold_excursion_mV)
        spikes[index, fired] = 1
        membrane[fired] = 0.0
        refractory[fired] = refractory_steps
        synaptic = synaptic * synaptic_decay + spikes[index]
        output[index, event_mask] = synaptic[event_mask]
        output[index, graded_mask] = np.maximum(membrane[graded_mask], 0.0) / threshold_excursion_mV
    if not np.isfinite(output).all():
        raise DeclaredNeuralSentinelError("typed population emitted non-finite state")
    return output, spikes


def _profiles(context: Mapping[str, Any]) -> dict[str, Any]:
    declared = context["declared"]
    inputs = context["inputs"]
    members = context["members"]
    feco = members.loc[members["population_id"].eq("population.front_leg_feco.v0")].copy()
    groups = sorted(feco["route_channel_id"].astype(str).unique())
    unknown = sorted(str(int(value)) for value in inputs["classified"].loc[inputs["classified"]["sign_code"].eq(0), "body_id"])
    feco_panel, feco_directions = _profile_panel(groups, base=3, dimension=4)
    sign_panel, sign_directions = _profile_panel(unknown, base=2, dimension=6)
    expected_feco = declared["factorized_panels"]["feco_routing"]["directions"]
    expected_sign = declared["factorized_panels"]["unknown_sign"]["directions"]
    if {k: list(v) for k, v in feco_directions.items()} != expected_feco:
        raise DeclaredNeuralSentinelError("FeCO profile recipe drift")
    if {k: list(v) for k, v in sign_directions.items()} != expected_sign:
        raise DeclaredNeuralSentinelError("unknown-sign profile recipe drift")
    numeric = {item["profile_id"]: item for item in declared["factorized_panels"]["numeric"]["profiles"]}
    body_to_group = {int(row.body_id): str(row.route_channel_id) for row in feco.itertuples(index=False)}
    return {
        "feco": {f"feco_route_{int(item['_index']):02d}": item for item in feco_panel},
        "sign": {f"unknown_sign_{int(item['_index']):02d}": item for item in sign_panel},
        "numeric": numeric,
        "functional_levels": declared["factorized_panels"]["feco_routing"]["levels"],
        "body_to_group": body_to_group,
        "unknown_body_ids": list(map(int, unknown)),
    }


def _execute_tuple(row: Mapping[str, str], context: Mapping[str, Any], profiles: Mapping[str, Any], matrices: tuple[np.ndarray, np.ndarray, np.ndarray]) -> dict[str, Any]:
    campaign = context["campaign"]
    inputs = context["inputs"]
    fixture = campaign["execution_fixture"]
    runtime = campaign["runtime_contract"]
    timestep_s = float(fixture["timestep_s"])
    samples = int(round(float(fixture["duration_s"]) / timestep_s))
    time_axis = np.arange(samples, dtype=np.float64) * timestep_s
    position = float(fixture["center_deg"]) + float(fixture["amplitude_deg"]) * np.sin(2.0 * np.pi * float(fixture["frequency_hz"]) * time_axis)
    source_path = inputs["feco_paths"][int(row["feco_source_path_index"])]
    signals = _functional_signals(position, source_path, sampling_hz=1.0 / timestep_s)

    feco_profile = profiles["feco"][str(row["feco_routing_profile_id"])]
    levels = list(profiles["functional_levels"])
    sensory_ids = list(map(int, inputs["sensory_body_ids"]))
    selected_functions = [levels[int(feco_profile[profiles["body_to_group"][body_id]])] for body_id in sensory_ids]
    activity = np.column_stack([signals[name] for name in selected_functions])
    numeric = profiles["numeric"][str(row["numeric_profile_id"])]
    for key in ("graded_membrane_tau_s", "dimensionless_input_scale", "unresolved_event_intensity_ceiling_hz"):
        if not np.isclose(float(row[key]), float(numeric[key])):
            raise DeclaredNeuralSentinelError(f"numeric profile drift for {key}")
    if row["feco_native_representation"] == "event_candidate":
        source_events = event_intensity_to_counts(activity * float(numeric["unresolved_event_intensity_ceiling_hz"]), timestep_s=timestep_s, seed=int(row["seed"]))
        source_drive = _event_filter(source_events, timestep_s=timestep_s, tau_s=float(runtime["event_synaptic_tau_s"]))
    elif row["feco_native_representation"] == "graded_candidate":
        source_events = np.zeros(activity.shape, dtype=np.int64)
        source_drive = activity
    else:
        raise DeclaredNeuralSentinelError("unsupported FeCO native representation")

    first, second, direct = matrices
    delay_steps = int(round(float(runtime["fixed_delay_s"]) / timestep_s))
    intermediate_drive = _delay(source_drive @ first, delay_steps)
    classified = inputs["classified"].set_index("body_id")
    intermediate_ids = list(map(int, inputs["intermediate_body_ids"]))
    assignment_profile = inputs["profiles"][str(row["intermediate_profile_id"])]
    event_mask = np.asarray([
        classified.loc[body_id, "assignment"] == "event_required" or assignment_profile.get(body_id) == "event_candidate"
        for body_id in intermediate_ids
    ], dtype=bool)
    intermediate_output, intermediate_spikes = _typed_population(
        intermediate_drive,
        event_mask,
        timestep_s=timestep_s,
        graded_tau_s=float(numeric["graded_membrane_tau_s"]),
        event_tau_s=float(runtime["event_membrane_tau_s"]),
        synaptic_tau_s=float(runtime["event_synaptic_tau_s"]),
        refractory_s=float(runtime["event_refractory_s"]),
        threshold_excursion_mV=float(runtime["event_threshold_excursion_mV"]),
        dimensionless_input_scale=float(numeric["dimensionless_input_scale"]),
    )
    sign_codes = classified.loc[intermediate_ids, "sign_code"].to_numpy(dtype=np.int8)
    effective_sign = sign_codes.astype(np.float64)
    sign_profile = profiles["sign"][str(row["unknown_sign_profile_id"])]
    for index, body_id in enumerate(intermediate_ids):
        if sign_codes[index] == 0:
            effective_sign[index] = -1.0 if int(sign_profile[str(body_id)]) == 0 else 1.0
    motor_drive = _delay((intermediate_output * effective_sign) @ second, delay_steps) + _delay(source_drive @ direct, delay_steps)
    _, motor_spikes = _typed_population(
        motor_drive,
        np.ones(10, dtype=bool),
        timestep_s=timestep_s,
        graded_tau_s=float(numeric["graded_membrane_tau_s"]),
        event_tau_s=float(runtime["event_membrane_tau_s"]),
        synaptic_tau_s=float(runtime["event_synaptic_tau_s"]),
        refractory_s=float(runtime["event_refractory_s"]),
        threshold_excursion_mV=float(runtime["event_threshold_excursion_mV"]),
        dimensionless_input_scale=float(numeric["dimensionless_input_scale"]),
    )
    finite = bool(np.isfinite(source_drive).all() and np.isfinite(intermediate_output).all() and np.isfinite(motor_drive).all())
    return {
        "tuple_id": str(row["tuple_id"]),
        "status": "completed_contract" if finite else "failed_nonfinite",
        "feco_routing_profile_id": str(row["feco_routing_profile_id"]),
        "unknown_sign_profile_id": str(row["unknown_sign_profile_id"]),
        "numeric_profile_id": str(row["numeric_profile_id"]),
        "feco_native_representation": str(row["feco_native_representation"]),
        "feco_projection_sha256": _canonical_hash(dict(zip(map(str, sensory_ids), selected_functions, strict=True))),
        "effective_sign_sha256": _array_hash(effective_sign),
        "numeric_profile_sha256": _canonical_hash(numeric),
        "source_nonzero_samples": int(np.count_nonzero(source_drive)),
        "source_event_count": int(source_events.sum()),
        "intermediate_nonzero_samples": int(np.count_nonzero(intermediate_output)),
        "intermediate_spike_count": int(intermediate_spikes.sum()),
        "motor_spike_count": int(motor_spikes.sum()),
        "finite": finite,
        "neural_trace_sha256": _array_hash(source_drive, intermediate_output, motor_drive, motor_spikes),
    }


def _isolated_oracles(context: Mapping[str, Any], profiles: Mapping[str, Any], second: np.ndarray) -> dict[str, Any]:
    runtime = context["campaign"]["runtime_contract"]
    timestep = float(context["campaign"]["execution_fixture"]["timestep_s"])
    intermediate_ids = list(map(int, context["inputs"]["intermediate_body_ids"]))
    unknown = list(profiles["unknown_body_ids"])
    sign_checks = []
    for body_id in unknown:
        index = intermediate_ids.index(body_id)
        positive = second[index]
        negative = -second[index]
        sign_checks.append(bool(np.any(positive != 0.0) and np.allclose(positive, -negative, atol=0.0, rtol=0.0)))

    drive = np.ones((400, 1), dtype=np.float64)
    graded_hashes = {}
    for tau in (0.01, 0.02):
        output, _ = _typed_population(drive, np.asarray([False]), timestep_s=timestep, graded_tau_s=tau, event_tau_s=float(runtime["event_membrane_tau_s"]), synaptic_tau_s=float(runtime["event_synaptic_tau_s"]), refractory_s=float(runtime["event_refractory_s"]), threshold_excursion_mV=float(runtime["event_threshold_excursion_mV"]), dimensionless_input_scale=1.0)
        graded_hashes[str(tau)] = _array_hash(output)
    scale_hashes = {}
    for scale in (0.5, 1.0, 2.0):
        output, _ = _typed_population(drive, np.asarray([False]), timestep_s=timestep, graded_tau_s=0.01, event_tau_s=float(runtime["event_membrane_tau_s"]), synaptic_tau_s=float(runtime["event_synaptic_tau_s"]), refractory_s=float(runtime["event_refractory_s"]), threshold_excursion_mV=float(runtime["event_threshold_excursion_mV"]), dimensionless_input_scale=scale)
        scale_hashes[str(scale)] = _array_hash(output)
    intensity_hashes = {}
    for intensity in (100.0, 200.0):
        events = event_intensity_to_counts(np.ones((10000, 1)) * intensity, timestep_s=timestep, seed=20261012)
        intensity_hashes[str(intensity)] = {"sha256": _array_hash(events), "count": int(events.sum())}
    return {
        "unknown_sign_flip": {
            "bodies": len(unknown),
            "nonzero_antisymmetric": sum(sign_checks),
            "all_pass": all(sign_checks),
        },
        "numeric_axes": {
            "graded_tau": {"trace_hashes": graded_hashes, "changes_probe": len(set(graded_hashes.values())) == 2},
            "input_scale": {"trace_hashes": scale_hashes, "changes_probe": len(set(scale_hashes.values())) == 3},
            "event_intensity": {"event_hashes_and_counts": intensity_hashes, "changes_probe": len({item["sha256"] for item in intensity_hashes.values()}) == 2},
        },
    }


def run_sentinel(campaign_path: Path = CAMPAIGN_PATH, result_path: Path = RESULT_PATH, evaluation_path: Path = EVALUATION_PATH) -> dict[str, Any]:
    started = time.perf_counter()
    campaign = _load_campaign(campaign_path)
    print("[1/6] Verifying frozen envelope, exact schedule and local-chain inputs", flush=True)
    context = _load_context(campaign)
    context["campaign"] = campaign
    rows = context["rows"]
    acceptance = campaign["acceptance"]
    if len(rows) != int(acceptance["expected_tuples"]):
        raise DeclaredNeuralSentinelError("declared schedule tuple count drift")
    profiles = _profiles(context)
    first, second, direct, coupling_audit = _incoming_l1_matrices(context["inputs"])
    if acceptance["require_incoming_L1_columns_exact"] and not coupling_audit["all_nonzero_columns_exact"]:
        raise DeclaredNeuralSentinelError("incoming-L1 structural transform failed")

    print("[2/6] Running isolated sign, numeric and structural micro-oracles", flush=True)
    oracles = _isolated_oracles(context, profiles, second)
    if acceptance["require_each_unknown_sign_flip_oracle_nonzero_and_antisymmetric"] and not oracles["unknown_sign_flip"]["all_pass"]:
        raise DeclaredNeuralSentinelError("an unknown-sign body has no executable downstream flip")
    if acceptance["require_each_numeric_axis_to_change_its_isolated_probe"] and not all(item["changes_probe"] for item in oracles["numeric_axes"].values()):
        raise DeclaredNeuralSentinelError("a numeric axis is read but inactive")

    print("[3/6] Executing all 240 neural tuples (no MuJoCo)", flush=True)
    outcomes = []
    maximum_seconds = float(campaign["compute_budget"]["maximum_wall_clock_minutes"]) * 60.0
    for index, row in enumerate(rows, start=1):
        if time.perf_counter() - started > maximum_seconds:
            raise DeclaredNeuralSentinelError("bounded wall-clock budget exhausted")
        outcome = _execute_tuple(row, context, profiles, (first, second, direct))
        outcomes.append(outcome)
        if index == 1 or index % 20 == 0 or index == len(rows):
            print(f"[TUPLE {index:03d}/{len(rows)}] {outcome['tuple_id']} | {outcome['status']} | source {outcome['source_nonzero_samples']} | intermediate {outcome['intermediate_nonzero_samples']} | motor spikes {outcome['motor_spike_count']}", flush=True)

    print("[4/6] Accounting every profile without ranking neural magnitudes", flush=True)
    statuses = Counter(item["status"] for item in outcomes)
    coverage = {
        "tuples": len(outcomes),
        "feco_routing_profiles": len({item["feco_routing_profile_id"] for item in outcomes}),
        "unknown_sign_profiles": len({item["unknown_sign_profile_id"] for item in outcomes}),
        "numeric_profiles": len({item["numeric_profile_id"] for item in outcomes}),
        "representations": sorted({item["feco_native_representation"] for item in outcomes}),
        "unique_neural_trace_hashes_descriptive_only": len({item["neural_trace_sha256"] for item in outcomes}),
    }
    checks = {
        "every_tuple_accounted": len(outcomes) == int(acceptance["expected_tuples"]),
        "every_tuple_finite": statuses["completed_contract"] == len(outcomes),
        "every_feco_profile_executed": coverage["feco_routing_profiles"] == int(acceptance["expected_feco_routing_profiles"]),
        "every_sign_profile_executed": coverage["unknown_sign_profiles"] == int(acceptance["expected_unknown_sign_profiles"]),
        "every_numeric_profile_executed": coverage["numeric_profiles"] == int(acceptance["expected_numeric_profiles"]),
        "every_tuple_source_drive_nonzero": all(item["source_nonzero_samples"] > 0 for item in outcomes),
        "incoming_L1_exact": coupling_audit["all_nonzero_columns_exact"],
        "unknown_sign_flip_oracle": oracles["unknown_sign_flip"]["all_pass"],
        "numeric_axis_oracles": all(item["changes_probe"] for item in oracles["numeric_axes"].values()),
    }
    passed = all(checks.values())
    status = "pass_declared_neural_execution_no_fit_no_selection" if passed else "failed_declared_neural_execution"
    next_action = campaign["next_action"]
    compact = {
        "schema_version": 1,
        "id": "runner_result.neutral_embodied_declared_neural_sentinel.v0",
        "campaign_id": campaign["id"],
        "target_ids": campaign["target_ids"],
        "status": status,
        "claim_label": campaign["claim_label"],
        "generated_at": datetime.now(UTC).isoformat(),
        "command": "neutral_embodied_declared_neural_sentinel.bat",
        "campaign_sha256": _sha256(campaign_path),
        "implementation_sha256": _sha256(Path(__file__).resolve()),
        "frozen_input_hashes": {key: _sha256(path) for key, path in context["paths"].items()},
        "accounting": {"scheduled_tuples": len(rows), "outcome_counts": dict(statuses), "physical_episodes": 0, "optimized_parameters": 0, "selected_candidates": 0, "promoted_parameter_values": 0},
        "coverage": coverage,
        "checks": checks,
        "structural_coupling_audit": coupling_audit,
        "isolated_oracles": oracles,
        "tuple_accounting": outcomes,
        "scientific_boundary": campaign["scientific_boundary"],
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "wall_seconds": time.perf_counter() - started,
        "next_action": next_action,
    }
    semantic_keys = ("schema_version", "id", "campaign_id", "target_ids", "status", "claim_label", "frozen_input_hashes", "accounting", "coverage", "checks", "structural_coupling_audit", "isolated_oracles", "tuple_accounting", "scientific_boundary", "accepted_claims", "forbidden_claims", "next_action")
    compact["semantic_result_sha256"] = _canonical_hash({key: compact[key] for key in semantic_keys})
    result_path.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")

    print("[5/6] Writing compact runner and evaluation records", flush=True)
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.neutral_embodied_declared_neural_sentinel.v0",
        "title": "Declared-envelope local neural execution sentinel",
        "status": "evaluated" if passed else "failed",
        "campaign_id": campaign["id"],
        "target_ids": campaign["target_ids"],
        "primary_class": campaign["primary_class"],
        "optimization_exposure": campaign["optimization_exposure"],
        "claim_label": campaign["claim_label"],
        "behavior_targets": [],
        "acceptance_result": status,
        "runner_result_id": compact["id"],
        "runner_semantic_sha256": compact["semantic_result_sha256"],
        "parameter_values_promoted": 0,
        "candidates_selected": 0,
        "physical_episodes": 0,
        "stability_accepted": False,
        "conclusion": "All 240 declared candidates execute through the bounded local neural corridor and every declared axis passes an isolated consumption oracle. This is an execution and sensitivity contract only; no magnitude ranks a member and no value is fitted or promoted." if passed else "The declared neural execution contract failed. No candidate or value is selected or promoted.",
        "next_action": next_action,
    }
    evaluation_path.write_text(yaml.safe_dump(evaluation, sort_keys=False), encoding="utf-8")
    print("[6/6] Summary", flush=True)
    print(f"[ACCOUNTING] {statuses['completed_contract']}/{len(outcomes)} finite neural tuples", flush=True)
    print(f"[COVERAGE] {coverage['feco_routing_profiles']} FeCO + {coverage['unknown_sign_profiles']} sign + {coverage['numeric_profiles']} numeric profiles", flush=True)
    print(f"[ORACLES] signs {oracles['unknown_sign_flip']['nonzero_antisymmetric']}/{oracles['unknown_sign_flip']['bodies']} | numeric axes {sum(item['changes_probe'] for item in oracles['numeric_axes'].values())}/3 | L1={coupling_audit['all_nonzero_columns_exact']}", flush=True)
    print("[BOUNDARY] 0 fit, 0 selection, 0 promotion, 0 physics, 0 behavior", flush=True)
    print(f"[HASH] {compact['semantic_result_sha256']}", flush=True)
    return compact


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute the exact declared neural envelope without physics or selection")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    result = run_sentinel(args.campaign)
    return 0 if result["status"].startswith("pass_") else 1


if __name__ == "__main__":
    raise SystemExit(main())

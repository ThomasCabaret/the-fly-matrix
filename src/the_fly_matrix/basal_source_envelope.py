from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml
from scipy import sparse

from .basal_source_bridges import (
    BasalSourceBridgeError,
    build_arm_rates,
    event_probability,
    hz_to_graded,
    sample_event_presence,
)
from .ledger import ROOT
from .typed_hybrid_runtime import (
    EVENT,
    GRADED,
    INACTIVE,
    DiagnosticConstants,
    TorchTypedHybridRuntime,
    _load_assignments,
)


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "basal-source-envelope-propagation-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "basal-source-envelope-propagation-v0.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "basal-source-envelope-propagation-v0.yaml"
PARAMETER_SET_PATH = ROOT / "calibration" / "parameter_sets" / "basal-source-technical-envelope-v0.yaml"
OUTPUT_ROOT = ROOT / "data" / "derived" / "calibration" / "basal-source-envelope-propagation-v0"


class BasalSourceEnvelopeError(RuntimeError):
    """Raised when the finite diagnostic envelope or its probe accounting drifts."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BasalSourceEnvelopeError(f"{path} must contain a YAML mapping")
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


def _semantic_float_quantization(value: Any, significant_digits: int) -> Any:
    """Remove backend reduction noise from hashes while retaining raw diagnostics."""

    if isinstance(value, dict):
        return {
            key: _semantic_float_quantization(item, significant_digits)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_semantic_float_quantization(item, significant_digits) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BasalSourceEnvelopeError("semantic metrics must be finite")
        return float(f"{value:.{significant_digits}g}")
    return value


def _verify_frozen_inputs(campaign: Mapping[str, Any]) -> dict[str, Path]:
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise BasalSourceEnvelopeError("the envelope cannot optimize parameters")
    if campaign.get("behavior_targets"):
        raise BasalSourceEnvelopeError("the envelope cannot expose named behavior")
    if campaign.get("topology_changes_allowed") is not False:
        raise BasalSourceEnvelopeError("the envelope cannot change topology")
    if int(campaign.get("parameter_values_promoted", -1)) != 0:
        raise BasalSourceEnvelopeError("technical envelope values cannot be promoted")
    paths: dict[str, Path] = {}
    for key, record in campaign["frozen_inputs"].items():
        path = ROOT / str(record["path"])
        if not path.is_file():
            raise BasalSourceEnvelopeError(f"missing frozen input {key}: {path}")
        observed = _sha256(path)
        if observed != str(record["sha256"]):
            raise BasalSourceEnvelopeError(
                f"frozen input drift for {key}: {observed} != {record['sha256']}"
            )
        paths[key] = path
    return paths


def _locate(body_ids: np.ndarray, selected: np.ndarray, label: str) -> np.ndarray:
    positions = np.searchsorted(body_ids, selected)
    clipped = np.minimum(positions, len(body_ids) - 1)
    if np.any(positions >= len(body_ids)) or not np.array_equal(body_ids[clipped], selected):
        raise BasalSourceEnvelopeError(f"{label} contains bodies outside the canonical graph")
    return positions.astype(np.int64)


def _probe_ids(paths: Mapping[str, Path]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    members = pd.read_csv(paths["local_members"])
    intermediates = pd.read_csv(paths["local_intermediates"])
    sensory = np.sort(
        members.loc[
            members["population_id"].eq("population.front_leg_feco.v0"), "body_id"
        ].to_numpy(np.int64)
    )
    intermediate = np.sort(intermediates["body_id"].astype(np.int64).unique())
    motor = np.sort(
        members.loc[
            members["population_id"].eq("population.front_leg_tibia_flexor_motor.v0"),
            "body_id",
        ].to_numpy(np.int64)
    )
    if (len(sensory), len(intermediate), len(motor)) != (36, 150, 10):
        raise BasalSourceEnvelopeError(
            f"local chain accounting drift: {(len(sensory), len(intermediate), len(motor))}"
        )
    if len(np.unique(np.concatenate((sensory, intermediate, motor)))) != 196:
        raise BasalSourceEnvelopeError("local chain populations overlap unexpectedly")
    return sensory, intermediate, motor


def compile_envelope_members(campaign: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Compile the complete preregistered technical grid without ranking members."""

    design = campaign["technical_envelope"]
    members: list[dict[str, Any]] = []
    for profile_id in design["assignment_profiles"]:
        members.append(
            {
                "member_id": f"{profile_id}__silence",
                "assignment_profile_id": profile_id,
                "shape_id": "explicit_silence_control",
                "scale_id": "zero",
                "uniform_rate_hz": 0.0,
                "equal_family_total_rate_hz": 0.0,
                "graded_half_saturation_hz": float(design["graded_half_saturation_hz"][0]),
                "ablated_family_id": None,
            }
        )
        for shape_id in ("uniform_per_terminal", "equal_family_mass"):
            scales = design[f"{shape_id}_scales"]
            half_saturations = (
                design["graded_half_saturation_hz"]
                if profile_id == "exact_event_plus_all_dual_as_graded"
                else [design["graded_half_saturation_hz"][1]]
            )
            for scale in scales:
                for half_saturation in half_saturations:
                    scale_id = str(scale["id"])
                    members.append(
                        {
                            "member_id": (
                                f"{profile_id}__{shape_id}__{scale_id}"
                                f"__half_sat_{float(half_saturation):g}hz"
                            ),
                            "assignment_profile_id": profile_id,
                            "shape_id": shape_id,
                            "scale_id": scale_id,
                            "uniform_rate_hz": float(scale.get("rate_hz", 0.0)),
                            "equal_family_total_rate_hz": float(scale.get("family_total_rate_hz", 0.0)),
                            "graded_half_saturation_hz": float(half_saturation),
                            "ablated_family_id": None,
                        }
                    )
        for family_id in design["ablation_family_ids"]:
            members.append(
                {
                    "member_id": f"{profile_id}__uniform_reference__without__{family_id}",
                    "assignment_profile_id": profile_id,
                    "shape_id": "uniform_per_terminal",
                    "scale_id": "reference",
                    "uniform_rate_hz": float(design["ablation_reference_uniform_rate_hz"]),
                    "equal_family_total_rate_hz": 0.0,
                    "graded_half_saturation_hz": float(
                        design["ablation_reference_graded_half_saturation_hz"]
                    ),
                    "ablated_family_id": family_id,
                }
            )
    long_horizon = design.get("long_horizon_event_reference")
    if long_horizon:
        members.append(
            {
                "member_id": "all_reached_as_event_candidate__uniform_high__long_horizon",
                "assignment_profile_id": "all_reached_as_event_candidate",
                "shape_id": "uniform_per_terminal",
                "scale_id": "high_long_horizon",
                "uniform_rate_hz": float(long_horizon["uniform_rate_hz"]),
                "equal_family_total_rate_hz": 0.0,
                "graded_half_saturation_hz": float(design["graded_half_saturation_hz"][1]),
                "ablated_family_id": None,
                "steps_override": int(long_horizon["steps"]),
            }
        )
    ids = [row["member_id"] for row in members]
    if len(ids) != len(set(ids)):
        raise BasalSourceEnvelopeError("technical envelope member ids are not unique")
    return members


def _execute_member(
    incoming: sparse.csr_matrix,
    assignment: np.ndarray,
    constants: DiagnosticConstants,
    source_positions: np.ndarray,
    rates_hz: np.ndarray,
    probe_groups: Mapping[str, np.ndarray],
    *,
    device: str,
    steps: int,
    seed: int,
    half_saturation_hz: float,
) -> dict[str, Any]:
    import torch

    source_types = assignment[source_positions]
    if np.any((source_types != EVENT) & (source_types != GRADED)):
        raise BasalSourceEnvelopeError("a basal source has no executable candidate port")
    event_mask = source_types == EVENT
    graded_mask = source_types == GRADED
    probabilities = event_probability(rates_hz, constants.dt_ms)
    graded_drive = hz_to_graded(rates_hz, half_saturation_hz)
    rng = np.random.default_rng(seed)
    runtime = TorchTypedHybridRuntime(incoming, assignment, constants, device)
    external = np.zeros(len(assignment), dtype=np.float32)
    external[source_positions[graded_mask]] = graded_drive[graded_mask]
    torch_probes = {
        key: torch.as_tensor(value, dtype=torch.int64, device=device)
        for key, value in probe_groups.items()
    }
    maxima = {
        key: {"event_g_l1": 0.0, "graded_l1": 0.0, "state_max_abs": 0.0}
        for key in probe_groups
    }
    generated_events = 0
    forced_events = 0
    for _ in range(steps):
        candidate_presence = sample_event_presence(rates_hz, constants.dt_ms, rng)
        selected = np.flatnonzero(candidate_presence & event_mask)
        forced = source_positions[selected]
        row = runtime.step(forced_event_indices=forced, external_graded=external)
        forced_events += int(len(forced))
        generated_events += int(row["generated_events"])
        for key, indices in torch_probes.items():
            event_l1 = float(torch.sum(torch.abs(runtime.g[indices])).item())
            graded_l1 = float(torch.sum(torch.abs(runtime.graded[indices])).item())
            state_max = float(
                torch.max(torch.maximum(torch.abs(runtime.g[indices]), torch.abs(runtime.graded[indices]))).item()
            )
            maxima[key]["event_g_l1"] = max(maxima[key]["event_g_l1"], event_l1)
            maxima[key]["graded_l1"] = max(maxima[key]["graded_l1"], graded_l1)
            maxima[key]["state_max_abs"] = max(maxima[key]["state_max_abs"], state_max)
    states = runtime.state_arrays()
    result = {
        "max_event_presence_probability_per_step": float(probabilities.max(initial=0.0)),
        "rate_hz": {
            "minimum": float(rates_hz.min()),
            "maximum": float(rates_hz.max(initial=0.0)),
            "sum": float(rates_hz.sum()),
            "nonzero_sources": int(np.count_nonzero(rates_hz)),
        },
        "graded_drive": {
            "minimum": float(graded_drive.min()),
            "maximum": float(graded_drive.max(initial=0.0)),
            "nonzero_ports": int(np.count_nonzero(graded_drive[graded_mask])),
        },
        "source_port_counts": {
            "event": int(np.count_nonzero(event_mask)),
            "graded": int(np.count_nonzero(graded_mask)),
        },
        "forced_source_events": forced_events,
        "generated_internal_events": generated_events,
        "probe_maxima": maxima,
        "finite_state": bool(all(np.isfinite(value).all() for value in states.values())),
    }
    del runtime
    gc.collect()
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    return result


def run_envelope(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    parameter_set_path: Path = PARAMETER_SET_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    import torch

    campaign = _load_yaml(campaign_path)
    paths = _verify_frozen_inputs(campaign)
    runtime_campaign = _load_yaml(paths["runtime_campaign"])
    constants = DiagnosticConstants.from_campaign(runtime_campaign)
    constants.validate()
    declared_dt_ms = float(campaign["technical_envelope"]["dt_ms"])
    if not math.isclose(declared_dt_ms, constants.dt_ms, rel_tol=0.0, abs_tol=1e-12):
        raise BasalSourceEnvelopeError("technical envelope dt differs from the typed/hybrid runtime")

    print("[1/9] Verifying frozen full graph, source table and local probe scope", flush=True)
    incoming = sparse.load_npz(paths["incoming_graph"]).tocsr()
    mixed_assignment, body_ids = _load_assignments(paths, runtime_campaign)
    source_rows = pd.read_csv(paths["source_terminals"]).sort_values(
        ["family_id", "channel_id", "body_id"]
    ).reset_index(drop=True)
    source_body_ids = source_rows["body_id"].to_numpy(np.int64)
    source_positions = _locate(body_ids, source_body_ids, "basal source table")
    sensory, intermediate, motor = _probe_ids(paths)
    probe_groups = {
        "sensory_36": _locate(body_ids, sensory, "local sensory probe"),
        "intermediate_150": _locate(body_ids, intermediate, "local intermediate probe"),
        "motor_10": _locate(body_ids, motor, "local motor probe"),
    }
    families = source_rows["family_id"].astype(str).to_numpy()
    observed_counts = {
        str(key): int(value)
        for key, value in source_rows["family_id"].value_counts().sort_index().items()
    }
    expected_counts = {
        str(key): int(value) for key, value in campaign["acceptance"]["expected_family_terminals"].items()
    }
    if observed_counts != expected_counts or len(source_rows) != 6041:
        raise BasalSourceEnvelopeError(f"basal source accounting drift: {observed_counts}")

    print("[2/9] Compiling the complete finite grid and six leave-one-family-out probes", flush=True)
    members = compile_envelope_members(campaign)
    expected_members = int(campaign["acceptance"]["expected_members"])
    if len(members) != expected_members:
        raise BasalSourceEnvelopeError(f"expected {expected_members} members, compiled {len(members)}")
    profiles = {
        "exact_event_plus_all_dual_as_graded": mixed_assignment,
        "all_reached_as_event_candidate": np.where(
            mixed_assignment == GRADED, EVENT, mixed_assignment
        ).astype(np.int8),
    }
    if set(profiles) != set(campaign["technical_envelope"]["assignment_profiles"]):
        raise BasalSourceEnvelopeError("assignment profile declaration drift")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    steps = int(campaign["technical_envelope"]["steps"])
    if steps <= 0:
        raise BasalSourceEnvelopeError("technical envelope steps must be positive")
    seed = int(campaign["technical_envelope"]["seed"])
    alias_limit = float(campaign["acceptance"]["max_event_presence_probability_per_step"])

    print(f"[3/9] Executing {len(members)} unranked members on {device}", flush=True)
    member_results: list[dict[str, Any]] = []
    for index, member in enumerate(members, start=1):
        if index == 1 or index % 5 == 0 or index == len(members):
            print(f"[3/9] member {index}/{len(members)}: {member['member_id']}", flush=True)
        rates = build_arm_rates(
            families,
            member["shape_id"],
            uniform_rate_hz=member["uniform_rate_hz"],
            equal_family_total_rate_hz=member["equal_family_total_rate_hz"],
        )
        if member["ablated_family_id"] is not None:
            rates[families == member["ablated_family_id"]] = 0.0
        member_steps = int(member.get("steps_override", steps))
        execution = _execute_member(
            incoming,
            profiles[member["assignment_profile_id"]],
            constants,
            source_positions,
            rates,
            probe_groups,
            device=device,
            steps=member_steps,
            seed=seed,
            half_saturation_hz=member["graded_half_saturation_hz"],
        )
        if execution["max_event_presence_probability_per_step"] > alias_limit:
            raise BasalSourceEnvelopeError(
                f"event-presence alias limit exceeded by {member['member_id']}"
            )
        member_results.append({**member, "steps": member_steps, **execution})

    print("[4/9] Comparing local-chain response to silence without ranking", flush=True)
    silence = {
        row["assignment_profile_id"]: row
        for row in member_results
        if row["shape_id"] == "explicit_silence_control"
    }
    for row in member_results:
        baseline = silence[row["assignment_profile_id"]]
        row["probe_delta_from_silence"] = {
            key: {
                metric: float(row["probe_maxima"][key][metric] - baseline["probe_maxima"][key][metric])
                for metric in ("event_g_l1", "graded_l1", "state_max_abs")
            }
            for key in probe_groups
        }

    print("[5/9] Quantifying family-ablation sensitivity as diagnostics only", flush=True)
    ablations = [row for row in member_results if row["ablated_family_id"] is not None]
    full_references = {
        profile_id: next(
            row
            for row in member_results
            if row["assignment_profile_id"] == profile_id
            and row["shape_id"] == "uniform_per_terminal"
            and row["scale_id"] == "reference"
            and math.isclose(row["graded_half_saturation_hz"], 100.0)
            and row["ablated_family_id"] is None
        )
        for profile_id in profiles
    }
    for row in ablations:
        reference = full_references[row["assignment_profile_id"]]
        row["ablation_effect_vs_full_reference"] = {
            key: {
                metric: {
                    "signed_delta": float(
                        row["probe_maxima"][key][metric]
                        - reference["probe_maxima"][key][metric]
                    ),
                    "absolute_delta": float(
                        abs(
                            row["probe_maxima"][key][metric]
                            - reference["probe_maxima"][key][metric]
                        )
                    ),
                    "absolute_fraction_of_reference": float(
                        abs(
                            row["probe_maxima"][key][metric]
                            - reference["probe_maxima"][key][metric]
                        )
                        / reference["probe_maxima"][key][metric]
                    )
                    if reference["probe_maxima"][key][metric] > 0
                    else None,
                }
                for metric in ("event_g_l1", "graded_l1", "state_max_abs")
            }
            for key in probe_groups
        }
    ablation_summary = {
        profile_id: {
            family_id: next(
                row["ablation_effect_vs_full_reference"]
                for row in ablations
                if row["assignment_profile_id"] == profile_id
                and row["ablated_family_id"] == family_id
            )
            for family_id in expected_counts
        }
        for profile_id in profiles
    }
    long_event = next(
        row for row in member_results if row["scale_id"] == "high_long_horizon"
    )
    unknown_family_id = "parameter.residual_sensory.unknown_nominal.v0"
    mixed_unknown_effect = ablation_summary[
        "exact_event_plus_all_dual_as_graded"
    ][unknown_family_id]["motor_10"]
    diagnostic_findings = {
        "mixed_reference_unknown_family_ablation_motor_event_g_l1_absolute_fraction":
            mixed_unknown_effect["event_g_l1"]["absolute_fraction_of_reference"],
        "mixed_reference_unknown_family_ablation_motor_state_max_absolute_fraction":
            mixed_unknown_effect["state_max_abs"]["absolute_fraction_of_reference"],
        "short_horizon_all_event_reference_motor_probe_is_zero": all(
            row["probe_maxima"]["motor_10"]["state_max_abs"] == 0.0
            for row in member_results
            if row["assignment_profile_id"] == "all_reached_as_event_candidate"
            and row["steps"] == steps
        ),
        "long_horizon_all_event_probe_nonzero_by_group": {
            key: bool(value["state_max_abs"] > 0.0)
            for key, value in long_event["probe_maxima"].items()
        },
        "long_horizon_all_event_generated_internal_events": int(
            long_event["generated_internal_events"]
        ),
        "interpretation": (
            "Under engineering fixtures only, the unknown-modality family dominates the mixed-profile "
            "motor-probe sensitivity. The event profile reaches all local probe groups only at the "
            "longer horizon and remains subthreshold for internally generated events. Neither finding "
            "selects a profile or establishes physiology."
        ),
    }

    print("[6/9] Applying completeness, finiteness and anti-promotion gates", flush=True)
    checks = {
        "all_6041_sources_accounted_once": len(source_rows) == 6041 and not source_rows["body_id"].duplicated().any(),
        "all_six_families_accounted": observed_counts == expected_counts,
        "local_probe_scope_is_36_plus_150_plus_10_disjoint": sum(len(value) for value in probe_groups.values()) == 196,
        "complete_finite_grid_executed": len(member_results) == expected_members,
        "both_assignment_profiles_retained": {row["assignment_profile_id"] for row in member_results} == set(profiles),
        "all_six_ablation_probes_per_profile_executed": len(ablations) == 12,
        "event_alias_bound_pass": all(row["max_event_presence_probability_per_step"] <= alias_limit for row in member_results),
        "all_runs_finite": all(row["finite_state"] for row in member_results),
        "non_silence_reaches_local_chain_in_at_least_one_profile": any(
            row["shape_id"] != "explicit_silence_control"
            and any(
                row["probe_delta_from_silence"][key][metric] > 0
                for key in probe_groups
                for metric in ("event_g_l1", "graded_l1", "state_max_abs")
            )
            for row in member_results
        ),
        "long_horizon_event_reference_reaches_all_local_probe_groups": all(
            value["state_max_abs"] > 0.0 for value in long_event["probe_maxima"].values()
        ),
        "parameter_values_promoted": False,
        "population_assignments_promoted": False,
        "members_ranked_or_selected": False,
        "named_behavior_exposed": False,
    }
    positive = [
        key for key in checks
        if key not in {
            "parameter_values_promoted", "population_assignments_promoted",
            "members_ranked_or_selected", "named_behavior_exposed",
        }
    ]
    if not all(checks[key] for key in positive) or any(
        checks[key]
        for key in (
            "parameter_values_promoted", "population_assignments_promoted",
            "members_ranked_or_selected", "named_behavior_exposed",
        )
    ):
        raise BasalSourceEnvelopeError(f"technical envelope gate failed: {checks}")

    stable_members = [
        {
            key: row[key]
            for key in (
                "member_id", "assignment_profile_id", "shape_id", "scale_id",
                "uniform_rate_hz", "equal_family_total_rate_hz",
                "graded_half_saturation_hz", "ablated_family_id", "steps",
                "max_event_presence_probability_per_step", "rate_hz", "graded_drive",
                "source_port_counts", "forced_source_events", "generated_internal_events",
                "probe_maxima", "probe_delta_from_silence", "finite_state",
            )
        }
        for row in member_results
    ]
    for stable, row in zip(stable_members, member_results, strict=True):
        if "ablation_effect_vs_full_reference" in row:
            stable["ablation_effect_vs_full_reference"] = row[
                "ablation_effect_vs_full_reference"
            ]
    semantic_members = [
        {
            "member_id": row["member_id"],
            "assignment_profile_id": row["assignment_profile_id"],
            "shape_id": row["shape_id"],
            "scale_id": row["scale_id"],
            "uniform_rate_hz": row["uniform_rate_hz"],
            "equal_family_total_rate_hz": row["equal_family_total_rate_hz"],
            "graded_half_saturation_hz": row["graded_half_saturation_hz"],
            "ablated_family_id": row["ablated_family_id"],
            "steps": row["steps"],
            "source_port_counts": row["source_port_counts"],
            "forced_source_events": row["forced_source_events"],
            "generated_internal_events": row["generated_internal_events"],
            "local_probe_reached_groups": {
                key: bool(value["state_max_abs"] > 0.0)
                for key, value in row["probe_maxima"].items()
            },
            "finite_state": row["finite_state"],
        }
        for row in member_results
    ]
    semantic_findings = {
        "mixed_unknown_ablation_motor_event_g_fraction_exceeds_0_8": bool(
            diagnostic_findings[
                "mixed_reference_unknown_family_ablation_motor_event_g_l1_absolute_fraction"
            ]
            > 0.8
        ),
        "mixed_unknown_ablation_motor_state_fraction_exceeds_0_8": bool(
            diagnostic_findings[
                "mixed_reference_unknown_family_ablation_motor_state_max_absolute_fraction"
            ]
            > 0.8
        ),
        "short_horizon_all_event_reference_motor_probe_is_zero":
            diagnostic_findings["short_horizon_all_event_reference_motor_probe_is_zero"],
        "long_horizon_all_event_probe_nonzero_by_group":
            diagnostic_findings["long_horizon_all_event_probe_nonzero_by_group"],
        "long_horizon_all_event_generated_internal_events":
            diagnostic_findings["long_horizon_all_event_generated_internal_events"],
    }
    semantic_raw = {
        "campaign_id": campaign["id"],
        "frozen_inputs": {key: value["sha256"] for key, value in campaign["frozen_inputs"].items()},
        "source_counts": observed_counts,
        "probe_counts": {key: len(value) for key, value in probe_groups.items()},
        "members": semantic_members,
        "diagnostic_findings": semantic_findings,
        "checks": checks,
    }
    significant_digits = int(campaign["reproducibility"]["semantic_float_significant_digits"])
    if significant_digits < 3 or significant_digits > 15:
        raise BasalSourceEnvelopeError("semantic float significant digits must be in [3, 15]")
    semantic = _semantic_float_quantization(semantic_raw, significant_digits)
    semantic_hash = _canonical_hash(semantic)
    compact_members = [
        {
            "member_id": row["member_id"],
            "assignment_profile_id": row["assignment_profile_id"],
            "shape_id": row["shape_id"],
            "scale_id": row["scale_id"],
            "ablated_family_id": row["ablated_family_id"],
            "steps": row["steps"],
            "finite_state": row["finite_state"],
            "local_probe_reached_groups": [
                key for key, value in row["probe_maxima"].items() if value["state_max_abs"] > 0.0
            ],
            "semantic_sha256": _canonical_hash(semantic["members"][index]),
        }
        for index, row in enumerate(member_results)
    ]
    compact_ablation_summary = {
        profile_id: {
            family_id: {
                "motor_event_g_l1_absolute_fraction_of_reference":
                    values["motor_10"]["event_g_l1"]["absolute_fraction_of_reference"],
                "motor_state_max_absolute_fraction_of_reference":
                    values["motor_10"]["state_max_abs"]["absolute_fraction_of_reference"],
                "intermediate_state_max_absolute_fraction_of_reference":
                    values["intermediate_150"]["state_max_abs"]["absolute_fraction_of_reference"],
            }
            for family_id, values in families_summary.items()
        }
        for profile_id, families_summary in ablation_summary.items()
    }
    compact_ablation_summary = _semantic_float_quantization(compact_ablation_summary, 3)
    versioned_findings = _semantic_float_quantization(diagnostic_findings, 3)
    result = {
        "schema_version": 1,
        "id": "runner_result.basal_source_envelope_propagation.v0",
        "campaign_id": campaign["id"],
        "status": "accepted_technical_envelope_propagated_zero_scientific_promotion",
        "completed_at": datetime.now(UTC).isoformat(),
        "command": "basal_source_envelope.bat",
        "claim_label": campaign["claim_label"],
        "backend": device,
        "accounting": {
            "families": len(observed_counts),
            "terminals": len(source_rows),
            "members": len(member_results),
            "assignment_profiles": len(profiles),
            "family_ablation_runs": len(ablations),
            "local_probe_neurons": sum(len(value) for value in probe_groups.values()),
        },
        "technical_boundary": campaign["technical_envelope"],
        "members": compact_members,
        "family_ablation_probe_summary": compact_ablation_summary,
        "diagnostic_findings": versioned_findings,
        "checks": checks,
        "scientific_boundary": {
            "physiological_basal_values_promoted": 0,
            "conversion_scales_promoted": 0,
            "population_assignments_promoted": 0,
            "members_ranked_or_selected": False,
            "named_behavior_exposed": False,
            "interpretation": "bounded engineering sensitivity only; not an admissible physiological set",
        },
        "reproducibility_boundary": {
            "semantic_float_significant_digits": significant_digits,
            "raw_float_diagnostics_retained": True,
            "raw_diagnostics_path": "data/derived/calibration/basal-source-envelope-propagation-v0/raw-diagnostics.json",
            "runtime_backend_noise_can_change_raw_last_bits": True,
        },
        "semantic_result_sha256": semantic_hash,
        "next_action": campaign["next_action"],
    }
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.basal_source_envelope_propagation.v0",
        "campaign_id": campaign["id"],
        "status": "accepted_technical_sensitivity_only_scientific_basal_values_unresolved",
        "conclusion": (
            "The finite behavior-naive engineering envelope and all family ablations execute "
            "through both candidate source-port profiles. The mixed profile reaches the frozen "
            "local-chain probe within 9.6 ms and is strongly fixture-sensitive to the unknown-modality "
            "family. The all-event profile reaches all three probe groups at 96 ms but produces no "
            "internal threshold crossing under the diagnostic constants. No member is ranked and no "
            "numerical value, conversion scale or population assignment is promoted as physiology."
        ),
        "diagnostic_findings": versioned_findings,
        "checks": checks,
        "runner_semantic_sha256": semantic_hash,
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    parameter_set = {
        "schema_version": 1,
        "id": "parameters.basal_source_technical_envelope.v0",
        "title": "Finite behavior-naive basal source engineering envelope",
        "status": "accepted_technical_sensitivity_set_unpromotable_as_physiology",
        "primary_class": "technical",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": semantic_hash,
        "member_count": len(member_results),
        "member_ids": [row["member_id"] for row in member_results],
        "members_ranked": False,
        "selected_reference_member_id": None,
        "values_are_physiological_bounds": False,
        "purpose": "runtime sensitivity and uncertainty propagation only",
        "family_ids": list(expected_counts),
        "assignment_profiles": list(profiles),
        "reopening_policy": "new_campaign_required_no_silent_selection_or_promotion",
        "next_action": campaign["next_action"],
    }

    print("[7/9] Writing compact immutable result, evaluation and parameter-set index", flush=True)
    for path, payload in (
        (result_path, result), (evaluation_path, evaluation), (parameter_set_path, parameter_set)
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "raw-diagnostics.json").write_text(
        json.dumps(
            {
                "campaign_id": campaign["id"],
                "members": member_results,
                "family_ablation_probe_summary": ablation_summary,
                "diagnostic_findings": diagnostic_findings,
            },
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_root / "semantic-summary.json").write_text(
        json.dumps(semantic, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    print("[8/9] Confirming written semantic hash", flush=True)
    if _load_yaml(result_path)["semantic_result_sha256"] != semantic_hash:
        raise BasalSourceEnvelopeError("written result semantic hash drift")
    print(
        f"[9/9] PASS: {len(member_results)} members, {len(ablations)} ablations, "
        f"196 local probes, semantic {semantic_hash}",
        flush=True,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--result", type=Path, default=RESULT_PATH)
    parser.add_argument("--evaluation", type=Path, default=EVALUATION_PATH)
    parser.add_argument("--parameter-set", type=Path, default=PARAMETER_SET_PATH)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    try:
        run_envelope(args.campaign, args.result, args.evaluation, args.parameter_set, args.output_root)
    except (BasalSourceEnvelopeError, BasalSourceBridgeError) as exc:
        print(f"[FAIL] {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml

from .basal_source_bridges import hz_to_graded
from .front_leg_coupled_identifiability_execution import (
    _verify_campaign as _verify_fh05_campaign,
    deterministic_event_presence,
)
from .front_leg_integrated_lineage import (
    _fh05_runtime_context,
    _load_yaml,
    _verify_inputs,
)
from .typed_hybrid_runtime import (
    EVENT,
    GRADED,
    DiagnosticConstants,
    LifConstants,
    TorchTypedHybridRuntime,
)


ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_PATH = (
    ROOT / "calibration" / "campaigns" / "front-leg-neutral-neural-regime-v0.yaml"
)
RESULT_PATH = ROOT / "calibration" / "runner" / "front-leg-neutral-neural-regime-v0.yaml"
EVALUATION_PATH = (
    ROOT / "calibration" / "evaluations" / "front-leg-neutral-neural-regime-v0.yaml"
)
PARAMETER_SET_PATH = (
    ROOT / "calibration" / "parameter_sets" / "front-leg-neutral-neural-regime-v0.yaml"
)


class NeutralNeuralRegimeError(RuntimeError):
    pass


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_frozen_inputs(campaign: Mapping[str, Any]) -> dict[str, str]:
    verified: dict[str, str] = {}
    for name, spec in campaign["frozen_inputs"].items():
        path = ROOT / str(spec["path"])
        if not path.is_file():
            raise NeutralNeuralRegimeError(f"missing frozen input {name}: {path}")
        observed = _sha256(path)
        if observed != str(spec["sha256"]):
            raise NeutralNeuralRegimeError(
                f"frozen input hash drift for {name}: {observed} != {spec['sha256']}"
            )
        verified[str(name)] = observed
    return verified


def build_pairwise_profiles(factors: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    """Return a deterministic greedy pairwise cover of the finite factor levels."""

    names = list(factors)
    if len(names) < 2 or any(len(factors[name]) < 2 for name in names):
        raise NeutralNeuralRegimeError("pairwise design requires at least two nontrivial factors")
    candidates = [
        dict(zip(names, values, strict=True))
        for values in itertools.product(*(factors[name] for name in names))
    ]
    universe = {
        (left, repr(row[left]), right, repr(row[right]))
        for left_index, left in enumerate(names)
        for right in names[left_index + 1 :]
        for row in candidates
    }
    row_pairs = []
    for row in candidates:
        row_pairs.append(
            {
                (left, repr(row[left]), right, repr(row[right]))
                for left_index, left in enumerate(names)
                for right in names[left_index + 1 :]
            }
        )
    uncovered = set(universe)
    selected: list[dict[str, Any]] = []
    remaining = set(range(len(candidates)))
    while uncovered:
        best = max(
            remaining,
            key=lambda index: (len(row_pairs[index] & uncovered), -index),
        )
        gain = row_pairs[best] & uncovered
        if not gain:
            raise NeutralNeuralRegimeError("pairwise cover construction stalled")
        selected.append(candidates[best])
        uncovered -= gain
        remaining.remove(best)
    for index, row in enumerate(selected):
        row["profile_id"] = f"regime_{index:03d}"
    return selected


def pairwise_coverage(
    profiles: Sequence[Mapping[str, Any]], factors: Mapping[str, Sequence[Any]]
) -> dict[str, Any]:
    names = list(factors)
    pairs: dict[str, Any] = {}
    complete = True
    for left_index, left in enumerate(names):
        for right in names[left_index + 1 :]:
            observed = {(repr(row[left]), repr(row[right])) for row in profiles}
            expected = {
                (repr(left_value), repr(right_value))
                for left_value in factors[left]
                for right_value in factors[right]
            }
            key = f"{left}__x__{right}"
            pairs[key] = {
                "observed": len(observed),
                "expected": len(expected),
                "complete": observed == expected,
            }
            complete &= observed == expected
    return {"complete": complete, "pairs": pairs}


def classify_regime(metrics: Mapping[str, Any], criteria: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "finite": bool(metrics["finite"]),
        "generated_event_occupancy_bounded": max(
            float(metrics["stimulus_generated_event_occupancy"]),
            float(metrics["sham_generated_event_occupancy"]),
        )
        <= float(criteria["generated_event_occupancy_max"]),
        "motor_event_occupancy_bounded": max(
            float(metrics["stimulus_motor_event_occupancy"]),
            float(metrics["sham_motor_event_occupancy"]),
        )
        <= float(criteria["motor_event_occupancy_max"]),
        "motor_event_response_nonzero": abs(
            int(metrics["stimulus_motor_events"]) - int(metrics["sham_motor_events"])
        )
        >= int(criteria["motor_event_count_difference_min"]),
        "motor_state_response_nonzero": float(metrics["motor_state_delta_peak_l1"])
        > float(criteria["motor_state_delta_peak_l1_min"]),
        "post_pulse_recovery": float(metrics["motor_state_post_pulse_ratio"])
        <= float(criteria["motor_state_post_pulse_ratio_max"]),
    }
    return {
        "accepted": all(checks.values()),
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def _constants(fixture: Mapping[str, Any], profile: Mapping[str, Any]) -> DiagnosticConstants:
    event = fixture["event_comparator"]
    boundary = fixture["boundary_scales"]
    rest = float(event["v_rest_mV"])
    distance = float(event["threshold_mV"]) - rest
    same = float(profile["same_native_efficacy_ratio"])
    cross = float(profile["cross_native_conversion_ratio"])
    return DiagnosticConstants(
        dt_ms=float(fixture["dt_ms"]),
        lif=LifConstants(
            v_rest_mV=rest,
            reset_mV=float(event["reset_mV"]),
            threshold_mV=rest + distance * float(profile["threshold_distance_ratio"]),
            tau_membrane_ms=float(event["tau_membrane_ms"]),
            tau_syn_ms=float(event["tau_syn_ms"]),
            refractory_ms=float(event["refractory_ms"]),
            fixed_delay_ms=float(event["fixed_delay_ms"]),
        ),
        event_to_event_mV=float(boundary["event_to_event_mV"]) * same,
        event_to_graded=float(boundary["event_to_graded"]) * cross,
        graded_to_event_mV=float(boundary["graded_to_event_mV"]) * cross,
        graded_to_graded=float(boundary["graded_to_graded"]) * same,
        graded_tau_ms=float(fixture["graded_tau_ms"]),
        external_graded_probe=float(fixture["feco_graded_drive"]),
    )


def _paired_schedules(
    *,
    assignment: np.ndarray,
    source_count: int,
    source_families: np.ndarray,
    feco_indices: np.ndarray,
    profile: Mapping[str, Any],
    source_profile: str,
    fixture: Mapping[str, Any],
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    steps = int(fixture["steps"])
    dt_ms = float(fixture["dt_ms"])
    pulse_start = int(fixture["pulse_start_step"])
    pulse_stop = int(fixture["pulse_stop_step"])
    event = np.zeros((steps, len(assignment)), dtype=bool)
    graded = np.zeros((steps, len(assignment)), dtype=np.float32)
    unknown = source_families == str(fixture["unknown_family_id"])
    basal_rate = float(fixture["basal_rate_hz"]) * float(
        profile["basal_source_intensity_ratio"]
    )
    rates = np.full(source_count, basal_rate, dtype=np.float64)
    policy = str(profile["unknown_afferent_policy"])
    if policy == "zero":
        rates[unknown] = 0.0
    phases = (np.arange(source_count, dtype=np.float64) * 0.6180339887498949) % 1.0
    rng = np.random.default_rng(seed)
    if source_profile == "all_event_candidate":
        event[:, :source_count] = deterministic_event_presence(rates, dt_ms, steps, phases)
        if policy == "matched_stochastic_fixture":
            probability = np.clip(rates[unknown] * dt_ms / 1000.0, 0.0, 1.0)
            event[:, np.flatnonzero(unknown)] = (
                rng.random((steps, int(np.count_nonzero(unknown)))) < probability[None, :]
            )
    elif source_profile == "all_graded_candidate":
        drive = hz_to_graded(rates, float(fixture["graded_half_saturation_hz"]))
        graded[:, :source_count] = drive[None, :]
        if policy == "matched_stochastic_fixture":
            toggles = rng.integers(0, 2, size=(steps, int(np.count_nonzero(unknown))))
            graded[:, np.flatnonzero(unknown)] = 2.0 * drive[unknown][None, :] * toggles
    else:
        raise NeutralNeuralRegimeError(f"unknown source mirror {source_profile!r}")

    event_feco = feco_indices[assignment[feco_indices] == EVENT]
    graded_feco = feco_indices[assignment[feco_indices] == GRADED]
    feco_ratio = float(profile["feco_native_amplitude_ratio"])
    if len(event_feco):
        rates = np.full(
            len(event_feco), float(fixture["feco_event_rate_hz"]) * feco_ratio
        )
        local_phase = (np.arange(len(event_feco)) * 0.4142135623730951) % 1.0
        event[pulse_start:pulse_stop, event_feco] |= deterministic_event_presence(
            rates, dt_ms, pulse_stop - pulse_start, local_phase
        )
    if len(graded_feco):
        graded[pulse_start:pulse_stop, graded_feco] += (
            float(fixture["feco_graded_drive"]) * feco_ratio
        )
    sham_event = event.copy()
    sham_graded = graded.copy()
    sham_event[pulse_start:pulse_stop, feco_indices] = False
    sham_graded[pulse_start:pulse_stop, feco_indices] = 0.0
    return event, graded, sham_event, sham_graded, {
        "basal_rate_hz": basal_rate,
        "feco_event_rate_hz": float(fixture["feco_event_rate_hz"]) * feco_ratio,
        "feco_graded_drive": float(fixture["feco_graded_drive"]) * feco_ratio,
        "unknown_afferent_policy": policy,
        "stimulus_forced_event_count": int(np.count_nonzero(event[:, feco_indices])),
        "stimulus_graded_integral": float(np.sum(graded[:, feco_indices])),
    }


def _execute_pair(
    *,
    context: Mapping[str, Any],
    profile: Mapping[str, Any],
    fixture: Mapping[str, Any],
    criteria: Mapping[str, Any],
    source_families: np.ndarray,
    seed: int,
    device: str,
) -> dict[str, Any]:
    import torch

    constants = _constants(fixture, profile)
    schedules = _paired_schedules(
        assignment=context["assignment"],
        source_count=int(context["source_count"]),
        source_families=source_families,
        feco_indices=context["feco_indices"],
        profile=profile,
        source_profile=str(context["source_profile"]),
        fixture=fixture,
        seed=seed,
    )
    stimulus = TorchTypedHybridRuntime(
        context["graph"], context["assignment"], constants, device
    )
    sham = TorchTypedHybridRuntime(context["graph"], context["assignment"], constants, device)
    motor_indices = torch.as_tensor(context["motor_indices"], dtype=torch.int64, device=device)
    event_count = max(1, int(np.count_nonzero(context["assignment"] == EVENT)))
    motor_count = max(1, len(context["motor_indices"]))
    generated = {"stimulus": 0, "sham": 0}
    motor_events = {"stimulus": 0, "sham": 0}
    delta_trace: list[float] = []
    max_abs_state = 0.0
    with torch.inference_mode():
        for step in range(int(fixture["steps"])):
            stim_row = stimulus.step(
                forced_event_indices=np.flatnonzero(schedules[0][step]),
                external_graded=schedules[1][step],
            )
            sham_row = sham.step(
                forced_event_indices=np.flatnonzero(schedules[2][step]),
                external_graded=schedules[3][step],
            )
            generated["stimulus"] += int(stim_row["generated_events"])
            generated["sham"] += int(sham_row["generated_events"])
            stim_event = stimulus.refractory[motor_indices] == stimulus.refractory_steps
            sham_event = sham.refractory[motor_indices] == sham.refractory_steps
            motor_events["stimulus"] += int(torch.count_nonzero(stim_event).item())
            motor_events["sham"] += int(torch.count_nonzero(sham_event).item())
            delta = torch.sum(torch.abs(stimulus.g[motor_indices] - sham.g[motor_indices]))
            delta += torch.sum(
                torch.abs(stimulus.graded[motor_indices] - sham.graded[motor_indices])
            )
            delta_trace.append(float(delta.item()))
            max_abs_state = max(
                max_abs_state,
                float(torch.max(torch.abs(stimulus.g)).item()),
                float(torch.max(torch.abs(stimulus.graded)).item()),
                float(torch.max(torch.abs(sham.g)).item()),
                float(torch.max(torch.abs(sham.graded)).item()),
            )
    states = (*stimulus.state_arrays().values(), *sham.state_arrays().values())
    finite = all(np.isfinite(value).all() for value in states)
    steps = int(fixture["steps"])
    pulse_start = int(fixture["pulse_start_step"])
    recovery_window = int(fixture["recovery_tail_steps"])
    peak = max(delta_trace[pulse_start:], default=0.0)
    tail = float(np.mean(delta_trace[-recovery_window:]))
    ratio = tail / peak if peak > 0.0 else math.inf
    metrics = {
        "finite": bool(finite),
        "stimulus_generated_events": generated["stimulus"],
        "sham_generated_events": generated["sham"],
        "stimulus_generated_event_occupancy": generated["stimulus"] / (steps * event_count),
        "sham_generated_event_occupancy": generated["sham"] / (steps * event_count),
        "stimulus_motor_events": motor_events["stimulus"],
        "sham_motor_events": motor_events["sham"],
        "stimulus_motor_event_occupancy": motor_events["stimulus"] / (steps * motor_count),
        "sham_motor_event_occupancy": motor_events["sham"] / (steps * motor_count),
        "motor_state_delta_peak_l1": peak,
        "motor_state_post_pulse_tail_l1": tail,
        "motor_state_post_pulse_ratio": ratio,
        "max_abs_internal_state": max_abs_state,
    }
    return {
        "metrics": metrics,
        "classification": classify_regime(metrics, criteria),
        "schedule_accounting": schedules[4],
    }


def _context_for_anchor(
    parent_campaign: Mapping[str, Any],
    verified: Mapping[str, Any],
    anchor: Mapping[str, Any],
    source_profile: str,
) -> dict[str, Any]:
    campaign = copy.deepcopy(parent_campaign)
    witness = campaign["execution_witness"]
    witness["sensory"]["routing_profile_id"] = anchor["routing_profile_id"]
    witness["sensory"]["native_profile_id"] = anchor["native_profile_id"]
    witness["central_basal"]["member_id"] = f"{anchor['anchor_id']}__owner_00"
    witness["central_basal"]["source_native_mirror"] = source_profile
    return _fh05_runtime_context(campaign, verified)


def run_gate(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    parameter_set_path: Path = PARAMETER_SET_PATH,
) -> dict[str, Any]:
    campaign = _load_yaml(campaign_path)
    frozen_hashes = _verify_frozen_inputs(campaign)
    parent_path = ROOT / campaign["frozen_inputs"]["fh06_campaign"]["path"]
    parent_campaign = _load_yaml(parent_path)
    verified = _verify_inputs(parent_campaign)
    fh05 = verified["documents"]["coupled_campaign"]
    fh05_paths = _verify_fh05_campaign(fh05)
    source_rows = pd.read_csv(fh05_paths["source_terminals"]).sort_values("body_id")
    source_families = source_rows.family_id.astype(str).to_numpy()
    factors = campaign["technical_factor_levels"]
    profiles = build_pairwise_profiles(factors)
    coverage = pairwise_coverage(profiles, factors)
    anchors = fh05["execution_anchors"]
    mirrors = campaign["source_native_mirrors"]
    rows_total = len(profiles) * len(anchors) * len(mirrors)
    if rows_total > int(campaign["budget"]["max_schedule_rows"]):
        raise NeutralNeuralRegimeError("pairwise schedule exceeds preregistered row budget")
    print(
        f"[1/6] Pairwise design: {len(profiles)} profiles x {len(anchors)} anchors "
        f"x {len(mirrors)} mirrors = {rows_total} paired rows",
        flush=True,
    )
    print("[2/6] Verifying FH-06 and FH-05 frozen dependencies", flush=True)
    contexts = {
        (str(anchor["anchor_id"]), str(mirror)): _context_for_anchor(
            parent_campaign, verified, anchor, str(mirror)
        )
        for anchor in anchors
        for mirror in mirrors
    }
    print("[3/6] Executing paired generic-pulse/sham neural regimes", flush=True)
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    accepted: list[str] = []
    index = 0
    for anchor in anchors:
        for mirror in mirrors:
            context = contexts[(str(anchor["anchor_id"]), str(mirror))]
            for profile in profiles:
                index += 1
                row_id = f"{anchor['anchor_id']}__{mirror}__{profile['profile_id']}"
                executed = _execute_pair(
                    context=context,
                    profile=profile,
                    fixture=campaign["execution_fixture"],
                    criteria=campaign["acceptance"],
                    source_families=source_families,
                    seed=int(campaign["execution_fixture"]["seed"]) + index * 104729,
                    device=str(campaign["execution_fixture"]["device"]),
                )
                row = {
                    "row_id": row_id,
                    "anchor_id": anchor["anchor_id"],
                    "source_native_mirror": mirror,
                    "profile": profile,
                    **executed,
                }
                rows.append(row)
                if executed["classification"]["accepted"]:
                    accepted.append(row_id)
                if index == 1 or index % 15 == 0 or index == rows_total:
                    print(
                        f"  [{index:03d}/{rows_total}] accepted={len(accepted)} "
                        f"latest={row_id}",
                        flush=True,
                    )
    wall_seconds = time.perf_counter() - started
    failure_counts: dict[str, int] = {}
    for row in rows:
        for reason in row["classification"]["failed_checks"]:
            failure_counts[reason] = failure_counts.get(reason, 0) + 1
    print("[4/6] Accounting every scheduled row and technical failure mode", flush=True)
    checks = {
        "pairwise_factor_coverage_complete": bool(coverage["complete"]),
        "all_schedule_rows_accounted": len(rows) == rows_total,
        "all_runs_finite": all(row["metrics"]["finite"] for row in rows),
        "all_anchors_executed": {row["anchor_id"] for row in rows}
        == {str(anchor["anchor_id"]) for anchor in anchors},
        "both_source_native_mirrors_executed": {row["source_native_mirror"] for row in rows}
        == set(map(str, mirrors)),
        "no_named_behavior_exposure": campaign["behavior_targets"] == [],
        "no_body_trajectory_or_posture_metric": campaign["forbidden_observables"]
        == ["body_pose", "body_trajectory", "named_action", "held_out_response"],
        "zero_reference_selection": True,
    }
    if not all(checks.values()):
        raise NeutralNeuralRegimeError(f"FH-07a contract failed: {checks}")
    semantic_payload = {
        "campaign_id": campaign["id"],
        "frozen_input_sha256": frozen_hashes,
        "profiles": profiles,
        "coverage": coverage,
        "rows": rows,
        "accepted_row_ids": accepted,
        "checks": checks,
    }
    semantic_hash = _canonical_hash(semantic_payload)
    status = (
        "accepted_nonempty_neural_technical_ensemble_FH07_physics_open"
        if accepted
        else "negative_no_neural_regime_passes_replan_required"
    )
    result = {
        "schema_version": 1,
        "id": "runner_result.front_leg_neutral_neural_regime.v0",
        "campaign_id": campaign["id"],
        "status": status,
        "completed_at": datetime.now(UTC).isoformat(),
        "command": "front_leg_neutral_neural_regime.bat",
        "claim_label": campaign["claim_label"],
        "frozen_input_sha256": frozen_hashes,
        "design": {
            "factor_profiles": len(profiles),
            "anchors": len(anchors),
            "source_native_mirrors": len(mirrors),
            "paired_schedule_rows": rows_total,
            "runtime_instances": rows_total * 2,
            "pairwise_coverage": coverage,
        },
        "execution_fixture": campaign["execution_fixture"],
        "acceptance": campaign["acceptance"],
        "rows": rows,
        "accepted_row_ids": accepted,
        "accepted_rows": len(accepted),
        "failure_counts": dict(sorted(failure_counts.items())),
        "checks": checks,
        "members_ranked": False,
        "reference_member_selected": False,
        "parameter_values_promoted": 0,
        "named_behavior_exposed": False,
        "body_outcomes_consumed": 0,
        "whole_body_stability_accepted": False,
        "wall_seconds": wall_seconds,
        "semantic_result_sha256": semantic_hash,
        "next_action": campaign["next_action_if_nonempty"] if accepted else campaign["next_action_if_empty"],
    }
    parameter_set = {
        "schema_version": 1,
        "id": "parameters.front_leg_neutral_neural_regime.v0",
        "title": "FH-07a non-ranked short-horizon neural technical regime ensemble",
        "status": status,
        "primary_class": "technical",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": semantic_hash,
        "member_count": len(accepted),
        "member_ids": accepted,
        "members_ranked": False,
        "selected_reference_member_id": None,
        "values_are_physiological_bounds": False,
        "body_outcomes_consumed": 0,
        "reopening_policy": "new_campaign_required_on_parent_hash_or_gate_change",
        "next_action": result["next_action"],
    }
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.front_leg_neutral_neural_regime.v0",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": semantic_hash,
        "parameter_set_id": parameter_set["id"],
        "status": status,
        "checks": checks,
        "accepted_rows": len(accepted),
        "scheduled_rows": rows_total,
        "failure_counts": result["failure_counts"],
        "whole_body_stability_accepted": False,
        "named_behavior_exposed": False,
        "interpretation": (
            "This gate may retain a non-ranked engineering ensemble that is finite, "
            "motor-responsive, bounded in event occupancy and recovering after a generic "
            "FeCO pulse. It neither identifies physiology nor accepts embodied stability."
            if accepted
            else
            "No scheduled engineering regime met the locked nondegeneracy, boundedness and "
            "recovery criteria. The empty result is retained and requires explicit replanning."
        ),
        "next_action": result["next_action"],
    }
    print("[5/6] Writing compact result, parameter-set and evaluation records", flush=True)
    result_path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    parameter_set_path.write_text(
        yaml.safe_dump(parameter_set, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    evaluation_path.write_text(
        yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    print(
        f"[6/6] COMPLETE — accepted={len(accepted)}/{rows_total}; "
        f"zero ranking, zero behavior, zero body outcomes; {semantic_hash}",
        flush=True,
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the FH-07a behavior-naive front-leg neural regime gate"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args(argv)
    run_gate(campaign_path=args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml
from scipy import sparse

from .ledger import ROOT
from .typed_hybrid_runtime import (
    EVENT,
    GRADED,
    INACTIVE,
    DiagnosticConstants,
    TorchTypedHybridRuntime,
    _load_assignments,
)


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "basal-source-bridge-mechanics-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "basal-source-bridge-mechanics-v0.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "basal-source-bridge-mechanics-v0.yaml"
OUTPUT_ROOT = ROOT / "data" / "derived" / "calibration" / "basal-source-bridge-mechanics-v0"


class BasalSourceBridgeError(RuntimeError):
    """Raised when source accounting, units or diagnostic boundaries drift."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BasalSourceBridgeError(f"{path} must contain a YAML mapping")
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


def event_probability(rate_hz: np.ndarray | Sequence[float], dt_ms: float) -> np.ndarray:
    """Probability that a Poisson source emits at least one event in one step.

    The runtime port carries event presence, not event multiplicity. Campaigns
    must therefore bound the probability so that collapsed multiple events do
    not silently become an uncontrolled approximation.
    """

    rates = np.asarray(rate_hz, dtype=np.float64)
    if dt_ms <= 0 or np.any(~np.isfinite(rates)) or np.any(rates < 0):
        raise BasalSourceBridgeError("event rates must be finite, non-negative and use positive dt")
    return -np.expm1(-rates * dt_ms / 1000.0)


def sample_event_presence(
    rate_hz: np.ndarray | Sequence[float], dt_ms: float, rng: np.random.Generator
) -> np.ndarray:
    probability = event_probability(rate_hz, dt_ms)
    return rng.random(probability.shape) < probability


def hz_to_graded(
    rate_hz: np.ndarray | Sequence[float], half_saturation_hz: float
) -> np.ndarray:
    """Bounded monotone candidate bridge from Hz to dimensionless drive.

    `half_saturation_hz` is unresolved calibration capacity. A number supplied
    by a diagnostic campaign is an unpromotable mechanics fixture.
    """

    rates = np.asarray(rate_hz, dtype=np.float64)
    if (
        half_saturation_hz <= 0
        or not math.isfinite(half_saturation_hz)
        or np.any(~np.isfinite(rates))
        or np.any(rates < 0)
    ):
        raise BasalSourceBridgeError("graded conversion requires finite non-negative Hz and positive scale")
    return (rates / (rates + half_saturation_hz)).astype(np.float32)


def build_arm_rates(
    family_ids: Sequence[str],
    arm_id: str,
    *,
    uniform_rate_hz: float,
    equal_family_total_rate_hz: float,
) -> np.ndarray:
    families = np.asarray(family_ids, dtype=str)
    if arm_id == "explicit_silence_control":
        return np.zeros(len(families), dtype=np.float64)
    if arm_id == "uniform_per_terminal":
        return np.full(len(families), uniform_rate_hz, dtype=np.float64)
    if arm_id == "equal_family_mass":
        values = np.zeros(len(families), dtype=np.float64)
        for family in np.unique(families):
            mask = families == family
            values[mask] = equal_family_total_rate_hz / int(np.count_nonzero(mask))
        return values
    raise BasalSourceBridgeError(f"unknown basal sensitivity arm: {arm_id}")


def _verify_campaign(campaign: Mapping[str, Any]) -> dict[str, Path]:
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise BasalSourceBridgeError("source bridge mechanics cannot optimize parameters")
    if campaign.get("behavior_targets"):
        raise BasalSourceBridgeError("source bridge mechanics cannot expose named behavior")
    if campaign.get("topology_changes_allowed") is not False:
        raise BasalSourceBridgeError("source bridge mechanics cannot change topology")
    if int(campaign.get("parameter_values_promoted", -1)) != 0:
        raise BasalSourceBridgeError("source bridge mechanics cannot promote parameter values")
    if int(campaign.get("population_assignments_promoted", -1)) != 0:
        raise BasalSourceBridgeError("source bridge mechanics cannot promote assignments")
    paths: dict[str, Path] = {}
    for key, record in campaign["frozen_inputs"].items():
        path = ROOT / str(record["path"])
        if not path.is_file():
            raise BasalSourceBridgeError(f"missing frozen input {key}: {path}")
        observed = _sha256(path)
        if observed != str(record["sha256"]):
            raise BasalSourceBridgeError(
                f"frozen input drift for {key}: {observed} != {record['sha256']}"
            )
        paths[key] = path
    return paths


def _source_accounting(
    source_rows: pd.DataFrame,
    body_ids: np.ndarray,
    campaign: Mapping[str, Any],
) -> tuple[np.ndarray, dict[str, int]]:
    required = {"family_id", "channel_id", "body_id"}
    if not required.issubset(source_rows.columns):
        raise BasalSourceBridgeError("source terminal table lacks required identity columns")
    if source_rows["body_id"].duplicated().any():
        raise BasalSourceBridgeError("a basal terminal appears more than once")
    positions = np.searchsorted(body_ids, source_rows["body_id"].to_numpy(np.int64))
    if np.any(positions >= len(body_ids)) or np.any(
        body_ids[positions] != source_rows["body_id"].to_numpy(np.int64)
    ):
        raise BasalSourceBridgeError("source terminal body mapping drift")
    counts = {
        str(key): int(value)
        for key, value in source_rows["family_id"].value_counts().sort_index().items()
    }
    expected = {str(k): int(v) for k, v in campaign["acceptance"]["expected_family_terminals"].items()}
    if counts != expected or len(source_rows) != int(campaign["acceptance"]["expected_terminals"]):
        raise BasalSourceBridgeError(f"basal source accounting drift: {counts}")
    return positions.astype(np.int64), counts


def _execute_arm(
    incoming: sparse.csr_matrix,
    assignment: np.ndarray,
    constants: DiagnosticConstants,
    source_positions: np.ndarray,
    rates_hz: np.ndarray,
    *,
    device: str,
    steps: int,
    seed: int,
    half_saturation_hz: float,
) -> dict[str, Any]:
    import torch

    source_types = assignment[source_positions]
    if np.any((source_types != EVENT) & (source_types != GRADED)):
        raise BasalSourceBridgeError("a basal source was compiled to an inactive or unresolved port")
    event_mask = source_types == EVENT
    graded_mask = source_types == GRADED
    probabilities = event_probability(rates_hz, constants.dt_ms)
    graded_drive = hz_to_graded(rates_hz, half_saturation_hz)
    max_probability = float(probabilities.max(initial=0.0))

    rng = np.random.default_rng(seed)
    schedule_digest = hashlib.sha256()
    runtime = TorchTypedHybridRuntime(incoming, assignment, constants, device)
    external = np.zeros(len(assignment), dtype=np.float32)
    external[source_positions[graded_mask]] = graded_drive[graded_mask]
    emitted = 0
    emitting_terminals: set[int] = set()
    delivered = 0
    generated = 0
    maxima = {"event_state_max_abs": 0.0, "graded_state_max_abs": 0.0}
    if device.startswith("cuda"):
        torch.cuda.synchronize(device)
    started = time.perf_counter()
    with torch.inference_mode():
        for step in range(steps):
            candidate_presence = sample_event_presence(rates_hz, constants.dt_ms, rng)
            schedule_digest.update(np.asarray([step], dtype=np.int32).tobytes())
            schedule_digest.update(np.packbits(candidate_presence).tobytes())
            selected = np.flatnonzero(candidate_presence & event_mask)
            forced = source_positions[selected]
            emitted += int(len(forced))
            emitting_terminals.update(selected.tolist())
            row = runtime.step(forced_event_indices=forced, external_graded=external)
            delivered += int(row["delivered_event_sources"])
            generated += int(row["generated_events"])
            for key in maxima:
                maxima[key] = max(maxima[key], float(row[key]))
    if device.startswith("cuda"):
        torch.cuda.synchronize(device)
    elapsed = time.perf_counter() - started
    states = runtime.state_arrays()
    inactive = assignment == INACTIVE
    result = {
        "source_port_counts": {
            "event": int(np.count_nonzero(event_mask)),
            "graded": int(np.count_nonzero(graded_mask)),
            "total": int(len(source_positions)),
        },
        "rate_hz_summary": {
            "minimum": float(rates_hz.min()),
            "maximum": float(rates_hz.max(initial=0.0)),
            "sum": float(rates_hz.sum()),
        },
        "max_event_presence_probability_per_step": max_probability,
        "graded_drive_summary": {
            "minimum": float(graded_drive.min()),
            "maximum": float(graded_drive.max(initial=0.0)),
            "nonzero_sources": int(np.count_nonzero((graded_drive != 0) & graded_mask)),
        },
        "steps": steps,
        "simulated_ms": steps * constants.dt_ms,
        "seed": seed,
        "candidate_event_schedule_sha256": schedule_digest.hexdigest(),
        "forced_source_events": emitted,
        "distinct_event_sources_emitting": int(len(emitting_terminals)),
        "delivered_source_events": delivered,
        "generated_internal_events": generated,
        "state_maxima": maxima,
        "finite_state": bool(all(np.isfinite(value).all() for value in states.values())),
        "inactive_state_exactly_zero_or_rest": bool(
            np.all(states["g"][inactive] == 0)
            and np.all(states["graded"][inactive] == 0)
            and np.all(states["refractory"][inactive] == 0)
            and np.all(states["v"][inactive] == constants.lif.v_rest_mV)
        ),
        "elapsed_seconds": elapsed,
        "steps_per_second": steps / elapsed,
        "peak_gpu_bytes": int(torch.cuda.max_memory_allocated(device))
        if device.startswith("cuda")
        else None,
    }
    del runtime
    gc.collect()
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    return result


def run_source_bridge_mechanics(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    import torch

    campaign = _load_yaml(campaign_path)
    paths = _verify_campaign(campaign)
    runtime_campaign = _load_yaml(paths["runtime_campaign"])
    constants = DiagnosticConstants.from_campaign(runtime_campaign)
    constants.validate()

    print("[1/8] Verifying frozen graph, source table and zero-promotion contract", flush=True)
    incoming = sparse.load_npz(paths["incoming_graph"]).tocsr()
    mixed_assignment, body_ids = _load_assignments(paths, runtime_campaign)
    source_rows = pd.read_csv(paths["source_terminals"]).sort_values(
        ["family_id", "channel_id", "body_id"]
    ).reset_index(drop=True)
    source_positions, family_counts = _source_accounting(source_rows, body_ids, campaign)
    if incoming.shape != (len(body_ids), len(body_ids)):
        raise BasalSourceBridgeError("canonical graph shape drift")

    execution = campaign["diagnostic_execution"]
    arms = [str(value) for value in execution["arms"]]
    profiles = {
        "exact_event_plus_all_dual_as_graded": mixed_assignment,
        "all_reached_as_event_candidate": np.where(
            mixed_assignment == GRADED, EVENT, mixed_assignment
        ).astype(np.int8),
    }
    device = "cuda" if torch.cuda.is_available() else "cpu"
    steps = int(execution["steps"])
    seed_by_arm = {str(k): int(v) for k, v in execution["seed_by_arm"].items()}
    if not math.isclose(float(execution["dt_ms"]), constants.dt_ms, abs_tol=1e-12):
        raise BasalSourceBridgeError("bridge campaign dt and typed/hybrid runtime dt differ")
    if set(seed_by_arm) != set(arms) or len(set(seed_by_arm.values())) != len(arms):
        raise BasalSourceBridgeError("every arm must have one distinct explicit diagnostic seed")
    uniform_rate = float(execution["uniform_per_terminal_fixture_hz"])
    family_mass = float(execution["equal_family_total_fixture_hz"])
    half_saturation = float(execution["graded_half_saturation_fixture_hz"])
    probability_limit = float(campaign["acceptance"]["max_event_presence_probability_per_step"])

    print("[2/8] Compiling all 6,041 sources for all three preregistered arms", flush=True)
    arm_rates = {
        arm: build_arm_rates(
            source_rows["family_id"].tolist(),
            arm,
            uniform_rate_hz=uniform_rate,
            equal_family_total_rate_hz=family_mass,
        )
        for arm in arms
    }
    equal_mass_totals = {
        family: float(arm_rates["equal_family_mass"][source_rows["family_id"].eq(family)].sum())
        for family in family_counts
    }
    if not all(math.isclose(value, family_mass, rel_tol=1e-12) for value in equal_mass_totals.values()):
        raise BasalSourceBridgeError("equal-family-mass arm does not conserve family totals")
    max_probability = max(
        float(event_probability(rates, constants.dt_ms).max(initial=0.0))
        for rates in arm_rates.values()
    )
    if max_probability > probability_limit:
        raise BasalSourceBridgeError(
            f"event-presence alias bound exceeded: {max_probability} > {probability_limit}"
        )

    print(f"[3/8] Executing mixed candidate profile on {device}", flush=True)
    profile_results: dict[str, Any] = {}
    for profile_index, (profile_id, assignment) in enumerate(profiles.items(), start=1):
        if profile_index == 2:
            print(f"[5/8] Executing all-event candidate profile on {device}", flush=True)
        arm_results: dict[str, Any] = {}
        for arm_index, arm in enumerate(arms, start=1):
            print(f"[{'3' if profile_index == 1 else '5'}/8] {profile_id}: arm {arm_index}/3 {arm}", flush=True)
            arm_results[arm] = _execute_arm(
                incoming,
                assignment,
                constants,
                source_positions,
                arm_rates[arm],
                device=device,
                steps=steps,
                seed=seed_by_arm[arm],
                half_saturation_hz=half_saturation,
            )
        profile_results[profile_id] = {
            "node_counts": {
                "inactive": int(np.count_nonzero(assignment == INACTIVE)),
                "event": int(np.count_nonzero(assignment == EVENT)),
                "graded": int(np.count_nonzero(assignment == GRADED)),
            },
            "arms": arm_results,
        }

    print("[6/8] Checking source completeness, deterministic schedules and runtime boundaries", flush=True)
    mixed = profile_results["exact_event_plus_all_dual_as_graded"]["arms"]
    event = profile_results["all_reached_as_event_candidate"]["arms"]
    checks = {
        "all_6041_sources_accounted_once": len(source_rows) == 6041,
        "all_six_families_accounted": len(family_counts) == 6,
        "all_three_preregistered_arms_executed_in_both_profiles": all(
            set(profile_results[profile]["arms"]) == set(arms) for profile in profiles
        ),
        "equal_family_mass_conserved": all(
            math.isclose(value, family_mass, rel_tol=1e-12)
            for value in equal_mass_totals.values()
        ),
        "event_presence_alias_bound_pass": max_probability <= probability_limit,
        "seeded_candidate_schedules_match_across_assignment_profiles": all(
            mixed[arm]["candidate_event_schedule_sha256"]
            == event[arm]["candidate_event_schedule_sha256"]
            for arm in arms
        ),
        "event_process_exercised": all(
            event[arm]["forced_source_events"] > 0 for arm in arms if arm != "explicit_silence_control"
        ),
        "graded_conversion_exercised": all(
            mixed[arm]["graded_drive_summary"]["nonzero_sources"] > 0
            for arm in arms
            if arm != "explicit_silence_control"
        ),
        "silence_control_is_zero": bool(
            event["explicit_silence_control"]["forced_source_events"] == 0
            and mixed["explicit_silence_control"]["graded_drive_summary"]["nonzero_sources"] == 0
        ),
        "all_runs_finite": all(
            arm["finite_state"]
            for profile in profile_results.values()
            for arm in profile["arms"].values()
        ),
        "inactive_269_neurons_remain_quiescent": all(
            arm["inactive_state_exactly_zero_or_rest"]
            for profile in profile_results.values()
            for arm in profile["arms"].values()
        ),
        "population_assignments_promoted": False,
        "parameter_values_promoted": False,
        "named_behavior_exposed": False,
    }
    positive_checks = [
        key for key in checks if key not in {
            "population_assignments_promoted", "parameter_values_promoted", "named_behavior_exposed"
        }
    ]
    if not all(checks[key] for key in positive_checks) or any(
        checks[key] for key in (
            "population_assignments_promoted", "parameter_values_promoted", "named_behavior_exposed"
        )
    ):
        raise BasalSourceBridgeError(f"source bridge mechanics failed: {checks}")

    def stable_arm(value: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value[key]
            for key in (
                "source_port_counts",
                "rate_hz_summary",
                "max_event_presence_probability_per_step",
                "graded_drive_summary",
                "steps",
                "simulated_ms",
                "seed",
                "candidate_event_schedule_sha256",
                "forced_source_events",
                "distinct_event_sources_emitting",
                "delivered_source_events",
                "generated_internal_events",
                "finite_state",
                "inactive_state_exactly_zero_or_rest",
            )
        }

    semantic = {
        "campaign_id": campaign["id"],
        "frozen_inputs": {key: str(value["sha256"]) for key, value in campaign["frozen_inputs"].items()},
        "family_counts": family_counts,
        "equal_family_rate_totals_hz": equal_mass_totals,
        "profiles": {
            profile_id: {
                "node_counts": profile["node_counts"],
                "arms": {arm: stable_arm(value) for arm, value in profile["arms"].items()},
            }
            for profile_id, profile in profile_results.items()
        },
        "checks": checks,
    }
    semantic_hash = _canonical_hash(semantic)
    result = {
        "schema_version": 1,
        "id": "runner_result.basal_source_bridge_mechanics.v0",
        "campaign_id": campaign["id"],
        "status": "accepted_source_bridge_mechanics_three_arms_two_assignment_extremes_zero_promotion",
        "completed_at": datetime.now(UTC).isoformat(),
        "command": "basal_source_bridges.bat",
        "claim_label": campaign["claim_label"],
        "backend": device,
        "source_accounting": {
            "family_counts": family_counts,
            "family_count": len(family_counts),
            "terminal_count": len(source_rows),
            "event_candidate_bridges_compiled": len(source_rows),
            "graded_candidate_bridges_compiled": len(source_rows),
        },
        "diagnostic_fixture_boundary": campaign["diagnostic_execution"],
        "equal_family_rate_totals_hz": equal_mass_totals,
        "profiles": profile_results,
        "checks": checks,
        "scientific_boundary": {
            "source_bridge_forms_implemented": 2,
            "sensitivity_arms_executed": 3,
            "assignment_profiles_executed": 2,
            "population_assignments_promoted": 0,
            "parameter_values_promoted": 0,
            "physiological_basal_values_selected": 0,
            "behavior_targets_exposed": 0,
        },
        "reproducibility_boundary": {
            "semantic_hash_includes": [
                "frozen_input_hashes",
                "complete_source_and_family_accounting",
                "rate_shape_summaries",
                "seeded_candidate_event_schedule_hashes",
                "source_port_counts_and_runtime_gates",
                "promotion_and_behavior_exposure_gates",
            ],
            "semantic_hash_excludes": [
                "elapsed_seconds",
                "steps_per_second",
                "peak_gpu_bytes",
                "raw_cuda_state_bytes",
                "raw_runtime_state_magnitudes",
            ],
        },
        "semantic_result_sha256": semantic_hash,
        "next_action": (
            "Replace diagnostic source-scale fixtures with independently sourced or bounded parameter "
            "ensembles per basal family, retain both event and graded candidates where assignment remains "
            "dual-unresolved, then propagate the finite ensemble into the first local sensor-CNS-motor chain."
        ),
    }
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.basal_source_bridge_mechanics.v0",
        "campaign_id": campaign["id"],
        "status": "accepted_mechanics_only_basal_values_and_population_assignments_unresolved",
        "conclusion": (
            "All 6,041 basal terminals now compile through explicit event-process and bounded Hz-to-graded "
            "candidate bridges. All three preregistered low-capacity shapes execute under both diagnostic "
            "assignment extremes with complete accounting, finite state and no named behavior. The fixture "
            "rates, saturation scale and neuronal assignments are unpromotable engineering probes, so this "
            "does not calibrate basal activity or select population dynamics."
        ),
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "checks": checks,
        "runner_semantic_sha256": semantic_hash,
        "next_action": result["next_action"],
    }

    print("[7/8] Writing compact versioned result and ignored diagnostic trace", flush=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    evaluation_path.parent.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    result_path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    evaluation_path.write_text(
        yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    (output_root / "summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8"
    )
    print("[8/8] Accepted: bridge mechanics closed; basal values and assignments remain unresolved", flush=True)
    print(f"Semantic result SHA-256: {semantic_hash}", flush=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute basal source bridge mechanics sentinel")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--result", type=Path, default=RESULT_PATH)
    parser.add_argument("--evaluation", type=Path, default=EVALUATION_PATH)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    run_source_bridge_mechanics(args.campaign, args.result, args.evaluation, args.output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

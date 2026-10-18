from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml
from scipy import sparse

from .ledger import ROOT


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "first-held-out-execution-preflight-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "first-held-out-execution-preflight-v0.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "first-held-out-execution-preflight-v0.yaml"
OUTPUT_ROOT = ROOT / "data" / "derived" / "calibration" / "first-held-out-execution-preflight-v0"


class HeldOutPreflightError(RuntimeError):
    """Raised when the locked FH-09 execution contract loses an invariant."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HeldOutPreflightError(f"{path} must contain a YAML mapping")
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


def _verify_frozen_inputs(campaign: Mapping[str, Any]) -> dict[str, Path]:
    if campaign.get("primary_class") != "evaluation_only":
        raise HeldOutPreflightError("FH-09 preflight must remain evaluation_only")
    if campaign.get("optimization_exposure") != "forbidden":
        raise HeldOutPreflightError("FH-09 preflight cannot expose outcomes to optimization")
    if int(campaign.get("outcome_rows_consumed", -1)) != 0:
        raise HeldOutPreflightError("FH-09 preflight must consume zero held-out rows")
    if campaign.get("members_ranked") is not False:
        raise HeldOutPreflightError("FH-09 preflight cannot rank FH-07 members")

    paths: dict[str, Path] = {}
    for key, record in campaign["frozen_inputs"].items():
        path = ROOT / str(record["path"])
        if not path.is_file():
            raise HeldOutPreflightError(f"missing frozen input {key}: {path}")
        observed = _sha256(path)
        expected = str(record["sha256"])
        if observed != expected:
            raise HeldOutPreflightError(
                f"frozen input drift for {key}: {observed} != {expected}"
            )
        paths[key] = path
    return paths


def _load_cone(paths: Mapping[str, Path]) -> tuple[np.ndarray, sparse.csr_matrix, np.ndarray]:
    members = pd.read_csv(paths["population_members"])
    sensory = members.loc[members["population_id"].eq("population.front_leg_feco.v0")]
    motor = members.loc[
        members["population_id"].eq("population.front_leg_tibia_flexor_motor.v0")
    ]
    classified = pd.read_csv(paths["classified_intermediates"])
    cone_ids = sorted(
        set(sensory["body_id"].astype(int))
        | set(motor["body_id"].astype(int))
        | set(classified["body_id"].astype(int))
    )
    if (len(sensory), len(classified), len(motor), len(cone_ids)) != (36, 150, 10, 196):
        raise HeldOutPreflightError("196-neuron cone accounting drift")

    nodes = pd.read_parquet(paths["central_nodes"])
    rows = nodes.loc[nodes["body_id"].astype(int).isin(cone_ids)].copy()
    rows = rows.sort_values("runtime_node_index").reset_index(drop=True)
    if len(rows) != 196 or rows["body_id"].nunique() != 196:
        raise HeldOutPreflightError("canonical node index does not resolve the cone")
    runtime_indices = rows["runtime_node_index"].to_numpy(np.int64)
    body_ids = rows["body_id"].to_numpy(np.int64)
    full = sparse.load_npz(paths["incoming_graph"]).tocsr()
    incoming = full[runtime_indices][:, runtime_indices].tocsr()

    prior = pd.read_parquet(paths["transmitter_prior"])
    prior = prior.set_index(prior["body_id"].astype(int))
    if any(int(body_id) not in prior.index for body_id in body_ids):
        raise HeldOutPreflightError("transmitter prior does not cover the cone")
    transmitters = np.asarray(
        [str(prior.loc[int(body_id), "effective_transmitter"]) for body_id in body_ids],
        dtype=object,
    )
    return body_ids, incoming, transmitters


def graph_semantic_hash(graph: sparse.spmatrix, body_ids: np.ndarray) -> str:
    coo = graph.tocoo()
    records = sorted(
        (int(body_ids[source]), int(body_ids[target]), float(weight))
        for target, source, weight in zip(coo.row, coo.col, coo.data, strict=True)
    )
    return _canonical_hash(records)


def deterministic_stratified_rewire(
    graph: sparse.spmatrix,
    *,
    body_ids: np.ndarray,
    source_transmitters: np.ndarray,
    seed: int,
    accepted_swap_target: int,
    maximum_attempts: int,
) -> tuple[sparse.csr_matrix, dict[str, Any]]:
    """Rewire targets by directed double-edge swaps within transmitter/weight strata."""

    coo = graph.tocoo()
    sources = coo.col.astype(np.int64, copy=True)
    targets = coo.row.astype(np.int64, copy=True)
    weights = coo.data.astype(np.float64, copy=True)
    if len(set(zip(sources.tolist(), targets.tolist(), strict=True))) != len(weights):
        raise HeldOutPreflightError("scoped sparse graph unexpectedly contains duplicate edges")

    strata: dict[tuple[str, float], list[int]] = defaultdict(list)
    for index, (source, weight) in enumerate(zip(sources, weights, strict=True)):
        strata[(str(source_transmitters[source]), float(weight))].append(index)
    eligible = [np.asarray(indexes, dtype=np.int64) for indexes in strata.values() if len(indexes) >= 2]
    if not eligible:
        raise HeldOutPreflightError("no transmitter/weight stratum supports a swap")

    canonical_pairs = set(zip(sources.tolist(), targets.tolist(), strict=True))
    current_pairs = set(canonical_pairs)
    canonical_self_loops = {pair for pair in canonical_pairs if pair[0] == pair[1]}
    rng = np.random.default_rng(int(seed))
    accepted = 0
    attempts = 0
    while accepted < accepted_swap_target and attempts < maximum_attempts:
        attempts += 1
        group = eligible[int(rng.integers(0, len(eligible)))]
        left, right = rng.choice(group, size=2, replace=False)
        left = int(left)
        right = int(right)
        source_left, source_right = int(sources[left]), int(sources[right])
        target_left, target_right = int(targets[left]), int(targets[right])
        if source_left == source_right or target_left == target_right:
            continue
        old_left = (source_left, target_left)
        old_right = (source_right, target_right)
        new_left = (source_left, target_right)
        new_right = (source_right, target_left)
        if new_left == new_right or new_left in (old_left, old_right) or new_right in (old_left, old_right):
            continue
        if new_left[0] == new_left[1] and new_left not in canonical_self_loops:
            continue
        if new_right[0] == new_right[1] and new_right not in canonical_self_loops:
            continue
        current_pairs.remove(old_left)
        current_pairs.remove(old_right)
        if new_left in current_pairs or new_right in current_pairs:
            current_pairs.add(old_left)
            current_pairs.add(old_right)
            continue
        current_pairs.add(new_left)
        current_pairs.add(new_right)
        targets[left], targets[right] = target_right, target_left
        accepted += 1

    if accepted < accepted_swap_target:
        raise HeldOutPreflightError(
            f"seed {seed} accepted only {accepted}/{accepted_swap_target} swaps in {attempts} attempts"
        )
    rewired = sparse.csr_matrix((weights, (targets, sources)), shape=graph.shape)
    rewired.sort_indices()

    canonical_csr = graph.tocsr()
    canonical_out = np.asarray((canonical_csr != 0).sum(axis=0)).ravel()
    rewired_out = np.asarray((rewired != 0).sum(axis=0)).ravel()
    canonical_in = np.asarray((canonical_csr != 0).sum(axis=1)).ravel()
    rewired_in = np.asarray((rewired != 0).sum(axis=1)).ravel()
    if not np.array_equal(canonical_out, rewired_out) or not np.array_equal(canonical_in, rewired_in):
        raise HeldOutPreflightError("directed degree changed during rewire")
    if sorted(map(float, canonical_csr.data)) != sorted(map(float, rewired.data)):
        raise HeldOutPreflightError("weight multiset changed during rewire")
    changed_edges = len(canonical_pairs.symmetric_difference(current_pairs))
    summary = {
        "seed": int(seed),
        "attempts": attempts,
        "accepted_swaps": accepted,
        "changed_directed_edges_symmetric_difference": changed_edges,
        "nodes": int(graph.shape[0]),
        "edges": int(graph.nnz),
        "exact_in_degree_preserved": True,
        "exact_out_degree_preserved": True,
        "exact_weight_multiset_preserved": True,
        "new_self_loops": len(
            {pair for pair in current_pairs if pair[0] == pair[1]} - canonical_self_loops
        ),
        "duplicate_edges": int(rewired.nnz != len(current_pairs)),
    }
    return rewired, summary


def build_execution_schedule(
    protocol: Mapping[str, Any],
    scenario_namespace: str = "heldout.proprio.resistance.v0",
) -> pd.DataFrame:
    topology_variants: list[dict[str, Any]] = [
        {
            "topology_variant": "canonical",
            "topology_family": "canonical",
            "rewire_seed": "",
            "parameter_disposition": "frozen_canonical_member",
        }
    ]
    for seed in protocol["topology_controls"]["rewire_seeds"]:
        topology_variants.extend(
            [
                {
                    "topology_variant": f"rewire-{seed}-frozen",
                    "topology_family": "frozen_parameter_rewire",
                    "rewire_seed": int(seed),
                    "parameter_disposition": "canonical_values_frozen_on_rewire",
                },
                {
                    "topology_variant": f"rewire-{seed}-recalibrated",
                    "topology_family": "same_recipe_recalibrated_rewire",
                    "rewire_seed": int(seed),
                    "parameter_disposition": "same_recipe_recalibration_pending",
                },
            ]
        )

    rows: list[dict[str, Any]] = []
    for topology in topology_variants:
        for member_id in protocol["frozen_lineage"]["member_ids"]:
            for side in protocol["stimulus"]["sides"]:
                for condition in ("stimulus", "sham"):
                    for seed in protocol["replication"]["paired_trial_seeds"]:
                        scenario_id = (
                            f"{scenario_namespace}/{topology['topology_variant']}/"
                            f"{member_id}/{side}/{condition}/seed-{seed}"
                        )
                        rows.append(
                            {
                                "scenario_id": scenario_id,
                                **topology,
                                "member_id": str(member_id),
                                "side": str(side),
                                "condition": condition,
                                "trial_seed": int(seed),
                                "outcome_status": "not_executed_outcome_blind_preflight",
                            }
                        )
    return pd.DataFrame(rows)


def native_response_effect(
    stimulus: np.ndarray,
    sham: np.ndarray,
    *,
    event_mask: np.ndarray,
) -> dict[str, np.ndarray]:
    """Keep event counts and graded-state integrals separate as locked by v0."""

    stimulus = np.asarray(stimulus, dtype=np.float64)
    sham = np.asarray(sham, dtype=np.float64)
    event_mask = np.asarray(event_mask, dtype=bool)
    if stimulus.shape != sham.shape or stimulus.ndim != 2:
        raise HeldOutPreflightError("stimulus and sham must be matching time-by-neuron arrays")
    if event_mask.shape != (stimulus.shape[1],):
        raise HeldOutPreflightError("event mask does not match the measured population")
    delta = stimulus - sham
    return {
        "event_count_delta": delta[:, event_mask].sum(axis=0),
        "graded_state_integral_delta": delta[:, ~event_mask].sum(axis=0),
    }


def write_jsonl_exclusive(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    """Create an outcome shard once; refusing overwrite makes inspection append-only."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(dict(row), sort_keys=True, allow_nan=False) + "\n")


def _timebase_report(protocol: Mapping[str, Any], timestep_s: float) -> dict[str, Any]:
    stimulus = protocol["stimulus"]
    tolerance = float(stimulus["implementation_tolerance"]["duration_abs_s"])
    report: dict[str, Any] = {"physics_timestep_s": timestep_s, "duration_tolerance_s": tolerance}
    all_exact = True
    for key in ("baseline_duration_s", "ramp_duration_s", "post_release_observation_s", "total_duration_s"):
        requested = float(stimulus[key])
        steps = int(round(requested / timestep_s))
        represented = steps * timestep_s
        error = abs(represented - requested)
        report[key] = {
            "requested_s": requested,
            "nearest_steps": steps,
            "represented_s": represented,
            "absolute_error_s": error,
            "within_locked_tolerance": error <= tolerance,
        }
        all_exact &= error <= tolerance
    report["all_locked_durations_representable"] = all_exact
    return report


def run_preflight(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    campaign_path = (
        campaign_path if campaign_path.is_absolute() else ROOT / campaign_path
    )
    result_path = result_path if result_path.is_absolute() else ROOT / result_path
    evaluation_path = evaluation_path if evaluation_path.is_absolute() else ROOT / evaluation_path
    output_root = output_root if output_root.is_absolute() else ROOT / output_root
    print("[1/8] Verifying the outcome-blind FH-09 contract and frozen inputs", flush=True)
    campaign = _load_yaml(campaign_path)
    paths = _verify_frozen_inputs(campaign)
    protocol = _load_yaml(paths["protocol"])
    if protocol["execution_gate"]["outcome_rows_present"] != 0:
        raise HeldOutPreflightError("protocol already reports held-out outcomes")

    print("[2/8] Reconstructing the frozen 196-neuron chemical cone", flush=True)
    body_ids, canonical, transmitters = _load_cone(paths)
    canonical_hash = graph_semantic_hash(canonical, body_ids)
    output_root.mkdir(parents=True, exist_ok=True)
    sparse.save_npz(output_root / "canonical-cone.npz", canonical)

    print("[3/8] Materializing four deterministic rewires and both control families", flush=True)
    topology_root = output_root / "topology-controls"
    topology_root.mkdir(parents=True, exist_ok=True)
    topology_records: list[dict[str, Any]] = []
    rewire_config = campaign["rewire_execution"]
    for seed in protocol["topology_controls"]["rewire_seeds"]:
        rewired, summary = deterministic_stratified_rewire(
            canonical,
            body_ids=body_ids,
            source_transmitters=transmitters,
            seed=int(seed),
            accepted_swap_target=int(rewire_config["accepted_swaps_per_graph"]),
            maximum_attempts=int(rewire_config["maximum_attempts_per_graph"]),
        )
        semantic_hash = graph_semantic_hash(rewired, body_ids)
        if semantic_hash == canonical_hash:
            raise HeldOutPreflightError(f"seed {seed} produced an unchanged topology hash")
        for family in ("frozen", "recalibrated"):
            artifact = topology_root / f"rewire-{seed}-{family}.npz"
            sparse.save_npz(artifact, rewired)
            topology_records.append(
                {
                    "topology_variant": f"rewire-{seed}-{family}",
                    "rewire_seed": int(seed),
                    "control_family": (
                        "frozen_parameter_rewire"
                        if family == "frozen"
                        else "same_recipe_recalibrated_rewire"
                    ),
                    "artifact": artifact.relative_to(ROOT).as_posix(),
                    "artifact_sha256": _sha256(artifact),
                    "semantic_topology_sha256": semantic_hash,
                    **summary,
                }
            )

    print("[4/8] Compiling and accounting the exact 3,168-scenario schedule", flush=True)
    schedule = build_execution_schedule(
        protocol,
        str(campaign.get("scenario_namespace", "heldout.proprio.resistance.v0")),
    )
    expected_rows = int(campaign["schedule_execution"]["expected_rows"])
    if len(schedule) != expected_rows or schedule["scenario_id"].nunique() != expected_rows:
        raise HeldOutPreflightError("execution schedule is not exactly unique and exhaustive")
    schedule_path = output_root / "execution-schedule.csv"
    schedule.to_csv(schedule_path, index=False, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")

    print("[5/8] Checking native-class measurement and append-only result mechanics", flush=True)
    probe = np.arange(24, dtype=np.float64).reshape(4, 6)
    effects = native_response_effect(probe, np.zeros_like(probe), event_mask=np.array([1, 0, 1, 0, 1, 0], dtype=bool))
    measurement_ok = effects["event_count_delta"].shape == (3,) and effects["graded_state_integral_delta"].shape == (3,)
    with tempfile.TemporaryDirectory(
        dir=output_root, prefix="append-only-mechanics-"
    ) as directory:
        destination = Path(directory) / "outcomes.jsonl"
        write_jsonl_exclusive(destination, [{"scenario_id": "mechanics-only"}])
        overwrite_refused = False
        try:
            write_jsonl_exclusive(destination, [{"scenario_id": "forbidden-overwrite"}])
        except FileExistsError:
            overwrite_refused = True
    if not measurement_ok or not overwrite_refused:
        raise HeldOutPreflightError("measurement or append-only result mechanic failed")

    print("[6/8] Auditing locked timing against the frozen MuJoCo timebase", flush=True)
    timebase = _timebase_report(
        protocol, float(campaign["runtime_contract"]["frozen_physics_timestep_s"])
    )

    print("[7/8] Evaluating execution readiness without running an outcome", flush=True)
    seed_pairs_match = all(
        len({row["semantic_topology_sha256"] for row in topology_records if row["rewire_seed"] == seed}) == 1
        for seed in protocol["topology_controls"]["rewire_seeds"]
    )
    checks = {
        "held_out_outcomes_consumed_zero": True,
        "eight_topology_control_artifacts_materialized": len(topology_records) == 8,
        "all_rewires_have_at_least_ten_accepted_swaps": all(
            row["accepted_swaps"] >= 10 for row in topology_records
        ),
        "all_rewires_change_semantic_topology": all(
            row["semantic_topology_sha256"] != canonical_hash for row in topology_records
        ),
        "seeded_control_pairs_share_exact_topology": seed_pairs_match,
        "directed_degrees_and_weight_multisets_preserved": all(
            row["exact_in_degree_preserved"]
            and row["exact_out_degree_preserved"]
            and row["exact_weight_multiset_preserved"]
            for row in topology_records
        ),
        "no_new_self_loop_or_duplicate": all(
            row["new_self_loops"] == 0 and row["duplicate_edges"] == 0
            for row in topology_records
        ),
        "schedule_exactly_3168_unique_rows": len(schedule) == schedule["scenario_id"].nunique() == 3168,
        "every_member_side_condition_seed_topology_accounted": (
            schedule["member_id"].nunique() == 11
            and schedule["side"].nunique() == 2
            and schedule["condition"].nunique() == 2
            and schedule["trial_seed"].nunique() == 8
            and schedule["topology_variant"].nunique() == 9
        ),
        "native_representations_kept_separate": measurement_ok,
        "append_only_writer_refuses_overwrite": overwrite_refused,
        "locked_timing_representable_on_frozen_timebase": bool(
            timebase["all_locked_durations_representable"]
        ),
    }
    non_timing_checks = {key: value for key, value in checks.items() if key != "locked_timing_representable_on_frozen_timebase"}
    if not all(non_timing_checks.values()):
        raise HeldOutPreflightError(
            f"preflight invariant failed: {[key for key, value in non_timing_checks.items() if not value]}"
        )
    execution_ready = all(checks.values())
    protocol_version = str(protocol["id"]).rsplit(".", maxsplit=1)[-1]

    result = {
        "schema_version": 1,
        "id": campaign.get(
            "result_id", "runner_result.first_held_out_execution_preflight.v0"
        ),
        "campaign_id": str(campaign["id"]),
        "protocol_id": str(protocol["id"]),
        "status": (
            "accepted_preflight_execution_ready"
            if execution_ready
            else "accepted_materialization_execution_blocked_by_locked_timebase_mismatch"
        ),
        "completed_at": datetime.now(UTC).isoformat(),
        "command": campaign.get("command", "first_held_out_execution_preflight.bat"),
        "claim_label": str(campaign["claim_label"]),
        "frozen_input_sha256": {key: _sha256(path) for key, path in paths.items()},
        "held_out_outcomes_consumed": 0,
        "members_ranked": False,
        "selected_reference_member_id": None,
        "canonical_graph": {
            "nodes": int(canonical.shape[0]),
            "edges": int(canonical.nnz),
            "semantic_topology_sha256": canonical_hash,
            "artifact": (output_root / "canonical-cone.npz").relative_to(ROOT).as_posix(),
            "artifact_sha256": _sha256(output_root / "canonical-cone.npz"),
        },
        "topology_controls": topology_records,
        "schedule": {
            "rows": len(schedule),
            "unique_scenarios": int(schedule["scenario_id"].nunique()),
            "topology_variants": int(schedule["topology_variant"].nunique()),
            "canonical_rows": int(schedule["topology_family"].eq("canonical").sum()),
            "frozen_rewire_rows": int(schedule["topology_family"].eq("frozen_parameter_rewire").sum()),
            "recalibrated_rewire_rows": int(schedule["topology_family"].eq("same_recipe_recalibrated_rewire").sum()),
            "artifact": schedule_path.relative_to(ROOT).as_posix(),
            "artifact_sha256": _sha256(schedule_path),
            "semantic_sha256": _canonical_hash(schedule.to_dict(orient="records")),
        },
        "timebase": timebase,
        "checks": checks,
        "execution_ready": execution_ready,
        "blocking_reasons": (
            []
            if execution_ready
            else [
                "One or more locked durations cannot be represented within tolerance "
                "on the frozen physical time step."
            ]
        ),
        "accepted_claims": [
            "All eight locked topology-control artifacts and all 3,168 outcome-blind schedule rows are reproducibly materialized.",
            "The preflight consumes zero held-out outcomes and selects no FH-07 member.",
        ],
        "forbidden_claims": [
            "This preflight demonstrates a proprioceptive response or any biological behavior.",
            "A rounded timing may silently replace the immutable protocol.",
        ],
        "next_action": (
            f"Execute FH-09 once without changing protocol {protocol_version}."
            if execution_ready
            else "Before any outcome, register a superseding protocol whose waveform is exactly representable on the frozen physical timebase, or version an independently justified timebase change; never round v0 silently."
        ),
    }
    semantic_payload = {
        key: value
        for key, value in result.items()
        if key not in {"completed_at", "semantic_result_sha256"}
    }
    result["semantic_result_sha256"] = _canonical_hash(semantic_payload)

    print("[8/8] Writing compact result and evaluation records", flush=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    evaluation = {
        "schema_version": 1,
        "id": campaign.get(
            "evaluation_id", "evaluation.first_held_out_execution_preflight.v0"
        ),
        "title": "Outcome-blind FH-09 execution readiness",
        "status": result["status"],
        "protocol_id": str(protocol["id"]),
        "primary_class": "evaluation_only",
        "outcome_rows_consumed": 0,
        "result_ref": result_path.relative_to(ROOT).as_posix(),
        "semantic_result_sha256": result["semantic_result_sha256"],
        "checks": checks,
        "timebase": timebase,
        "interpretation": (
            "Topology controls, scenario accounting, native-measure separation and append-only storage are ready. "
            + (
                "The immutable waveform timing is exactly representable on the frozen physical time step."
                if execution_ready
                else (
                    "Execution remains blocked because the immutable waveform timing "
                    "is not representable within its own tolerance on the frozen "
                    "physical time step."
                )
            )
        ),
        "next_action": result["next_action"],
    }
    evaluation_path.parent.mkdir(parents=True, exist_ok=True)
    evaluation_path.write_text(
        yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    print(
        f"[RESULT] controls=8 schedule={len(schedule)} outcomes=0 ready={execution_ready} semantic={result['semantic_result_sha256']}",
        flush=True,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize the outcome-blind FH-09 execution gate")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--result", type=Path, default=RESULT_PATH)
    parser.add_argument("--evaluation", type=Path, default=EVALUATION_PATH)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    run_preflight(args.campaign, args.result, args.evaluation, args.output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

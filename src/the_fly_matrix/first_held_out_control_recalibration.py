from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import numpy as np
import yaml
from scipy import sparse

from . import front_leg_coupled_identifiability_execution as fh05
from . import front_leg_integrated_lineage as fh06
from . import front_leg_neutral_embodied_regime as fh07b
from . import front_leg_neutral_neural_regime as fh07a
from .ledger import ROOT


CAMPAIGN_PATH = (
    ROOT
    / "calibration"
    / "campaigns"
    / "first-held-out-control-recalibration-v1.yaml"
)
RESULT_PATH = (
    ROOT
    / "calibration"
    / "runner"
    / "first-held-out-control-recalibration-v1.yaml"
)
EVALUATION_PATH = (
    ROOT
    / "calibration"
    / "evaluations"
    / "first-held-out-control-recalibration-v1.yaml"
)
PARAMETER_SET_PATH = (
    ROOT
    / "calibration"
    / "parameter_sets"
    / "first-held-out-recalibrated-topology-controls-v1.yaml"
)
RUN_ROOT = (
    ROOT
    / "runs"
    / "calibration"
    / "first-held-out-control-recalibration-v1"
)


class HeldOutControlRecalibrationError(RuntimeError):
    """Raised when an outcome-blind topology-control calibration loses its contract."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HeldOutControlRecalibrationError(f"{path} must contain a YAML mapping")
    return value


def _write_yaml(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(dict(value), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _verify_frozen_inputs(campaign: Mapping[str, Any]) -> dict[str, Path]:
    if campaign.get("primary_class") != "technical":
        raise HeldOutControlRecalibrationError("control recalibration must remain technical")
    if campaign.get("optimization_exposure") != "allowed_nonbehavioral_only":
        raise HeldOutControlRecalibrationError(
            "control recalibration must forbid held-out exposure"
        )
    if campaign.get("behavior_targets") != []:
        raise HeldOutControlRecalibrationError("control recalibration names a behavior target")
    if int(campaign.get("held_out_outcome_rows_consumed", -1)) != 0:
        raise HeldOutControlRecalibrationError(
            "control recalibration must consume zero held-out outcomes"
        )

    paths: dict[str, Path] = {}
    for name, record in campaign["frozen_inputs"].items():
        path = ROOT / str(record["path"])
        if not path.is_file():
            raise HeldOutControlRecalibrationError(f"missing frozen input {name}: {path}")
        observed = _sha256(path)
        if observed != str(record["sha256"]):
            raise HeldOutControlRecalibrationError(
                f"frozen input drift for {name}: {observed} != {record['sha256']}"
            )
        paths[str(name)] = path
    return paths


def replace_cone_recurrence(
    graph: sparse.spmatrix,
    *,
    source_count: int,
    canonical_cone: sparse.spmatrix,
    replacement_cone: sparse.spmatrix,
) -> sparse.csr_matrix:
    """Replace only cone recurrence while preserving all external source ports."""

    base = graph.tocsr()
    canonical = canonical_cone.tocsr()
    replacement = replacement_cone.tocsr()
    cone_count = base.shape[0] - int(source_count)
    if base.shape[0] != base.shape[1] or cone_count <= 0:
        raise HeldOutControlRecalibrationError("boundary graph is not square")
    expected_shape = (cone_count, cone_count)
    if canonical.shape != expected_shape or replacement.shape != expected_shape:
        raise HeldOutControlRecalibrationError(
            f"cone shape drift: expected {expected_shape}, got "
            f"canonical={canonical.shape}, replacement={replacement.shape}"
        )
    observed = base[source_count:, source_count:].tocsr()
    if (observed != canonical).nnz:
        raise HeldOutControlRecalibrationError(
            "runtime context recurrence no longer matches the frozen canonical cone"
        )
    zero_ss = sparse.csr_matrix((source_count, source_count), dtype=base.dtype)
    zero_sc = sparse.csr_matrix((source_count, cone_count), dtype=base.dtype)
    source_to_cone = base[source_count:, :source_count].tocsr()
    replaced = sparse.bmat(
        [[zero_ss, zero_sc], [source_to_cone, replacement]],
        format="csr",
    )
    replaced.sort_indices()
    return replaced


def _replace_context_graph(
    context: Mapping[str, Any],
    *,
    canonical_cone: sparse.spmatrix,
    replacement_cone: sparse.spmatrix,
) -> dict[str, Any]:
    updated = dict(context)
    source_count = int(context["source_count"])
    graph = replace_cone_recurrence(
        context["graph"],
        source_count=source_count,
        canonical_cone=canonical_cone,
        replacement_cone=replacement_cone,
    )
    updated["graph"] = graph
    summary = dict(context.get("graph_summary", {}))
    summary["cone_recurrent_edges"] = int(replacement_cone.nnz)
    summary["total_edges"] = int(graph.nnz)
    summary["topology_control_override"] = True
    updated["graph_summary"] = summary
    return updated


@contextlib.contextmanager
def _topology_override(
    canonical_cone: sparse.csr_matrix,
    replacement_cone: sparse.csr_matrix,
) -> Iterator[None]:
    """Inject one explicit control topology into unchanged FH-05--FH-07 recipes."""

    original_build = fh05.build_boundary_graph
    original_context = fh06._fh05_runtime_context
    original_neural_context = fh07a._fh05_runtime_context
    original_embodied_context = fh07b._fh05_runtime_context

    def build_boundary_graph_override(
        incoming_full: sparse.csr_matrix,
        source_positions: np.ndarray,
        cone_positions: np.ndarray,
    ) -> tuple[sparse.csr_matrix, dict[str, Any]]:
        graph, summary = original_build(incoming_full, source_positions, cone_positions)
        graph = replace_cone_recurrence(
            graph,
            source_count=len(source_positions),
            canonical_cone=canonical_cone,
            replacement_cone=replacement_cone,
        )
        summary = dict(summary)
        summary["cone_recurrent_edges"] = int(replacement_cone.nnz)
        summary["total_edges"] = int(graph.nnz)
        summary["topology_control_override"] = True
        return graph, summary

    def context_override(
        campaign: Mapping[str, Any], verified: Mapping[str, Any]
    ) -> dict[str, Any]:
        return _replace_context_graph(
            original_context(campaign, verified),
            canonical_cone=canonical_cone,
            replacement_cone=replacement_cone,
        )

    fh05.build_boundary_graph = build_boundary_graph_override
    fh06._fh05_runtime_context = context_override
    fh07a._fh05_runtime_context = context_override
    fh07b._fh05_runtime_context = context_override
    try:
        yield
    finally:
        fh05.build_boundary_graph = original_build
        fh06._fh05_runtime_context = original_context
        fh07a._fh05_runtime_context = original_neural_context
        fh07b._fh05_runtime_context = original_embodied_context


def _replace_input(
    campaign: dict[str, Any],
    name: str,
    path: Path,
    *,
    semantic_sha256: str | None = None,
) -> None:
    record = dict(campaign["frozen_inputs"][name])
    record["path"] = _relative(path)
    record["sha256"] = _sha256(path)
    if semantic_sha256 is not None:
        record["semantic_sha256"] = str(semantic_sha256)
    campaign["frozen_inputs"][name] = record


def _run_one_control(
    *,
    seed: int,
    canonical_cone: sparse.csr_matrix,
    replacement_cone: sparse.csr_matrix,
    run_root: Path,
) -> dict[str, Any]:
    seed_root = run_root / f"rewire-{seed}"
    seed_root.mkdir(parents=True, exist_ok=False)

    fh05_result_path = seed_root / "fh05-result.yaml"
    fh05_evaluation_path = seed_root / "fh05-evaluation.yaml"
    fh05_parameter_path = seed_root / "fh05-parameters.yaml"
    fh05_output_root = seed_root / "fh05-diagnostics"
    fh06_campaign_path = seed_root / "fh06-campaign.yaml"
    fh06_result_path = seed_root / "fh06-result.yaml"
    fh06_evaluation_path = seed_root / "fh06-evaluation.yaml"
    fh06_parameter_path = seed_root / "fh06-parameters.yaml"
    fh06_run_root = seed_root / "fh06-run"
    fh07a_campaign_path = seed_root / "fh07a-campaign.yaml"
    fh07a_result_path = seed_root / "fh07a-result.yaml"
    fh07a_evaluation_path = seed_root / "fh07a-evaluation.yaml"
    fh07a_parameter_path = seed_root / "fh07a-parameters.yaml"
    fh07b_campaign_path = seed_root / "fh07b-campaign.yaml"
    fh07b_result_path = seed_root / "fh07b-result.yaml"
    fh07b_evaluation_path = seed_root / "fh07b-evaluation.yaml"
    fh07b_parameter_path = seed_root / "fh07b-parameters.yaml"

    print(f"[CONTROL {seed}] FH-05 exact owner-separated recipe", flush=True)
    fh05_result = fh05.run_execution(
        result_path=fh05_result_path,
        evaluation_path=fh05_evaluation_path,
        parameter_set_path=fh05_parameter_path,
        output_root=fh05_output_root,
    )

    fh06_campaign = _load_yaml(fh06.CAMPAIGN_PATH)
    _replace_input(fh06_campaign, "coupled_result", fh05_result_path)
    _replace_input(
        fh06_campaign,
        "coupled_ensemble",
        fh05_parameter_path,
    )
    _write_yaml(fh06_campaign_path, fh06_campaign)
    print(f"[CONTROL {seed}] FH-06 exact factorization and causal witness", flush=True)
    fh06_result = fh06.run_integrated_lineage(
        campaign_path=fh06_campaign_path,
        result_path=fh06_result_path,
        evaluation_path=fh06_evaluation_path,
        parameter_set_path=fh06_parameter_path,
        run_root=fh06_run_root,
    )

    fh07a_campaign = _load_yaml(fh07a.CAMPAIGN_PATH)
    _replace_input(fh07a_campaign, "fh06_campaign", fh06_campaign_path)
    _replace_input(
        fh07a_campaign,
        "fh06_result",
        fh06_result_path,
        semantic_sha256=str(fh06_result["semantic_result_sha256"]),
    )
    _write_yaml(fh07a_campaign_path, fh07a_campaign)
    print(f"[CONTROL {seed}] FH-07a exact neural technical recipe", flush=True)
    fh07a_result = fh07a.run_gate(
        campaign_path=fh07a_campaign_path,
        result_path=fh07a_result_path,
        evaluation_path=fh07a_evaluation_path,
        parameter_set_path=fh07a_parameter_path,
    )
    neural_members = list(map(str, fh07a_result.get("accepted_row_ids", [])))
    if not neural_members:
        return {
            "rewire_seed": seed,
            "status": "failed_control_calibration_empty_FH07a",
            "fh05_semantic_sha256": fh05_result["semantic_result_sha256"],
            "fh06_semantic_sha256": fh06_result["semantic_result_sha256"],
            "fh07a_semantic_sha256": fh07a_result["semantic_result_sha256"],
            "fh07a_accepted_members": 0,
            "fh07b_accepted_members": 0,
            "fh07b_member_ids": [],
            "held_out_outcomes_consumed": 0,
        }

    fh07b_campaign = _load_yaml(fh07b.CAMPAIGN_PATH)
    _replace_input(fh07b_campaign, "fh06_campaign", fh06_campaign_path)
    _replace_input(
        fh07b_campaign,
        "fh07a_result",
        fh07a_result_path,
        semantic_sha256=str(fh07a_result["semantic_result_sha256"]),
    )
    _replace_input(fh07b_campaign, "fh07a_parameter_set", fh07a_parameter_path)
    fh07b_campaign["budget"]["expected_neural_parent_rows"] = len(neural_members)
    _write_yaml(fh07b_campaign_path, fh07b_campaign)
    print(f"[CONTROL {seed}] FH-07b exact embodied technical recipe", flush=True)
    fh07b_result = fh07b.run_gate(
        campaign_path=fh07b_campaign_path,
        result_path=fh07b_result_path,
        evaluation_path=fh07b_evaluation_path,
        parameter_set_path=fh07b_parameter_path,
    )
    embodied_members = list(map(str, fh07b_result.get("accepted_row_ids", [])))
    return {
        "rewire_seed": seed,
        "status": (
            "accepted_nonempty_same_recipe_control_ensemble"
            if embodied_members
            else "failed_control_calibration_empty_FH07b"
        ),
        "fh05_semantic_sha256": fh05_result["semantic_result_sha256"],
        "fh06_semantic_sha256": fh06_result["semantic_result_sha256"],
        "fh07a_semantic_sha256": fh07a_result["semantic_result_sha256"],
        "fh07b_semantic_sha256": fh07b_result["semantic_result_sha256"],
        "fh07a_accepted_members": len(neural_members),
        "fh07a_member_ids": neural_members,
        "fh07b_accepted_members": len(embodied_members),
        "fh07b_member_ids": embodied_members,
        "fh07b_failure_counts": fh07b_result.get("failure_counts", {}),
        "held_out_outcomes_consumed": 0,
    }


def run_control_recalibration(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    parameter_set_path: Path = PARAMETER_SET_PATH,
    run_root: Path = RUN_ROOT,
) -> dict[str, Any]:
    campaign_path = campaign_path if campaign_path.is_absolute() else ROOT / campaign_path
    result_path = result_path if result_path.is_absolute() else ROOT / result_path
    evaluation_path = evaluation_path if evaluation_path.is_absolute() else ROOT / evaluation_path
    parameter_set_path = (
        parameter_set_path if parameter_set_path.is_absolute() else ROOT / parameter_set_path
    )
    run_root = run_root if run_root.is_absolute() else ROOT / run_root
    campaign = _load_yaml(campaign_path)
    paths = _verify_frozen_inputs(campaign)
    preflight = _load_yaml(paths["preflight_result"])
    protocol = _load_yaml(paths["protocol"])
    if not bool(preflight.get("execution_ready")):
        raise HeldOutControlRecalibrationError("FH-09 preflight is not execution-ready")
    if int(preflight.get("held_out_outcomes_consumed", -1)) != 0:
        raise HeldOutControlRecalibrationError("preflight has consumed held-out outcomes")

    canonical_path = ROOT / str(preflight["canonical_graph"]["artifact"])
    if _sha256(canonical_path) != str(preflight["canonical_graph"]["artifact_sha256"]):
        raise HeldOutControlRecalibrationError("canonical cone artifact drift")
    canonical = sparse.load_npz(canonical_path).tocsr()
    topology_by_seed: dict[int, Path] = {}
    for row in preflight["topology_controls"]:
        if row["control_family"] != "same_recipe_recalibrated_rewire":
            continue
        seed = int(row["rewire_seed"])
        path = ROOT / str(row["artifact"])
        if _sha256(path) != str(row["artifact_sha256"]):
            raise HeldOutControlRecalibrationError(f"rewire artifact drift for seed {seed}")
        topology_by_seed[seed] = path
    expected_seeds = list(map(int, protocol["topology_controls"]["rewire_seeds"]))
    if sorted(topology_by_seed) != sorted(expected_seeds):
        raise HeldOutControlRecalibrationError("rewire seed accounting drift")

    if run_root.exists():
        raise HeldOutControlRecalibrationError(
            f"append-only control run root already exists: {run_root}"
        )
    run_root.mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    try:
        for index, seed in enumerate(expected_seeds, start=1):
            replacement = sparse.load_npz(topology_by_seed[seed]).tocsr()
            print(
                f"[{index}/{len(expected_seeds)}] Replaying the complete nonbehavioral "
                f"FH-05--FH-07 recipe on rewire seed {seed}",
                flush=True,
            )
            with _topology_override(canonical, replacement):
                rows.append(
                    _run_one_control(
                        seed=seed,
                        canonical_cone=canonical,
                        replacement_cone=replacement,
                        run_root=run_root,
                    )
                )
    except Exception:
        # Partial evidence is deliberately retained under runs/ for diagnosis.
        raise

    all_accounted = len(rows) == len(expected_seeds)
    zero_outcomes = all(int(row["held_out_outcomes_consumed"]) == 0 for row in rows)
    nonempty = sum(row["fh07b_accepted_members"] > 0 for row in rows)
    checks = {
        "all_rewire_seeds_accounted": all_accounted,
        "exact_FH05_through_FH07_recipe_executed": all_accounted,
        "held_out_outcomes_consumed_zero": zero_outcomes,
        "members_ranked": False,
        "parameter_values_promoted": 0,
        "failed_control_calibrations_omitted": False,
    }
    if not all(
        value is True
        for key, value in checks.items()
        if key not in {"members_ranked", "parameter_values_promoted", "failed_control_calibrations_omitted"}
    ):
        raise HeldOutControlRecalibrationError(f"control recalibration contract failed: {checks}")
    semantic_payload = {
        "campaign_id": campaign["id"],
        "frozen_input_sha256": {key: _sha256(path) for key, path in paths.items()},
        "preflight_semantic_sha256": preflight["semantic_result_sha256"],
        "rows": rows,
        "checks": checks,
    }
    semantic_hash = _canonical_hash(semantic_payload)
    result = {
        "schema_version": 1,
        "id": "runner_result.first_held_out_control_recalibration.v1",
        "campaign_id": campaign["id"],
        "status": "complete_control_ensembles_accounted_outcome_blind",
        "completed_at": datetime.now(UTC).isoformat(),
        "command": "first_held_out_control_recalibration_v1.bat",
        "claim_label": campaign["claim_label"],
        "frozen_input_sha256": semantic_payload["frozen_input_sha256"],
        "preflight_semantic_sha256": preflight["semantic_result_sha256"],
        "rewire_controls": rows,
        "accounting": {
            "rewire_seeds": len(rows),
            "nonempty_control_ensembles": nonempty,
            "failed_control_calibrations": len(rows) - nonempty,
            "held_out_outcomes_consumed": 0,
        },
        "checks": checks,
        "members_ranked": False,
        "parameter_values_promoted": 0,
        "semantic_result_sha256": semantic_hash,
        "next_action": (
            "Compile a superseding outcome-blind execution schedule from the exact "
            "per-rewire survivor sets before any held-out outcome is run."
        ),
    }
    parameter_set = {
        "schema_version": 1,
        "id": "parameters.first_held_out_recalibrated_topology_controls.v1",
        "status": "accepted_outcome_blind_control_ensembles",
        "primary_class": "technical",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": semantic_hash,
        "ensembles_by_rewire_seed": [
            {
                "rewire_seed": row["rewire_seed"],
                "status": row["status"],
                "member_ids": row["fh07b_member_ids"],
                "member_count": row["fh07b_accepted_members"],
            }
            for row in rows
        ],
        "members_ranked": False,
        "selected_reference_member_id": None,
        "held_out_outcomes_consumed": 0,
        "next_action": result["next_action"],
    }
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.first_held_out_control_recalibration.v1",
        "status": result["status"],
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": semantic_hash,
        "accounting": result["accounting"],
        "checks": checks,
        "interpretation": (
            "Every rewired graph received the same nonbehavioral FH-05--FH-07 "
            "recipes and budgets. The retained sets are topology-control calibration "
            "outputs, not references, and no held-out response was available."
        ),
        "next_action": result["next_action"],
    }
    for path, payload in (
        (result_path, result),
        (evaluation_path, evaluation),
        (parameter_set_path, parameter_set),
    ):
        _write_yaml(path, payload)
    print(
        f"[COMPLETE] rewires={len(rows)} nonempty={nonempty} outcomes=0 "
        f"semantic={semantic_hash}",
        flush=True,
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run outcome-blind same-recipe calibration for FH-09 rewired controls"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--result", type=Path, default=RESULT_PATH)
    parser.add_argument("--evaluation", type=Path, default=EVALUATION_PATH)
    parser.add_argument("--parameter-set", type=Path, default=PARAMETER_SET_PATH)
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    args = parser.parse_args(argv)
    run_control_recalibration(
        campaign_path=args.campaign,
        result_path=args.result,
        evaluation_path=args.evaluation,
        parameter_set_path=args.parameter_set,
        run_root=args.run_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

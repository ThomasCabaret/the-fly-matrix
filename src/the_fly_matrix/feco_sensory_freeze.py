from __future__ import annotations

import hashlib
import itertools
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml

from .feco_calcium_fit import _design_matrix, _metrics, candidates_for, prepare_frame
from .ledger import ROOT


CAMPAIGN_PATH = ROOT / "calibration/campaigns/feco-sensory-ensemble-freeze-v0.yaml"
PARAMETER_SET_PATH = ROOT / "calibration/parameter_sets/front-leg-feco-sensory-ensemble-v0.yaml"
RUNNER_PATH = ROOT / "calibration/runner/feco-sensory-ensemble-freeze-v0.yaml"
EVALUATION_PATH = ROOT / "calibration/evaluations/feco-sensory-ensemble-freeze-v0.yaml"
OUTPUT_PATH = ROOT / "data/derived/calibration/feco-sensory-ensemble-freeze-v0/summary.json"


class FeCOSensoryFreezeError(ValueError):
    """Raised when the scoped sensory ensemble cannot be reconstructed honestly."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FeCOSensoryFreezeError(f"{path} must contain a YAML mapping")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _verify_campaign(campaign: Mapping[str, Any]) -> None:
    if campaign.get("primary_class") != "local_interface":
        raise FeCOSensoryFreezeError("campaign must remain local_interface")
    if campaign.get("behavior_targets") != []:
        raise FeCOSensoryFreezeError("sensory freeze cannot expose behavior targets")
    if campaign.get("topology_changes_allowed") is not False:
        raise FeCOSensoryFreezeError("sensory freeze cannot change topology")
    policy = campaign.get("acceptance_policy", {})
    if policy.get("choose_residual_winner") is not False:
        raise FeCOSensoryFreezeError("calcium residuals cannot choose a winner")
    if policy.get("choose_native_representation") is not False:
        raise FeCOSensoryFreezeError("calcium cannot choose the native representation")


def _verify_crosswalk(crosswalk: Mapping[str, Any], annotations: pd.DataFrame) -> dict[str, Any]:
    selector = crosswalk["scope"]["selector"]
    selected = annotations.copy()
    for column, value in selector.items():
        selected = selected.loc[selected[column].eq(value)]
    counts = {str(key): int(value) for key, value in selected["type"].value_counts().sort_index().items()}
    expected = {
        str(item["type"]): int(item["scoped_bodies"])
        for item in crosswalk["type_assignments"]
    }
    if counts != expected:
        raise FeCOSensoryFreezeError(f"MaleCNS FeCO type accounting drift: {counts!r}")
    if int(len(selected)) != int(crosswalk["scope"]["scoped_bodies"]):
        raise FeCOSensoryFreezeError("MaleCNS FeCO body count drift")
    mapped = [item for item in crosswalk["type_assignments"] if item["functional_class"]]
    unknown = sorted(
        str(item["type"]) for item in crosswalk["type_assignments"] if not item["functional_class"]
    )
    class_counts: dict[str, int] = {}
    for item in mapped:
        key = str(item["functional_class"])
        class_counts[key] = class_counts.get(key, 0) + int(item["scoped_bodies"])
    routing_profiles = [
        {"profile_id": f"routing_{index:02d}", "unknown_type_assignments": dict(zip(unknown, values, strict=True))}
        for index, values in enumerate(itertools.product(("claw", "club", "hook"), repeat=len(unknown)))
    ]
    if len(routing_profiles) != int(crosswalk["uncertainty_policy"]["routing_profiles"]):
        raise FeCOSensoryFreezeError("crosswalk routing profile count drift")
    return {
        "selected_body_ids": sorted(int(value) for value in selected["bodyId"].tolist()),
        "type_counts": counts,
        "mapped_body_counts_by_class": dict(sorted(class_counts.items())),
        "unknown_types": unknown,
        "routing_profiles": routing_profiles,
    }


def _fit_full_dataset(dataset: Mapping[str, Any], retained: set[str]) -> list[dict[str, Any]]:
    path = ROOT / str(dataset["path"])
    if _sha256(path) != str(dataset["sha256"]):
        raise FeCOSensoryFreezeError(f"FeCO table hash drift for {path}")
    prepared = prepare_frame(pd.read_parquet(path), dataset)
    observed = prepared.frame["calcium"].to_numpy(dtype=np.float64)
    results: list[dict[str, Any]] = []
    for candidate in candidates_for(dataset):
        if candidate.candidate_id not in retained:
            continue
        design, parameter_names = _design_matrix(prepared.frame, candidate)
        coefficients, _, rank, _ = np.linalg.lstsq(design, observed, rcond=None)
        if rank != len(parameter_names):
            raise FeCOSensoryFreezeError(f"full-data fit is rank deficient for {candidate.candidate_id}")
        result = {
            "candidate_id": candidate.candidate_id,
            "functional_class": str(dataset["functional_class"]),
            "fit_kind": candidate.fit_kind,
            "sampling_policy": candidate.sampling_policy,
            "grouping_policy": candidate.grouping_policy,
            "source_activation_parameters": {
                "threshold_deg_s": candidate.threshold_deg_s,
                "claw_center_deg": candidate.claw_center_deg,
                "pad_first_sample": candidate.pad_first_sample,
            },
            "observation_space_fit": {
                name: float(value) for name, value in zip(parameter_names, coefficients, strict=True)
            },
            "observation_space_metrics": _metrics(observed, design @ coefficients),
            "native_runtime_amplitude_identified": False,
        }
        results.append(result)
    return results


def run(
    campaign_path: Path = CAMPAIGN_PATH,
    parameter_set_path: Path = PARAMETER_SET_PATH,
    runner_path: Path = RUNNER_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    output_path: Path = OUTPUT_PATH,
) -> dict[str, Any]:
    campaign = _load_yaml(campaign_path)
    _verify_campaign(campaign)
    print("[1/5] Verifying immutable scope, annotation hash and type crosswalk", flush=True)
    crosswalk_path = ROOT / str(campaign["inputs"]["crosswalk"])
    crosswalk = _load_yaml(crosswalk_path)
    annotation_path = ROOT / str(campaign["inputs"]["annotations"])
    if _sha256(annotation_path) != str(campaign["inputs"]["expected_annotation_sha256"]):
        raise FeCOSensoryFreezeError("MaleCNS annotation hash drift")
    routing = _verify_crosswalk(crosswalk, pd.read_feather(annotation_path))

    print("[2/5] Verifying the completed 86-fold source comparison", flush=True)
    prior = _load_yaml(ROOT / str(campaign["inputs"]["source_fit_result"]))
    accounting = prior.get("accounting", {})
    expected_folds = int(campaign["materialization"]["expected_cross_validation_folds_verified"])
    if accounting.get("folds_total") != expected_folds or accounting.get("folds_blocked") != 0:
        raise FeCOSensoryFreezeError("the prerequisite FeCO cross-validation result is incomplete")
    if accounting.get("candidate_winner_selected") is not False:
        raise FeCOSensoryFreezeError("the prerequisite result silently selected a winner")

    print("[3/5] Refitting six retained boundary-valid observation shapes", flush=True)
    source_campaign = _load_yaml(ROOT / str(campaign["inputs"]["source_fit_campaign"]))
    retained_by_class = campaign["acceptance_policy"]["retained_candidates"]
    retained = {str(value) for values in retained_by_class.values() for value in values}
    fits: list[dict[str, Any]] = []
    all_candidates: set[str] = set()
    for dataset in source_campaign["inputs"]["datasets"]:
        all_candidates.update(candidate.candidate_id for candidate in candidates_for(dataset))
        fits.extend(_fit_full_dataset(dataset, retained))
    excluded = set(campaign["acceptance_policy"]["excluded_candidates"])
    if {item["candidate_id"] for item in fits} != retained:
        raise FeCOSensoryFreezeError("retained candidate materialization is incomplete")
    if all_candidates != retained | excluded:
        raise FeCOSensoryFreezeError("candidate acceptance accounting is not exhaustive")

    print("[4/5] Factorizing routing x source-path x native-representation uncertainty", flush=True)
    source_paths = [
        {"source_path_id": f"source_{index:02d}", "candidate_by_class": dict(zip(("claw", "club", "hook"), values, strict=True))}
        for index, values in enumerate(
            itertools.product(
                retained_by_class["claw"], retained_by_class["club"], retained_by_class["hook"]
            )
        )
    ]
    native_representations = list(campaign["acceptance_policy"]["native_representations"])
    factorized_count = len(routing["routing_profiles"]) * len(source_paths) * len(native_representations)
    if factorized_count != int(campaign["materialization"]["expected_factorized_members"]):
        raise FeCOSensoryFreezeError("factorized sensory member count drift")
    semantic = {
        "scope_id": campaign["scope_id"],
        "topology_sha256": campaign["inputs"]["expected_topology_sha256"],
        "annotation_sha256": campaign["inputs"]["expected_annotation_sha256"],
        "mapped_body_counts_by_class": routing["mapped_body_counts_by_class"],
        "unknown_types": routing["unknown_types"],
        "routing_profiles": routing["routing_profiles"],
        "source_paths": source_paths,
        "native_representations": native_representations,
        "observation_fits": sorted(fits, key=lambda item: item["candidate_id"]),
        "excluded_candidates": campaign["acceptance_policy"]["excluded_candidates"],
        "factorized_member_count": factorized_count,
        "behavior_targets": [],
        "native_runtime_amplitude_identified": False,
        "reference_member_selected": False,
    }
    semantic_hash = _canonical_hash(semantic)
    parameter_set = {
        "schema_version": 1,
        "id": "parameters.front_leg_feco_sensory_ensemble.v0",
        "title": "Frozen scoped FeCO routing and observation-shape ensemble",
        "status": "frozen_scoped_shapes_native_scale_open",
        "scope_id": campaign["scope_id"],
        "campaign_id": campaign["id"],
        "primary_class": "local_interface",
        "behavior_targets": [],
        "topology_changes": 0,
        "semantic_parameter_set_sha256": semantic_hash,
        "factorization": {
            "routing_profiles": len(routing["routing_profiles"]),
            "joint_source_paths": len(source_paths),
            "native_representations": len(native_representations),
            "factorized_members": factorized_count,
        },
        "routing": {
            "mapped_body_counts_by_class": routing["mapped_body_counts_by_class"],
            "unknown_types": routing["unknown_types"],
            "profiles": routing["routing_profiles"],
        },
        "transfer_shape": {
            "source_paths": source_paths,
            "full_data_observation_fits": sorted(fits, key=lambda item: item["candidate_id"]),
            "excluded_candidates": campaign["acceptance_policy"]["excluded_candidates"],
        },
        "native_boundary": {
            "representations": native_representations,
            "representation_selected": False,
            "runtime_amplitude_identified": False,
            "blocker": "native_unit_and_amplitude_bridge_not_identified_by_calcium",
        },
        "selection": {
            "reference_member_selected": False,
            "candidate_winner_selected": False,
            "future_held_out_outcome_inspected": False,
        },
        "reproducibility": {"command": "feco_sensory_freeze.bat"},
        "next_action": "Bound the native-unit/amplitude bridge without behavior exposure to close FH-03.",
    }
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.feco_sensory_ensemble_freeze.v0",
        "title": "Scoped FeCO sensory ensemble freeze result",
        "status": "pass_partial_fh03_native_scale_open",
        "campaign_id": campaign["id"],
        "target_id": campaign["target_id"],
        "primary_class": "local_interface",
        "behavior_targets": [],
        "acceptance_result": "pass_routing_and_observation_shape_ensemble_frozen",
        "accounting": parameter_set["factorization"],
        "scientific_boundary": {
            "mapped_bodies": 26,
            "unresolved_bodies": 10,
            "unresolved_types": 3,
            "candidate_paths_retained": len(retained),
            "candidate_paths_excluded": len(excluded),
            "cross_validation_folds_verified": expected_folds,
            "native_runtime_amplitude_identified": False,
            "fh03_complete": False,
        },
        "semantic_parameter_set_sha256": semantic_hash,
        "next_action": parameter_set["next_action"],
    }
    runner = {
        "schema_version": 1,
        "id": "runner_result.feco_sensory_ensemble_freeze.v0",
        "generated_at": datetime.now(UTC).isoformat(),
        "campaign_id": campaign["id"],
        "status": "completed_scoped_shapes_frozen_native_scale_open",
        "semantic_result_sha256": semantic_hash,
        "accounting": evaluation["scientific_boundary"] | parameter_set["factorization"],
        "outputs": {
            "parameter_set": _display_path(parameter_set_path),
            "evaluation": _display_path(evaluation_path),
            "detailed_summary": _display_path(output_path),
        },
    }

    print("[5/5] Writing versioned freeze, evaluation and reproducible derived summary", flush=True)
    for path, value in ((parameter_set_path, parameter_set), (evaluation_path, evaluation), (runner_path, runner)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"semantic": semantic, "runner": runner}, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[DONE] 26 exact bodies + 10 bodies in 3 shared unknown types; {factorized_count} factorized members", flush=True)
    print("[OPEN] Native event/graded choice and runtime amplitude remain unresolved", flush=True)
    return runner


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    try:
        run()
    except (FeCOSensoryFreezeError, OSError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

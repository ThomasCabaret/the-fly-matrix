from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml
from scipy import sparse

from .ledger import ROOT
from .typed_hybrid_runtime import EVENT, GRADED, boundary_edge_counts


CAMPAIGN_PATH = (
    ROOT / "calibration" / "campaigns" / "front-leg-coupled-identifiability-design-v0.yaml"
)
RESULT_PATH = (
    ROOT / "calibration" / "runner" / "front-leg-coupled-identifiability-design-v0.yaml"
)
EVALUATION_PATH = (
    ROOT / "calibration" / "evaluations" / "front-leg-coupled-identifiability-design-v0.yaml"
)
OUTPUT_ROOT = (
    ROOT / "data" / "derived" / "calibration" / "front-leg-coupled-identifiability-design-v0"
)


class CoupledIdentifiabilityError(RuntimeError):
    """Raised when the FH-05 owner-separation design loses an invariant."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CoupledIdentifiabilityError(f"{path} must contain a YAML mapping")
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


def build_owner_orthogonal_array(
    level_names: Mapping[str, Sequence[str]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return a 27-run, six-factor, three-level strength-two design.

    The columns are distinct linear forms over GF(3). Consequently every pair of
    factors sees all nine level pairs exactly three times. This is a diagnostic
    crossing design, not a prior or a physiological parameter range.
    """

    required = (
        "feco_native_amplitude",
        "basal_source_intensity",
        "same_native_efficacy",
        "cross_native_conversion",
        "threshold_distance",
        "unknown_afferent_policy",
    )
    if tuple(level_names) != required:
        raise CoupledIdentifiabilityError(
            f"owner axes must be ordered exactly as {required}, got {tuple(level_names)}"
        )
    if any(len(tuple(level_names[name])) != 3 for name in required):
        raise CoupledIdentifiabilityError("every owner axis must declare exactly three levels")

    rows: list[dict[str, Any]] = []
    for x, y, z in itertools.product(range(3), repeat=3):
        coordinates = (x, y, z, (x + y) % 3, (x + z) % 3, (y + z) % 3)
        row: dict[str, Any] = {"owner_design_id": f"owner_{len(rows):02d}"}
        for name, coordinate in zip(required, coordinates, strict=True):
            row[name] = str(level_names[name][coordinate])
        rows.append(row)
    frame = pd.DataFrame(rows)

    pair_counts: dict[str, dict[str, int]] = {}
    for left, right in itertools.combinations(required, 2):
        counts = frame.groupby([left, right], observed=True).size()
        pair_counts[f"{left}__x__{right}"] = {
            "combinations": int(len(counts)),
            "minimum_repeats": int(counts.min()),
            "maximum_repeats": int(counts.max()),
        }
    summary = {
        "runs": len(frame),
        "factors": len(required),
        "levels_per_factor": 3,
        "factor_pairs": len(pair_counts),
        "all_factor_pairs_cover_nine_combinations": all(
            value["combinations"] == 9 for value in pair_counts.values()
        ),
        "all_pair_combinations_repeated_three_times": all(
            value["minimum_repeats"] == value["maximum_repeats"] == 3
            for value in pair_counts.values()
        ),
        "pair_coverage": pair_counts,
    }
    return frame, summary


def build_structural_schedule(
    routing_ids: Sequence[str],
    native_ids: Sequence[str],
    intermediate_ids: Sequence[str],
) -> pd.DataFrame:
    """Cover routing/native and intermediate/native pairs without a full product."""

    routing = tuple(str(value) for value in routing_ids)
    native = tuple(str(value) for value in native_ids)
    intermediate = tuple(str(value) for value in intermediate_ids)
    if not routing or not native or not intermediate:
        raise CoupledIdentifiabilityError("structural axes must be nonempty")
    rows: dict[tuple[str, str, str], dict[str, str]] = {}
    for routing_index, routing_id in enumerate(routing):
        for native_index, native_id in enumerate(native):
            intermediate_id = intermediate[(routing_index * len(native) + native_index) % len(intermediate)]
            key = (routing_id, native_id, intermediate_id)
            rows[key] = {
                "routing_profile_id": routing_id,
                "native_profile_id": native_id,
                "intermediate_profile_id": intermediate_id,
            }
    for intermediate_index, intermediate_id in enumerate(intermediate):
        for native_index, native_id in enumerate(native):
            routing_id = routing[(intermediate_index * len(native) + native_index) % len(routing)]
            key = (routing_id, native_id, intermediate_id)
            rows[key] = {
                "routing_profile_id": routing_id,
                "native_profile_id": native_id,
                "intermediate_profile_id": intermediate_id,
            }
    ordered = sorted(rows.values(), key=lambda row: tuple(row.values()))
    for index, row in enumerate(ordered):
        row["structural_design_id"] = f"structural_{index:03d}"
    return pd.DataFrame(ordered)


def _verify_campaign(campaign: Mapping[str, Any]) -> dict[str, Path]:
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise CoupledIdentifiabilityError("FH-05 design must remain diagnostic_only")
    if campaign.get("behavior_targets"):
        raise CoupledIdentifiabilityError("FH-05 design cannot expose a named behavior")
    if campaign.get("topology_changes_allowed") is not False:
        raise CoupledIdentifiabilityError("FH-05 design cannot change topology")
    if int(campaign.get("parameter_values_promoted", -1)) != 0:
        raise CoupledIdentifiabilityError("FH-05 design cannot promote parameter values")
    paths: dict[str, Path] = {}
    for key, record in campaign["frozen_inputs"].items():
        path = ROOT / str(record["path"])
        if not path.is_file():
            raise CoupledIdentifiabilityError(f"missing frozen input {key}: {path}")
        expected = str(record["sha256"])
        observed = _sha256(path)
        if observed != expected:
            raise CoupledIdentifiabilityError(
                f"frozen input drift for {key}: {observed} != {expected}"
            )
        paths[key] = path
    return paths


def _functional_class_map(crosswalk: Mapping[str, Any], routing: Mapping[str, Any]) -> dict[str, str]:
    result = {
        str(item["type"]): str(item["functional_class"])
        for item in crosswalk["type_assignments"]
        if item.get("functional_class")
    }
    for type_id, functional_class in routing["unknown_type_assignments"].items():
        result[str(type_id)] = str(functional_class)
    return result


def _assignment_for_member(
    *,
    feco: pd.DataFrame,
    motor: pd.DataFrame,
    classified: pd.DataFrame,
    panel_lookup: Mapping[tuple[str, int], str],
    routing: Mapping[str, Any],
    native: Mapping[str, Any],
    crosswalk: Mapping[str, Any],
    body_ids: np.ndarray,
    index_by_body: Mapping[int, int],
    intermediate_profile_id: str,
) -> np.ndarray:
    assignment = np.zeros(len(body_ids), dtype=np.int8)
    class_by_type = _functional_class_map(crosswalk, routing)
    representation_by_class = {
        str(key): str(value) for key, value in native["representation_by_class"].items()
    }
    for row in feco.itertuples(index=False):
        functional_class = class_by_type[str(row.annotation_type)]
        representation = representation_by_class[functional_class]
        assignment[index_by_body[int(row.body_id)]] = (
            EVENT if representation == "event_intensity_hz" else GRADED
        )
    for row in classified.itertuples(index=False):
        if str(row.assignment) == "event_required":
            value = EVENT
        elif str(row.assignment) == "dual_unresolved":
            candidate = panel_lookup[(intermediate_profile_id, int(row.body_id))]
            value = EVENT if candidate == "event_candidate" else GRADED
        else:
            raise CoupledIdentifiabilityError(
                f"unsupported intermediate assignment {row.assignment!r}"
            )
        assignment[index_by_body[int(row.body_id)]] = value
    for body_id in motor["body_id"].astype(int):
        assignment[index_by_body[int(body_id)]] = EVENT
    if np.any(assignment == 0):
        missing = body_ids[assignment == 0].tolist()
        raise CoupledIdentifiabilityError(f"unassigned cone bodies: {missing[:10]}")
    return assignment


def _pair_coverage(frame: pd.DataFrame, left: str, right: str) -> int:
    return int(frame[[left, right]].drop_duplicates().shape[0])


def run_design(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    campaign = _load_yaml(campaign_path)
    print("[1/8] Verification du contrat FH-05 et des entrees gelees", flush=True)
    paths = _verify_campaign(campaign)

    print("[2/8] Chargement du cone causal de 196 neurones", flush=True)
    members = pd.read_csv(paths["population_members"])
    feco = members.loc[members["population_id"].eq("population.front_leg_feco.v0")].copy()
    motor = members.loc[
        members["population_id"].eq("population.front_leg_tibia_flexor_motor.v0")
    ].copy()
    classified = pd.read_csv(paths["classified_intermediates"])
    cone_body_ids = sorted(
        set(feco["body_id"].astype(int))
        | set(motor["body_id"].astype(int))
        | set(classified["body_id"].astype(int))
    )
    if (len(feco), len(classified), len(motor), len(cone_body_ids)) != (36, 150, 10, 196):
        raise CoupledIdentifiabilityError("196-neuron cone population accounting drift")

    nodes = pd.read_parquet(paths["central_nodes"])
    node_rows = nodes.loc[nodes["body_id"].astype(int).isin(cone_body_ids)].copy()
    if len(node_rows) != 196 or node_rows["body_id"].nunique() != 196:
        raise CoupledIdentifiabilityError("canonical node index does not resolve the cone uniquely")
    node_rows = node_rows.sort_values("runtime_node_index").reset_index(drop=True)
    runtime_indices = node_rows["runtime_node_index"].to_numpy(np.int64)
    body_ids = node_rows["body_id"].to_numpy(np.int64)
    index_by_body = {int(body_id): index for index, body_id in enumerate(body_ids)}
    incoming_full = sparse.load_npz(paths["incoming_graph"]).tocsr()
    incoming = incoming_full[runtime_indices][:, runtime_indices].tocsr()

    print("[3/8] Compilation des axes structurels factorises", flush=True)
    sensory = _load_yaml(paths["feco_parameter_set"])
    routing_profiles = sensory["routing"]["profiles"]
    native_profiles = sensory["native_boundary_capacity"]["profiles"]
    routing_by_id = {str(item["profile_id"]): item for item in routing_profiles}
    native_by_id = {str(item["profile_id"]): item for item in native_profiles}
    panel = pd.read_csv(paths["intermediate_panel"])
    intermediate_ids = list(dict.fromkeys(panel["profile_id"].astype(str)))
    panel_lookup = {
        (str(row.profile_id), int(row.body_id)): str(row.assignment)
        for row in panel.itertuples(index=False)
    }
    structural = build_structural_schedule(
        list(routing_by_id), list(native_by_id), intermediate_ids
    )

    print("[4/8] Comptage des quatre frontieres sur le graphe local reel", flush=True)
    crosswalk = _load_yaml(paths["feco_crosswalk"])
    boundary_rows: list[dict[str, Any]] = []
    for row in structural.itertuples(index=False):
        assignment = _assignment_for_member(
            feco=feco,
            motor=motor,
            classified=classified,
            panel_lookup=panel_lookup,
            routing=routing_by_id[str(row.routing_profile_id)],
            native=native_by_id[str(row.native_profile_id)],
            crosswalk=crosswalk,
            body_ids=body_ids,
            index_by_body=index_by_body,
            intermediate_profile_id=str(row.intermediate_profile_id),
        )
        counts = boundary_edge_counts(incoming, assignment)
        boundary_rows.append(
            {
                **row._asdict(),
                "event_nodes": int(np.count_nonzero(assignment == EVENT)),
                "graded_nodes": int(np.count_nonzero(assignment == GRADED)),
                **counts,
                "all_four_boundary_kinds_present": all(
                    counts[name] > 0
                    for name in (
                        "event_to_event",
                        "event_to_graded",
                        "graded_to_event",
                        "graded_to_graded",
                    )
                ),
            }
        )
    structural = pd.DataFrame(boundary_rows)

    print("[5/8] Construction du plan orthogonal des six proprietaires", flush=True)
    owner, owner_summary = build_owner_orthogonal_array(campaign["owner_design"]["levels"])
    anchors = campaign["execution_anchors"]
    execution_rows: list[dict[str, Any]] = []
    for anchor in anchors:
        for owner_row in owner.to_dict(orient="records"):
            execution_rows.append(
                {
                    "execution_id": f"{anchor['anchor_id']}__{owner_row['owner_design_id']}",
                    "anchor_id": anchor["anchor_id"],
                    "routing_profile_id": anchor["routing_profile_id"],
                    "native_profile_id": anchor["native_profile_id"],
                    "intermediate_profile_id": anchor["intermediate_profile_id"],
                    **owner_row,
                }
            )
    execution = pd.DataFrame(execution_rows)

    print("[6/8] Validation des couvertures et des absences de selection", flush=True)
    structural_summary = {
        "cone_neurons": len(body_ids),
        "cone_edges": int(incoming.nnz),
        "structural_rows": len(structural),
        "routing_profiles": len(routing_by_id),
        "native_profiles": len(native_by_id),
        "intermediate_profiles": len(intermediate_ids),
        "routing_native_pairs_covered": _pair_coverage(
            structural, "routing_profile_id", "native_profile_id"
        ),
        "routing_native_pairs_expected": len(routing_by_id) * len(native_by_id),
        "intermediate_native_pairs_covered": _pair_coverage(
            structural, "intermediate_profile_id", "native_profile_id"
        ),
        "intermediate_native_pairs_expected": len(intermediate_ids) * len(native_by_id),
        "all_four_boundary_rows": int(structural["all_four_boundary_kinds_present"].sum()),
        "boundary_edge_ranges": {
            name: {"min": int(structural[name].min()), "max": int(structural[name].max())}
            for name in (
                "event_to_event",
                "event_to_graded",
                "graded_to_event",
                "graded_to_graded",
            )
        },
        "event_node_range": {
            "min": int(structural["event_nodes"].min()),
            "max": int(structural["event_nodes"].max()),
        },
        "graded_node_range": {
            "min": int(structural["graded_nodes"].min()),
            "max": int(structural["graded_nodes"].max()),
        },
    }
    acceptance = campaign["acceptance"]
    checks = {
        "cone_population_accounting_exact": len(body_ids) == int(acceptance["expected_cone_neurons"]),
        "structural_row_count_exact": len(structural)
        == int(acceptance["expected_structural_rows"]),
        "routing_native_pairs_complete": structural_summary["routing_native_pairs_covered"]
        == int(acceptance["expected_routing_native_pairs"]),
        "intermediate_native_pairs_complete": structural_summary[
            "intermediate_native_pairs_covered"
        ]
        == int(acceptance["expected_intermediate_native_pairs"]),
        "owner_pairwise_design_complete": bool(
            len(owner) == int(acceptance["expected_owner_design_rows"])
            and owner_summary["factor_pairs"]
            == int(acceptance["expected_owner_factor_pairs"])
            and
            owner_summary["all_factor_pairs_cover_nine_combinations"]
            and owner_summary["all_pair_combinations_repeated_three_times"]
        ),
        "execution_anchor_rows_complete": len(execution)
        == int(acceptance["expected_execution_anchor_rows"]),
        "cross_native_boundaries_exercisable": bool(
            structural["event_to_graded"].max() > 0
            and structural["graded_to_event"].max() > 0
        ),
        "no_parameter_value_promoted": int(campaign["parameter_values_promoted"]) == 0,
        "no_behavior_outcome_consumed": not bool(campaign["behavior_targets"]),
        "no_topology_change": campaign["topology_changes_allowed"] is False,
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise CoupledIdentifiabilityError(f"FH-05 design acceptance failed: {failed}")

    print("[7/8] Ecriture des artefacts et du registre compact", flush=True)
    output_root.mkdir(parents=True, exist_ok=True)
    structural_path = output_root / "structural-boundary-design.csv"
    owner_path = output_root / "owner-orthogonal-array.csv"
    execution_path = output_root / "execution-anchor-schedule.csv"
    structural.to_csv(structural_path, index=False)
    owner.to_csv(owner_path, index=False)
    execution.to_csv(execution_path, index=False)

    upstream_unknown = _load_yaml(paths["unknown_afferent_evaluation"])
    unknown_summary = upstream_unknown["diagnostic_findings"]
    scientific_boundary = {
        "parameter_values_promoted": 0,
        "population_assignments_promoted": 0,
        "routing_profiles_selected": 0,
        "native_profiles_selected": 0,
        "intermediate_profiles_selected": 0,
        "behavior_outcomes_consumed": 0,
        "topology_changes": 0,
        "numeric_owner_levels_are_engineering_coordinates_not_bounds": True,
        "full_higher_order_interaction_coverage_claimed": False,
        "finite_admissible_local_ensemble_established": False,
    }
    semantic_payload = {
        "campaign_id": campaign["id"],
        "structural": structural_summary,
        "owner_design": owner_summary,
        "execution_anchor_rows": len(execution),
        "checks": checks,
        "unknown_afferent_prior_diagnostic": {
            "event_g_l1_absolute_fraction": unknown_summary[
                "mixed_reference_unknown_family_ablation_motor_event_g_l1_absolute_fraction"
            ],
            "state_max_absolute_fraction": unknown_summary[
                "mixed_reference_unknown_family_ablation_motor_state_max_absolute_fraction"
            ],
            "scientific_interpretation": "fixture_sensitivity_only_not_biological_dominance",
        },
        "scientific_boundary": scientific_boundary,
        "next_action": campaign["next_action"],
    }
    semantic_sha256 = _canonical_hash(semantic_payload)
    artifact = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        **semantic_payload,
        "semantic_result_sha256": semantic_sha256,
        "artifact_refs": [
            str(path.relative_to(ROOT)).replace("\\", "/")
            for path in (structural_path, owner_path, execution_path)
        ],
    }
    (output_root / "summary.json").write_text(
        json.dumps(artifact, indent=2), encoding="utf-8"
    )

    compact = {
        "schema_version": 1,
        "id": "runner_result.front_leg_coupled_identifiability_design.v0",
        "campaign_id": campaign["id"],
        "status": "pass_FH05_owner_separated_design_compiled_execution_pending",
        "claim_label": campaign["claim_label"],
        "command": "front_leg_coupled_identifiability_design.bat",
        "campaign_sha256": _sha256(campaign_path),
        "semantic_result_sha256": semantic_sha256,
        "structural_design": structural_summary,
        "owner_design": owner_summary,
        "execution_anchor_rows": len(execution),
        "unknown_afferent_prior_diagnostic": semantic_payload[
            "unknown_afferent_prior_diagnostic"
        ],
        "checks": checks,
        "scientific_boundary": scientific_boundary,
        "artifact_ref": str((output_root / "summary.json").relative_to(ROOT)).replace(
            "\\", "/"
        ),
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    result_path.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")

    evaluation = {
        "schema_version": 1,
        "id": "evaluation.front_leg_coupled_identifiability_design.v0",
        "campaign_id": campaign["id"],
        "runner_result_id": compact["id"],
        "status": "accepted_design_FH05_in_progress_no_values_selected",
        "acceptance_result": "pass_static_scope_and_owner_separation_execution_pending",
        "checks": checks,
        "structural_design": structural_summary,
        "owner_design": {
            "runs": owner_summary["runs"],
            "factors": owner_summary["factors"],
            "factor_pairs": owner_summary["factor_pairs"],
            "all_pair_combinations_repeated_three_times": owner_summary[
                "all_pair_combinations_repeated_three_times"
            ],
        },
        "execution_anchor_rows": len(execution),
        "unknown_afferent_prior_diagnostic": semantic_payload[
            "unknown_afferent_prior_diagnostic"
        ],
        "scientific_boundary": scientific_boundary,
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "semantic_result_sha256": semantic_sha256,
        "next_action": campaign["next_action"],
    }
    evaluation_path.write_text(yaml.safe_dump(evaluation, sort_keys=False), encoding="utf-8")

    print("[8/8] Resume", flush=True)
    print(
        f"[CONE] {len(body_ids)} neurones, {incoming.nnz} aretes induites, "
        f"{len(structural)} profils structurels",
        flush=True,
    )
    print(
        "[COVERAGE] 216/216 routing x native; 400/400 intermediate x native",
        flush=True,
    )
    print(
        f"[OWNERS] {owner_summary['runs']} lignes, 15/15 paires de facteurs en 3x3",
        flush=True,
    )
    print(f"[NEXT] {len(execution)} sentinelles dynamiques preregistrees", flush=True)
    print("[BOUNDARY] 0 valeur, 0 affectation, 0 comportement selectionne", flush=True)
    print(f"[HASH] {semantic_sha256}", flush=True)
    return compact


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compile the FH-05 front-leg coupled-identifiability design"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    run_design(args.campaign, output_root=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

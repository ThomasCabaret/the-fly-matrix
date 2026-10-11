from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from .ledger import ROOT


CAMPAIGN_PATH = (
    ROOT / "calibration" / "campaigns" / "front-leg-uncertainty-propagation-v0.yaml"
)
RESULT_PATH = (
    ROOT / "calibration" / "runner" / "front-leg-uncertainty-propagation-v0.yaml"
)
OUTPUT_ROOT = (
    ROOT / "data" / "derived" / "calibration" / "front-leg-uncertainty-propagation-v0"
)


class UncertaintyPropagationError(RuntimeError):
    """Raised when the bounded uncertainty-propagation contract is violated."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise UncertaintyPropagationError(f"{path} must contain a YAML mapping")
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


def _assignment_bit(policy_id: str, seed_index: int, body_id: int) -> int:
    payload = f"{policy_id}:{seed_index}:{body_id}".encode("utf-8")
    return hashlib.sha256(payload).digest()[0] & 1


def build_balanced_pairwise_panel(
    body_ids: list[int], *, policy_id: str, complement_pairs: int
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build a deterministic sensitivity panel without reducing scientific uncertainty.

    Each hash profile is paired with its complement, and the two homogeneous
    extremes are retained. Consequently every body appears equally often as
    event and graded. Pairwise coverage is measured and enforced by the campaign;
    this does not cover higher-order interactions or define a probability prior.
    """

    ordered = sorted(int(value) for value in body_ids)
    if not ordered or len(set(ordered)) != len(ordered):
        raise UncertaintyPropagationError("body IDs must be nonempty and unique")
    if complement_pairs < 1:
        raise UncertaintyPropagationError("at least one complement pair is required")

    profiles: list[tuple[str, list[int]]] = [
        ("extreme_all_event", [1] * len(ordered)),
        ("extreme_all_graded", [0] * len(ordered)),
    ]
    for seed_index in range(complement_pairs):
        values = [
            _assignment_bit(policy_id, seed_index, body_id) for body_id in ordered
        ]
        profiles.append((f"hash_{seed_index:02d}", values))
        profiles.append((f"hash_{seed_index:02d}_complement", [1 - value for value in values]))

    rows = []
    for profile_id, values in profiles:
        for body_id, value in zip(ordered, values, strict=True):
            rows.append(
                {
                    "profile_id": profile_id,
                    "body_id": body_id,
                    "assignment": "event_candidate" if value else "graded_candidate",
                }
            )
    panel = pd.DataFrame(rows)

    matrix = {
        profile_id: dict(zip(ordered, values, strict=True))
        for profile_id, values in profiles
    }
    per_body_counts = panel.groupby(["body_id", "assignment"]).size().unstack(fill_value=0)
    pairwise_histogram = {str(count): 0 for count in range(1, 5)}
    incomplete_pairs: list[dict[str, Any]] = []
    for left, right in combinations(ordered, 2):
        states = {(values[left], values[right]) for values in matrix.values()}
        count = len(states)
        pairwise_histogram[str(count)] += 1
        if count < 4:
            incomplete_pairs.append(
                {"left_body_id": left, "right_body_id": right, "states_seen": count}
            )

    profile_signatures = {
        tuple(matrix[profile_id][body_id] for body_id in ordered)
        for profile_id, _values in profiles
    }
    summary = {
        "unresolved_bodies": len(ordered),
        "scientific_assignment_space": f"2^{len(ordered)}",
        "scientific_assignment_space_decimal": str(2 ** len(ordered)),
        "diagnostic_profiles": len(profiles),
        "complement_pairs": complement_pairs,
        "unique_profile_signatures": len(profile_signatures),
        "assignments_per_body": {
            "event_candidate": int(per_body_counts["event_candidate"].min()),
            "graded_candidate": int(per_body_counts["graded_candidate"].min()),
        },
        "body_pairs": len(ordered) * (len(ordered) - 1) // 2,
        "pairwise_state_count_histogram": pairwise_histogram,
        "pairs_with_all_four_states": pairwise_histogram["4"],
        "incomplete_pair_count": len(incomplete_pairs),
        "incomplete_pairs": incomplete_pairs,
        "higher_order_coverage_claimed": False,
        "probability_prior_implied": False,
    }
    return panel, summary


def _validate_interface_records(
    feco: Mapping[str, Any],
    motor_classes: Mapping[str, Any],
    motor_temporal: Mapping[str, Any],
    motor_bridge: Mapping[str, Any],
    chain: Mapping[str, Any],
    campaign: Mapping[str, Any],
) -> dict[str, Any]:
    acceptance = campaign["acceptance"]
    feco_readiness = feco["procedure_readiness"]
    motor_members = motor_classes["members"]
    temporal = motor_temporal["procedure_result"]
    bridge = motor_bridge["procedure_result"]
    chain_sensory = chain["procedure_result"]["sensory"]
    chain_motor = chain["procedure_result"]["motor"]

    feco_alternatives = int(chain_sensory["total_boundary_alternatives"])
    if int(feco_readiness["candidate_paths_preregistered"]) != 7:
        raise UncertaintyPropagationError("FeCO candidate-path count drift")
    if feco_readiness["candidate_winner_selected"] is not False:
        raise UncertaintyPropagationError("FeCO source candidate was selected upstream")
    if feco_readiness["native_representation_selected"] is not False:
        raise UncertaintyPropagationError("FeCO native representation was selected upstream")
    if feco_alternatives != 24:
        raise UncertaintyPropagationError("FeCO boundary alternative contract drift")

    class_count = len(motor_classes["admissible_classes"])
    body_count = len(motor_members)
    motor_upper_bound = class_count**body_count
    if motor_upper_bound != int(motor_classes["factorized_assignment_upper_bound"]):
        raise UncertaintyPropagationError("motor class factorization drift")
    if motor_upper_bound != int(chain_motor["factorized_class_assignment_upper_bound"]):
        raise UncertaintyPropagationError("chain motor class accounting drift")
    if any(member.get("selected_class") is not None for member in motor_members):
        raise UncertaintyPropagationError("a motor body class was selected upstream")
    executable_classes = int(temporal["fitted_classes"])
    blocked_classes = int(temporal["unfitted_classes"])
    executable_assignments = executable_classes**body_count
    blocked_assignments = motor_upper_bound - executable_assignments
    if temporal["slow_35C09"]["interpretation"] != "not_fit_no_isolated_single_spike_trials":
        raise UncertaintyPropagationError("slow-kernel blocker drift")
    if int(bridge["reported_gain_candidates"]) != int(
        acceptance["expected_bridge_gain_candidates"]
    ):
        raise UncertaintyPropagationError("motor bridge gain count drift")

    return {
        "feco": {
            "boundary_alternatives": feco_alternatives,
            "source_candidates": 7,
            "native_representations": 2,
            "decision": "accepted_as_unselected_propagation_set",
            "parameter_values_promoted": 0,
        },
        "motor": {
            "body_class_variables": body_count,
            "class_candidates_per_body": class_count,
            "scientific_class_assignment_upper_bound": motor_upper_bound,
            "kernel_executable_fast_or_intermediate_assignments": executable_assignments,
            "kernel_blocked_slow_containing_assignments": blocked_assignments,
            "route_basis_edges": int(chain_motor["route_basis_edges"]),
            "routing_simplex_dof_upper_bound": int(
                chain_motor["local_routing_simplex_dof_upper_bound"]
            ),
            "bridge_gain_candidates": int(bridge["reported_gain_candidates"]),
            "decision": "partially_executable_factorized_set_slow_branch_blocked",
            "parameter_values_promoted": 0,
        },
    }


def _validate_acceptance(
    panel_summary: Mapping[str, Any],
    interfaces: Mapping[str, Any],
    campaign: Mapping[str, Any],
) -> None:
    acceptance = campaign["acceptance"]
    observed = {
        "expected_unresolved_intermediates": panel_summary["unresolved_bodies"],
        "expected_diagnostic_profiles": panel_summary["diagnostic_profiles"],
        "expected_complement_pairs": panel_summary["complement_pairs"],
        "expected_pairwise_complete_pairs": panel_summary["pairs_with_all_four_states"],
        "expected_feco_boundary_alternatives": interfaces["feco"]["boundary_alternatives"],
        "expected_motor_class_assignment_upper_bound": interfaces["motor"][
            "scientific_class_assignment_upper_bound"
        ],
        "expected_motor_kernel_executable_assignments": interfaces["motor"][
            "kernel_executable_fast_or_intermediate_assignments"
        ],
        "expected_motor_kernel_blocked_assignments": interfaces["motor"][
            "kernel_blocked_slow_containing_assignments"
        ],
        "expected_route_basis_edges": interfaces["motor"]["route_basis_edges"],
        "expected_routing_simplex_dof_upper_bound": interfaces["motor"][
            "routing_simplex_dof_upper_bound"
        ],
        "expected_bridge_gain_candidates": interfaces["motor"]["bridge_gain_candidates"],
    }
    for key, value in observed.items():
        if int(acceptance[key]) != int(value):
            raise UncertaintyPropagationError(
                f"acceptance drift for {key}: observed {value}, expected {acceptance[key]}"
            )
    expected_per_state = int(acceptance["expected_assignments_per_body_per_state"])
    if set(panel_summary["assignments_per_body"].values()) != {expected_per_state}:
        raise UncertaintyPropagationError("per-body event/graded balance drift")
    if panel_summary["incomplete_pair_count"]:
        raise UncertaintyPropagationError("diagnostic panel misses pairwise states")
    if campaign.get("behavior_targets"):
        raise UncertaintyPropagationError("propagation policy cannot expose behavior")
    if campaign.get("topology_changes_allowed") is not False:
        raise UncertaintyPropagationError("propagation policy cannot change topology")


def run_uncertainty_propagation(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    campaign = _load_yaml(campaign_path)
    frozen = campaign["frozen_inputs"]
    paths = {key: ROOT / str(value) for key, value in frozen.items()}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise UncertaintyPropagationError(f"missing frozen inputs: {missing}")

    print("[1/6] Verification des dispositions intermediaires", flush=True)
    classified = pd.read_csv(paths["classified_intermediates"])
    unresolved = classified.loc[classified["assignment"].eq("dual_unresolved")].copy()
    if unresolved["parameter_values_emitted"].astype(bool).any():
        raise UncertaintyPropagationError("upstream unresolved bodies emitted parameter values")

    print("[2/6] Construction du panneau equilibre et complemente", flush=True)
    panel_policy = campaign["intermediate_propagation_policy"]
    panel, panel_summary = build_balanced_pairwise_panel(
        unresolved["body_id"].astype(int).tolist(),
        policy_id=str(panel_policy["hash_namespace"]),
        complement_pairs=int(panel_policy["complement_pairs"]),
    )

    print("[3/6] Controle de la couverture par neurone et par paire", flush=True)
    print(
        f"[PANEL] {panel_summary['diagnostic_profiles']} profils; "
        f"{panel_summary['pairs_with_all_four_states']}/{panel_summary['body_pairs']} paires "
        "voient les quatre etats",
        flush=True,
    )

    print("[4/6] Validation separee des ensembles FeCO et moteur", flush=True)
    interfaces = _validate_interface_records(
        _load_yaml(paths["feco_evaluation"]),
        _load_yaml(paths["motor_class_ensemble"]),
        _load_yaml(paths["motor_temporal_evaluation"]),
        _load_yaml(paths["motor_bridge_evaluation"]),
        _load_yaml(paths["chain_evaluation"]),
        campaign,
    )
    _validate_acceptance(panel_summary, interfaces, campaign)

    print("[5/6] Ecriture des artefacts reproductibles", flush=True)
    output_root.mkdir(parents=True, exist_ok=True)
    panel_path = output_root / "intermediate-assignment-panel.csv"
    panel.to_csv(panel_path, index=False)
    input_hashes = {key: _sha256(path) for key, path in paths.items()}
    artifact = {
        "schema_version": 1,
        "campaign_id": campaign["id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "pass_bounded_propagation_feasible_interface_decisions_explicit",
        "claim_label": campaign["claim_label"],
        "input_hashes": input_hashes,
        "intermediate_panel": panel_summary,
        "interface_decisions": interfaces,
        "scientific_boundary": {
            "parameter_values_promoted": 0,
            "native_dynamics_assignments_promoted": 0,
            "routes_selected": 0,
            "behavior_targets_exposed": 0,
            "topology_changes": 0,
            "slow_kernel_borrowed": False,
        },
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "artifact_refs": [str(panel_path.relative_to(ROOT)).replace("\\", "/")],
        "next_action": campaign["next_action"],
    }
    artifact["semantic_result_sha256"] = _canonical_hash(
        {key: value for key, value in artifact.items() if key != "generated_at"}
    )
    summary_path = output_root / "summary.json"
    summary_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

    compact = {
        "schema_version": 1,
        "id": "runner_result.front_leg_uncertainty_propagation.v0",
        "campaign_id": campaign["id"],
        "target_id": campaign["target_id"],
        "status": artifact["status"],
        "claim_label": campaign["claim_label"],
        "command": "front_leg_uncertainty_panel.bat",
        "behavior_targets": [],
        "campaign_sha256": _sha256(campaign_path),
        "semantic_result_sha256": artifact["semantic_result_sha256"],
        "intermediate_panel": panel_summary,
        "interface_decisions": interfaces,
        "scientific_boundary": artifact["scientific_boundary"],
        "artifact_ref": str(summary_path.relative_to(ROOT)).replace("\\", "/"),
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
    }
    result_path.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")

    print("[6/6] Resume", flush=True)
    print(
        f"[UNCERTAINTY] {panel_summary['scientific_assignment_space']} conserve; "
        f"{panel_summary['diagnostic_profiles']} profils diagnostiques seulement",
        flush=True,
    )
    print("[FECO] 24 alternatives acceptees comme ensemble; aucune selection", flush=True)
    print(
        "[MOTOR] 1024 affectations fast/intermediate executables; "
        "58025 affectations contenant slow restent bloquees",
        flush=True,
    )
    print("[BOUNDARY] 0 valeur, 0 route, 0 comportement, 0 topologie", flush=True)
    print(f"[HASH] {artifact['semantic_result_sha256']}", flush=True)
    return compact


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile the front-leg unresolved-assignment propagation panel"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    run_uncertainty_propagation(args.campaign, output_root=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml

from .ledger import ROOT
from .neutral_embodied_declared_closed_loop_sentinel import (
    _array_hash,
    _canonical_hash,
    _load_campaign as _load_causal_campaign,
    _load_yaml,
    _run_episode,
    _verified_context,
)
from .neutral_embodied_declared_neural_sentinel import _incoming_l1_matrices, _profiles
from .neutral_embodied_full_chain_sentinel import _sha256
from .physical_trajectory import (
    SCHEMA_NAME,
    SCHEMA_VERSION,
    PhysicalTrajectory,
    model_contract,
    run_replay,
)
from .runtime import FlyBodyPhysicsLoop


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "front-leg-member-physical-preview-v0.yaml"
RESULT_PATH = ROOT / "calibration" / "runner" / "front-leg-member-physical-preview-v0.yaml"
EVALUATION_PATH = ROOT / "calibration" / "evaluations" / "front-leg-member-physical-preview-v0.yaml"
RUN_ROOT = ROOT / "runs" / "calibration" / "front-leg-member-physical-preview-v0"


class PhysicalPreviewError(RuntimeError):
    """Raised when the local-member preview contract is violated."""


def _jsonable(value: Any) -> Any:
    """Convert measurement metadata to the strict JSON subset used by replays."""

    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = _load_yaml(path)
    if campaign.get("primary_class") != "technical" or campaign.get("behavior_targets"):
        raise PhysicalPreviewError("physical preview must remain technical and behavior-naive")
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise PhysicalPreviewError("physical preview cannot optimize parameters")
    if campaign.get("topology_changes_allowed") is not False:
        raise PhysicalPreviewError("physical preview cannot change topology")
    if campaign["acceptance"]["allow_member_ranking"] is not False:
        raise PhysicalPreviewError("physical preview cannot rank members")
    return campaign


def _verified_inputs(campaign: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    frozen = campaign["frozen_inputs"]
    bundle_path = ROOT / str(frozen["conditioned_bundles"])
    causal_path = ROOT / str(frozen["causal_execution_campaign"])
    if _sha256(bundle_path) != frozen["conditioned_bundles_sha256"]:
        raise PhysicalPreviewError("conditioned bundle file drift")
    if _sha256(causal_path) != frozen["causal_execution_campaign_sha256"]:
        raise PhysicalPreviewError("causal execution campaign drift")
    bundles = _load_yaml(bundle_path)
    if bundles.get("runner_semantic_sha256") != frozen["conditioned_bundles_semantic_sha256"]:
        raise PhysicalPreviewError("conditioned bundle semantic hash drift")
    causal = _load_causal_campaign(causal_path)
    expected = list(map(str, campaign["execution"]["exact_member_ids"]))
    observed = list(map(str, bundles["ensemble"]["member_ids"]))
    if observed != expected or len(expected) != int(campaign["acceptance"]["expected_members"]):
        raise PhysicalPreviewError("exact member identity or order drift")
    return bundles, causal


def _trajectory_from_episode(
    episode: Mapping[str, np.ndarray],
    *,
    model: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> PhysicalTrajectory:
    frames = len(np.asarray(episode["timestamps_s"]))
    sensory = {
        "joint_positions": np.asarray(episode["joint_positions"], dtype=np.float32),
        "joint_velocities": np.asarray(episode["joint_velocities"], dtype=np.float32),
        "actuator_forces": np.asarray(episode["actuator_forces"], dtype=np.float32),
        "center_of_mass": np.asarray(episode["center_of_mass"], dtype=np.float32),
        "root_up_z": np.asarray(episode["root_up_z"], dtype=np.float32).reshape(frames, 1),
    }
    return PhysicalTrajectory(
        timestamps_s=np.asarray(episode["timestamps_s"], dtype=np.float64),
        qpos=np.asarray(episode["qpos"], dtype=np.float64),
        qvel=np.asarray(episode["qvel"], dtype=np.float64),
        actuator_commands=np.asarray(episode["applied_commands"], dtype=np.float32),
        neural_summary=np.empty((frames, 0), dtype=np.float32),
        sensory_observations=sensory,
        metadata={
            "schema_name": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "model": dict(model),
            **dict(metadata),
        },
    )


def _trajectory_semantic_hash(trajectory: PhysicalTrajectory, member_id: str) -> str:
    observation_names = sorted(trajectory.sensory_observations)
    array_digest = _array_hash(
        np.asarray(trajectory.timestamps_s),
        np.asarray(trajectory.qpos),
        np.asarray(trajectory.qvel),
        np.asarray(trajectory.actuator_commands),
        np.asarray(trajectory.neural_summary),
        *(np.asarray(trajectory.sensory_observations[name]) for name in observation_names),
    )
    return _canonical_hash(
        {
            "member_id": member_id,
            "array_digest": array_digest,
            "observation_names": observation_names,
            "model_contract_sha256": trajectory.metadata["model"]["contract_sha256"],
            "claim_label": trajectory.metadata["claim_label"],
        }
    )


def run_previews(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    evaluation_path: Path = EVALUATION_PATH,
    run_root: Path = RUN_ROOT,
) -> dict[str, Any]:
    print("[1/7] Verifying exact conditioned members and frozen causal protocol", flush=True)
    campaign = _load_campaign(campaign_path)
    bundles, causal_campaign = _verified_inputs(campaign)

    print("[2/7] Reconstructing the local typed/hybrid corridor and exact rows", flush=True)
    context = _verified_context(causal_campaign)
    profiles = _profiles(context)
    first, second, direct, coupling_audit = _incoming_l1_matrices(context["inputs"])
    matrices = (first, second, direct)
    by_id = {str(row["tuple_id"]): row for row in context["rows"]}
    member_ids = list(map(str, campaign["execution"]["exact_member_ids"]))
    if set(member_ids) - set(by_id):
        raise PhysicalPreviewError("an accepted member is absent from the frozen exact schedule")

    print("[3/7] Executing one frozen 0.2 s closed-loop episode per member", flush=True)
    run_root.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = []
    pending_replays: list[Path] = []
    with FlyBodyPhysicsLoop.from_generated_wiring(with_vision=False) as loop:
        physical_model = model_contract(loop)
        for index, member_id in enumerate(member_ids, start=1):
            print(f"  [{index}/{len(member_ids)}] {member_id}", flush=True)
            episode, measurement, diagnostic = _run_episode(
                causal_campaign,
                by_id[member_id],
                context,
                profiles,
                matrices,
                perturbation=None,
                reusable_loop=loop,
            )
            member_root = run_root / member_id
            trajectory_path = member_root / "physical-trajectory.npz"
            trajectory = _trajectory_from_episode(
                episode,
                model=physical_model,
                metadata={
                    "run_id": f"front-leg-member-preview-{member_id}",
                    "created_at": datetime.now(UTC).isoformat(),
                    "creator": "the_fly_matrix.front_leg_member_physical_preview.v0",
                    "claim_label": campaign["claim_label"],
                    "scientific_claim": "none; diagnostic physical presentation of one frozen local exact composite",
                    "campaign_id": campaign["id"],
                    "member_id": member_id,
                    "scope": {
                        "complete_FlyBody_physics": True,
                        "local_front_leg_chain_only": True,
                        "complete_recurrent_MaleCNS": False,
                        "basal_families_consumed": False,
                        "vision_consumed": False,
                    },
                    "neural_summary_fields": [],
                    "measurement_contract": _jsonable(measurement),
                    "known_limits": campaign["forbidden_claims"],
                },
            )
            trajectory.save(trajectory_path)
            pending_replays.append(trajectory_path)
            artifacts.append(
                {
                    "member_id": member_id,
                    "path": str(trajectory_path.relative_to(ROOT)).replace("\\", "/"),
                    "sha256": _sha256(trajectory_path),
                    "trajectory_semantic_sha256": _trajectory_semantic_hash(trajectory, member_id),
                    "bytes": trajectory_path.stat().st_size,
                    "frames": trajectory.frame_count,
                    "duration_s": trajectory.duration_s,
                    "diagnostic": diagnostic,
                }
            )

    print("[4/7] Validating every trajectory with the controller-independent headless player", flush=True)
    replay_checks = [run_replay(path, headless=True) for path in pending_replays]
    all_replays_valid = all(bool(item["model_contract_passed"]) for item in replay_checks)

    print("[5/7] Enforcing no-ranking, no-basal and no-whole-MaleCNS claims", flush=True)
    checks = {
        "all_exact_members_accounted": [item["member_id"] for item in artifacts] == member_ids,
        "all_trajectories_created": len(artifacts) == int(campaign["acceptance"]["expected_trajectories"]),
        "all_trajectories_finite_and_replayable": all_replays_valid,
        "zero_numeric_optimization": True,
        "zero_named_behavior_exposure": True,
        "zero_member_ranking": True,
        "basal_families_not_consumed": True,
        "complete_recurrent_MaleCNS_not_claimed": True,
        "human_checkpoint_required": bool(campaign["human_checkpoint"]["required_after_generation"]),
    }
    if not all(checks.values()):
        raise PhysicalPreviewError(f"preview checks failed: {[key for key, value in checks.items() if not value]}")

    semantic_payload = {
        "campaign_id": campaign["id"],
        "member_ids": member_ids,
        "trajectory_semantic_hashes": {
            item["member_id"]: item["trajectory_semantic_sha256"] for item in artifacts
        },
        "checks": checks,
        "coupling_audit": coupling_audit,
    }
    semantic_hash = _canonical_hash(semantic_payload)
    result = {
        "schema_version": 1,
        "id": "runner_result.front_leg_member_physical_preview.v0",
        "campaign_id": campaign["id"],
        "status": "completed_local_chain_physical_previews_pending_human_checkpoint",
        "completed_at": datetime.now(UTC).isoformat(),
        "command": "front_leg_member_physical_preview.bat",
        "replay_command": "front_leg_member_preview_replay.bat [129|141|238]",
        "claim_label": campaign["claim_label"],
        "accounting": {
            "expected_members": len(member_ids),
            "completed_members": len(artifacts),
            "replay_validated_members": len(replay_checks),
            "numeric_optimization_steps": 0,
            "named_behavior_exposures": 0,
            "basal_families_consumed": 0,
        },
        "artifacts": artifacts,
        "checks": checks,
        "human_checkpoint": campaign["human_checkpoint"],
        "accepted_claims": campaign["accepted_claims"],
        "forbidden_claims": campaign["forbidden_claims"],
        "next_action": campaign["next_action"],
        "semantic_result_sha256": semantic_hash,
    }

    print("[6/7] Writing compact result and evaluation", flush=True)
    evaluation = {
        "schema_version": 1,
        "id": "evaluation.front_leg_member_physical_preview.v0",
        "campaign_id": campaign["id"],
        "runner_result_id": result["id"],
        "runner_semantic_sha256": semantic_hash,
        "status": "accepted_diagnostic_previews_pending_human_checkpoint",
        "checks": checks,
        "member_ids": member_ids,
        "members_ranked": False,
        "basal_families_consumed": False,
        "whole_MaleCNS_executed": False,
        "whole_body_stability_accepted": False,
        "named_behavior_exposed": False,
        "interpretation": (
            "The complete FlyBody physics model replayed all three local exact composites. "
            "Only the declared front-leg corridor controlled one actuator per member; these are not global MaleCNS runs."
        ),
        "human_checkpoint": campaign["human_checkpoint"],
        "next_action": campaign["next_action"],
    }
    result_path.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    evaluation_path.write_text(yaml.safe_dump(evaluation, sort_keys=False, allow_unicode=True), encoding="utf-8")

    print("[7/7] COMPLETE — three local-chain physical replays await human inspection", flush=True)
    for item in artifacts:
        print(f"[REPLAY] {item['member_id']}: {item['path']} ({item['bytes'] / 1024**2:.2f} MiB)", flush=True)
    print("[BOUNDARY] complete FlyBody physics, local front-leg controller, no basal, not whole MaleCNS", flush=True)
    print(f"[HASH] {semantic_hash}", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate physical previews for the three exact local members")
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    args = parser.parse_args()
    run_previews(campaign_path=args.campaign)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

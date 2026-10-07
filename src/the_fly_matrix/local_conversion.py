from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Mapping

import numpy as np
import yaml

from .ledger import ROOT


CAMPAIGN_PATH = (
    ROOT / "calibration" / "campaigns" / "front-leg-local-conversion-contract-v0.yaml"
)
RESULT_PATH = (
    ROOT / "calibration" / "runner" / "front-leg-local-conversion-contract-v0.yaml"
)
OUTPUT_ROOT = ROOT / "data" / "derived" / "calibration" / "front-leg-local-conversion-v0"


class LocalConversionError(ValueError):
    """Raised when a local conversion crosses an undeclared unit boundary."""


@dataclass(frozen=True)
class FeCOTransferParameters:
    """Explicit kinematic-to-native-output coefficients for one FeCO channel.

    These are runtime mechanics, not defaults.  A campaign must provide every
    coefficient and say whether the native output is a graded activity or an
    event intensity.  The class intentionally does not infer a representation
    from the annotation name.
    """

    output_mode: Literal["graded_activity", "event_intensity_hz"]
    position_gain: np.ndarray
    velocity_gain: np.ndarray
    bias: np.ndarray


@dataclass(frozen=True)
class MotorTwitchParameters:
    """Per-channel causal event-to-force kernel parameters.

    ``force_per_event_uN`` is the peak of an isolated normalized bi-exponential
    twitch.  This candidate parameterization is not a claim that every fly motor
    unit follows this kernel; alternate kernels can be compared without changing
    the event-capable boundary.
    """

    force_per_event_uN: np.ndarray
    rise_time_s: np.ndarray
    decay_time_s: np.ndarray


@dataclass(frozen=True)
class ActuatorBridgeParameters:
    """Separate biological-force to MuJoCo direct-motor surrogate bridge."""

    command_per_uN: np.ndarray
    command_offset: np.ndarray


def _as_vector(name: str, value: np.ndarray, size: int | None = None) -> np.ndarray:
    result = np.asarray(value, dtype=np.float64)
    if result.ndim != 1:
        raise LocalConversionError(f"{name} must be a one-dimensional vector")
    if size is not None and len(result) != size:
        raise LocalConversionError(f"{name} has {len(result)} values, expected {size}")
    if not np.isfinite(result).all():
        raise LocalConversionError(f"{name} must contain only finite values")
    return result


def _as_time_channels(name: str, value: np.ndarray) -> np.ndarray:
    result = np.asarray(value, dtype=np.float64)
    if result.ndim != 2:
        raise LocalConversionError(f"{name} must have shape (time, channels)")
    if not np.isfinite(result).all():
        raise LocalConversionError(f"{name} must contain only finite values")
    return result


def feco_kinematics_to_native_output(
    position_rad: np.ndarray,
    velocity_rad_s: np.ndarray,
    parameters: FeCOTransferParameters,
) -> np.ndarray:
    """Apply an explicit local affine candidate without changing its native units."""

    position = _as_time_channels("position_rad", position_rad)
    velocity = _as_time_channels("velocity_rad_s", velocity_rad_s)
    if position.shape != velocity.shape:
        raise LocalConversionError("position and velocity shapes must match")
    channel_count = position.shape[1]
    position_gain = _as_vector("position_gain", parameters.position_gain, channel_count)
    velocity_gain = _as_vector("velocity_gain", parameters.velocity_gain, channel_count)
    bias = _as_vector("bias", parameters.bias, channel_count)
    if parameters.output_mode not in {"graded_activity", "event_intensity_hz"}:
        raise LocalConversionError(f"unsupported FeCO output mode {parameters.output_mode!r}")
    output = position * position_gain + velocity * velocity_gain + bias
    if parameters.output_mode == "event_intensity_hz" and (output < 0.0).any():
        raise LocalConversionError(
            "event_intensity_hz cannot be negative; fit an explicit non-negative transfer"
        )
    return output


def event_intensity_to_counts(
    intensity_hz: np.ndarray,
    *,
    timestep_s: float,
    seed: int,
) -> np.ndarray:
    """Sample explicit Poisson event counts with a reproducible named seed."""

    intensity = _as_time_channels("intensity_hz", intensity_hz)
    if not np.isfinite(timestep_s) or timestep_s <= 0.0:
        raise LocalConversionError("timestep_s must be finite and strictly positive")
    if (intensity < 0.0).any():
        raise LocalConversionError("event intensity cannot be negative")
    expected_counts = intensity * float(timestep_s)
    generator = np.random.default_rng(int(seed))
    return generator.poisson(expected_counts).astype(np.int64, copy=False)


def motor_events_to_force_uN(
    event_counts: np.ndarray,
    parameters: MotorTwitchParameters,
    *,
    timestep_s: float,
) -> np.ndarray:
    """Convolve integer events with explicit causal, peak-normalized twitch kernels."""

    events = np.asarray(event_counts)
    if events.ndim != 2:
        raise LocalConversionError("event_counts must have shape (time, channels)")
    if not np.issubdtype(events.dtype, np.integer):
        raise LocalConversionError("event_counts must be integer-valued")
    if (events < 0).any():
        raise LocalConversionError("event_counts cannot be negative")
    if not np.isfinite(timestep_s) or timestep_s <= 0.0:
        raise LocalConversionError("timestep_s must be finite and strictly positive")
    channel_count = events.shape[1]
    force_per_event = _as_vector(
        "force_per_event_uN", parameters.force_per_event_uN, channel_count
    )
    rise = _as_vector("rise_time_s", parameters.rise_time_s, channel_count)
    decay = _as_vector("decay_time_s", parameters.decay_time_s, channel_count)
    if (force_per_event < 0.0).any():
        raise LocalConversionError("force_per_event_uN cannot be negative")

    if (rise <= 0.0).any() or (decay <= rise).any():
        raise LocalConversionError("motor kernel requires 0 < rise_time_s < decay_time_s")
    peak_time = rise * decay / (decay - rise) * np.log(decay / rise)
    peak = np.exp(-peak_time / decay) - np.exp(-peak_time / rise)
    if not np.isfinite(peak).all() or (peak <= 0.0).any():
        raise LocalConversionError("invalid motor-kernel normalization")

    # Exact discrete samples of the continuous bi-exponential candidate.  This
    # recurrence is O(time * channels), unlike one full convolution per neuron.
    decay_factor = np.exp(-float(timestep_s) / decay)
    rise_factor = np.exp(-float(timestep_s) / rise)
    decay_state = np.zeros(channel_count, dtype=np.float64)
    rise_state = np.zeros(channel_count, dtype=np.float64)
    force = np.zeros(events.shape, dtype=np.float64)
    for sample_index in range(events.shape[0]):
        decay_state = decay_state * decay_factor + events[sample_index]
        rise_state = rise_state * rise_factor + events[sample_index]
        force[sample_index] = (
            (decay_state - rise_state) / peak * force_per_event
        )
    return force


def force_uN_to_actuator_command(
    force_uN: np.ndarray,
    parameters: ActuatorBridgeParameters,
) -> np.ndarray:
    """Cross the force/surrogate boundary explicitly; do not merge with the twitch."""

    force = _as_time_channels("force_uN", force_uN)
    channel_count = force.shape[1]
    gain = _as_vector("command_per_uN", parameters.command_per_uN, channel_count)
    offset = _as_vector("command_offset", parameters.command_offset, channel_count)
    return force * gain + offset


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_campaign(path: Path) -> dict[str, Any]:
    campaign = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(campaign, dict):
        raise LocalConversionError("campaign must be a YAML mapping")
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise LocalConversionError("local conversion contract probe must remain diagnostic_only")
    if campaign.get("behavior_targets"):
        raise LocalConversionError("local conversion contract cannot expose behavior targets")
    if campaign.get("capacity_policy", {}).get("optimized_parameters") != 0:
        raise LocalConversionError("contract probe cannot optimize parameters")
    return campaign


def _verify_topology_boundary(campaign: Mapping[str, Any]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for family_id, item in campaign["topology_boundary"].items():
        if family_id == "topology_changes_allowed":
            if item is not False:
                raise LocalConversionError("local conversion campaign cannot change topology")
            continue
        if not isinstance(item, Mapping):
            raise LocalConversionError(f"invalid topology boundary for {family_id}")
        record_path = ROOT / str(item["parameter_family_record"])
        record = yaml.safe_load(record_path.read_text(encoding="utf-8"))
        actual = str(record["scope"]["topology_snapshot"]["semantic_topology_sha256"])
        expected = str(item["semantic_topology_sha256"])
        if actual != expected:
            raise LocalConversionError(
                f"topology drift for {family_id}: expected {expected}, got {actual}"
            )
        observed[str(family_id)] = actual
    return observed


def run_local_conversion_contract(
    campaign_path: Path = CAMPAIGN_PATH,
    result_path: Path = RESULT_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    campaign = _load_campaign(campaign_path)
    print("[1/5] Verification du perimetre, des unites et des hashes topologiques", flush=True)
    topology_hashes = _verify_topology_boundary(campaign)

    probe = campaign["structural_probe"]
    timestep_s = float(probe["timestep_s"])
    samples = int(probe["samples"])
    seed = int(probe["seed"])
    time = np.arange(samples, dtype=np.float64) * timestep_s
    position = np.column_stack((time, -time))
    velocity = np.column_stack((np.ones(samples), -np.ones(samples)))

    print("[2/5] Exercice des deux sorties FeCO sans choisir entre elles", flush=True)
    graded_parameters = FeCOTransferParameters(
        output_mode="graded_activity",
        position_gain=np.asarray([2.0, -2.0]),
        velocity_gain=np.asarray([0.25, -0.25]),
        bias=np.asarray([0.0, 0.0]),
    )
    event_parameters = FeCOTransferParameters(
        output_mode="event_intensity_hz",
        position_gain=np.asarray([20.0, -20.0]),
        velocity_gain=np.asarray([5.0, -5.0]),
        bias=np.asarray([10.0, 10.0]),
    )
    graded = feco_kinematics_to_native_output(position, velocity, graded_parameters)
    intensity = feco_kinematics_to_native_output(position, velocity, event_parameters)
    events_first = event_intensity_to_counts(intensity, timestep_s=timestep_s, seed=seed)
    events_second = event_intensity_to_counts(intensity, timestep_s=timestep_s, seed=seed)
    if not np.array_equal(events_first, events_second):
        raise LocalConversionError("seeded event conversion is not deterministic")

    print("[3/5] Exercice separe evenements moteurs -> force biologique", flush=True)
    motor_events = np.zeros((samples, 2), dtype=np.int64)
    motor_events[samples // 4, :] = 1
    motor_parameters = MotorTwitchParameters(
        force_per_event_uN=np.asarray([1.0, 1.0]),
        rise_time_s=np.asarray([0.003, 0.003]),
        decay_time_s=np.asarray([0.012, 0.012]),
    )
    force = motor_events_to_force_uN(
        motor_events, motor_parameters, timestep_s=timestep_s
    )
    event_index = samples // 4
    if np.any(force[: event_index + 1] != 0.0):
        raise LocalConversionError("motor force is not causal")
    if not np.allclose(force[:, 0], force[:, 1]):
        raise LocalConversionError("identical homolog probes produced asymmetric force")

    print("[4/5] Exercice du pont force -> commande MuJoCo comme etape distincte", flush=True)
    bridge = ActuatorBridgeParameters(
        command_per_uN=np.asarray([0.01, 0.02]),
        command_offset=np.asarray([0.0, 0.0]),
    )
    command = force_uN_to_actuator_command(force, bridge)
    if not np.allclose(command[:, 0], force[:, 0] * 0.01):
        raise LocalConversionError("force-to-command stage changed its declared gain")
    if not np.allclose(command[:, 1], force[:, 1] * 0.02):
        raise LocalConversionError("force-to-command stage changed its declared gain")

    summary = {
        "schema_version": 1,
        "campaign_id": campaign["id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "claim_label": campaign["claim_label"],
        "status": "pass_contract_only_values_unresolved",
        "campaign_sha256": _sha256_file(campaign_path),
        "topology_hashes": topology_hashes,
        "probe": {
            "samples": samples,
            "timestep_s": timestep_s,
            "seed": seed,
            "feco_modes_exercised": ["graded_activity", "event_intensity_hz"],
            "sampled_event_count": int(events_first.sum()),
            "graded_output_shape": list(graded.shape),
            "motor_event_count": int(motor_events.sum()),
            "motor_force_peak_uN": force.max(axis=0).tolist(),
            "actuator_command_peak": command.max(axis=0).tolist(),
        },
        "accounting": {
            "scoped_feco_neurons": 36,
            "scoped_motor_neurons": 10,
            "promoted_parameter_values": 0,
            "optimized_parameters": 0,
            "behavior_targets_exposed": 0,
            "topology_changes": 0,
        },
        "accepted_claims": [
            "FeCO graded activity and event intensity have separate executable output contracts.",
            "Seeded intensity-to-event conversion is reproducible and unit-explicit.",
            "Motor events convert causally to biological force before a separate force-to-actuator surrogate bridge.",
            "The accepted proprioception and motor topology hashes remain unchanged.",
        ],
        "forbidden_claims": [
            "FeCO event or graded representation has been selected scientifically.",
            "Any FeCO, motor-twitch or force-to-actuator value has been calibrated.",
            "The selected MaleCNS motor body IDs have been mapped to fast, intermediate or slow experimental cells.",
            "A movement or named behavior has been fitted, inspected or reproduced.",
        ],
        "open_blockers": campaign["open_blockers"],
        "next_action": campaign["next_action"],
    }
    summary["semantic_result_sha256"] = _canonical_hash(
        {key: value for key, value in summary.items() if key != "generated_at"}
    )
    output_root.mkdir(parents=True, exist_ok=True)
    artifact_path = output_root / "summary.json"
    artifact_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    try:
        artifact_ref = str(artifact_path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        artifact_ref = str(artifact_path)

    compact = {
        "schema_version": 1,
        "id": "runner_result.front_leg_local_conversion_contract.v0",
        "campaign_id": campaign["id"],
        "target_id": campaign["target_id"],
        "status": summary["status"],
        "claim_label": campaign["claim_label"],
        "command": "local_conversion_contract.bat",
        "campaign_sha256": summary["campaign_sha256"],
        "semantic_result_sha256": summary["semantic_result_sha256"],
        "topology_hashes": topology_hashes,
        "accounting": summary["accounting"],
        "behavior_targets": [],
        "artifact_ref": artifact_ref,
        "accepted_claims": summary["accepted_claims"],
        "forbidden_claims": summary["forbidden_claims"],
        "open_blockers": summary["open_blockers"],
        "next_action": summary["next_action"],
    }
    result_path.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")
    print("[5/5] Resume", flush=True)
    print("[OK] 2 sorties FeCO exercees; aucun choix scientifique", flush=True)
    print("[OK] evenements moteurs -> force -> commande: frontieres distinctes", flush=True)
    print("[OK] 0 valeur promue, 0 optimisation, 0 comportement, 0 changement topologique", flush=True)
    print(f"[HASH] {summary['semantic_result_sha256']}", flush=True)
    return compact


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate typed front-leg local conversion contracts without calibration"
    )
    parser.add_argument("--campaign", type=Path, default=CAMPAIGN_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    run_local_conversion_contract(args.campaign, output_root=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

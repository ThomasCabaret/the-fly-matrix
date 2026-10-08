from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .ledger import ROOT


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "motor-spike-force-source-contract-v0.yaml"
RUNNER_PATH = ROOT / "calibration" / "runner" / "motor-spike-force-source-contract-v0.yaml"
OUTPUT_ROOT = ROOT / "data" / "derived" / "calibration" / "motor-spike-force-source-contract-v0"


class MotorSourceContractError(ValueError):
    """Raised when the pinned motor source contract drifts or is overclaimed."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MotorSourceContractError(f"{path} must contain a YAML mapping")
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


def load_campaign(path: Path = CAMPAIGN_PATH) -> dict[str, Any]:
    campaign = _load_yaml(path)
    if campaign.get("primary_class") != "evidence_transfer":
        raise MotorSourceContractError("motor source contract must be evidence_transfer")
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise MotorSourceContractError("motor source contract must remain diagnostic_only")
    if campaign.get("behavior_targets") != []:
        raise MotorSourceContractError("motor source contract cannot expose behavior targets")
    if campaign.get("topology_changes_allowed") is not False:
        raise MotorSourceContractError("motor source contract cannot change topology")
    capacity = campaign.get("capacity_policy", {})
    if capacity.get("optimized_parameters") != 0 or capacity.get("promoted_parameter_values") != 0:
        raise MotorSourceContractError("source inspection cannot fit or promote parameters")
    source_files = campaign.get("inputs", {}).get("source_files")
    if not isinstance(source_files, list) or len(source_files) != 5:
        raise MotorSourceContractError("five exact Zenodo source snapshots are required")
    return campaign


def verify_sources(campaign: Mapping[str, Any]) -> list[dict[str, str]]:
    verified: list[dict[str, str]] = []
    for item in campaign["inputs"]["source_files"]:
        path = ROOT / str(item["path"])
        if not path.is_file():
            raise MotorSourceContractError(f"missing pinned source snapshot {path}")
        actual = _sha256(path)
        expected = str(item["sha256"])
        if actual != expected:
            raise MotorSourceContractError(f"source hash drift for {path}: {actual} != {expected}")
        verified.append({"path": str(item["path"]), "sha256": actual})
    return verified


def _inclusive_range(expression: str) -> list[int]:
    values: list[int] = []
    for token in expression.replace(" ", "").split(","):
        if not token:
            continue
        parts = token.split(":")
        if len(parts) == 1:
            values.append(int(parts[0]))
        elif len(parts) == 2:
            start, stop = map(int, parts)
            step = 1 if stop >= start else -1
            values.extend(range(start, stop + step, step))
        else:
            raise MotorSourceContractError(f"unsupported MATLAB range expression {expression!r}")
    if not values or len(values) != len(set(values)):
        raise MotorSourceContractError(f"empty or duplicate trial range {expression!r}")
    return values


def parse_cohort(source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        # Keep rejected alternatives in the snapshot for provenance, but do
        # not mistake a trailing MATLAB comment for executable trial scope.
        stripped = line.split("%", 1)[0].strip()
        if stripped.startswith("%") or "=" not in stripped:
            continue
        table = None
        if stripped.startswith("T_fastinter{"):
            table = "fastinter"
        elif stripped.startswith("T_slow{"):
            table = "slow"
        if table is None:
            continue
        strings = re.findall(r"'([^']*)'", stripped)
        brackets = re.findall(r"\[([^\]]*)\]", stripped)
        if len(strings) < 5 or len(brackets) < 2:
            raise MotorSourceContractError(f"cannot parse active cohort row {line_number}")
        trials = _inclusive_range(brackets[-1])
        rows.append(
            {
                "cell_id": strings[0],
                "genotype": strings[1],
                "cell_label": strings[2],
                "protocol": strings[3],
                "positions_expression": brackets[-2].strip(),
                "trial_expression": brackets[-1].strip(),
                "trial_first": min(trials),
                "trial_last": max(trials),
                "trial_count": len(trials),
                "source_table": table,
                "source_line": line_number,
            }
        )
    if len(rows) != len({item["cell_id"] for item in rows}):
        raise MotorSourceContractError("active source cohort contains duplicate cell IDs")
    return rows


def inspect_force_rules(
    force_source: str,
    force_rate_source: str,
    calibration_source: str,
    readme_source: str,
) -> dict[str, Any]:
    constants = [
        float(value)
        for value in re.findall(r"\bk\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*;\s*%N/m", force_source)
    ]
    if constants != [0.2234, 0.2234]:
        raise MotorSourceContractError(f"unexpected force-display constants {constants}")
    required_force_fragments = (
        "NumSpikes<=30",
        "PeakErr>0",
        "Position == 0",
        "FiringRate-T_FvsFiringRate_0.Rest",
        "Step>13",
        "*0.5",
        "@linethrough0",
    )
    missing_force = [item for item in required_force_fragments if item not in force_source]
    if missing_force:
        raise MotorSourceContractError(f"force source lost required rules: {missing_force}")
    required_rate_fragments = ("NumSpikes", "Peak", "FiringRate", "Rest", "Step>13", "*0.5")
    missing_rate = [item for item in required_rate_fragments if item not in force_rate_source]
    if missing_rate:
        raise MotorSourceContractError(f"force/rate source lost required rules: {missing_rate}")
    calibration_fragments = (
        "Probe4(:,1) = Probe4(:,1)*1E-6",
        "Probe4(:,2) = Probe4(:,2)*1E-7",
        "Probe4(:,2)*9.8",
        "polyfit",
        "xlabel('m')",
        "ylabel('N')",
    )
    missing_calibration = [item for item in calibration_fragments if item not in calibration_source]
    if missing_calibration:
        raise MotorSourceContractError(
            f"force-probe calibration source lost unit rules: {missing_calibration}"
        )
    readme_fragments = (
        "<ProtocolName>_Raw_<CellID>_<Trial number>.mat",
        "recorded inputs in natural units (pA, mV, etc)",
        "Spike detection and tracking of the force probe",
    )
    missing_readme = [item for item in readme_fragments if item not in readme_source]
    if missing_readme:
        raise MotorSourceContractError(f"README lost raw-data contract: {missing_readme}")
    return {
        "force_probe_spring_constant_N_per_m": constants[0],
        "fast_inter_filter": {
            "maximum_spikes": 30,
            "peak_error_positive": True,
            "probe_position": 0,
        },
        "slow_count_proxy": {
            "formula": "(FiringRate-Rest)*0.5",
            "stimulus_duration_s": 0.5,
            "step_filter": "Step>13",
        },
        "fit_form": "least_squares_line_through_origin",
        "probe_calibration": {
            "displacement_input_scale_to_m": 1e-6,
            "mass_input_scale_to_kg": 1e-7,
            "gravity_m_per_s2": 9.8,
            "spring_fit": "polyfit_degree_1",
            "declared_axes": ["m", "N"],
        },
        "raw_file_naming": "<ProtocolName>_Raw_<CellID>_<Trial number>.mat",
        "raw_trial_claim": "stimulus_parameters_recorded_inputs_spike_detection_and_force_probe_tracking",
        "twitch_time_course_fit_defined_by_these_five_files": False,
    }


def run(
    campaign_path: Path = CAMPAIGN_PATH,
    runner_path: Path = RUNNER_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    campaign = load_campaign(campaign_path)
    print("[1/5] Verifying five exact Zenodo source snapshots", flush=True)
    verified = verify_sources(campaign)
    by_role = {str(item["role"]): ROOT / str(item["path"]) for item in campaign["inputs"]["source_files"]}
    print("[2/5] Reconstructing the active source cohort and trial ranges", flush=True)
    cohort = parse_cohort(by_role["dataset3_cohort"].read_text(encoding="utf-8"))
    class_counts: dict[str, int] = {}
    for row in cohort:
        label = str(row["cell_label"])
        class_counts[label] = class_counts.get(label, 0) + 1
    expected_counts = {"fast": 7, "intermediate": 7, "slow": 9}
    if class_counts != expected_counts:
        raise MotorSourceContractError(f"source class counts differ: {class_counts}")

    selected_ids = campaign["pilot_scope"]["selected_cell_ids"]
    cohort_by_id = {str(row["cell_id"]): row for row in cohort}
    if set(selected_ids.values()) - set(cohort_by_id):
        raise MotorSourceContractError("a selected pilot cell is absent from the source cohort")
    pilot = {
        class_name: dict(cohort_by_id[cell_id])
        for class_name, cell_id in selected_ids.items()
    }
    pilot_trials = sum(int(item["trial_count"]) for item in pilot.values())
    if pilot_trials != int(campaign["pilot_scope"]["expected_selected_trials"]):
        raise MotorSourceContractError("selected pilot trial accounting drifted")

    print("[3/5] Locking force, filtering, duration and probe-calibration rules", flush=True)
    rules = inspect_force_rules(
        by_role["force_per_spike_plot"].read_text(encoding="utf-8"),
        by_role["force_per_spike_and_rate"].read_text(encoding="utf-8"),
        by_role["force_probe_calibration"].read_text(encoding="utf-8"),
        by_role["readme"].read_text(encoding="utf-8"),
    )
    print("[4/5] Enforcing value-free and behavior-naive interpretation", flush=True)
    semantic = {
        "source_hashes": verified,
        "cohort_cells": len(cohort),
        "class_counts": class_counts,
        "pilot": pilot,
        "selected_pilot_trials": pilot_trials,
        "rules": rules,
        "optimized_parameters": 0,
        "promoted_parameter_values": 0,
        "body_class_assignments_selected": 0,
        "behavior_targets_exposed": 0,
        "topology_changes": 0,
    }
    summary = {
        "schema_version": 1,
        "id": "runner_result.motor_spike_force_source_contract.v0",
        "generated_at": datetime.now(UTC).isoformat(),
        "campaign_id": campaign["id"],
        "campaign_sha256": _sha256(campaign_path),
        "semantic_result_sha256": _canonical_hash(semantic),
        "status": "accepted_source_contract_raw_fit_blocked",
        "accounting": semantic,
        "interpretation": {
            "source_cohort_and_filters_reconstructed": True,
            "raw_variable_schema_identified": False,
            "twitch_kernel_identified": False,
            "body_level_crosswalk_resolved": False,
            "next_action": "inspect_exact_archives_then_version_variable_parser_and_fit",
        },
    }
    print("[5/5] Writing compact lineage and derived cohort inventory", flush=True)
    output_root.mkdir(parents=True, exist_ok=True)
    with (output_root / "source-cohort.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(cohort[0]))
        writer.writeheader()
        writer.writerows(cohort)
    (output_root / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    runner_path.parent.mkdir(parents=True, exist_ok=True)
    runner_path.write_text(yaml.safe_dump(summary, sort_keys=False), encoding="utf-8")
    print(
        f"[PASS] {len(cohort)} cells, {pilot_trials} selected trials, zero values promoted",
        flush=True,
    )
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

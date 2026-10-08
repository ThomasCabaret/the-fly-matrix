from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

import yaml

from .ledger import ROOT


CAMPAIGN_PATH = ROOT / "calibration" / "campaigns" / "motor-spike-force-pilot-inventory-v0.yaml"
ENSEMBLE_PATH = ROOT / "calibration" / "evidence" / "front-leg-motor-class-ensemble-v0.yaml"
RUNNER_PATH = ROOT / "calibration" / "runner" / "motor-spike-force-pilot-inventory-v0.yaml"
OUTPUT_ROOT = ROOT / "runs" / "calibration" / "motor-spike-force-pilot-inventory-v0"


class MotorPilotInventoryError(ValueError):
    """Raised when the motor pilot cannot be inventoried without ambiguity."""


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MotorPilotInventoryError(f"{path} must contain a YAML mapping")
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
    if campaign.get("primary_class") != "local_interface":
        raise MotorPilotInventoryError("motor pilot must remain a local_interface campaign")
    if campaign.get("optimization_exposure") != "diagnostic_only":
        raise MotorPilotInventoryError("archive inventory cannot optimize parameters")
    if campaign.get("behavior_targets") != []:
        raise MotorPilotInventoryError("motor pilot inventory cannot expose behavior targets")
    if campaign.get("topology_changes_allowed") is not False:
        raise MotorPilotInventoryError("motor pilot inventory cannot change topology")
    if campaign.get("capacity_policy", {}).get("optimized_parameters") != 0:
        raise MotorPilotInventoryError("schema inventory must optimize zero parameters")
    archives = campaign.get("inputs", {}).get("archives")
    if not isinstance(archives, list) or len(archives) != 3:
        raise MotorPilotInventoryError("exactly one archive per motor-unit class is required")
    classes = {str(item.get("functional_class")) for item in archives}
    expected = {"fast_81A07", "intermediate_22A08", "slow_35C09"}
    if classes != expected:
        raise MotorPilotInventoryError(f"motor class coverage differs: {classes} != {expected}")
    return campaign


def load_class_ensemble(path: Path = ENSEMBLE_PATH) -> dict[str, Any]:
    ensemble = _load_yaml(path)
    bodies = ensemble.get("members")
    classes = ensemble.get("admissible_classes")
    if not isinstance(bodies, list) or len(bodies) != 10:
        raise MotorPilotInventoryError("class ensemble must account for ten MaleCNS bodies")
    if len({int(item["body_id"]) for item in bodies}) != 10:
        raise MotorPilotInventoryError("class ensemble body IDs must be unique")
    expected = {"fast_81A07", "intermediate_22A08", "slow_35C09"}
    if set(classes or []) != expected:
        raise MotorPilotInventoryError("class ensemble must retain all three article classes")
    for item in bodies:
        if set(item.get("candidate_classes", [])) != expected:
            raise MotorPilotInventoryError(
                f"body {item.get('body_id')} silently lost a motor-unit class"
            )
        if item.get("selected_class") is not None:
            raise MotorPilotInventoryError("v0 may not select a body-to-class crosswalk")
    expected_count = len(expected) ** len(bodies)
    if ensemble.get("factorized_assignment_upper_bound") != expected_count:
        raise MotorPilotInventoryError("class-assignment upper-bound accounting is inconsistent")
    return ensemble


def _safe_member_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or normalized.startswith("/") or path.is_absolute():
        raise MotorPilotInventoryError(f"unsafe absolute ZIP member {name!r}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise MotorPilotInventoryError(f"unsafe ZIP member path {name!r}")
    if path.parts and ":" in path.parts[0]:
        raise MotorPilotInventoryError(f"unsafe drive-qualified ZIP member {name!r}")
    return path.as_posix()


def _header_format(name: str, header: bytes) -> str:
    suffix = PurePosixPath(name).suffix.lower()
    if header.startswith(b"MATLAB 5.0 MAT-file"):
        return "matlab_v5"
    if header.startswith(b"\x89HDF\r\n\x1a\n"):
        return "hdf5_or_matlab_v73"
    if header.startswith((b"ABF ", b"ABF2")):
        return "axon_abf"
    return {
        ".mat": "matlab_unknown_generation",
        ".abf": "axon_abf_unknown_header",
        ".csv": "delimited_text",
        ".tsv": "delimited_text",
        ".txt": "plain_text",
        ".xlsx": "excel_openxml",
        ".xls": "excel_binary",
        ".nwb": "nwb_unknown_header",
    }.get(suffix, "unclassified")


def inspect_zip(path: Path) -> dict[str, Any]:
    """Inspect the central directory and tiny headers without extracting files."""
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as error:
        raise MotorPilotInventoryError(f"cannot open {path.name}: {error}") from error
    with archive:
        infos = archive.infolist()
        if not infos:
            raise MotorPilotInventoryError(f"{path.name} is an empty ZIP archive")
        normalized_names: list[str] = []
        members: list[dict[str, Any]] = []
        suffix_counts: Counter[str] = Counter()
        format_counts: Counter[str] = Counter()
        for info in infos:
            normalized = _safe_member_name(info.filename)
            normalized_names.append(normalized.casefold())
            encrypted = bool(info.flag_bits & 0x1)
            if encrypted:
                raise MotorPilotInventoryError(
                    f"encrypted ZIP member cannot be audited: {info.filename!r}"
                )
            suffix = PurePosixPath(normalized).suffix.lower() or "<none>"
            suffix_counts[suffix] += 1
            if info.is_dir():
                detected = "directory"
                header_bytes = 0
            else:
                with archive.open(info, "r") as stream:
                    header = stream.read(128)
                header_bytes = len(header)
                detected = _header_format(normalized, header)
            format_counts[detected] += 1
            ratio = None
            if info.compress_size > 0:
                ratio = float(info.file_size / info.compress_size)
            members.append(
                {
                    "name": normalized,
                    "suffix": suffix,
                    "uncompressed_bytes": int(info.file_size),
                    "compressed_bytes": int(info.compress_size),
                    "compression_ratio": ratio,
                    "header_bytes_read": header_bytes,
                    "detected_format": detected,
                }
            )
        duplicates = sorted(
            name for name, count in Counter(normalized_names).items() if count > 1
        )
        if duplicates:
            raise MotorPilotInventoryError(
                f"duplicate normalized ZIP member names in {path.name}: {duplicates}"
            )
        data_like = sum(
            count
            for fmt, count in format_counts.items()
            if fmt not in {"directory", "plain_text", "unclassified"}
        )
        return {
            "archive": path.name,
            "members_total": len(members),
            "files_total": sum(not info.is_dir() for info in infos),
            "uncompressed_bytes": sum(int(info.file_size) for info in infos),
            "compressed_bytes": sum(int(info.compress_size) for info in infos),
            "suffix_counts": dict(sorted(suffix_counts.items())),
            "format_counts": dict(sorted(format_counts.items())),
            "data_like_members": data_like,
            "members": members,
            "extracted_files": 0,
        }


def _archive_path(item: Mapping[str, Any]) -> Path:
    return ROOT / str(item["path"])


def run(
    campaign_path: Path = CAMPAIGN_PATH,
    ensemble_path: Path = ENSEMBLE_PATH,
    runner_path: Path = RUNNER_PATH,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    campaign = load_campaign(campaign_path)
    ensemble = load_class_ensemble(ensemble_path)
    campaign_hash = _sha256(campaign_path)
    ensemble_hash = _sha256(ensemble_path)
    archives = campaign["inputs"]["archives"]
    print("[1/4] Verifying the three preregistered motor archives", flush=True)
    blocked: list[dict[str, str]] = []
    verified: list[tuple[Mapping[str, Any], Path]] = []
    for item in archives:
        path = _archive_path(item)
        label = str(item["functional_class"])
        if not path.is_file():
            print(f"      [MISSING] {label}: {path.name}", flush=True)
            blocked.append({"functional_class": label, "reason": "missing_file"})
            continue
        size = path.stat().st_size
        if size != int(item["expected_bytes"]):
            raise MotorPilotInventoryError(
                f"size drift for {path}: {size} != {item['expected_bytes']}"
            )
        actual_hash = _sha256(path)
        if actual_hash != str(item["sha256"]):
            raise MotorPilotInventoryError(f"SHA-256 drift for {path}: {actual_hash}")
        print(f"      [VERIFIED] {label}: {path.name}", flush=True)
        verified.append((item, path))

    base_accounting = {
        "campaign_sha256": campaign_hash,
        "class_ensemble_sha256": ensemble_hash,
        "archives_expected": 3,
        "archives_verified": len(verified),
        "archives_blocked": blocked,
        "article_classes_expected": 3,
        "article_classes_accounted": 3,
        "malecns_bodies_accounted": len(ensemble["members"]),
        "body_class_assignments_selected": 0,
        "factorized_assignment_upper_bound": ensemble["factorized_assignment_upper_bound"],
        "optimized_parameters": 0,
        "parameter_values_promoted": 0,
        "behavior_targets_exposed": 0,
        "topology_changes": 0,
    }
    if blocked:
        summary = {
            "schema_version": 1,
            "id": "runner_result.motor_spike_force_pilot_inventory.v0",
            "generated_at": datetime.now(UTC).isoformat(),
            "campaign_id": campaign["id"],
            "status": "blocked_missing_authenticated_archives",
            "semantic_result_sha256": _canonical_hash(base_accounting),
            "accounting": base_accounting,
            "interpretation": {
                "archive_schema_inspected": False,
                "spike_force_fit_completed": False,
                "body_level_crosswalk_resolved": False,
                "next_action": "acquire_motor_pilot_with_explicit_large_flag_then_rerun_inventory",
            },
        }
        runner_path.parent.mkdir(parents=True, exist_ok=True)
        runner_path.write_text(yaml.safe_dump(summary, sort_keys=False), encoding="utf-8")
        print(f"[BLOCKED] {len(blocked)}/3 archives are absent", flush=True)
        return summary

    print("[2/4] Reading ZIP directories and bounded 128-byte member headers", flush=True)
    inventories = []
    for index, (item, path) in enumerate(verified, start=1):
        print(f"      [{index}/3] {item['functional_class']}: {path.name}", flush=True)
        inventory = inspect_zip(path)
        inventory["functional_class"] = str(item["functional_class"])
        inventories.append(inventory)
    print("[3/4] Checking archive, class and body uncertainty accounting", flush=True)
    semantic = {
        **base_accounting,
        "archive_members": sum(item["members_total"] for item in inventories),
        "data_like_members": sum(item["data_like_members"] for item in inventories),
        "extracted_files": 0,
    }
    status = "completed_schema_inventory_fit_not_started"
    summary = {
        "schema_version": 1,
        "id": "runner_result.motor_spike_force_pilot_inventory.v0",
        "generated_at": datetime.now(UTC).isoformat(),
        "campaign_id": campaign["id"],
        "status": status,
        "semantic_result_sha256": _canonical_hash(
            {"accounting": semantic, "archive_inventories": inventories}
        ),
        "accounting": semantic,
        "archive_inventories": inventories,
        "interpretation": {
            "archive_schema_inspected": True,
            "spike_force_fit_completed": False,
            "body_level_crosswalk_resolved": False,
            "next_action": "version_the_observed_variable_schema_and_preregister_class_level_kernel_fit",
        },
    }
    print("[4/4] Writing compact lineage and ignored detailed inventory", flush=True)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "inventory.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    compact = {key: value for key, value in summary.items() if key != "archive_inventories"}
    compact["artifact_ref"] = str((output_root / "inventory.json").relative_to(ROOT)).replace(
        "\\", "/"
    )
    runner_path.parent.mkdir(parents=True, exist_ok=True)
    runner_path.write_text(yaml.safe_dump(compact, sort_keys=False), encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        result = run()
    except (MotorPilotInventoryError, OSError, KeyError, zipfile.BadZipFile) as error:
        print(f"[ERROR] {error}", file=sys.stderr, flush=True)
        return 1
    if result["status"].startswith("blocked_"):
        return 2
    print("[DONE] Archive schemas are inventoried; no fit or class assignment was selected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.request
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd
import yaml

from .ledger import ROOT


SUBSET_PATH = (
    ROOT / "calibration" / "evidence" / "front-leg-local-source-subsets-v0.yaml"
)
DATASETS_PATH = ROOT / "ledger" / "datasets.yaml"
OUTPUT_ROOT = ROOT / "data" / "derived" / "calibration" / "front-leg-local-source-v0"
MOTOR_ROOT = ROOT / "data" / "raw" / "calibration" / "front-leg-local-v0" / "motor"
LARGE_FILE_BYTES = 100_000_000
DRYAD_HOST = "datadryad.org"


class LocalSourceDataError(RuntimeError):
    """Raised when a preregistered local source cannot be reproduced safely."""


@dataclass(frozen=True)
class SourceFile:
    dataset_id: str
    functional_class: str
    path: Path
    url: str
    expected_bytes: int
    sha256: str
    group: str
    optional_large: bool


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise LocalSourceDataError(f"{path} must contain a YAML mapping")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _dataset_index(path: Path = DATASETS_PATH) -> dict[str, Mapping[str, Any]]:
    datasets = _load_yaml(path).get("datasets")
    if not isinstance(datasets, list):
        raise LocalSourceDataError("ledger/datasets.yaml must contain a datasets list")
    result: dict[str, Mapping[str, Any]] = {}
    for item in datasets:
        if not isinstance(item, Mapping) or not item.get("id"):
            raise LocalSourceDataError("each dataset entry must be an identified mapping")
        dataset_id = str(item["id"])
        if dataset_id in result:
            raise LocalSourceDataError(f"duplicate dataset id {dataset_id}")
        result[dataset_id] = item
    return result


def build_source_plan(
    subset_path: Path = SUBSET_PATH,
    datasets_path: Path = DATASETS_PATH,
) -> list[SourceFile]:
    subset = _load_yaml(subset_path)
    if subset.get("scientific_boundary", {}).get("behavior_targets") != []:
        raise LocalSourceDataError("local source acquisition must remain behavior-naive")
    if subset.get("scientific_boundary", {}).get("topology_changes_allowed") is not False:
        raise LocalSourceDataError("source acquisition cannot change topology")

    datasets = _dataset_index(datasets_path)
    plan: list[SourceFile] = []
    for item in subset["feco_calcium_subset"]["files"]:
        dataset_id = str(item["dataset_id"])
        if dataset_id not in datasets:
            raise LocalSourceDataError(f"unknown FeCO dataset id {dataset_id}")
        dataset = datasets[dataset_id]
        plan.append(
            SourceFile(
                dataset_id=dataset_id,
                functional_class=str(item["functional_class"]),
                path=ROOT / str(dataset["path"]),
                url=str(dataset["url"]),
                expected_bytes=int(dataset["expected_bytes"]),
                sha256=str(dataset["sha256"]),
                group="feco",
                optional_large=False,
            )
        )

    for item in subset["motor_spike_force_pilot"]["files"]:
        expected_bytes = int(item["expected_bytes"])
        name = str(item["name"])
        plan.append(
            SourceFile(
                dataset_id=f"motor-dryad-file-{item['dryad_file_id']}",
                functional_class=str(item["functional_class"]),
                path=MOTOR_ROOT / name,
                url=str(item["url"]),
                expected_bytes=expected_bytes,
                sha256=str(item["sha256"]),
                group="motor",
                optional_large=expected_bytes >= LARGE_FILE_BYTES,
            )
        )
    if sum(item.expected_bytes for item in plan if item.group == "feco") != int(
        subset["feco_calcium_subset"]["total_expected_bytes"]
    ):
        raise LocalSourceDataError("FeCO manifest byte accounting is inconsistent")
    if sum(item.expected_bytes for item in plan if item.group == "motor") != int(
        subset["motor_spike_force_pilot"]["selected_total_expected_bytes"]
    ):
        raise LocalSourceDataError("motor manifest byte accounting is inconsistent")
    return plan


class _SafeAuthorizationRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never forward a Dryad bearer credential to presigned object storage."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        old_host = urllib.parse.urlparse(req.full_url).netloc.lower()
        new_host = urllib.parse.urlparse(newurl).netloc.lower()
        if old_host != new_host:
            redirected.remove_header("Authorization")
        return redirected


def _dotenv_value(name: str, path: Path = ROOT / ".env") -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == name and value.strip():
            return value.strip().strip('"').strip("'")
    return None


def _dryad_token() -> str | None:
    return os.environ.get("DRYAD_BEARER_TOKEN") or _dotenv_value("DRYAD_BEARER_TOKEN")


def verify_source_file(source: SourceFile) -> tuple[bool, str]:
    if not source.path.is_file():
        return False, "missing"
    size = source.path.stat().st_size
    if size != source.expected_bytes:
        return False, f"size_mismatch:{size}"
    digest = _sha256(source.path)
    if digest != source.sha256:
        return False, f"sha256_mismatch:{digest}"
    return True, "verified"


def _format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB")
    amount = float(value)
    for unit in units:
        if amount < 1024.0 or unit == units[-1]:
            return f"{amount:.2f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024.0
    raise AssertionError("unreachable")


def _download(source: SourceFile, *, dryad_token: str | None) -> None:
    source.path.parent.mkdir(parents=True, exist_ok=True)
    part = source.path.with_name(source.path.name + ".part")
    if part.exists():
        part.unlink()
    headers = {"User-Agent": "TheFlyMatrix-local-source-data/1"}
    is_dryad = urllib.parse.urlparse(source.url).netloc.lower() == DRYAD_HOST
    if is_dryad:
        if not dryad_token:
            raise LocalSourceDataError("Dryad file bytes require DRYAD_BEARER_TOKEN")
        headers["Authorization"] = f"Bearer {dryad_token}"
    request = urllib.request.Request(source.url, headers=headers)
    opener = urllib.request.build_opener(_SafeAuthorizationRedirectHandler())
    started = time.monotonic()
    last_percent = -10
    with opener.open(request, timeout=60) as response, part.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            downloaded = output.tell()
            percent = int(downloaded * 100 / source.expected_bytes)
            if percent >= last_percent + 10 or downloaded == source.expected_bytes:
                elapsed = max(time.monotonic() - started, 0.001)
                speed = downloaded / elapsed
                print(
                    f"      {min(percent, 100):3d}%  {_format_bytes(downloaded)} / "
                    f"{_format_bytes(source.expected_bytes)}  ({_format_bytes(int(speed))}/s)",
                    flush=True,
                )
                last_percent = percent
    if part.stat().st_size != source.expected_bytes:
        raise LocalSourceDataError(
            f"downloaded size for {source.dataset_id} is {part.stat().st_size}, "
            f"expected {source.expected_bytes}; .part retained"
        )
    digest = _sha256(part)
    if digest != source.sha256:
        raise LocalSourceDataError(
            f"SHA-256 mismatch for {source.dataset_id}: {digest}; .part retained"
        )
    shutil.move(str(part), str(source.path))


def acquire_sources(
    plan: Iterable[SourceFile],
    *,
    include_large_motor_pilot: bool,
    verify_only: bool,
    dryad_token: str | None,
) -> list[dict[str, Any]]:
    plan = list(plan)
    records: list[dict[str, Any]] = []
    for index, source in enumerate(plan, start=1):
        selected = not source.optional_large or include_large_motor_pilot
        print(
            f"[{index}/{len(plan)}] {source.group}/{source.functional_class}: "
            f"{source.path.name} ({_format_bytes(source.expected_bytes)})",
            flush=True,
        )
        verified, status = verify_source_file(source)
        if verified:
            print("      verified: exact size and SHA-256", flush=True)
        elif not selected:
            status = "deferred_large_not_requested"
            print("      deferred: use --include-large-motor-pilot to acquire", flush=True)
        elif urllib.parse.urlparse(source.url).netloc.lower() == DRYAD_HOST and not dryad_token:
            status = "blocked_missing_dryad_bearer_token"
            print("      blocked: set DRYAD_BEARER_TOKEN in .env or the environment", flush=True)
        elif verify_only:
            status = f"required_but_{status}"
            print(f"      not acquired in verify-only mode: {status}", flush=True)
        else:
            print(f"      acquiring from {source.url}", flush=True)
            _download(source, dryad_token=dryad_token)
            verified, status = verify_source_file(source)
            if not verified:
                raise LocalSourceDataError(f"post-download verification failed: {status}")
            print("      downloaded and verified", flush=True)
        records.append(
            {
                "dataset_id": source.dataset_id,
                "functional_class": source.functional_class,
                "group": source.group,
                "path": str(source.path.relative_to(ROOT)).replace("\\", "/"),
                "expected_bytes": source.expected_bytes,
                "optional_large": source.optional_large,
                "selected": selected,
                "status": status,
                "sha256": source.sha256,
            }
        )
    return records


def _column_summary(series: pd.Series) -> dict[str, Any]:
    result: dict[str, Any] = {
        "dtype": str(series.dtype),
        "null_count": int(series.isna().sum()),
        "non_null_count": int(series.notna().sum()),
    }
    if pd.api.types.is_numeric_dtype(series):
        clean = series.dropna()
        if not clean.empty:
            result.update(
                {
                    "minimum": float(clean.min()),
                    "maximum": float(clean.max()),
                    "mean": float(clean.mean()),
                    "standard_deviation": float(clean.std(ddof=0)),
                }
            )
    else:
        unique = series.dropna().astype(str).unique()
        result["unique_count"] = int(len(unique))
        if len(unique) <= 20:
            result["values"] = sorted(unique.tolist())
    return result


def inspect_feco_tables(plan: Iterable[SourceFile]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for source in plan:
        if source.group != "feco" or source.path.suffix.lower() != ".parquet":
            continue
        verified, _ = verify_source_file(source)
        if not verified:
            continue
        print(f"[SCHEMA] Inspecting {source.path.name}", flush=True)
        frame = pd.read_parquet(source.path)
        summaries.append(
            {
                "dataset_id": source.dataset_id,
                "functional_class": source.functional_class,
                "rows": int(len(frame)),
                "columns": {name: _column_summary(frame[name]) for name in frame.columns},
                "duplicate_rows": int(frame.duplicated().sum()),
            }
        )
    return summaries


def run(
    *,
    include_large_motor_pilot: bool = False,
    verify_only: bool = False,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    print("[PLAN] Loading preregistered source subset and dataset ledger", flush=True)
    plan = build_source_plan()
    print(
        f"[PLAN] {len(plan)} files; FeCO {_format_bytes(sum(x.expected_bytes for x in plan if x.group == 'feco'))}; "
        f"motor pilot {_format_bytes(sum(x.expected_bytes for x in plan if x.group == 'motor'))}",
        flush=True,
    )
    if not include_large_motor_pilot:
        print("[POLICY] Large motor cell archives are deferred; metadata still acquired.", flush=True)
    dryad_token = _dryad_token()
    print(
        "[AUTH] Dryad bearer token detected." if dryad_token else
        "[AUTH] No Dryad bearer token; public metadata/source code remain usable, file bytes will be blocked.",
        flush=True,
    )
    records = acquire_sources(
        plan,
        include_large_motor_pilot=include_large_motor_pilot,
        verify_only=verify_only,
        dryad_token=dryad_token,
    )
    table_summaries = inspect_feco_tables(plan)
    counts: dict[str, int] = {}
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    summary: dict[str, Any] = {
        "schema_version": 1,
        "id": "runner_result.front_leg_local_source_data.v0",
        "generated_at": datetime.now(UTC).isoformat(),
        "manifest": str(SUBSET_PATH.relative_to(ROOT)).replace("\\", "/"),
        "behavior_targets_exposed": 0,
        "topology_changes": 0,
        "include_large_motor_pilot": include_large_motor_pilot,
        "verify_only": verify_only,
        "accounting": {
            "files_total": len(records),
            "status_counts": counts,
            "feco_tables_inspected": len(table_summaries),
            "feco_rows_inspected": sum(item["rows"] for item in table_summaries),
        },
        "files": records,
        "feco_tables": table_summaries,
        "scientific_interpretation": {
            "calcium_is_native_spiking_evidence": False,
            "calcium_is_runtime_activity_unit": False,
            "body_level_crosswalk_resolved": False,
            "motor_pilot_sufficient_for_promotion": False,
        },
    }
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / "summary.json"
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(
        f"[DONE] {counts}; {len(table_summaries)} FeCO tables, "
        f"{summary['accounting']['feco_rows_inspected']} rows inspected",
        flush=True,
    )
    print(f"[REPORT] {output_path}", flush=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-large-motor-pilot", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        summary = run(
            include_large_motor_pilot=args.include_large_motor_pilot,
            verify_only=args.verify_only,
        )
    except (LocalSourceDataError, OSError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr, flush=True)
        return 1
    if summary["accounting"]["status_counts"].get("blocked_missing_dryad_bearer_token", 0):
        print("[BLOCKED] Required Dryad bytes remain unavailable.", file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

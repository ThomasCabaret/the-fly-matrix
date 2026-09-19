from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from .ledger import ROOT
from .runtime import BasalClampBox, CNSInputBuffer, SparseActivity


OUTPUT = ROOT / "runs" / "wiring-smoke" / "latest.json"
CLAMP_IDS = ("clamp.olfaction", "clamp.gustation")
SMOKE_SEED = 260919


def section(title: str) -> None:
    print(f"\n==> {title}", flush=True)


def _arbitrary_values(box: BasalClampBox, seed: int) -> np.ndarray:
    # These values only exercise data flow. They are not physiological guesses.
    return np.random.default_rng(seed).uniform(0.0, 1.0, len(box.channel_ids))


def _digest(activity: SparseActivity) -> str:
    digest = hashlib.sha256()
    digest.update(activity.body_ids.tobytes())
    digest.update(activity.values.tobytes())
    return digest.hexdigest()


def run_smoke(output: Path = OUTPUT, seed: int = SMOKE_SEED) -> dict[str, object]:
    section("Chargement des boîtes abstraites type A")
    boxes = [BasalClampBox.from_generated_wiring(box_id) for box_id in CLAMP_IDS]
    for box in boxes:
        print(
            f"[OK] {box.box_id}: {len(box.channel_ids):,} instances/canaux, "
            f"{len(box.routes):,} destinations exactes"
        )

    section("Injection déterministe de valeurs arbitraires")
    first_outputs = [box.step(_arbitrary_values(box, seed + index)) for index, box in enumerate(boxes)]
    second_outputs = [box.step(_arbitrary_values(box, seed + index)) for index, box in enumerate(boxes)]
    first = CNSInputBuffer.merge(*first_outputs)
    second = CNSInputBuffer.merge(*second_outputs)
    if not np.array_equal(first.body_ids, second.body_ids) or not np.array_equal(
        first.values, second.values
    ):
        raise RuntimeError("Le rejeu avec la même graine n'est pas déterministe")
    if len(first.body_ids) != 4067:
        raise RuntimeError(f"4067 destinations attendues, {len(first.body_ids)} obtenues")
    print(f"[OK] {len(first.body_ids):,} entrées CNS uniques reçues")
    print("[OK] Rejeu bit-à-bit identique avec la même graine")

    result: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": "structural runtime smoke test with arbitrary non-calibrated values",
        "seed": seed,
        "boxes": [
            {
                "id": box.box_id,
                "adapter_type": box.adapter_type,
                "terminal_box_instances": len(box.channel_ids),
                "exact_routes": len(box.routes),
                "parameter_status": "arbitrary_smoke_only",
            }
            for box in boxes
        ],
        "cns_ingress": {
            "adapter_type": CNSInputBuffer.adapter_type,
            "unique_body_ids": len(first.body_ids),
            "activity_digest": _digest(first),
        },
        "checks": {
            "all_routes_executed": True,
            "deterministic_replay": True,
            "scientific_parameters_selected": False,
            "activity_values_persisted": False,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Compte rendu non scientifique : {output}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Teste le runtime du câblage sans calibration")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--seed", type=int, default=SMOKE_SEED)
    args = parser.parse_args()
    try:
        run_smoke(args.output, args.seed)
    except Exception as exc:
        print(f"\nWIRING_SMOKE_FAILED: {type(exc).__name__}: {exc}")
        return 1
    print("\nWIRING_SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

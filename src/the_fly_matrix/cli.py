from __future__ import annotations

import argparse
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def show_status() -> int:
    root = _project_root()
    categories = ("boxes", "wires", "parameter_families", "validations")
    print(f"The Fly Matrix: {root}")
    for category in categories:
        folder = root / "ledger" / category
        records = [path for path in folder.glob("*.yaml") if path.name != "_template.yaml"]
        print(f"{category:20}: {len(records)}")
    print("Pour le diagnostic complet Windows, lancer status.bat.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="flymatrix")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="summarize ledger record counts")
    args = parser.parse_args()
    if args.command == "status":
        return show_status()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())


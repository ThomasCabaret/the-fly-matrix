from __future__ import annotations

import argparse
from pathlib import Path

from .ledger import SECTOR_LABELS, build_summary, load_ledger, validate_ledger


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def show_status() -> int:
    ledger = load_ledger()
    validate_ledger(ledger)
    summary = build_summary(ledger)
    print(f"The Fly Matrix: {_project_root()}")
    print(f"Avancement global : {summary['overall_progress']}%")
    print(
        "Registre           : "
        f"{summary['counts']['boxes']} boîtes, {summary['counts']['groups']} groupes, "
        f"{summary['counts']['wires']} fils, "
        f"{summary['counts']['parameters']} paramètres, {summary['counts']['validations']} validations"
    )
    print("Secteurs :")
    for sector in sorted(summary["sectors"], key=lambda item: item["name"]):
        print(
            f"  {SECTOR_LABELS.get(sector['id'], sector['name']):28} "
            f"{sector['progress']:3}%  ({len(sector['boxes'])} boîtes, "
            f"{len(sector['groups'])} groupes, {len(sector['wires'])} fils)"
        )
    print("Tableau de bord    : dashboard.bat")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="flymatrix")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="summarize ledger record counts")
    subparsers.add_parser("inventory", help="audit local MaleCNS and FlyBody data")
    subparsers.add_parser("report", help="generate the project dashboard")
    args = parser.parse_args()
    if args.command == "status":
        return show_status()
    if args.command == "inventory":
        from .inventory import main as inventory_main

        return inventory_main()
    if args.command == "report":
        from .report import main as report_main

        return report_main()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

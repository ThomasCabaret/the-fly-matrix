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
    print(f"Câblage exécutable : {summary['wiring_progress']}%")
    print(f"Indice structurel  : {summary['overall_progress']}% (secondaire, hors objectif courant)")
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
            f"{sector['wiring_progress']:3}% câblé  ({len(sector['boxes'])} boîtes, "
            f"{len(sector['groups'])} groupes, {len(sector['wires'])} fils)"
        )
    print("Tableau de bord    : dashboard.bat")
    print("État de reprise    : PROJECT_STATE.md")
    print("Méthodologie       : docs/wiring-methodology.md")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="flymatrix")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="summarize ledger record counts")
    subparsers.add_parser("inventory", help="audit local MaleCNS and FlyBody data")
    subparsers.add_parser("wiring", help="build structural wiring manifests")
    subparsers.add_parser("wiring-smoke", help="execute wired boxes with arbitrary values")
    subparsers.add_parser("report", help="generate the project dashboard")
    subparsers.add_parser("neuprint-audit", help="verify authenticated neuPrint access")
    args = parser.parse_args()
    if args.command == "status":
        return show_status()
    if args.command == "inventory":
        from .inventory import main as inventory_main

        return inventory_main()
    if args.command == "wiring":
        from .wiring import main as wiring_main

        return wiring_main()
    if args.command == "wiring-smoke":
        from .wiring_smoke import main as wiring_smoke_main

        return wiring_smoke_main()
    if args.command == "report":
        from .report import main as report_main

        return report_main()
    if args.command == "neuprint-audit":
        from .neuprint_audit import main as neuprint_audit_main

        return neuprint_audit_main()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .ledger import ROOT, build_summary, load_ledger, validate_ledger


REPORT_ROOT = ROOT / "reports" / "generated"
INVENTORY_PATH = ROOT / "data" / "derived" / "inventory" / "inventory.json"
NEUPRINT_AUDIT_PATH = ROOT / "data" / "derived" / "inventory" / "neuprint-audit.json"
ROI_AUDIT_PATH = ROOT / "data" / "derived" / "inventory" / "roi-audit.json"
BASAL_WIRING_PATH = ROOT / "data" / "derived" / "wiring" / "basal-clamp-routing.json"


def section(title: str) -> None:
    print(f"\n==> {title}", flush=True)


def _color(progress: int) -> str:
    if progress >= 75:
        return "#b7e4c7"
    if progress >= 45:
        return "#bfdbfe"
    if progress >= 20:
        return "#fde68a"
    return "#fecaca"


def _dot_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def build_dot(summary: dict[str, Any]) -> str:
    boxes = {box["id"]: box for box in summary["boxes"]}
    lines = [
        "digraph ProjectStatus {",
        '  graph [rankdir=TB, splines=spline, bgcolor="white", fontname="Arial", nodesep=0.3, ranksep=0.6,',
        '         label="The Fly Matrix — préparation du câblage exécutable\\nFils : vert = fixé, bleu = proposé, orange = candidats, rouge = inconnu", labelloc=t, fontsize=18, pad=0.3];',
        '  node [shape=box, style="rounded,filled", fontname="Arial", fontsize=10, margin="0.12,0.08"];',
        '  edge [arrowsize=0.65, penwidth=1.4];',
    ]
    for sector in summary["sectors"]:
        lines.append(f'  subgraph "cluster_{_dot_escape(sector["id"])}" {{')
        lines.append(
            f'    label="{_dot_escape(sector["name"])} — câblage {sector["wiring_progress"]}%"; color="#cbd5e1";'
        )
        for box_id in sector["boxes"]:
            box = boxes[box_id]
            label = f'{box["name"]}\ncâblage {box["wiring_progress"]}%'
            lines.append(
                f'    "{_dot_escape(box_id)}" [label="{_dot_escape(label)}", '
                f'fillcolor="{_color(box["wiring_progress"])}"];'
            )
        lines.append("  }")
    edge_colors = {
        "unknown": "#dc2626",
        "candidates_known": "#d97706",
        "proposed": "#2563eb",
        "fixed": "#15803d",
        "verified": "#166534",
    }
    for wire in summary["wires"]:
        routing = wire["status"]["routing"]
        source = wire["source"]["box_id"]
        target = wire["target"]["box_id"]
        style = "solid" if routing in {"fixed", "verified"} else "dashed"
        lines.append(
            f'  "{_dot_escape(source)}" -> "{_dot_escape(target)}" '
            f'[color="{edge_colors[routing]}", style="{style}", '
            f'tooltip="{_dot_escape(wire["name"])} — {routing}, {wire["progress"]}%"];'
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def _bar(progress: int) -> str:
    return (
        f'<div class="bar" role="progressbar" aria-valuenow="{progress}" '
        f'aria-valuemin="0" aria-valuemax="100"><span style="width:{progress}%"></span></div>'
    )


def _status_text(record: dict[str, Any]) -> str:
    status = record["status"]
    return " · ".join(f"{html.escape(key)}: {html.escape(str(value))}" for key, value in status.items())


def _inventory_metrics(inventory: dict[str, Any] | None) -> str:
    if not inventory:
        return '<p class="muted">Inventaire local absent : lancer run_analysis.bat.</p>'
    datasets = inventory["datasets"]
    body = inventory["flybody"]
    neuprint = inventory.get("neuprint_audit")
    roi_audit = inventory.get("roi_audit")
    basal_wiring = inventory.get("basal_wiring")
    annotations = datasets["annotations"]
    types = annotations.get("profiles", {}).get("type", {}).get("distinct_count", "?")
    groups = "".join(
        f'<tr><td><code>{html.escape(group["id"])}</code></td>'
        f'<td>{group["neurons"]:,}</td><td>{group["named_types"]:,}</td>'
        f'<td>{group.get("first_tier_subgroups", 0):,}</td>'
        f'<td>{group.get("candidate_subgroups", 0):,}</td>'
        f'<td>{html.escape(group["query"])}</td></tr>'
        for group in inventory.get("interface_groups", [])
    )
    remote_metrics = ""
    if neuprint:
        comparisons = neuprint.get("group_comparisons", [])
        exact = sum(item.get("exact_match") is True for item in comparisons)
        remote_metrics = (
            f'<div><strong>{neuprint["neuron_count"]:,}</strong><span>nœuds neuPrint :Neuron</span></div>'
            f'<div><strong>{neuprint["primary_roi_count"]:,}</strong><span>ROI primaires neuPrint</span></div>'
            f'<div><strong>{exact}/{len(comparisons)}</strong><span>groupes locaux = distants</span></div>'
        )
    roi_table = ""
    if roi_audit:
        roi_groups = roi_audit.get("groups", [])
        roi_rows = "".join(
            f'<tr><td><code>{html.escape(group["group_id"])}</code></td>'
            f'<td>{group["neurons"]:,}</td>'
            f'<td>{group["primary_roi_coverage_percent"]:.2f}%</td>'
            f'<td>{html.escape((group.get("top_input_roi") or {}).get("roi", "—"))}</td>'
            f'<td>{html.escape((group.get("top_output_roi") or {}).get("roi", "—"))}</td>'
            f'<td>{group["distinct_primary_rois"]:,}</td></tr>'
            for group in roi_groups
        )
        remote_metrics += (
            f'<div><strong>{len(roi_groups)}</strong><span>groupes avec signature ROI</span></div>'
        )
        roi_table = (
            '<h3>Signatures anatomiques neuPrint</h3>'
            '<p class="muted">Observations directes des synapses dans les ROI primaires; '
            'elles ne constituent pas encore une attribution fonctionnelle.</p>'
            '<div class="table-wrap compact"><table><thead><tr><th>Groupe</th>'
            '<th>Neurones</th><th>Couverture ROI</th><th>ROI d’entrée dominante</th>'
            '<th>ROI de sortie dominante</th><th>ROI distinctes</th></tr></thead>'
            f'<tbody>{roi_rows}</tbody></table></div>'
        )
    if basal_wiring:
        totals = basal_wiring.get("totals", {})
        remote_metrics += (
            f'<div><strong>{totals.get("generated_box_instances", 0):,}</strong><span>instances de boîte type A</span></div>'
            f'<div><strong>{totals.get("exact_routes", 0):,}</strong><span>routes clamp exactes</span></div>'
        )
    return (
        '<div class="metrics">'
        f'<div><strong>{annotations["rows"]:,}</strong><span>lignes d’annotations</span></div>'
        f'<div><strong>{types:,}</strong><span>types MaleCNS</span></div>'
        f'<div><strong>{datasets["connectome_weights"]["rows"]:,}</strong><span>arêtes pondérées</span></div>'
        f'<div><strong>{body["model"]["nu"]}</strong><span>actionneurs FlyBody</span></div>'
        f'{remote_metrics}'
        '</div>'
        '<div class="table-wrap compact"><table><thead><tr><th>Groupe reproductible</th>'
        '<th>Neurones</th><th>Types nommés</th><th>Premier niveau</th><th>Détail candidat</th>'
        '<th>Requête locale</th></tr></thead>'
        f'<tbody>{groups}</tbody></table></div>{roi_table}'
    )


def build_html(summary: dict[str, Any], inventory: dict[str, Any] | None) -> str:
    sectors = "".join(
        f'''<article class="sector" data-progress="{item['wiring_progress']}">
          <div class="sector-head"><h3>{html.escape(item['name'])}</h3><strong>{item['wiring_progress']}%</strong></div>
          {_bar(item['wiring_progress'])}
          <p>{len(item['boxes'])} boîtes · {len(item['groups'])} groupes · {len(item['wires'])} fils</p>
        </article>'''
        for item in summary["sectors"]
    )
    box_rows = "".join(
        f'''<tr data-sector="{html.escape(box.get('sector', 'unknown'))}">
          <td><strong>{html.escape(box['name'])}</strong><br><code>{html.escape(box['id'])}</code></td>
          <td>{html.escape(box.get('sector', 'unknown'))}</td>
          <td class="progress-cell"><strong>{box['wiring_progress']}%</strong>{_bar(box['wiring_progress'])}</td>
          <td>{_status_text(box)}</td>
          <td>{html.escape(box.get('next_action', ''))}</td>
        </tr>'''
        for box in sorted(summary["boxes"], key=lambda item: (item.get("sector", ""), item["wiring_progress"], item["name"]))
    )
    group_rows = "".join(
        f'''<tr data-sector="{html.escape(group.get('sector', 'unknown'))}">
          <td><strong>{html.escape(group['name'])}</strong><br><code>{html.escape(group['id'])}</code></td>
          <td>{group['member_count']:,}</td><td>{group['named_type_count']:,}</td>
          <td class="progress-cell"><strong>{group['wiring_progress']}%</strong>{_bar(group['wiring_progress'])}</td>
          <td>{_status_text(group)}</td><td>{html.escape(group.get('next_action', ''))}</td>
        </tr>'''
        for group in sorted(summary["groups"], key=lambda item: (item.get("sector", ""), item["wiring_progress"], item["name"]))
    )
    actions = "".join(
        f'''<li><span class="pct">{item['progress']}%</span><div><strong>{html.escape(item['name'])}</strong>
          <small>{html.escape(item['sector'])} · {html.escape(item['kind'])}</small>
          <p>{html.escape(item['action'])}</p></div></li>'''
        for item in summary["next_actions"][:16]
    )
    routing = summary["routing_counts"]
    validations = summary["validation_counts"]
    wiring = summary["wiring_components"]
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return f'''<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>The Fly Matrix — état du projet</title>
<style>
:root{{--bg:#f8fafc;--panel:#fff;--text:#172033;--muted:#64748b;--line:#dbe3ee;--accent:#334155;--fill:#2563eb}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,Segoe UI,sans-serif}}
main{{max-width:1500px;margin:auto;padding:28px}} h1{{margin:0;font-size:30px}} h2{{margin:32px 0 12px}} h3{{margin:0;font-size:15px}}
.muted,small{{color:var(--muted)}} .hero{{display:flex;gap:24px;align-items:end;justify-content:space-between;flex-wrap:wrap}}
.overall{{font-size:52px;font-weight:700;line-height:1}} .overall span{{display:block;font-size:13px;font-weight:500;color:var(--muted)}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-top:20px}}
.metrics div,.sector{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}}
.metrics strong{{display:block;font-size:22px}} .metrics span{{color:var(--muted)}}
.sectors{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}} .sector-head{{display:flex;justify-content:space-between;gap:8px}}
.sector p{{margin:8px 0 0;color:var(--muted)}} .bar{{height:7px;background:#e2e8f0;border-radius:9px;overflow:hidden;margin-top:8px}} .bar span{{display:block;height:100%;background:var(--fill)}}
.graph{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px;overflow:auto}} .graph img{{display:block;min-width:1100px;width:100%;height:auto}}
.grid2{{display:grid;grid-template-columns:minmax(0,2fr) minmax(280px,1fr);gap:20px;align-items:start}}
.table-wrap{{overflow:auto;background:var(--panel);border:1px solid var(--line);border-radius:10px}} table{{border-collapse:collapse;width:100%;min-width:1050px}}
th,td{{padding:10px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}} th{{position:sticky;top:0;background:#eef2f7}}
code{{font-size:12px;color:#475569}} .progress-cell{{min-width:120px}} .actions{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:4px 16px}}
.compact{{margin-top:12px}} .compact table{{min-width:700px}}
.actions ol{{list-style:none;padding:0;margin:0}} .actions li{{display:flex;gap:10px;padding:12px 0;border-bottom:1px solid var(--line)}} .actions li:last-child{{border:0}}
.actions p{{margin:4px 0}} .actions small{{display:block}} .pct{{font-weight:700;min-width:38px}} .legend{{display:flex;gap:14px;flex-wrap:wrap;color:var(--muted)}}
@media(max-width:900px){{main{{padding:16px}}.grid2{{grid-template-columns:1fr}}.overall{{font-size:40px}}}}
</style></head><body><main>
<header class="hero"><div><h1>The Fly Matrix</h1><p class="muted">État calculé depuis le registre · {generated}</p></div>
<div class="overall">{summary['wiring_progress']}%<span>câblage exécutable — paramètres exclus</span></div></header>
<div class="metrics">
  <div><strong>{summary['counts']['boxes']}</strong><span>boîtes suivies</span></div>
  <div><strong>{summary['counts']['groups']}</strong><span>groupes suivis</span></div>
  <div><strong>{summary['counts']['wires']}</strong><span>fils suivis</span></div>
  <div><strong>{routing.get('fixed',0)+routing.get('verified',0)}</strong><span>routages fixés/vérifiés</span></div>
  <div><strong>{validations.get('local_pass',0)+validations.get('integration_pass',0)+validations.get('held_out_pass',0)}</strong><span>validations réussies</span></div>
  <div><strong>{summary['overall_progress']}%</strong><span>ancien indice structurel secondaire</span></div>
</div>
<h2>Composantes du câblage</h2>
<div class="metrics">
  <div><strong>{wiring['box_inventory']}%</strong><span>contrats/inventaire des boîtes</span></div>
  <div><strong>{wiring['group_decomposition']}%</strong><span>décomposition terminale</span></div>
  <div><strong>{wiring['group_routing']}%</strong><span>routage des groupes</span></div>
  <div><strong>{wiring['wire_routing']}%</strong><span>routage des fils</span></div>
  <div><strong>{wiring['box_execution']}%</strong><span>boîtes exécutables</span></div>
  <div><strong>{wiring['wire_execution']}%</strong><span>fils exécutables</span></div>
</div>
<h2>Données réellement inventoriées</h2>{_inventory_metrics(inventory)}
<h2>Câblage par secteur</h2><section class="sectors">{sectors}</section>
<h2>Carte globale</h2><p class="legend">Vert ≥75% · bleu ≥45% · jaune ≥20% · rouge &lt;20%. Les fils pointillés ne sont pas fixés.</p>
<div class="graph"><img src="project-status.svg" alt="Graphe global des boîtes et fils du projet"></div>
<section><h2>Groupes anatomiques et fonctionnels</h2><div class="table-wrap"><table><thead><tr><th>Groupe</th><th>Neurones</th><th>Types</th><th>Câblage</th><th>Statuts</th><th>Prochaine décomposition</th></tr></thead><tbody>{group_rows}</tbody></table></div></section>
<div class="grid2"><section><h2>Boîtes</h2><div class="table-wrap"><table><thead><tr><th>Boîte</th><th>Secteur</th><th>Câblage</th><th>Statuts</th><th>Prochaine action</th></tr></thead><tbody>{box_rows}</tbody></table></div></section>
<aside><h2>Prochaines actions</h2><div class="actions"><ol>{actions}</ol></div></aside></div>
</main></body></html>'''


def build_report(output_dir: Path = REPORT_ROOT) -> dict[str, Path]:
    section("Validation du registre")
    ledger = load_ledger()
    for message in validate_ledger(ledger):
        print(f"[OK] {message}")
    summary = build_summary(ledger)
    output_dir.mkdir(parents=True, exist_ok=True)

    inventory = None
    if INVENTORY_PATH.is_file():
        inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        print(f"[OK] Inventaire local chargé: {INVENTORY_PATH}")
        if NEUPRINT_AUDIT_PATH.is_file():
            inventory["neuprint_audit"] = json.loads(
                NEUPRINT_AUDIT_PATH.read_text(encoding="utf-8")
            )
            print(f"[OK] Audit neuPrint chargé: {NEUPRINT_AUDIT_PATH}")
        if ROI_AUDIT_PATH.is_file():
            inventory["roi_audit"] = json.loads(
                ROI_AUDIT_PATH.read_text(encoding="utf-8")
            )
            print(f"[OK] Audit ROI chargé: {ROI_AUDIT_PATH}")
        if BASAL_WIRING_PATH.is_file():
            inventory["basal_wiring"] = json.loads(
                BASAL_WIRING_PATH.read_text(encoding="utf-8")
            )
            print(f"[OK] Câblage des clamps chargé: {BASAL_WIRING_PATH}")
    else:
        print("[AVERTISSEMENT] Inventaire local absent; lancer run_analysis.bat")

    section("Génération des rapports")
    json_path = output_dir / "project-status.json"
    dot_path = output_dir / "project-status.dot"
    svg_path = output_dir / "project-status.svg"
    png_path = output_dir / "project-status.png"
    html_path = output_dir / "project-status.html"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    dot_path.write_text(build_dot(summary), encoding="utf-8")
    html_path.write_text(build_html(summary, inventory), encoding="utf-8")

    dot_executable = shutil.which("dot")
    if dot_executable is None:
        fallback = Path(r"C:\Program Files\Graphviz\bin\dot.exe")
        dot_executable = str(fallback) if fallback.is_file() else None
    if dot_executable is None:
        raise RuntimeError("Graphviz dot.exe introuvable")
    completed = subprocess.run(
        [dot_executable, "-Tsvg", str(dot_path), "-o", str(svg_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stderr.strip():
        print(completed.stderr.strip())
    subprocess.run(
        [dot_executable, "-Tpng", str(dot_path), "-o", str(png_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    for path in (json_path, dot_path, svg_path, png_path, html_path):
        print(f"[OK] {path}")
    print(f"\nCâblage exécutable: {summary['wiring_progress']}%")
    print(f"Indice structurel secondaire: {summary['overall_progress']}%")
    return {
        "json": json_path,
        "dot": dot_path,
        "svg": svg_path,
        "png": png_path,
        "html": html_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Génère le tableau de bord du projet")
    parser.add_argument("--output-dir", type=Path, default=REPORT_ROOT)
    args = parser.parse_args()
    try:
        build_report(args.output_dir)
    except Exception as exc:
        print(f"\nREPORT_FAILED: {type(exc).__name__}: {exc}")
        return 1
    print("\nREPORT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

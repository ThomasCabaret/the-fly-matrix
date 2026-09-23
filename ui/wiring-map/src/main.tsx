import React, { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import cytoscape, { Core, CytoscapeOptions, ElementDefinition, SingularElementReturnValue } from "cytoscape";
import "./styles.css";

interface DetailObject { [key: string]: DetailValue }
type DetailValue = string | number | boolean | null | DetailValue[] | DetailObject;

type MapElementData = {
  id: string;
  label: string;
  kind: string;
  lane?: string;
  sector: string;
  state: string;
  details: Record<string, DetailValue>;
  source?: string;
  target?: string;
  count?: number;
  width?: number;
  height?: number;
};

type MapPayload = {
  schema_version: number;
  generated_at: string;
  project: string;
  source_of_truth: string;
  meta: {
    wiring_progress: number;
    counts: Record<string, number>;
    input_box_states: Record<string, number>;
    motor_group_states: Record<string, number>;
  };
  sectors: Array<{
    id: string;
    label: string;
    start_y: number;
    end_y: number;
    terminal_count: number;
    channel_count: number;
  }>;
  elements: { nodes: ElementDefinition[]; edges: ElementDefinition[] };
};

const COLORS = {
  exact: "#55d98b",
  parameterized: "#ffb84a",
  basal: "#64a9ff",
  proxy: "#b485ff",
  blocked: "#ff6174",
  structural: "#93a8bd",
};

const formatCount = (value: number | undefined) =>
  typeof value === "number" ? value.toLocaleString("en-US") : "—";

function stateLabel(state: string) {
  return state.replaceAll("_", " ");
}

function detailText(value: DetailValue): string {
  if (value === null) return "—";
  if (Array.isArray(value)) return value.map(detailText).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function DetailsPanel({ element }: { element: MapElementData | null }) {
  if (!element) {
    return (
      <aside className="details empty-details">
        <div className="empty-orbit" aria-hidden="true" />
        <h2>Inspect the wiring</h2>
        <p>Select a terminal, box, actuator, or route to see its canonical identity, status, and evidence.</p>
        <p className="hint">Tip: search accepts a bodyId, channel ID, type, or label.</p>
      </aside>
    );
  }

  const rows = Object.entries(element.details || {}).filter(([, value]) => {
    if (value === null || value === "") return false;
    if (Array.isArray(value) && value.length === 0) return false;
    return true;
  });

  return (
    <aside className="details">
      <div className="detail-heading">
        <span className={`state state-${element.state}`}>{stateLabel(element.state)}</span>
        <span className="kind">{stateLabel(element.kind)}</span>
      </div>
      <h2>{element.label || element.id}</h2>
      <code className="element-id">{element.id}</code>
      {element.source && element.target ? (
        <div className="route-summary">
          <div><span>From</span><code>{element.source}</code></div>
          <div><span>To</span><code>{element.target}</code></div>
          {element.count && element.count > 1 ? <strong>{formatCount(element.count)} underlying edges</strong> : null}
        </div>
      ) : null}
      <dl className="detail-list">
        <div><dt>Sector</dt><dd>{stateLabel(element.sector)}</dd></div>
        {rows.map(([key, value]) => (
          <div key={key}><dt>{stateLabel(key)}</dt><dd>{detailText(value)}</dd></div>
        ))}
      </dl>
    </aside>
  );
}

function App() {
  const graphRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [payload, setPayload] = useState<MapPayload | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<MapElementData | null>(null);
  const [query, setQuery] = useState("");
  const [activeSector, setActiveSector] = useState("all");
  const [zoom, setZoom] = useState(0);
  const [loadingMessage, setLoadingMessage] = useState("Loading 27 MiB wiring manifest…");

  useEffect(() => {
    let cancelled = false;
    fetch("./wiring-map.json")
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        setLoadingMessage("Parsing terminals, boxes, and routes…");
        return response.json();
      })
      .then((data: MapPayload) => {
        if (!cancelled) setPayload(data);
      })
      .catch((error: Error) => {
        if (!cancelled) setLoadError(error.message);
      });
    return () => { cancelled = true; };
  }, []);

  const style = useMemo<NonNullable<CytoscapeOptions["style"]>>(() => [
    {
      selector: "node",
      style: {
        width: 12, height: 7, shape: "round-rectangle", "background-color": COLORS.structural,
        "border-width": 0, label: "data(label)", color: "#d9e7f3", "font-size": 12,
        "font-family": "IBM Plex Mono, Cascadia Mono, Consolas, monospace",
        "text-halign": "center", "text-valign": "top", "text-margin-y": -8,
        "min-zoomed-font-size": 11, "z-index-compare": "manual", "z-index": 4,
      },
    },
    { selector: 'node[state = "exact"]', style: { "background-color": COLORS.exact } },
    { selector: 'node[state = "parameterized"]', style: { "background-color": COLORS.parameterized } },
    { selector: 'node[state = "basal"]', style: { "background-color": COLORS.basal } },
    { selector: 'node[state = "proxy"]', style: { "background-color": COLORS.proxy } },
    { selector: 'node[state = "blocked"]', style: { "background-color": COLORS.blocked } },
    {
      selector: 'node[kind = "cns_input_terminal"], node[kind = "cns_output_terminal"]',
      style: { width: 8, height: 3, shape: "rectangle", "text-margin-y": -6 },
    },
    {
      selector: 'node[kind = "physical_visual_observable"], node[kind = "physical_joint_observable"], node[kind = "physical_contact_observable"], node[kind = "physical_actuator"]',
      style: { width: 14, height: 5, shape: "round-rectangle" },
    },
    {
      selector: 'node[kind = "input_adapter_channel"], node[kind = "motor_group"]',
      style: { width: 22, height: 8, shape: "round-rectangle" },
    },
    {
      selector: 'node[kind = "anatomical_source_model"], node[kind = "basal_source"]',
      style: { width: 28, height: 10, shape: "round-rectangle" },
    },
    {
      selector: 'node[kind = "input_transform_box"]',
      style: { width: "data(width)", height: "data(height)", shape: "round-rectangle", "border-width": 2, "border-color": "#ffb84a" },
    },
    {
      selector: 'node[kind = "cns_core"]',
      style: {
        width: "data(width)", height: "data(height)", shape: "round-rectangle",
        "background-color": "#101c29", "background-opacity": 0.96, "border-width": 4,
        "border-color": "#29445b", color: "#92b6d3", "font-size": 28, "font-weight": 600,
        "text-wrap": "wrap", "text-max-width": "420px", "text-valign": "top",
        "text-margin-y": 80, "z-index": 0,
      },
    },
    {
      selector: 'node[kind = "lane_label"]',
      style: {
        width: 680, height: 42, "background-opacity": 0, color: "#7693aa",
        "font-size": 18, "font-weight": 600, "text-valign": "center",
        "text-margin-y": 0, "min-zoomed-font-size": 8,
      },
    },
    {
      selector: 'node[kind = "sector_label"]',
      style: {
        width: 1300, height: 50, "background-color": "#142435", "background-opacity": 0.82,
        "border-width": 1, "border-color": "#2a4358", color: "#b8cee0",
        "font-size": 19, "font-weight": 600, "text-valign": "center",
        "text-margin-y": 0, "z-index": 1,
      },
    },
    {
      selector: "edge",
      style: {
        width: 1, opacity: 0.28, "curve-style": "haystack", "haystack-radius": 0.9,
        "line-color": "#72899d", label: "data(label)", color: "#d6e2eb", "font-size": 10,
        "min-zoomed-font-size": 12, "text-background-color": "#081019",
        "text-background-opacity": 0.82, "text-background-padding": "2px",
        "z-index-compare": "manual", "z-index": 2,
      },
    },
    { selector: 'edge[state = "exact"]', style: { "line-color": COLORS.exact, opacity: 0.22 } },
    { selector: 'edge[state = "parameterized"]', style: { "line-color": COLORS.parameterized, opacity: 0.34 } },
    { selector: 'edge[state = "basal"]', style: { "line-color": COLORS.basal, opacity: 0.34 } },
    { selector: 'edge[state = "proxy"]', style: { "line-color": COLORS.proxy, opacity: 0.34 } },
    {
      selector: 'edge[kind = "cns_interface"]',
      style: { "line-color": "#334b5e", opacity: 0.13, width: 0.7 },
    },
    { selector: ".dimmed", style: { opacity: 0.035, "text-opacity": 0 } },
    {
      selector: ":selected",
      style: {
        "overlay-color": "#ffffff", "overlay-opacity": 0.12, "overlay-padding": 8,
        "border-width": 2, "border-color": "#ffffff", opacity: 1, "z-index": 20,
      },
    },
  ], []);

  useEffect(() => {
    if (!payload || !graphRef.current) return;
    setLoadingMessage("Rendering the exhaustive topology…");
    const cy = cytoscape({
      container: graphRef.current,
      elements: [...payload.elements.nodes, ...payload.elements.edges],
      style,
      layout: { name: "preset", fit: false },
      wheelSensitivity: 0.18,
      hideEdgesOnViewport: true,
      textureOnViewport: true,
      pixelRatio: 1,
      minZoom: 0.001,
      maxZoom: 5,
      boxSelectionEnabled: false,
      selectionType: "single",
    });
    cyRef.current = cy;

    const fitWidth = () => {
      const container = graphRef.current;
      if (!container) return;
      const extent = cy.elements().boundingBox({ includeLabels: false });
      const level = Math.min((container.clientWidth - 100) / Math.max(extent.w, 1), 0.36);
      cy.zoom(level);
      cy.pan({ x: 50 - extent.x1 * level, y: 85 - extent.y1 * level });
    };
    requestAnimationFrame(fitWidth);

    cy.on("tap", "node, edge", (event) => {
      const element = event.target as SingularElementReturnValue;
      setSelected(element.data() as MapElementData);
    });
    cy.on("tap", (event) => { if (event.target === cy) setSelected(null); });

    let zoomFrame = 0;
    cy.on("zoom", () => {
      cancelAnimationFrame(zoomFrame);
      zoomFrame = requestAnimationFrame(() => setZoom(cy.zoom()));
    });
    setZoom(cy.zoom());

    return () => {
      cancelAnimationFrame(zoomFrame);
      cy.destroy();
      cyRef.current = null;
    };
  }, [payload, style]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.elements().removeClass("dimmed");
      if (activeSector !== "all") {
        cy.elements().forEach((element) => {
          const sector = String(element.data("sector") || "");
          const kind = String(element.data("kind") || "");
          if (sector !== activeSector && kind !== "cns_core" && kind !== "lane_label") {
            element.addClass("dimmed");
          }
        });
      }
    });
  }, [activeSector]);

  function fitWidth() {
    const cy = cyRef.current;
    const container = graphRef.current;
    if (!cy || !container) return;
    const extent = cy.elements().boundingBox({ includeLabels: false });
    const level = Math.min((container.clientWidth - 100) / Math.max(extent.w, 1), 0.36);
    cy.animate({ zoom: level, pan: { x: 50 - extent.x1 * level, y: 85 - extent.y1 * level } }, { duration: 360 });
  }

  function fitAll() {
    const cy = cyRef.current;
    if (cy) cy.animate({ fit: { eles: cy.elements(), padding: 45 } }, { duration: 420 });
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    const cy = cyRef.current;
    const normalized = query.trim().toLowerCase();
    if (!cy || !normalized) return;
    const found = cy.nodes().filter((node) => {
      const data = node.data() as MapElementData;
      return data.id.toLowerCase().includes(normalized)
        || (data.label || "").toLowerCase().includes(normalized)
        || JSON.stringify(data.details || {}).toLowerCase().includes(normalized);
    })[0];
    if (!found) {
      setSelected({
        id: `No match for “${query.trim()}”`, label: "No matching element",
        kind: "search_result", sector: "search", state: "blocked",
        details: { suggestion: "Try a bodyId, channel ID, neuron type, joint, or actuator name." },
      });
      return;
    }
    cy.elements().unselect();
    found.select();
    setSelected(found.data() as MapElementData);
    cy.animate({ center: { eles: found }, zoom: Math.max(cy.zoom(), 0.72) }, { duration: 420 });
  }

  if (loadError) {
    return (
      <main className="fatal"><div>
        <p className="eyebrow">THE FLY MATRIX</p>
        <h1>Wiring map unavailable</h1>
        <p>The generated manifest could not be loaded: <code>{loadError}</code></p>
        <p>Run <code>wiring_map.bat</code> from the project root.</p>
      </div></main>
    );
  }

  if (!payload) {
    return (
      <main className="loading">
        <div className="fly-mark" aria-hidden="true"><span /><span /><span /></div>
        <p className="eyebrow">THE FLY MATRIX</p>
        <h1>{loadingMessage}</h1>
      </main>
    );
  }

  const counts = payload.meta.counts;
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true"><span /><span /></div>
          <div><p>THE FLY MATRIX</p><h1>Exhaustive wiring map</h1></div>
        </div>
        <div className="metrics" aria-label="Map metrics">
          <div><strong>{payload.meta.wiring_progress}%</strong><span>wiring</span></div>
          <div><strong>{formatCount(counts.cns_inputs)}</strong><span>CNS inputs</span></div>
          <div><strong>{formatCount(counts.cns_outputs)}</strong><span>CNS outputs</span></div>
          <div><strong>{formatCount(counts.edges)}</strong><span>visible relations</span></div>
        </div>
        <form className="search" onSubmit={submitSearch}>
          <label htmlFor="graph-search">Find terminal or box</label>
          <div>
            <input id="graph-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="bodyId, type, channel…" />
            <button type="submit">Find</button>
          </div>
        </form>
      </header>

      <nav className="sectorbar" aria-label="Sector focus">
        <button className={activeSector === "all" ? "active" : ""} onClick={() => setActiveSector("all")}>All sectors</button>
        {payload.sectors.map((sector) => (
          <button key={sector.id} className={activeSector === sector.id ? "active" : ""} onClick={() => setActiveSector(sector.id)}>
            {sector.label}<span>{formatCount(sector.terminal_count)}</span>
          </button>
        ))}
        <button className={activeSector === "motor_output" ? "active" : ""} onClick={() => setActiveSector("motor_output")}>
          Motor output<span>{formatCount(counts.cns_outputs)}</span>
        </button>
      </nav>

      <main className="workspace">
        <section className="graph-panel" aria-label="Interactive wiring topology">
          <div className="viewport-controls">
            <button onClick={fitWidth}>Fit width</button>
            <button onClick={fitAll}>Fit all</button>
            <span>{Math.round(zoom * 100)}%</span>
          </div>
          <div ref={graphRef} className="graph" />
          <div className="legend" aria-label="Wiring states">
            {Object.entries(COLORS).map(([state, color]) => (
              <span key={state}><i style={{ background: color }} />{stateLabel(state)}</span>
            ))}
          </div>
          <div className="navigation-note">Scroll to zoom · drag the background to travel vertically · select any mark for provenance</div>
        </section>
        <DetailsPanel element={selected} />
      </main>
      <footer>
        <span>Generated {new Date(payload.generated_at).toLocaleString()}</span>
        <span>{payload.source_of_truth}</span>
        <span>No calibration values are selected in this view</span>
      </footer>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode><App /></React.StrictMode>,
);

# ADR 0003 — Exhaustive interactive wiring map

## Status

Accepted, with an intentionally evolutionary implementation plan.

## Context

The static DOT overview and progress tables show project-level status, but they do
not let a reviewer inspect the actual granularity of the wiring. In particular,
they cannot make these distinctions immediately visible:

- an unconnected physical degree of freedom or MaleCNS terminal;
- one large parameterized `100 → 100` mapping;
- several independent, smaller mappings whose internal routes remain unknown;
- an exact terminal-to-terminal route;
- a route refined, split, completed, or regressed between two revisions.

This view is needed before structural wiring reaches 100%. It must expose current
gaps as first-class objects rather than infer a complete graph from completed
records only. It will later carry calibration and validation overlays without
mixing those states with structural coverage.

## Decision

Build a custom local web viewer generated from the project's canonical ledger and
derived manifests. The initial architecture is:

- a Python exporter that validates and normalizes the real project state;
- a TypeScript, React, and Vite application shell;
- Cytoscape.js as the initial interactive graph renderer;
- deterministic horizontal lanes and stable sector-local ordering computed during
  report generation; ELK.js remains an option for later nested layouts;
- generated, chunkable JSON under `reports/generated/`, never a second manually
  maintained source of truth.

The renderer is replaceable behind the generated graph contract. If realistic
benchmarks show that dense Canvas rendering is insufficient, a WebGL layer such
as Sigma.js or PixiJS may replace or complement Cytoscape.js without changing the
ledger, exported identities, hierarchy, or layout semantics.

## Exhaustive-view contract

The default map must spatially represent every relevant terminal, including
unconnected terminals:

- physical-world observables and body degrees of freedom;
- sensor, transduction, routing, clamp, proxy, and sink boxes;
- every MaleCNS input and output terminal in scope;
- motor routing, transduction, actuators, and physical feedback paths;
- terminals whose disposition is still `blocked`.

Sector boundaries and the actual grouping of routes must remain visible. A single
`100 → 100` box must not be visually interchangeable with three independent
sub-boxes that partition those terminals. Aggregation may reduce drawing noise,
but it must preserve and expose real group boundaries, cardinalities, and children.

Semantic zoom changes graphical detail, not topology or scientific granularity.
At wide zoom levels the viewer may omit labels, shorten decorations, reduce edge
opacity, use compact terminal marks, and render dense adjacent routes as bundles.
It must not collapse the whole model into a handful of summary edges. As space
becomes available, individual routes, ports, identifiers, and metadata appear.
A raw-route mode must allow all individual edges to be requested explicitly.

The unavoidable screen-resolution limit is handled visually: multiple routes may
occupy the same pixels while zoomed out, but their existence, density, grouping,
and coverage state remain represented and they become individually inspectable
when zooming in.

## Hierarchy and navigation

The map follows the complete signal path from left to right:

1. environment and physical observables;
2. body degrees of freedom;
3. sensors, basal sources, proxies, and transduction;
4. sensory routing;
5. MaleCNS inputs;
6. the MaleCNS central graph, collapsed by default in the interface map;
7. MaleCNS outputs;
8. motor routing and transduction;
9. body actuators;
10. environment and sensory feedback paths.

Boxes may contain child boxes and internal routes. Expansion or semantic zoom can
replace a box envelope with its child graph while breadcrumbs and stable selection
preserve context. The full internal synaptic MaleCNS graph is a related but
distinct high-density view; its requirements must not weaken the interface map.

## Stable identity and change visibility

Generated elements use stable project identifiers. Sector order, terminal order,
and unchanged positions should remain deterministic across generations. A change
in one sector must not arbitrarily rearrange the whole diagram.

The viewer should support comparison with a previous generated snapshot or Git
revision. It should make at least these changes discoverable:

- newly covered or newly blocked terminals;
- creation, removal, split, or merge of boxes;
- refinement from a coarse mapping to smaller independent mappings;
- changes of terminal disposition or mapping level;
- routes promoted to exact or executable status;
- changes to parameter, test, provenance, or validation state.

## Traceability contract

Selecting a terminal, route, group, or box should expose, when applicable:

- its stable identifier, parent hierarchy, sector, ports, and cardinalities;
- terminal disposition and structural status;
- mapping level and free discrete or continuous degrees of freedom;
- calibration and validation status as separate axes;
- evidence files, source claims, assumptions, and confidence;
- associated tests, last known result, and reproducible command;
- blockers, completion criteria, and next action;
- the canonical repository record from which it was generated.

Missing evidence or validation must remain explicit. The viewer reports state; it
does not manufacture confidence or completion.
## Initial implementation checkpoint

The first read-only implementation exports 31,037 nodes and 45,496 visible
relations from the current derived manifests. It includes every CNS input and
output terminal in scope, physical observables, anatomical source models, input
adapter channels, motor groups, actuators, and the collapsed MaleCNS core.

The viewer currently provides deterministic lanes, pan and zoom, fit-width and
fit-all controls, sector focus by dimming rather than removing other elements,
search, state colouring, and a traceability panel for nodes and edges. Individual
terminals remain distinct even where many marks share pixels at overview scale.
The generated manifest and compiled frontend remain ignored build artifacts.

This checkpoint does not yet implement hierarchy expansion, revision comparison,
raw-edge switching, or true multi-level semantic styling. Those are incremental

## Interaction and delivery

The first version is read-only. Search, filters, and focus modes may highlight or
temporarily isolate a subset, but the default overview remains exhaustive. It must
be possible to return to the complete map immediately.

A Windows launcher should validate and regenerate the data, start a local server,
open the browser, report useful progress and errors, and pause before closing when
launched by double-click. No remote service is required. Browser full-screen mode
and deterministic presentation modes should support later screen recording.

## Validation

The exporter must be tested against ledger invariants and terminal cardinalities.
Generated counts must reconcile with canonical inventory, wiring manifests, and
the exhaustive terminal dispositions defined in ADR 0002.

Before committing to a renderer long-term, benchmark a representative synthetic
and real graph containing thousands of terminals, tens of thousands of routes,
compound boxes, selection, pan, and zoom. Performance optimization may simplify
styling or rendering technique, but must not silently remove topology.

## Consequences

- The interactive map becomes the primary human inspection surface for structural
  wiring, while DOT remains a compact static export and regression aid.
- The map is useful immediately because disconnected and blocked terminals are
  deliberately represented.
- Structural wiring, anatomical resolution, calibration, and validation remain
  visually and numerically distinct.
- The next implementation priority is a minimal exhaustive viewer and generated
  data contract before the next large wiring batch.
- This ADR records current intent and may evolve as real-scale benchmarks reveal
  better rendering or interaction choices.

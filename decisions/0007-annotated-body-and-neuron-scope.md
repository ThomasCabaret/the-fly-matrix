# ADR 0007 — Retain every annotated body and explicitly flag the neuronal scope

## Status

Accepted after correction of an analysis error on 2026-09-25.

## Context

The MaleCNS body-annotation table has 211,577 rows, but a row in that table is not
by itself evidence that the represented body is a neuron. It also contains glia,
unresolved bodies and curation objects carrying statuses such as `Orphan`,
`Unimportant`, `Assign` or an unknown status.

The first central-graph implementation and the first cycle-topology report
incorrectly called every annotation row a neuron. That produced a false universe
of 211,577 “neurons”, 26,028,386 “neural” edges and 26,232 apparently unreachable
“neurons”. This was an implementation error in The Fly Matrix, not a property of
the MaleCNS neuronal connectome. It must remain documented so that later agents do
not repeat it.

## Decision

No annotation row is deleted. `central-node-index.parquet` retains every published
`bodyId` and its stable inventory `node_index`, then adds explicit scope fields:

- `is_canonical_neuron`;
- `included_in_neural_runtime`;
- `population_scope`;
- `scope_reason`;
- `runtime_node_index`, set to `-1` outside the neuronal runtime.

For MaleCNS v1.0, the versioned rule
`malecns-v1.0-population-scope-v1` classifies a body as a canonical neuron when
its published `superclass` is present and its status is not `Glia`. Published
`status=Glia` is retained as
`non_neuronal_glia`; the remaining rows without a superclass are retained as
`unresolved_or_non_neuronal_body`. The rule yields:

- 211,577 retained annotation rows;
- 166,700 canonical neurons included in neural computation;
- 11,864 explicitly labelled glial bodies;
- 33,013 other unresolved or non-neuronal bodies.

The complete annotated-body edge inventory is also retained. The neural runtime
uses only edges whose two endpoints are flagged canonical neurons:

- 26,028,386 edges between retained annotation rows;
- 25,582,938 canonical-neuron runtime edges;
- 445,448 retained but runtime-excluded edges touching a noncanonical body.

The topology analysis separately records, for every retained body, whether it is
reachable from a declared CNS input, whether it can reach a modeled motor output,
its shortest input depth and its behavioral-relevance class. These are derived
model-scope flags, not biological cell-type claims.

## Wiring impact audit

All 17,884 existing CNS input routes and all 815 motor-output routes target bodies
flagged canonical neurons. Therefore the interface decomposition, terminal
dispositions, routing boxes and terminal coverage remain valid.

The central runtime did include 44,877 noncanonical bodies and 445,448 associated
edges. In the present one-hop smoke test those extra bodies had zero injected
activity, so terminal reachability was not fabricated. They would nevertheless
have entered any future recurrent temporal dynamics and could have changed later
activity. The runtime scope is therefore corrected before calibration begins.

The original cycle-topology report is superseded. Its SCC and reachability numbers
must be regenerated over the flagged canonical-neuron graph. Its BFS depth-gap
histogram is a traversal diagnostic and must not be described as a cycle-length or
locality distribution.

## Consequences

- Code must say “annotation row” or “annotated body” unless a neuronal flag has
  actually been checked.
- Consumers may filter computation by `included_in_neural_runtime`, but must never
  destroy the excluded inventory or conceal its cardinality.
- Every runtime/interface validation must assert that routed terminal `bodyId`s
  are canonical neurons.
- A future dataset version may change the classification rule only through a new
  versioned rule and an explicit count/provenance update.
- Neural dynamics and calibration are blocked if the generated scope flags are
  absent, internally inconsistent or disagree with the expected cardinalities.

## Provenance

- Dataset observation: MaleCNS v1.0 body annotations and connection weights from
  `ledger/datasets.yaml`.
- Published dataset description: <https://male-cns.janelia.org/download/>.
- Derived rule: published non-empty `superclass` defines the v1.0 canonical
  neuronal population used by this project.
- Engineering choice: retain every row in the inventory while limiting neural
  computation to explicitly flagged canonical neurons.

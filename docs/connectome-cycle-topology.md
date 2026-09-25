# MaleCNS cycle-topology analysis

`cycle_topology.bat` generates a structural view of recurrence in the real
MaleCNS v1.0 graph. It does not select parameters, simulate neural dynamics, or
make a behavioral claim.

The annotation table is a mixed inventory, not a neuron table. The analysis keeps
all 211,577 rows in `node-classification.parquet`, but graph metrics use only the
166,700 bodies flagged `is_canonical_neuron`. This rule and the correction of the
earlier 211,577-neuron interpretation are recorded in ADR 0007. Each retained body
also receives input-reachability, modeled-output-reachability, shortest-depth and
behavioral-relevance flags.

## Questions answered

The analysis starts a multi-source breadth-first traversal at every declared CNS
input terminal. Generation zero therefore contains the terminal neurons reached
by the world/body interface; generation *n* is the shortest directed distance
from any such input. Traversal continues to exhaustion rather than stopping at
the first motor output. The report shows:

- neuron and motor-output counts by shortest input depth;
- exact strongly connected components (SCCs), including their size distribution;
- edges inside cyclic SCCs that return to the same or an earlier generation;
- exact cycles closed against an ancestor of the chosen BFS forest.

The “feedback generation gap” follows the exploratory convention from the project
discussion: an edge from generation 10 to generation 5 has gap 5. Requiring both
endpoints to belong to the same cyclic SCC guarantees that the edge participates
in at least one directed cycle. The gap is nevertheless not generally an exact
simple-cycle length.

The exact BFS-tree measure is deliberately narrower. If an edge returns to an
actual ancestor in the selected BFS forest, the tree path plus that edge is a real
cycle; its length includes the closing edge. It is a deterministic fundamental
subset for this traversal, not an enumeration of every simple cycle.
Neither histogram measures biological locality: many inputs compress shortest-path
depth, and a same-depth edge may participate in a macroscopic directed cycle.

Enumerating all simple directed cycles is not a reasonable default for this graph:
their number may be exponential even though the MaleCNS graph has a manageable
166,700 canonical neurons and 25,582,938 runtime edges. SCCs plus the two return
profiles provide reproducible structural diagnostics without presenting a
traversal proxy as a full cycle census, a cycle-length distribution or a measure
of biological locality.

## Running it

Double-click `cycle_topology.bat`, or run:

```text
cycle_topology.bat
```

The first run reads the roughly 1 GB edge table twice and creates a topology-only
CSR cache under `data/derived/analysis/cycle-topology/`. It reports progress during
both scans. Later runs reuse that cache while the source fingerprint is unchanged.

Outputs are:

- `reports/generated/connectome-cycle-topology.html`: standalone visual report;
- `data/derived/analysis/cycle-topology/summary.json`: definitions, provenance,
  complete histograms, coverage, SCC summaries and limitations;
- `data/derived/analysis/cycle-topology/node-classification.parquet`: retained
  per-body population scope and causal-relevance flags;
- two NumPy CSR arrays plus cache metadata in the same derived directory.

All generated artifacts are ignored by Git. The implementation, launcher, tests,
method and interpretation remain versioned. Use `--no-open` to suppress opening
the report, for example `cycle_topology.bat --no-open`.

## Interpretation boundaries

Generation is a shortest-path layer, not biological time. A long return gap is
evidence of a structurally long-range recurrence relative to the declared inputs,
not proof of a slow oscillation. This analysis ignores signs, synapse weights,
time constants and nonlinear dynamics; those belong to later characterization
and calibration work.

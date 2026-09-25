# MaleCNS cycle-topology analysis

`cycle_topology.bat` generates a structural view of recurrence in the real
MaleCNS v1.0 graph. It does not select parameters, simulate neural dynamics, or
make a behavioral claim.

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

Enumerating all simple directed cycles is not a reasonable default for this graph:
their number may be exponential even though the MaleCNS graph has a manageable
211,577 annotated neurons and 26,028,386 induced edges. SCCs plus the two return
profiles provide an exact/reproducible way to test for local versus long-range
recurrence without presenting a traversal proxy as a full cycle census.

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

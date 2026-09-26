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

## Planned hierarchical quasi-feed-forward module diagnostic

### Hypothesis to test

The intended model is recursive and explicitly permits recurrence at the coarse
scale. A candidate module should admit a local ordering in which most internal
connection weight moves forward. Forward skips are allowed, while backward edges
should be relatively sparse and preferentially local, closing short intramodule
cycles. A module may contain smaller modules with the same property.

After replacing neurons by modules, the directed module graph is **not** required
to be acyclic. Outputs of one largely feed-forward module may enter another module
whose outputs eventually return to the first, producing a long macroscopic ring.
The analysis must preserve and describe these intermodule cycles rather than
remove them to manufacture a global feed-forward graph.

This is the concrete hypothesis to accept, qualify or reject:

> MaleCNS can be compressed into a hierarchy of locally quasi-feed-forward modules
> with predominantly local intramodule feedback, sparse forward skips and a
> potentially recurrent, long-cycle intermodule graph.

### Why SCC condensation is not the module definition

Exact strongly connected components remain useful measurements, but they are not
candidate biological modules. A ring of many feed-forward modules is itself one
SCC, so condensing SCCs would collapse precisely the macroscopic recurrent
organization of interest. Whole-brain FlyWire analysis has likewise reported one
giant SCC containing most neurons, despite separate evidence for hierarchical
communities. SCCs will therefore be reported as constraints and comparison
baselines, not used as the terminal partition.

### Realistic analysis strategy

There is no unique exact decomposition. The planned diagnostic will compare
hierarchical directed partitions rather than assume the hypothesis is true:

1. build candidate nested communities from the directed weighted graph, including
   a hierarchical stochastic block model and at least one alternative partition;
2. fit a deterministic weighted ordering inside every candidate module, using a
   maximum-acyclic-subgraph or feedback-arc heuristic rather than claiming an
   NP-hard exact optimum;
3. classify internal edges as local forward, forward skip, same-level or backward
   and measure their count, synapse weight and ordering span;
4. retain every intermodule edge, construct the directed quotient at each scale,
   and measure its long cycles, rings, reciprocity and recurrent motifs;
5. split, merge and recursively refine modules according to description length,
   boundary sparsity and local-order quality, without forcing the quotient to be
   acyclic;
6. test stability across synapse thresholds, seeds and degree-preserving null
   graphs, and compare recovered modules with annotations only after the
   unsupervised fit.

The hypothesis is supported only if stable partitions explain substantially more
edge weight by local forward structure than matched null graphs, leave a bounded
and interpretable residual of internal feedback/skips, and expose reproducible
macroscopic recurrence between modules. Failure to find such a partition is an
informative rejection, not a reason to tune the method until the picture appears.

The existing CSR cache makes repeated linear edge passes realistic for 166,700
nodes and 25,582,938 edges. Exact maximum-acyclic-subgraph optimization and
exhaustive simple-cycle enumeration remain out of scope. This is a structural
characterization and cannot establish temporal direction, synaptic sign or
functional influence.

### Related primary work

The ingredients are established in connectome network science, although the exact
joint hypothesis above is project-specific:

- Kunin et al., *Hierarchical Modular Structure of the Drosophila Connectome*,
  J. Neurosci. 43, 6384–6400 (2023),
  https://doi.org/10.1523/JNEUROSCI.0134-23.2023.
- Betzel et al., *Hierarchical communities in the larval Drosophila connectome*,
  PNAS 121, e2320177121 (2024), https://doi.org/10.1073/pnas.2320177121.
- Baker et al., *Neural Network Organization for Courtship Song Feature Detection
  in Drosophila*, Curr. Biol. 32, 3317–3333 (2022), which applies orderability,
  feedforwardness and treeness to a directed fly circuit.
- Lin et al., *Network statistics of the whole-brain connectome of Drosophila*,
  Nature 634, 153–165 (2024), https://doi.org/10.1038/s41586-024-07968-y.

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

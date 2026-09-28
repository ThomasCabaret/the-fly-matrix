# ADR 0011 — Reconstructible peripheral topology and bounded routing spaces

## Status

Accepted on 2026-09-28.

## Context

Terminal coverage is executable, but four fine peripheral relation families are
still under independent scientific review. Keeping generated matrices as the
practical source of truth would make later corrections hard to audit. Conversely,
requiring a unique point-to-point mapping everywhere would force unsupported
anatomy into the model.

There is a second failure mode: a nominally local adapter can expose such a broad
routing space that calibration effectively learns a behavioral controller. A
green smoke test, a complete matrix, or a small number of source channels does not
by itself bound that capacity.

## Decision

### Canonical layers

Peripheral topology is organized in four ordered layers:

1. immutable source data or immutable source references with versions and hashes;
2. versioned biological, anatomical, and engineering rules;
3. a small versioned table of genuinely singular exceptions, each with rationale,
   provenance, review trigger, and next action;
4. generated groups, candidate matrices, manifests, and reports.

Layer 4 is a derived cache. It may be retained for speed, diffs, and experiment
lineage, but it is not the construction recipe. The ledger remains canonical for
status, ownership, claims, validation, and next actions; it does not replace the
rules that generate relation-level topology.

### Clean-room reconstruction

An independently validated family must be rebuildable into an empty destination
from layers 1–3 without reading the current generated family. Only after the
independent result is closed may the procedure compare it with the prewiring.

The procedure records input, rule, exception, code, and environment identities.
It computes a semantic hash over canonically ordered relation records. File-byte
hashes may also be recorded, but are not the sole reproducibility criterion
because container metadata and library versions can change byte representation
without changing topology. A repeated clean build with the same declared inputs
must reproduce the semantic hash.

### Bounded structural uncertainty

Unknown point-to-point anatomy is represented as a finite candidate envelope, not
as an invented mapping. The envelope is part of topology. Calibration may select
or weight relations only inside it; expanding it is a wiring change and reopens
scientific review.

Routing parameters and transfer-function parameters are distinct even when one
runtime component implements both:

- routing parameters represent structural uncertainty such as a permutation,
  sparse assignment, or choice among local candidates;
- transfer parameters represent physiological uncertainty such as gain, threshold,
  time constant, adaptation, delay, or noise.

No universal maximum candidate count is imposed: legitimate biological groups
have different fan-in and fan-out. Each family must nevertheless justify a local
capacity budget from anatomical boundaries such as side, nerve, segment, receptor
or effector class, and topography. Reports expose candidate-set size distributions,
free discrete and continuous degrees of freedom, and the largest groups. A routing
space broad enough to mix unrelated sectors or learn a global policy remains
`blocked`, even if it is executable.

### Quantitative validation

Family acceptance requires quantitative evidence appropriate to the available
biology, including:

- exhaustive and exclusive terminal accounting;
- cardinality, duplicate, overlap, and non-empty-path checks;
- negative anatomical constraints in addition to positive matches;
- expected homologous symmetry and documented asymmetry;
- topographic constraints where the source supports them;
- recovery of known mappings as gold standards when a non-circular masked
  protocol can be defined;
- counts by provenance and relation class, candidate-set mean/quantiles/maximum,
  proxies, unresolved cases, and manual exceptions;
- clean-build semantic hash and comparison with the accepted predecessor;
- compilation through the declared runtime interfaces without anonymous terminal
  injection.

A masked gold-standard score is evidence only when the tested relations were not
also used to author the evaluated rule. The protocol records that separation.

### Downstream feasibility

Before a family is called ready for calibration, its generated topology must have
a finite typed parameterization, a runtime path, declared bounds or domains, and
an identifiability status. Missing local evidence or an underdetermined parameter
family does not justify inventing a mapping: it is reported early with a fallback
or replacement path and may block calibration readiness while leaving executable
terminal coverage intact.

The accepted topology snapshot, candidate-envelope hash, and exception-table hash
are frozen before a calibration campaign. Calibration infrastructure, isolated
central benchmarks, and tooling may be developed while peripheral review is open,
but affected parameters may not be fitted or promoted against unaccepted topology.

## Consequences

- The current rules-v1 terminal/group pass is necessary but not sufficient: the
  four fine candidate families still need clean independent builders.
- A scientifically honest small candidate set is preferable to a false exact map.
- A huge unconstrained candidate matrix is not considered finished merely because
  it contains every terminal.
- Generated matrices can be discarded and rebuilt without losing the scientific
  decision, while accepted historical runs remain reproducible by their hashes.
- Revalidation reports become capacity and provenance audits, not only equality
  checks against the current prewiring.

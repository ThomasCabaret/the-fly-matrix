# ADR 0008 — Treat current scientific mappings as prewiring pending independent revalidation

## Status

Accepted on 2026-09-26.

## Context

The terminal wiring is executable and its boundary populations were recomputed
directly from the raw MaleCNS annotations: 17,884 input bodies and 815 motor bodies
are canonical, exhaustive under the declared selectors, disjoint and routed once.

However, ADR 0007 records that the first central-graph and cycle analysis confused
annotation rows with neurons. Correcting that scope error does not by itself prove
that the same implementation process made sound scientific choices when it built
functional groups, candidate matrices, proxy observables and motor groupings.
Passing cardinality and smoke tests proves that the present graph executes; it does
not independently validate the biological reasoning that constrains it.

## Decision

The vision, proprioception, mechanosensation and motor scientific-interface layers
are classified as **executable prewiring requiring independent revalidation**.
Their manifests remain useful hypotheses and must not be deleted, silently trusted
or passed into calibration as accepted scientific topology.

`validation.scientific_wiring_reaudit` owns every affected box, group, wire and
parameter family. The dashboard must expose its `revalidation_required` status.
Existing `integration_pass` results remain valid only as execution/cardinality
evidence. They do not supersede the scientific-review status.

The raw terminal memberships and exact one-body routes remain preserved claims.
The following claims are explicitly not accepted until independently rebuilt:

- functional grouping granularity;
- completeness and exclusion quality of candidate matrices;
- adequacy of kinematic and mean-light proxies;
- the 441 motor groups and their permitted actuator sets;
- readiness of affected parameter families for calibration.

## Required review method

For each sector, a reviewer must start from versioned raw data and primary sources
without using the current manifest as the construction recipe. The independently
derived result is then compared with the manifest. Every relation is classified as
`exact`, `source_supported_candidate`, `engineering_candidate`, `proxy`,
`unsupported` or `removed`; discrepancies, tests and source claims are recorded.

Calibration of an affected family is blocked until all four workstreams pass this
review. Local corrections may be committed workstream by workstream, but the global
review remains open until its complete acceptance criteria are met.

## Consequences

- Executable coverage and scientific confidence are separate dashboard axes.
- A smoke test can remain green while scientific review remains red.
- Current prewiring is retained as a comparison baseline, not presented as truth.
- Exact physical addressing and terminal inventories need not be rebuilt unless an
  independent check finds contrary evidence.
- The next project phase is revalidation, not calibration.

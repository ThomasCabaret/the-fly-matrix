# ADR 0004 — Explicit nominal sources for unresolved sensory afferents

- Status: accepted
- Date: 2026-09-23
- Phase: structural wiring before calibration

## Context

The exact residual of the inventoried sensory interface contains 1,883 MaleCNS
afferents. Their downstream `bodyId` routes are known, but the available annotations
do not justify a physical input and transduction for every channel. The residual is
not homogeneous: it contains 57 `chemosensory`, 11 `mechanosensory_tbc`, 1,712
`unknown_sensory`, and 103 class-unknown afferents.

Passing an arbitrary vector directly into the type-C router proved code continuity
but left 1,883 dangling structural inputs. Mapping the whole residual to a generic
body observable would instead invent behavioral capacity and biological locality.

## Decision

Every residual terminal is owned by exactly one explicit type-A nominal source
before entering the existing exact type-C router. Three source families preserve
the annotation boundaries:

- 57 residual chemosensory channels;
- 11 `mechanosensory_tbc` channels awaiting supported localization;
- 1,815 channels whose modality is unknown.

Each terminal has one externally supplied, uncalibrated source parameter. The
terminal disposition is `basal`: this is a neutral structural fallback, not a claim
that the biological neuron is intrinsically constant, not a zero-activity choice,
and not a calibrated physiological baseline. Smoke tests may inject arbitrary
finite parameter values only through these declared source boxes.

## Invariants

- The union of source channels equals the 1,883-channel router input exactly.
- Source families are disjoint and preserve the original class annotations.
- Downstream routes remain one-to-one by published MaleCNS `bodyId`.
- No source claims a physical modality, receptor location, gain, sign, rate, noise
  model, or behavior.
- A channel may later be replaced by an exact, parameterized, or proxy
  transduction when evidence supports it; unrelated channels need not change.
- Calibration is responsible for selecting nominal values or replacing this
  fallback, and must not reinterpret arbitrary smoke-test values as scientific.

## Consequences

The executable input graph has no direct test injection and no dangling residual
terminal. Simple short-duration experiments can proceed using the already physical
vision, proprioception, and mechanosensation stacks while the unresolved residual
is explicitly neutralized. Scientific resolution has not increased for those
1,883 afferents, so dashboards and the wiring map must show them as nominal/basal
rather than exact physical transductions.

## Evidence and traceability

The partition is regenerated from the local MaleCNS annotation inventory by
`build_unclassified_sensory_wiring`. Its class and anatomy counts are recorded in
`data/derived/wiring/unclassified-sensory-routing.json`; terminal ownership is in
`unclassified-sensory-channels.csv`; exact downstream routes are in
`unclassified-sensory-routes.parquet`. Runtime coverage and the absence of direct
terminal injection are checked by `run_wiring_smoke.bat` and the automated tests.

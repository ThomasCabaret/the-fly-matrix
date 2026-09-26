# ADR 0009 — Prefer proportional, exception-aware rule automation

- Status: accepted
- Date: 2026-09-26

## Context

The wiring revalidation, runtime benchmark, topology analyses, and future
calibration campaigns all contain a mixture of repeated deterministic work and
small numbers of scientific decisions. Repeating every item manually consumes
review effort and model quota, while prematurely building a generic framework can
cost more than resolving the cases directly. A successful batch must also expose
what its rules did not understand instead of producing a superficially complete
artifact.

## Decision

The project will prefer a rules-first workflow when a rule is repeated,
re-runnable, safety-critical, or cheaper to review once than case by case. Rules
are versioned, traceable, scoped, and mechanically checked. Their execution must
account for every item as applied, explicitly excluded, blocked, or exceptional,
and must emit both a compact summary and a machine-readable exception report.

Rules may be incomplete on their first run. Unmatched cases, conflicting matches,
failed invariants, input drift, unexpected fallbacks, and material output changes
are first-class results. They are triaged, converted into a refined rule or an
explicitly acknowledged special case when justified, and then re-executed.
Silent drops and silent scientific fallbacks are forbidden.

This preference is proportional, not absolute. The smallest mechanism that
provides useful replay and checking should be used. Automation may stop when its
expected implementation and maintenance cost exceeds the remaining manual work.
One-off or irreducibly ambiguous cases may be decided directly, provided normal
provenance, status, tests, and next-action requirements are preserved.

Human or agent review should receive compact evidence packets and decide only the
irreducible scientific ambiguity. The resulting decision should become a reusable
rule when a meaningful class of cases shares it. Offline programs then perform
the large-scale application, search, testing, and reporting without one model
call per record or trial.

The operational contract is defined in
[`docs/rules-first-automation.md`](../docs/rules-first-automation.md).

## Consequences

- Revalidation can reconstruct and compare large candidate sets while directing
  attention to exceptions and unsupported relations.
- Calibration runners can perform many trials locally while reserving agent work
  for new failure classes, scientific interpretation, and phase decisions.
- A successful run means all declared inputs were accounted for and no
  unexplained exception remains; it does not by itself establish biological
  correctness.
- The project avoids both per-record agent work and automation for automation's
  sake.
- Existing wiring, provenance, neuronal-scope, and calibration invariants take
  precedence over convenience or coverage metrics.

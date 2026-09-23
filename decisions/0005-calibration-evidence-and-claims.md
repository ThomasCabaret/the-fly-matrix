# ADR 0005 — Calibration evidence and behavioral claims

- Status: accepted
- Date: 2026-09-23

## Context

The completed terminal wiring can support several fundamentally different forms
of parameter estimation: copying biological measurements, fitting local transfer
functions, stabilizing recurrent dynamics, stabilizing an embodied simulation,
and potentially training toward a recognizable behavior.

Without a strict distinction, an action used as an optimization target could later
be presented as if it emerged from MaleCNS. Visual inspection and manual trial
selection can leak the target just as effectively as a numerical loss. Conversely,
banning all optimization would prevent legitimate technical calibration such as
avoiding numerical divergence, irreversible silence, or invalid body states.

## Decision

1. Every calibration target is classified as `evidence_transfer`, `technical`,
   `local_interface`, `behavior_targeted`, or `evaluation_only` and separately
   declares its optimization exposure.
2. Biological measurements may be transferred with explicit provenance, unit and
   scope transformations, uncertainty, and applicability limits.
3. Generic system properties may be optimized. Bounded and recoverable neural
   activity, numerical stability, joint-limit compliance, and neutral embodied
   stability are technical targets, not evidence of an emergent fly behavior.
4. A recognizable action or outcome used for loss computation, model selection,
   early stopping, manual parameter choice, or iterative visual tuning is
   `behavior_targeted`. This requires explicit user authorization and a highly
   visible lineage label.
5. A parameter lineage exposed to a behavior cannot support a claim that the same
   behavior emerged without training. It may support an explicitly labelled
   engineering demonstration.
6. Held-out stimulus-response protocols are locked before fitting. Their results
   may not affect parameters or model selection; doing so contaminates that
   protocol version.
7. The first system-level scientific target is a bounded, stimulus-specific
   response relative to sham in a simple 3D environment, with parameters frozen.
   No exact trajectory or named action is prescribed.
8. No external behavioral controller may bypass MaleCNS. Calibration modifies
   declared parameters of the connectome runtime and local interface boxes only.
9. Full parameter lineage, scenario exposure, commands, seeds, sources, failures,
   compact results, and next actions are versioned. Heavy run artifacts remain
   outside Git and are referenced by stable identifiers or checksums.

## Consequences

- The project can optimize for engineering stability without claiming that
  stability or a resulting movement is biologically emergent.
- A behavior-trained branch remains useful, but it is unmistakable in registries,
  dashboards, reports, and descendants.
- Held-out evaluation requires protocol discipline and may need replacement after
  accidental inspection-driven tuning.
- Calibration cannot repair a missing structural path. Any required topology or
  cardinality change returns to the wiring methodology.
- Status is multidimensional: a parameter set may be evidence-backed but untested,
  technically accepted but behavior-contaminated, or locally validated without a
  closed-loop result.

## Exceptions and revision

An unanticipated calibration type may be proposed when it preserves auditability
and the no-external-controller invariant. A choice that changes the scientific
claim, exposes a held-out behavior, or introduces a controller requires user
review and a superseding ADR. This decision is intentionally evolvable; it is not
a ban on experimentation.

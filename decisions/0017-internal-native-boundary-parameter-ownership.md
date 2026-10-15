# ADR 0017 — Internal native-boundary parameter ownership

- Status: accepted
- Date: 2026-10-15

## Context

ADR 0016 requires a population-typed, event-capable runtime. The full-graph
implementation now executes event→event, event→graded, graded→event and
graded→graded edges, but its first sentinels used fixed engineering scales. Those
constants proved execution mechanics only. They are not biological values and
must not remain hidden implementation choices while basal, central or peripheral
families are calibrated around them.

The four boundary directions do not all represent the same scientific object.
Same-native event→event and graded→graded edge strength belongs to the central
synaptic-efficacy family, interpreted in the native units of the pre- and
post-synaptic population. Cross-native event→graded and graded→event transforms
add a distinct conversion model whose kernel, scale, units and uncertainty need
their own ownership.

## Decision

1. `parameter.central.native_boundary_conversion.v0` owns internal
   event→graded and graded→event conversion capacity. It is distinct from the
   external basal-source bridges.
2. `parameter.central.synaptic_efficacy.v0` owns event→event and graded→graded
   effective coupling. Population dynamics owns thresholds, time constants,
   refractoriness and native state semantics. A campaign may identify these
   families jointly, but it may not hide one inside another.
3. The current values such as `event_to_graded = 0.5` and
   `graded_to_event_mV = 0.05` remain diagnostic fixtures attached to their
   original campaigns. They are not defaults, priors, bounds or promoted
   parameters.
4. Cross-native conversions must declare direction, input and output units,
   temporal kernel or event-generation rule, sharing level, applicability scope
   and uncertainty. Increasing their capacity requires a new family version.
5. Basal source intensity, same-native synaptic efficacy, cross-native conversion
   and neuron threshold/dynamics are treated as a coupled identifiability problem.
   A threshold crossing, finite execution or plausible body motion cannot select
   any member of that coupled space.
6. The 166,419 `dual_unresolved` basal-reached neurons need not be classified
   globally before local work. A first scientific chain must bound and account
   the causal population cone it actually exercises, propagate unresolved native
   alternatives there, and report what remains outside scope.
7. A downstream family may not be independently frozen if its result depends
   materially on an unfrozen boundary conversion. Member-conditioned composite
   bundles may be retained when the dependence is explicit and indivisible.

## Consequences

- The parameter-family inventory grows by one family and remains exhaustive at
  the level of currently known runtime capacity.
- The typed/hybrid runtime remains valid implementation evidence, but its four
  diagnostic boundary scales receive no scientific promotion.
- Local evidence can constrain one boundary class or causal cone without forcing
  a homogeneous whole-CNS assignment.
- Negative local results must first separate source intensity, synaptic efficacy,
  conversion and threshold effects before motivating a behavior-specific fit or
  a larger model.

## Revision

This ADR fixes ownership and anti-compensation rules, not one conversion equation.
A sourced conductance model, stochastic event process, graded kernel or more
biophysical representation may supersede the v0 family if its units, scope and
additional capacity are versioned. Such a revision does not reopen structural
wiring unless it changes the accepted candidate edge envelope.

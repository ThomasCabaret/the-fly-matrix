# ADR 0016 — Event-capable typed/hybrid neural runtime

- Status: accepted
- Date: 2026-10-06
- Decides: `target.neural_model_class_gate.v0`
- Supersedes as a project-wide default: neither the homogeneous rate comparator
  nor the homogeneous point-neuron LIF comparator

## Context

The first central runtime represented every canonical MaleCNS neuron by one
continuous rate state. It was fast and useful for engineering, but it has no
spikes, refractory state, event kernel or transmission delay. Locked temporal
probes demonstrate that its 5 ms representation aliases within-bin phase,
cross-channel order and sub-bin delay.

A source-aligned fixed-delay LIF comparator now reproduces the pinned Brian2
2.5.1 scheduling semantics and accounts for the complete canonical graph. It is
computationally feasible offline, but its constants are not accepted MaleCNS
physiology. Published whole-brain LIF results establish useful precedent, not the
validity of one point-neuron class for every population. Independent evidence for
graded/non-spiking fly visual populations makes that global promotion especially
unsafe.

The locked aBN1 pilot was directionally positive for the event comparator and
all nine sampled rate-member/input-bridge series. Completing the unbatched
protocol would cost roughly sixteen GPU-hours and is unlikely to discriminate
the global classes. Spending that budget would not repair the category error:
one circuit can accept a representation only for its own population scope.

## Decision

The global model-class gate returns **revise**.

MaleCNS will use an **event-capable typed/hybrid architecture**:

1. the runtime contract must be able to preserve explicit events, membrane and
   synaptic state, refractory state and declared transmission delays;
2. it must also permit explicitly typed graded/rate populations where independent
   evidence supports that abstraction;
3. conversion boundaries between event and graded state are named interfaces
   with units, temporal semantics, provenance and uncertainty—never hidden binning;
4. population assignments are local scientific decisions. An unclassified
   population is `dual_unresolved`, not silently rate or LIF;
5. unresolved populations may be propagated as an ensemble of admissible
   assignments through a bounded local campaign;
6. neither existing comparator supplies promoted parameter values. The 31 rate
   survivors remain an engineering ensemble, and the LIF unitary weight remains
   comparison-only because its source fit was behavior-exposed;
7. the fixed 1.8 ms delay is a source-traceable comparator baseline, not proof
   that morphology-dependent delays are irrelevant.

This is an architecture decision, not an implementation claim that the full
hybrid engine already exists and not a population census. The downstream gate is
`target.population_dynamics_assignment.v0`.

## Why this closes the global gate

The dangerous decision was whether weeks of calibration could assume one global
native representation. The answer is now no. Further evidence can change a
population assignment without invalidating wiring, the event scheduler, evidence
inventories, physical replay or other populations. The blast radius has therefore
been reduced from the entire calibration lineage to explicit local scopes.

The aBN1 full run is not executed merely to manufacture a binary winner. It may
be reopened as a population-capability experiment if batching makes it cheap or
if a new analysis gives it discriminating value. A second timing-sensitive
circuit can inform an assignment, but is no longer allowed to decide a universal
class by itself.

## Consequences and remaining blocks

- Local sensory and motor chain work may proceed with dynamics assignments and
  unit bridges declared per population.
- Basal rates cannot yet be copied into one universal input unit. Each downstream
  interface must target a declared event intensity, graded variable or explicit
  conversion boundary.
- A global embodied calibration remains blocked until every population exercised
  by that campaign has an accepted assignment or a preregistered unresolved
  ensemble policy.
- The point-neuron and morphology-dependent-delay risks remain scoped escalation
  risks. They are reopened by repeated independent residuals, not by default.
- No named behavior was fitted, inspected or used to make this decision.

## Evidence used

- `calibration/runner/neural-model-class-source-fidelity-v1.yaml`
- `calibration/runner/neural-model-class-brian2-conformance-v1.yaml`
- `calibration/runner/neural-model-class-temporal-probes-v1.yaml`
- `calibration/runner/neural-model-class-abn1-v2.yaml`
- `calibration/models/malecns-typed-signed-rate-v0.yaml`
- `calibration/models/malecns-lif-source-aligned-v1.yaml`
- Shiu et al. 2024, DOI `10.1038/s41586-024-07763-9`
- Lappalainen et al. 2024, DOI `10.1038/s41586-024-07939-3`

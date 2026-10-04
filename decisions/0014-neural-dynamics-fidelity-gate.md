# ADR 0014 — Neural dynamics fidelity and work-at-risk gate

- Status: accepted
- Date: 2026-10-04

## Context

The first full-graph runtime used
`model.malecns_typed_signed_rate.v0`: one bounded continuous state per neuron,
instantaneous sparse propagation at each numerical step, and no spike events,
refractory state, synaptic event kernel, or transmission delay. This was a useful
throughput and calibration-runner probe. It was not derived from evidence that a
rate model preserves the computations needed for fly behavior.

That distinction has a large blast radius. It determines the native units of
sensory input, the interpretation of basal firing rates, the families that can be
calibrated, the temporal information available to recurrent circuits, and the
meaning of every downstream embodied result. Continuing to build a rate-to-model
activity bridge before challenging this model class would put substantial work at
risk.

There is a closer published baseline. Shiu et al. used a whole-brain leaky
integrate-and-fire model with spike events, membrane and synaptic integration,
refractory state, and a fixed 1.8 ms transmission delay. Most constants came from
previous Drosophila modelling or electrophysiology; one global unitary synaptic
weight was selected using a sugar-GRN-to-MN9 response. The model then made many
feeding and antennal-grooming circuit predictions that were compared with calcium,
optogenetic, and behavioral experiments. Across the authors' 164 comparisons,
91% agreed. This is strong evidence that a simple event model can extract useful
sensorimotor predictions from a fly connectome. It is not evidence that the model
produces autonomous embodied fly behavior, and the sugar/MN9 calibration makes
feeding-related claims partially exposed rather than universally held out.

Other successful reductions have different scopes. Lappalainen et al. used
non-spiking graded dynamics in the early visual system, where many represented
neurons are themselves non-spiking, and optimized the model for optic flow before
comparing neural predictions with published experiments. NeuroMechFly v2 validates
an embodied mechanics platform, but its demonstrated behaviors use designed or
trained controllers rather than an untrained whole-connectome controller. These
works do not justify applying one global rate abstraction to all canonical
MaleCNS neurons.

The same caution applies to the event comparator. Some fly populations use graded
or otherwise non-standard transmission, and morphology or synapse location can
matter in selected circuits. One successful point-neuron LIF circuit therefore
does not authorize a homogeneous event model across MaleCNS. A typed or hybrid
result is a valid outcome of this gate, not a failure to choose between two global
models.

Primary references:

- Shiu et al., *A Drosophila computational brain model reveals sensorimotor
  processing*, Nature 634, 210–219 (2024),
  https://doi.org/10.1038/s41586-024-07763-9 and the authors' implementation at
  https://github.com/philshiu/Drosophila_brain_model.
- Lappalainen et al., *Connectome-constrained networks predict neural activity
  across the fly visual system*, Nature 634, 1132–1140 (2024),
  https://doi.org/10.1038/s41586-024-07939-3.
- Wang-Chen et al., *NeuroMechFly v2: simulating embodied sensorimotor control in
  adult Drosophila*, Nature Methods 21, 2353–2362 (2024),
  https://doi.org/10.1038/s41592-024-02497-y.

## Decision

### The current rate runtime is a retained engineering baseline, not the default scientific model

All completed v0 runs remain valid for the claims they actually tested: complete
edge accounting, sparse CPU/GPU execution, runner determinism, numerical
pathology detection, and rate-model timestep portability. They do not validate a
neural representation, a biological time course, or the 31-member ensemble as a
scientific starting population.

No v0 rate member may be promoted as the central biological reference. Numerical
calibration work whose meaning depends on the central model's native units is
paused. Evidence inventories, wiring work, model-independent local measurements,
and reusable runner engineering may continue.

### A small discriminating model-class gate precedes further dependent calibration

The next central milestone is not a large calibration campaign. It is a bounded
comparison that must:

1. implement or faithfully adapt an event-based leaky integrate-and-fire baseline
   with explicit spike times, membrane integration, synaptic integration,
   refractory state, and a declared transmission-delay policy;
2. reproduce a deterministic CPU reference on a small fixed graph and establish a
   full-MaleCNS CPU/GPU throughput and memory benchmark;
3. distinguish source-derived constants, one or more genuinely free parameters,
   MaleCNS-specific adaptations, and unsupported assumptions;
4. compare event and rate candidates on model-independent technical probes and at
   least one preregistered circuit-level reference that was not used to choose the
   compared parameters;
5. record what temporal information each representation necessarily destroys and
   issue an explicit go, revise, or stop decision before dependent calibration is
   scaled.

The purpose is not to prove that LIF is the final biology. It is to reject obvious
dead ends cheaply and establish the least simplified model class for which the
project has affirmative evidence.

Acceptance is scope-aware. The gate may accept different representations for
different annotated populations when the evidence supports that split. A single
circuit reference can reject or support a local candidate, but cannot by itself
close the global point-neuron or homogeneous-class risk.

### Delay fidelity is a separate explicit hypothesis

The published whole-brain LIF precedent uses one fixed 1.8 ms delay; it does not
derive delay from each axonal path. The current MaleCNS flat weight table also does
not by itself provide an accepted edge-specific conduction delay. Therefore:

- zero-delay propagation is not an accepted biological default;
- a fixed evidence-backed delay is a valid first event-model baseline;
- morphology-dependent delays require versioned geometry, path-length extraction,
  a conduction-velocity model, units, uncertainty, and a sensitivity comparison;
- absence of those inputs is reported as unresolved, never silently approximated
  as negligible.

### Critical assumptions control work at risk

Before a project-wide or high-cost implementation depends on an unresolved
assumption, record its scientific consequence, blast radius, evidence for and
against, cheapest discriminating experiment, compute and agent-work budget, stop
criteria, and rollback/reuse plan. If failure could invalidate multiple future
lots or change the meaning of their parameters, run that discriminating experiment
before scaling the dependent work.

This is a proportional rule, not a demand to prove every implementation detail.
Reversible local assumptions may proceed with a declared fallback. A critical
unvalidated model-class assumption is a stage gate. Passing an engineering smoke
test, achieving high throughput, or making an optimizer converge cannot satisfy a
scientific model-class gate.

## Consequences

- The basal evidence inventory remains accepted, but the planned
  spikes-per-second to normalized-rate bridge is no longer the next action. A
  spike-native model may consume rates as stochastic event intensities instead.
- The 31 rate-model survivors are retained as a reproducible engineering ensemble,
  not propagated as if they sampled plausible fly physiology.
- The full-graph benchmark, calibration runner, signed edge inventory, physical
  loop, and replay infrastructure remain reusable by an event model.
- Model selection becomes an explicit, auditable calibration dependency rather
  than an implicit implementation choice.

## Revision

The gate may accept a rate, event, hybrid, or compartmental model if the bounded
comparison supports it. It does not require maximal biophysical detail. Any
accepted simplification must state its scope; for example, a graded visual model
does not automatically authorize the same dynamics for motor or central neurons.
Embodied attribution and actuator semantics remain a separate downstream gate
under ADR 0015.

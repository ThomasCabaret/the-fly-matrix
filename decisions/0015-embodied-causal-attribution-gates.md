# ADR 0015 — Embodied causal attribution and first held-out path

- Status: accepted
- Date: 2026-10-04

## Context

The project must eventually distinguish a response caused by MaleCNS from one
supplied by a permissive interface, actuator controller, body model or global
optimizer. This boundary is as important as neural-model fidelity because an
embodied trajectory can look coherent even when most of its control is carried by
an abstraction downstream of the connectome.

The current runtime is more specific than a generic FlyBody deployment. It creates
all 102 articulated channels with `ActuatorType.MOTOR`; it does not currently use
MuJoCo position or velocity servos. This rules out one particular hidden-position-
controller failure in the present path. It does not establish biological motor
fidelity: direct joint motor commands still collapse muscles, activation dynamics,
compliance and local reflex contributions into the motor-transfer and mechanical
surrogate boundary.

Other ambiguities have the same causal-attribution shape. Highly flexible sensory
or motor transfers could compensate for an inadequate central model. Unknown
afferents could dominate a result under one arbitrary basal policy. A chemical-
synapse graph may omit electrical or other mechanisms required by a candidate
behavior. Finally, one successful LIF circuit does not establish that a homogeneous
spiking point-neuron abstraction is suitable for graded or compartment-sensitive
populations throughout MaleCNS.

## Decision

### Actuator semantics are a gate before embodied behavioral interpretation

The resolved actuator type, MuJoCo gain/bias/dynamics parameters, force and control
limits, targeted joint, body contract and FlyBody version are frozen and hashed in
every embodied campaign. A regression must fail if a position or velocity servo
appears without a new versioned decision.

Before neutral embodied fitting or a held-out behavioral claim, a bounded actuator
semantics audit must quantify, by actuator class and homologous side:

1. command-to-force and command-to-joint-state responses under passive, unloaded
   and representative loaded conditions;
2. the response to impulses, steps and release to zero, including mechanical
   damping, saturation, delay and stored-energy effects;
3. how much stabilization remains in FlyBody/MuJoCo when the same open-loop command
   trace is replayed without sensory feedback;
4. whether a direct motor surrogate remains defensible for the first claim or a
   muscle/activation model is required.

This audit is technical and behavior-naive. It does not tune a gait, pose, escape
or grooming response. Passing it attributes and bounds the physical abstraction;
it does not make the actuator model biological.

### Interfaces may not absorb central or mechanical error silently

Local sensory, motor and basal families should be constrained and frozen from
independent local evidence before a global embodied objective whenever possible.
If a joint campaign is required, it must declare the compensation graph, sharing
capacity, frozen families, family-wise residuals, ablations and identifiability
diagnostics. At minimum, compare fits with each high-capacity interface family
held fixed or removed and report whether materially different parameter blocks
produce indistinguishable observations.

Whole-vector flexibility, per-channel residuals or broad learned transfers cannot
be introduced merely to make neutral stability pass. A local interface whose
output directly selects a coordinated whole-body action is an external controller,
even if it is implemented as a differentiable calibration layer.

### Neural-model decisions may be typed or hybrid

The ADR 0014 gate may conclude `rate`, `event`, `typed_hybrid`, `compartmental` or
`stop`. A model class is accepted only for the biological scopes actually tested.
A circuit-level success cannot authorize one homogeneous neuron abstraction over
all MaleCNS. Systematic failures by cell class or region trigger a typed/hybrid
comparison before a project-wide higher-capacity homogeneous model.

The point-neuron assumption is retained as an explicit background risk. It does
not block the current bounded comparison. It becomes a priority when multiple
independent circuits fail after sign, delay, input-unit and local-interface errors
have been excluded.

### Missing inputs and mechanisms are propagated, not hidden

Unknown afferents receive a preregistered sensitivity analysis over a small set of
poor, behavior-naive basal hypotheses. The analysis does not choose the hypothesis
that improves a named behavior. High sensitivity promotes the family to a gate;
low sensitivity permits the uncertainty to be propagated with its tested range.

Each candidate evaluation records a mechanism-coverage statement. A behavior
whose causal circuit may materially require absent electrical coupling, detailed
muscle dynamics, flight mechanics or another unrepresented mechanism is not an
early falsification test of calibration. It can remain a later integration target,
but a negative result must be labelled mechanistically ambiguous.

### Gate order toward the first clean observation

Progress is reported by these gates rather than a single calibration percentage:

1. select a defensible, scope-aware central dynamics lineage;
2. quantify the current direct-motor actuator abstraction;
3. calibrate and freeze one minimal local sensory chain;
4. calibrate and freeze one minimal local motor chain;
5. obtain short-horizon neutral embodied stability without a named action target;
6. lock and run one held-out stimulus/sham protocol with topology controls.

The currently preferred first candidate is a mirrored, localized tactile response
of a leg because it can test spatial specificity before requiring a full grooming
sequence or flight. This is a planning priority, not a locked protocol. It remains
conditional on a stimulus-resolution audit and independent biological sourcing.
Optomotor evaluation follows only after visual registration is defensible.
Localized grooming requires finer tactile semantics, and antennal grooming is not
cleanly held out for any lineage that used the antennal circuit reference during
model selection. Looming/takeoff remains later because visual, flight and missing-
mechanism confounds make a negative result difficult to interpret.

## Consequences

- The actuator concern is corrected rather than copied literally: the present
  runtime has direct motor actuators, not position servos, but its causal
  contribution still requires measurement.
- Neutral stability cannot jointly free central, sensory, motor and mechanical
  capacity without an explicit identifiability decision.
- Unknown afferents and omitted mechanisms become counted uncertainties with
  sensitivity or applicability records.
- A negative early evaluation is interpretable only after the mechanism and
  interface gates relevant to it are closed.
- Architectural progress remains advanced, while scientific behavioral evidence
  remains early until these gates have produced accepted results.

## Revision

This decision fixes attribution and reporting invariants, not one permanent
actuator or neuron implementation. A later muscle model, typed neural model or
different first evaluation is allowed through a new versioned decision that
preserves exposure history and revalidates affected descendants.

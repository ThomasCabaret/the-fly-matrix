# Prospective emergent-behavior evaluations

## Status and purpose

This document is a **prospective observation catalog**, not a runnable protocol,
training objective, acceptance gate or claim that any behavior exists. None of
the items below has been run or inspected. One item—the front-leg proprioceptive
resistance reflex—was promoted on 2026-10-18 to the immutable `evaluation_only`
protocol `calibration/protocols/first-held-out-proprioceptive-resistance-reflex-v0.yaml`.
The other entries remain candidates rather than protocols.

Their scientific value depends on the tested behavior not having influenced
parameter fitting, model selection, early stopping, routing refinement, capacity
changes or manual trial selection. Merely registering a category does not expose
an outcome, but any later design decision made specifically to improve that
category contaminates it for the affected lineage and must be recorded.

Before execution, each selected item requires its own immutable protocol version:
scene and body contract, stimulus generator, intensities and timing, seeds,
metrics, thresholds, exclusions, analysis code, topology-control recipe and
parameter-set hashes. Protocols should be locked only when the runnable system is
ready; this catalog must not be mistaken for that lock.

## Current planning priority and confounds

FH-01 has now selected a **front-leg proprioceptive resistance-reflex candidate**
for planning, before any simulated response was generated or inspected. The
locked stimulus is a passive 8° extension of one front tibia at 123°/s, with
paired sham and matched left/right trials. Eight paired seeds, a 7-of-8
directional sign rule, all eleven unranked FH-07 members and four seeds for each
of two topology-control families were fixed before any outcome was inspected.
No effect-magnitude threshold was invented because the sources do not supply one
in transferable simulator units. The lock is not a prediction that the response
will be positive.

The decision is recorded in
`calibration/evaluations/first-held-out-channel-readiness-v0.yaml`. It relies on
independent Drosophila evidence for the tibial resistance reflex and on the
existing bounded FeCO→front-leg chain. The motor paper also supports local
spike-to-force and event-capability claims used elsewhere; therefore the reflex
direction, timing, spatial specificity and body response are explicitly withheld
from fitting and model selection. A shared publication does not make those
held-out observations calibration data.

The mirrored localized tactile response remains scientifically attractive but is
deferred as the first attempt. Its separate mechanosensory families contain 323
groups, 2,108 local route candidates and up to 1,785 routing dimensions. Their
routing weights, transfer functions and local calibration dataset remain
unresolved, while FlyBody supplies only six leg-level aggregate contact sensors
plus coarse head/thorax force channels. Treating FeCO proprioception as contact
would still be forbidden.

The alternatives remain valuable but currently carry larger confounds. Grooming
requires finer tactile resolution and a sequence interpretation; antennal grooming
is also exposed for any lineage that uses the antennal circuit reference to select
a neural model. Optomotor evaluation depends on defensible visual registration.
Looming/takeoff combines vision, flight mechanics and potentially absent
electrical coupling, so a negative result would not cleanly identify a calibration
failure. Every eventual protocol must include a mechanism-coverage statement.

## Candidate observations

### Localized grooming

Apply a localized mechanical perturbation to a declared body region and measure
whether the response recruits anatomically appropriate limbs toward that region.
Candidate contrasts include head versus wing/posterior stimulation and mirrored
left/right trials. Useful future metrics include limb-region specificity,
stimulus-side preference, latency, repeatability and difference from sham. An
arbitrary increase in global motor activity is not sufficient.

### Grooming hierarchy

Stimulate two or more regions simultaneously and observe whether a reproducible
ordering of cleaning-like responses emerges, including candidate anterior versus
posterior priority. The eventual protocol must distinguish ordered selection from
simple reachability, actuator saturation or whichever stimulus is physically
stronger. Sequence definitions and scoring must be frozen before viewing results.

### Looming escape response

Present a visual object with rapidly increasing angular size and compare the
response with sham, non-approaching visual controls and mirrored stimulus
locations. Observe escape-like or takeoff-preparation motor structure, especially
direction relative to stimulus position, rather than merely total activity.

### Sensorimotor lateralization

Apply matched tactile or visual stimuli on the left and right. Test whether motor
response distributions transform under mirror symmetry in a biologically
coherent way. Candidate metrics include mirrored-output equivariance, ipsilateral
and contralateral recruitment, directional specificity and paired effect size
relative to sham. This is more discriminating than a global activity increase.

### Front-leg proprioceptive resistance reflex (protocol v0 locked, not run)

Apply a bounded passive extension or flexion to one front tibia and compare the
scoped motor and physical response with sham. Adult Drosophila recordings report
a resistance-reflex response of tibia-flexor motor neurons to passive extension
([Azevedo et al., 2020](https://doi.org/10.7554/eLife.56754)); FeCO populations
encode joint position and movement direction
([Mamiya et al., 2018](https://doi.org/10.1016/j.neuron.2018.09.009)). Protocol v0
fixes response direction relative to paired sham as the primary neural criterion
and treats physical opposition, latency, recovery, motor-class detail and
left/right symmetry as secondary or descriptive measurements. Missing
muscle/compliance fidelity still makes a physical negative result ambiguous.
None of these response properties may enter calibration or rank an FH-07 member.

### Optomotor response

Move the visual field leftward or rightward and observe whether a coherent yaw or
turning tendency follows the stimulus direction. Mirrored stimuli, stationary
patterns and equal-energy non-directional motion are candidate controls. The
metric must use body or motor directionality, not only neural activation.

### Non-trivial optomotor temporal dynamics

Use prolonged visual motion to look for temporal structure beyond an instantaneous
stimulus-response gain, such as adaptation, delayed modification or reversal of a
motor tendency. This remains exploratory until a sourced biological expectation
and a preregistered time-domain statistic are available. Post-hoc discovery of a
temporal pattern cannot be promoted as a clean held-out result.

### Structured spontaneous motor activity

During nominal no-stimulus periods, look for occasional reproducible motor motifs,
including possible grooming-like sequences. This is the least specific candidate:
arbitrary motion, oscillation or instability is not evidence of biological
behavior. Any motif detector must be defined from independent evidence and locked
before opening the evaluated trajectories; otherwise the result is exploratory.

## Required control ladder

Each eventual protocol should include, where applicable:

1. sham or no-stimulus trials with identical initialization and observation;
2. a behavior-naive calibrated MaleCNS lineage whose parameters were not chosen
   using the tested behavior;
3. topology controls receiving the same body, interfaces, stimulus and analysis.

Topology controls should be an ensemble rather than one convenient rewire. Their
recipe should preserve relevant nuisance statistics where practical, such as
directed in/out degree, weight distribution, sign or transmitter-class counts and
declared interface cardinalities, while destroying the topology under test.
Targeted pathway or module scrambling may complement whole-graph rewiring.

Two topology-control comparisons answer different questions and should remain
separate:

- **frozen-parameter control** applies the same accepted parameter set after
  rewiring and tests the immediate dependence on topology;
- **recipe-matched control** reruns the same non-behavioral calibration protocol
  and compute budget on each rewired graph, then asks whether arbitrary topology
  can recover the evaluated specificity.

Neither control may be calibrated against the held-out behavior. A compelling
result is repeatable, stimulus-specific and directionally or anatomically coherent
in MaleCNS, while becoming absent, disorganized or materially less specific across
the preregistered topology-control ensemble.

## Cross-protocol reporting

Every executed evaluation should report sham effect size, repeatability, latency,
boundedness, recovery, directional or anatomical specificity, uncertainty across
seeds and central parameter members, and the gap from topology controls. Negative
and ambiguous outcomes remain first-class results. Biological expectations and
thresholds require sources before protocol lock; this catalog currently records
project suggestions, not literature-backed numerical criteria.


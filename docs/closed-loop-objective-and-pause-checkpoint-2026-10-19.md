# Closed-loop objective and pause checkpoint — first attempt

**Status:** project paused by user decision on 2026-10-19.

**Git checkpoint:** `checkpoint-first-closed-loop-attempt-v0`.

This document records the intended end state and the honest boundary reached by
the first attempt. It overrides any reading of a completed local roadmap as
completion of the project-level objective.

## Actual project objective

The objective is one embodied, continuously closed loop using the complete
canonical MaleCNS connectome:

1. the physical simulator advances the fly body and its environment;
2. body and world observations enter MaleCNS through explicit sensory and basal
   interface boxes;
3. all 166,700 canonical neurons and the canonical recurrent graph evolve under
   a biologically defensible, event-capable typed/hybrid dynamics contract;
4. MaleCNS outputs pass through explicit motor-transfer boxes to the physical
   actuators;
5. the resulting physical state becomes the next neural input, continuously.

The parameters used by that loop must come from a non-naive, reproducible and
auditable calibration procedure. MaleCNS must remain the principal controller.
An external behavioral controller, a diagnostic bypass, an uncalibrated full-
graph execution, an open-loop trace or a replay is not completion. Replay remains
useful as a presentation mechanism after a closed-loop trajectory has been
computed, but it is not a substitute for the loop.

The eventual scientific validation is at least one specific response that was
not used to fit, rank, manually choose or stop the calibration, with the declared
sham and topology controls.

## What the first attempt actually completed

### Structural wiring

Structural wiring v0 is complete within its declared contract. Every terminal
input and output has an explicit disposition and the four peripheral wiring
families can be rebuilt from versioned rules and exceptions and independently
revalidated. The wiring campaigns are rules-first and apply across the complete
input/output boundary; this work is not merely a hand-written 196-neuron sample.

This establishes where information may enter and leave MaleCNS. It does not
provide calibrated neural dynamics, sensory amplitudes, motor physiology or a
biologically valid whole-connectome parameter set.

### Reusable execution and governance infrastructure

The repository contains a real 166,700-neuron, 25,582,938-edge MaleCNS runtime,
GPU execution paths, closed-loop record/live modes, producer-independent physical
replay, a calibration registry and dependency DAG, reproducible campaigns,
parameter lineage, uncertainty sets, controls, tests and audit packaging. These
are substantial reusable results.

The full graph has been loaded and exercised by integration benchmarks and
diagnostic sentinels. Those executions prove mechanics and accounting, not full-
graph calibration or biological fidelity.

### Calibration scope actually exercised

The detailed calibration effort is a local front-leg proprioceptive chain:

- 36 FeCO sensory neurons;
- 150 intermediate neurons;
- 10 motor neurons;
- 196 neurons in total, about 0.118% of the 166,700 canonical neurons (roughly
  one neuron in 850);
- 12 locally `event_required` and 184 locally `dual_unresolved` populations.

It is not one generic calibration program that can now be launched unchanged to
calibrate the other 166,504 neurons. It is a reproducible DAG of local evidence,
candidate construction, coupled technical gates, uncertainty propagation,
neutral-regime filtering and one held-out evaluation. Parts of its runner and
governance are reusable, but the biological rules, evidence and parameter
identifiability are specific to the exercised chain.

The local machinery **works as engineering infrastructure**: it reconstructs its
scope, executes finite candidate ensembles, preserves uncertainty, drives the
body, produces exact replays and runs frozen and recalibrated topology controls.
It has **not worked as a scientific calibration of a functional fly**: no complete
reference parameter set is promoted, most local dynamics remain unresolved and
no result licenses extrapolation to all MaleCNS populations.

### Outcome of the first held-out attempt

The completed v2 protocol executed 1,536 paired trials / 3,072 outcome rows. It
reported zero canonical primary passes and zero canonical physical-support
passes. Every canonical physical row was masked by a joint-limit violation; the
neural response was left-only and member-dependent; and the response was not
topology-specific against the declared controls. The protocol is therefore
closed as `mechanism_limited_ambiguous_no_canonical_primary_pass`, with no tuning
after outcome inspection.

This is an honest negative/ambiguous first attempt, not evidence that the desired
closed-loop fly has been obtained.

## Principal work still required for the actual objective

The following are research fronts, not a reliable list of fifty mechanical
deliveries:

1. assign or propagate defensible typed neural dynamics over the relevant whole
   MaleCNS computation; 166,419 basal-reached neurons remain
   `dual_unresolved`;
2. establish morphology-aware transmission-delay sensitivity and, if required,
   derive versioned path-length/delay data rather than retaining one fixed 1.8 ms
   comparator delay;
3. identify central synaptic efficacies, thresholds, time constants, conversions
   and capacity beyond the unvalidated minimal shared-parameter hypothesis;
4. calibrate basal-source families and the sensory interfaces needed by a whole
   embodied run without allowing interfaces to become hidden controllers;
5. calibrate motor-neuron-to-force and force-to-body transfer beyond the current
   bounded direct-MOTOR surrogate, including unresolved class and mechanism
   uncertainty;
6. obtain a stable, non-pathological full-connectome closed loop at the required
   temporal fidelity and quantify its performance relative to biological time;
7. lock and execute a new held-out response protocol only after the lineage is
   frozen, with sham, mirrored and topology controls.

There is currently no evidence-backed batch count for completing these fronts.
The previous order-of-magnitude estimate of roughly fifty agent deliveries is
withdrawn as a project forecast: the remaining work contains unresolved data and
model-identification questions whose branching factor has not been bounded. It
must not be silently converted into another rolling estimate.

## Pause and possible resumption

No new calibration, fitting or behavior-evaluation campaign should be started
from this checkpoint without an explicit user decision to resume. Read-only
inspection, preservation and reproducibility checks remain safe.

A future resumption should first decide whether new biological data, a materially
stronger automation strategy or improved agent capabilities make the global
objective tractable. The cheapest credible restart is not another local fit: it
is a bounded demonstration that one rules-first population/delay/calibration
procedure generalizes across several independent neural families while retaining
honest exception and uncertainty accounting.

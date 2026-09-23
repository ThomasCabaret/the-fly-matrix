# Calibration methodology

## Purpose

Calibration begins only after structural wiring has a terminal disposition for
every exposed channel. It assigns or estimates the parameters of the already
declared boxes and of the recurrent MaleCNS runtime. It must not conceal missing
wiring, add an external behavioral controller, or turn a requested behavior into
evidence that the behavior emerged from the connectome.

The long-term system-level demonstration is an embodied fly in a simple 3D
environment that remains bounded and recoverable at rest, then produces a
stimulus-specific response. This is a sequence of engineering and scientific
claims, not one optimization objective.

## Calibration classes

Every target and every parameter set declares exactly one primary class. A
campaign may combine targets only if their individual losses and exposure rules
remain separately reportable.

### `evidence_transfer`

Values are copied or transformed from biological measurements, published models,
or another versioned dataset. The record must identify the source, biological
scope, units, transformation, uncertainty, and mismatches with this model.
Borrowed values are evidence-backed initial conditions; they are not automatically
validated in The Fly Matrix.

### `technical`

The target constrains generic properties of the simulated system rather than a
recognizable fly action. Examples include finite numerical values, bounded
activity, recovery after perturbation, avoiding global irreversible silence,
avoiding runaway recurrent amplification, respecting joint limits, and keeping a
nominal body simulation from immediately diverging.

Technical calibration may optimize parameters. Its results must be described as
trained engineering stability, not as an emergent behavior. Criticality may be
measured, but it must not be assumed to be the correct target without explicit
evidence.

### `local_interface`

The target estimates a local map already represented by a wiring box: physical
sensor state to afferent channels, efferent channels to actuator commands, basal
input statistics, or a justified feedback path absent from the physical model.
The calibrated scope must remain local and explicit. A mapping that directly
selects a whole-body action is a behavioral controller and is forbidden unless
the project contract is changed explicitly.

### `behavior_targeted`

The objective contains a recognizable action, trajectory, gait, pose sequence, or
task outcome. This class is permitted only after explicit user authorization. It
must be visually prominent in the target, campaign, parameter-set lineage,
dashboard, and any report using the result.

A behavior exposed through the loss, validation used for model selection, early
stopping, manual trial selection, or iterative visual tuning is considered trained
on that behavior. It cannot later support a claim that the behavior emerged
without behavioral training. Such a result can still be a useful engineering
demonstration.

### `evaluation_only`

The protocol measures a held-out outcome. Its scenarios, traces, and derived
metrics may not influence optimization, model selection, early stopping, manual
parameter choice, or acceptance of intermediate parameter sets. Inspecting the
result and then changing parameters contaminates the protocol version; a new
held-out protocol must be registered before another claim.

## Exposure and claim policy

Each target declares `optimization_exposure` as `allowed`, `diagnostic_only`, or
`evaluation_only`.

- `allowed`: the objective may drive fitting within its declared scope.
- `diagnostic_only`: it may be observed during development but cannot decide which
  parameter set is promoted.
- `evaluation_only`: it is locked before fitting and opened only for final
  evaluation.

Target names are not sufficient protection against leakage. Closely related
variants, mirrored trials, and manual qualitative judgments count as exposure
when they reveal the desired behavior. The registry must therefore record train,
validation, diagnostic, and held-out scenario identifiers separately.

Claims follow the most exposed dependency in a parameter set's complete lineage.
If any ancestor used a behavior-targeted objective, descendants cannot be called
behavior-naive unless the affected parameters are reset and the clean lineage is
demonstrated.

## Calibration objects

The versioned registry under `calibration/` uses small, reviewable records:

- **target**: objective class, scope, metrics, exposure policy, acceptance gates,
  dependencies, provenance, and claim policy;
- **scope**: boxes, channels, neuron populations, body degrees of freedom, and
  parameters that may change;
- **campaign**: executable plan including target versions, datasets, scenario
  splits, optimizer or search method, bounds, seeds, command, and compute budget;
- **parameter set**: immutable values or references, parent lineage, origin per
  parameter family, units, source transformations, and promotion status;
- **evaluation**: protocol version, parameter-set identifier, metrics, failures,
  artifacts, and conclusion.

Large traces, checkpoints, videos, and optimizer histories belong under
`runs/calibration/` and remain unversioned. Git stores compact summaries,
configuration, checksums or content identifiers, and promoted parameter sets.

## Independent status dimensions

There is no single `calibrated` boolean. Records track at least:

- target lifecycle: `proposed`, `runnable`, `running`, `evaluated`, `accepted`,
  `rejected`, `blocked`, or `superseded`;
- parameter origin: `unknown`, `assumed`, `borrowed`, `measured`, `fitted`, or
  `frozen`;
- validation level: `not_run`, `sanity`, `local`, `closed_loop`, `held_out`, or
  `failed`;
- evidence quality and remaining assumptions;
- `next_action` and the reason for every block.

Status changes must identify the command or protocol, date, Git commit, relevant
dataset or source version, seed, result, and generated artifact location.
Failures and negative results are retained in compact form; silently discarding
them would make later tuning impossible to audit.

## Parameter-family coverage

The registry must be able to represent at least these independent families:

1. MaleCNS temporal dynamics, synaptic interpretation, delays, signs, and global
   or typed scaling rules;
2. sensory transduction and routing boxes;
3. motor decoding and actuator transfer boxes;
4. basal source statistics for intentionally simplified modalities;
5. justified feedback boxes outside the connectome when the environment or body
   model does not provide the relevant loop;
6. simulator and contact parameters that affect the embodied result.

Calibration may start with shared or typed parameters and later refine them. The
degrees of freedom, frozen values, constraints, and inheritance rules must remain
explicit. Calibration must never change structural cardinality or topology
silently; such a need returns to the wiring workflow.

## Recommended staged program

### Stage 0 — Characterize the uncalibrated system

Run deterministic sanity cases and record numerical failures, silence, saturation,
activity distributions, latency, and runtime cost. This baseline is not a failed
calibration; it is the reference against which progress is judged.

### Stage 1 — Technical neural dynamics

Establish finite, bounded and recoverable temporal activity under basal input and
small perturbations. Measure both pathological extremes: irreversible quiescence
and self-amplifying or saturating echoes. Do not prescribe a fly action.

### Stage 2 — Local interfaces

Calibrate evidence-backed sensory, motor, basal, and missing-feedback transfer
functions independently where possible. Use local measurements or generic
physical constraints before whole-body behavioral objectives.

### Stage 3 — Neutral embodied stability

On a simple flat-ground scene, seek a numerically bounded, physically recoverable
closed loop. Permissible objectives include not exploding, not violating limits,
not falling immediately, limited actuator energy, and bounded CNS activity. A
particular stance, gait, step sequence, or recognizable action is not prescribed.
This remains trained technical stability and must be labelled as such.

### Stage 4 — Held-out stimulus response

With parameters frozen, compare stimulus, sham, and when appropriate mirrored
stimulus trials. Measure time locking, difference from sham, directional or
stimulus specificity, repeatability, boundedness, and recovery. The protocol does
not prescribe a jump, grooming sequence, exact trajectory, or other named action.
A positive result is evidence of a causal, specific response, not automatically of
naturalistic behavior.

Behavior-targeted fitting, if later desired, is a separate explicitly authorized
stage and uses separate parameter lineages and reports.

## Promotion gates

A parameter set may become the project reference only when:

1. its complete lineage and parameter origins are recorded;
2. the campaign is reproducible from a documented command and fixed inputs;
3. all structural and runtime invariants still pass;
4. its declared acceptance metrics pass without consulting forbidden targets;
5. regressions against earlier accepted technical targets are reported;
6. its claim label reflects every behavior exposure in its ancestry;
7. rollback to the previous reference set is possible.

Promotion does not erase alternative parameter sets. The active reference is a
pointer in `calibration/state.yaml`, not a mutable file overwritten in place.

## Provenance and reproducibility checklist

For each substantive result, record:

- the scientific or engineering assertion being supported;
- source URL, citation or dataset identifier, and access/version information;
- source-to-model transformation, units, exclusions, and uncertainty;
- exact scope and allowed parameter names;
- initial values, bounds, frozen values, random seeds, and search method;
- objective terms and weights, including penalties;
- train, validation, diagnostic, and held-out scenario identifiers;
- command, environment description, Git commit, and input hashes;
- metrics, acceptance decision, artifact paths and checksums;
- known failures, remaining assumptions, and `next_action`.

When no source exists, say so and classify the value as `assumed` or `fitted`.
Never convert an intuition into biological provenance.

## Resuming work

A new contributor or agent should read, in order:

1. `PROJECT_STATE.md`;
2. this document and `decisions/0005-calibration-evidence-and-claims.md`;
3. `calibration/state.yaml` and the active target records;
4. relevant parameter-set, campaign, and evaluation records;
5. the wiring ledger and provenance records for every box in scope.

The next action must be derivable from those files without relying on chat
history. If a case does not fit this taxonomy, prefer a new explicit class or ADR
over forcing it into a misleading status, and ask the user when the choice changes
the scientific meaning of the project.

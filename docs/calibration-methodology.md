# Calibration methodology

## Purpose

Calibration begins only after structural wiring has a terminal disposition for
every exposed channel. It assigns or estimates the parameters of the already
declared boxes and of the recurrent MaleCNS runtime. It must not conceal missing
wiring, add an external behavioral controller, or turn a requested behavior into
evidence that the behavior emerged from the connectome.

Terminal coverage is necessary but not sufficient for fitting an interface. When
a box, group, wire or parameter family is owned by an open
`scientific_wiring_revalidation`, its current manifest is executable prewiring,
not accepted calibration topology. No affected parameter may be fitted, borrowed
or promoted until that review is `independently_validated`. Runtime scaffolding
may still be built if it does not accept or tune the disputed mapping.

The long-term system-level demonstration is an embodied fly in a simple 3D
environment that remains bounded and recoverable at rest, then produces a
stimulus-specific response. This is a sequence of engineering and scientific
claims, not one optimization objective.

An isolated body/viewer diagnostic may bypass MaleCNS only under ADR 0006. It is
not a calibration target, campaign, parameter set, baseline for CNS quality, or
closed-loop validation. Its code, warning overlay and run outputs must remain in
the diagnostic namespace and cannot be reused by calibration or evaluation.

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

The durable dependency, sharing, uncertainty and reopening rules are fixed by
[`ADR 0012`](../decisions/0012-hierarchical-reconstructible-calibration.md).

## Parameter-family inventory and dependency DAG

Before fitting values, create one versioned record per parameter family. A family
is the smallest useful unit that can be scoped, constrained, calibrated, frozen
and reopened coherently. Its record includes:

- biological or technical meaning, parameter kind, units and applicability;
- owners, names, dimension and continuous or discrete domain;
- sharing hierarchy and the currently selected sharing level;
- origin policy, priors, bounds and explicit fallback;
- allowed fitting data, local held-out data and forbidden behavior exposures;
- identifiability and any family that must be estimated jointly;
- upstream and downstream dependencies;
- topology, candidate-envelope, ruleset and exception hashes where applicable;
- uncertainty representation, accepted-set criteria and reference-selection rule;
- freeze state, accepted parameter set, reopening reason and stale descendants.

`parameter_kind` distinguishes `routing`, `transfer`, `basal`,
`neural_dynamics`, `mechanical` and `technical_nuisance`. `claim_role` separately
states whether a value is interpreted as `biological`, `technical` or
`surrogate`. Fitting a technical stabilizer does not turn it into estimated
physiology, and behavioral exposure is tracked independently through lineage.

Families and campaigns form a DAG. The expected broad flow is evidence transfers
and basal priors → local sensory and motor interfaces → typed central dynamics →
physical closed loop → global technical constraints → held-out evaluation. This
is an order of dependencies, not a rigid serial recipe: independent branches may
run in parallel and central diagnostic studies may begin before every interface is
accepted. A value may not flow downstream until its required acceptance gate is
satisfied.

A joint campaign is permitted when separate fitting is genuinely
non-identifiable. It must state the compensation risk, capacity, local evidence,
ablation or sensitivity checks, and why a smaller factorization failed. Do not
force an artificial separation, but do not use global fitting merely because it
is convenient.

## Sharing hierarchy and capacity discipline

Prefer, in order, direct measurement, documented evidence transfer, sharing by a
biologically justified class, a small local vector, and only then individual
parameters. Cell, receptor, transmitter or muscle type is a candidate sharing key
rather than proof of identical physiology. Select the level using independent
local evidence and complexity-aware validation.

Campaign failure is information. It may indicate an inadequate transfer model, a
missing variable, incorrect routing, incompatible evidence or genuine biological
heterogeneity. The runner must not silently respond by adding parameters,
widening bounds or candidate envelopes, relaxing locality, or introducing a
behavioral objective. A material capacity increase creates a new model or wiring
version, records the residual that motivates it and re-evaluates simpler
alternatives.

An explicit fallback chain may use a measured value, documented homologue,
accepted class value or generic prior before leaving the family unresolved. The
fallback retains its real origin and uncertainty; it is never relabelled as a
measurement merely because it makes the runtime executable.

## Admissible solutions and reproducibility

The numerically best trial and the scientifically admissible set are different
objects. When the observations do not identify a unique value, retain uncertainty
as the simplest adequate representation: intervals, a finite accepted ensemble,
samples or a fitted distribution. A full posterior is optional, not a default
requirement. Downstream claims must be tested across the relevant accepted
variation rather than only on one lucky seed.

The canonical source is the campaign recipe and immutable inputs; parameter files
are derived artifacts. Deterministic campaigns should reproduce semantic outputs
exactly. For stochastic or multi-modal problems, reconstruction succeeds when the
declared metrics, acceptance rate and admissible domain are reproduced within
predeclared tolerances. Exact equality of one optimum is neither expected nor
scientifically meaningful in that case.

## Freeze and reopen

The normal unit of progress is **calibrate locally, validate, then freeze**. A
freeze records parameter-set and input identifiers, structural hashes, evaluation
results and descendants. Downstream failure does not automatically reopen an
accepted family.

Reopening requires a new campaign version, a diagnostic reason and an explicit
statement of affected descendants. Descendants become stale until sensitivity
analysis proves them unaffected or they are revalidated. The previous parameter
set remains immutable and available for rollback. If reopening follows inspection
of an `evaluation_only` behavior, the inspected protocol is contaminated as
specified by ADR 0005.

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

### Routing parameters versus transfer parameters

Peripheral boxes may expose two different parameter classes that must never be
collapsed into one anonymous vector:

- **routing parameters** select or weight relations inside an already accepted,
  finite candidate envelope and represent residual structural uncertainty;
- **transfer parameters** describe local physiology or mechanics such as gain,
  threshold, time constant, adaptation, delay, saturation, or noise.

The topology snapshot, candidate-envelope semantic hash, rule-set hash, and
exception-table hash are frozen in the campaign scope. Selecting within that
envelope is calibration; adding a new candidate edge or crossing its anatomical
boundary is a wiring change that invalidates the affected campaign lineage.

Before fitting, each family declares the number and domain of discrete routing
variables, the number and sharing rule of continuous transfer variables, and an
identifiability status such as `evidence_supported`, `technically_constrained`,
`underdetermined`, or `no_local_observation`. An underdetermined family may remain
executable, but it is not silently made learnable by widening its routing space or
using a global behavioral target. Calibration-runner engineering and isolated
central studies may continue while peripheral review is open; affected parameter
sets cannot be fitted or promoted until their topology is accepted.

## MaleCNS static priors and synaptic-sign policy

MaleCNS v1.0 includes aggregate neurotransmitter records for nearly every
canonical neuron, but a presynaptic transmitter label is not a complete
postsynaptic sign or conductance measurement. On the current checked dataset,
166,522 of 166,700 canonical neurons have a consensus label; 2,999 of those are
`unclear`, and 85,484 have a non-null `ground_truth` field. These counts are an
evidence inventory, not a calibrated signed graph.

Calibration must preserve these levels separately:

1. directly measured or source-curated transmitter evidence;
2. predicted transmitter and its confidence;
3. receptor- or pathway-supported effect sign where available;
4. a typed sign prior when the biological interpretation is sufficiently stable;
5. context-dependent, modulatory or unknown effects that remain free or use a
   dedicated model rather than being forced to `+1` or `-1`.

Acetylcholine and GABA may seed typed excitatory and inhibitory priors where the
source scope supports that interpretation. Glutamate, histamine and monoaminergic
signals must not receive a universal sign without receptor or pathway evidence.
Per-presynapse probabilities can refine uncertainty later, but still do not by
themselves identify the postsynaptic response.

The historical `benchmark.malecns.leaky_tanh.v0` runtime uses unsigned positive
synapse counts with incoming normalization. It remains an execution profile and
must not be promoted as a biological initial parameter set. The frozen evidence
transfer now provides transmitter labels, typed ACh/GABA sign priors, confidence
where available and explicit unknown masks.

`model.malecns_typed_signed_rate.v0` is the first executable model candidate
that consumes this prior. It uses one explicit efficacy for each of the nine
effective-transmitter classes, three global temporal parameters, no per-edge
residuals and no behavior target. ACh and GABA efficacies obey their typed sign
priors. Glutamate, histamine, monoamines, `unclear` and `missing` remain signed
free parameters: sign code zero must never become an implicit zero effect. The
candidate equation and its structural test values are not accepted physiology.
Its first gate is exhaustive edge assignment and CPU/GPU-compatible sparse
execution; only later campaigns may characterize baselines, lock technical
thresholds and fit values.

The calibration runner should optimize shared families before individual
connections: global parameters, then transmitter or cell classes, anatomical
regions and only finally justified local exceptions. Stability objectives can
constrain gain scales, time constants, thresholds, biases, delays and basal
statistics. They cannot determine an unknown anatomical routing or local
input/output transfer uniquely; those require local evidence or must remain
explicitly underdetermined.

## Logical parameter compilation

An executable coefficient vector is not necessarily the scientific parameter
model. When a runtime class stores the product of routing and transfer, calibration
must keep two logical families and compile them only at the runtime boundary. The
compiler validates the exact candidate-key set, frozen source hashes, deterministic
runtime order and one normalized routing simplex per declared route group.

Transfer sharing is an explicit versioned assignment from runtime edges to
transfer keys. It is never inferred by the compiler. This permits global,
class-shared, homologous, local-vector or individual transfer models without
changing runtime code, while making any capacity increase reviewable. A logical
route may expand to several runtime slots: in the motor interface, one
group-to-actuator routing decision is replicated over the terminals belonging to
that group and then combined with their declared transfer keys.

Compilation does not select routes, gains, offsets, filters or dynamics. Synthetic
unit gains and uniform simplexes may be used only for structural tests carrying a
visible `NOT CALIBRATION` label; they are not parameter sets and cannot be
promoted. Offset and temporal terms remain distinct parameters rather than being
silently folded into a scalar gain. Any need to add an edge or widen a candidate
set returns to the wiring workflow.

## Rules-first campaign execution

Calibration campaigns should concentrate scientific choices in versioned target,
scope, bounds, sharing, metric, exposure, and acceptance rules. Once declared, a
runner should execute trials, detect invalid states, retain failures, compare
reference implementations, compute metrics, and produce compact result and
exception reports without requiring an agent decision for each trial.

The runner must account for every scheduled trial and surface new failure classes,
conflicting objectives, exhausted bounds, data drift, forbidden exposure, and
non-reproducible results. These events return to human or agent review; ordinary
trials do not. This is a proportional preference rather than a mandate to build a
general optimizer before the first benchmark. The detailed cross-project policy
is in [`rules-first-automation.md`](rules-first-automation.md) and ADR 0009.

Rules decide which family exists, its sharing, evidence, priors, model class,
solver, seeds, budget and acceptance gates. They do not need to predict the final
numeric value. Autonomous runners may consume substantial GPU time, but they must
produce exhaustive trial accounting, compact summaries, exception classes and a
clear stop state without interactive model decisions.

The runner contract is specified in [`calibration-runner.md`](calibration-runner.md).
Jobs cannot name arbitrary shell commands: evaluators are registered code paths.
Every trial remains accounted as accepted, rejected, errored or budget-skipped,
and fitting/validation jobs reject held-out scenario identifiers before execution.
A passed runner-validation job proves only this infrastructure. It does not accept
the scientific parameters exercised by a synthetic probe.

## Recommended staged program

These stages are milestones over the dependency DAG, not an obligation to finish
every item in one stage before any independent work in another. Evidence transfers
and local interface branches should usually be resolved before global fitting;
documented identifiability may justify a joint campaign.

### Stage -1 — Establish execution readiness

Before fitting, benchmark the real canonical MaleCNS graph with a deterministic
CPU reference and a GPU sparse backend. Measure loading, memory, warm-up,
steady-state neural steps per second and simulated time per wall-clock second on
the available hardware. Test the full graph and declared induced subgraphs, and
check CPU/GPU agreement within explicit tolerances.

A provisional temporal rule is allowed only as a versioned `BENCHMARK ONLY /
UNCALIBRATED` profile. It is not a parameter set and must not be promoted by
accident. Produce compact neural and physical traces that can be replayed offline,
so interactive rendering is not required for calibration throughput. The detailed
contract is in `docs/runtime-execution-benchmark.md`.

This engineering stage may proceed while scientific wiring is revalidated. It
does not authorize fitting any parameter family whose review remains open.

### Stage 0 — Characterize the uncalibrated system

Inventory parameter families, sharing candidates, dependencies and structural
hashes. Run deterministic sanity cases and record numerical failures, silence,
saturation, activity distributions, latency, and runtime cost. This baseline is
not a failed calibration; it is the reference against which progress is judged.

### Stage 0.5 — Evidence transfers and basal priors

Compile directly measured or externally transferable constants, basal-source
statistics and typed transmitter/sign priors with units, confidence, unknown masks
and applicability limits. This stage creates reproducible derived parameter sets;
it does not turn uncertain transmitter identity into a universal synaptic sign.

### Stage 1 — Local interfaces and bounded routing

Calibrate evidence-backed sensory transduction, discrete routing choices, motor
interfaces, basal sources and justified missing-feedback models independently
where possible. Use local physiological or physical measurements and local held-
out splits. Keep physical feedback through MuJoCo unless a documented biological
pathway or validated surrogate justifies a shortcut.

### Stage 2 — Technical neural dynamics

Establish finite, bounded and recoverable temporal activity under basal input and
small perturbations. Measure both pathological extremes: irreversible quiescence
and self-amplifying or saturating echoes. Do not prescribe a fly action.

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

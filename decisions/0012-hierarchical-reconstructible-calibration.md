# ADR 0012 — Hierarchical and reconstructible calibration campaigns

- Status: accepted
- Date: 2026-09-30

## Context

Structural wiring v0 is complete and its four peripheral candidate topologies are
independently reconstructible. The remaining unknowns are heterogeneous: measured
constants, basal statistics, discrete routing choices, local transfer functions,
motor mechanics, MaleCNS dynamics and whole-system technical constraints. Fitting
all of them against one embodied objective would make compensation between layers
likely and would obscure which part of the model carries the result.

The project needs automation that scales with the number of parameter-family
types rather than the number of neurons, synapses or channels. It also needs to
retain scientific uncertainty when the available observations do not identify one
unique vector.

## Decision

### Parameter-family registry

Calibration begins with a versioned inventory of parameter families. Each family
records its biological or technical meaning, scope, kind, dimension, units,
sharing rule, allowed evidence, forbidden exposures, identifiability, priors or
bounds, topology boundary, dependencies, uncertainty representation, freeze state
and next action.

Routing variables and transfer variables remain separate families even when one
runtime class executes both. A topology snapshot, candidate-envelope hash,
ruleset hash and exception-table hash bound every routing family.

### Dependency DAG, not a rigid sequence

Targets, parameter families and campaigns form a directed acyclic dependency
graph. Its usual flow is:

1. evidence transfers, measured constants and basal-source priors;
2. local sensory transduction and bounded routing choices;
3. local motor routing, activation and mechanics;
4. typed MaleCNS signs and temporal dynamics;
5. the physically closed embodied loop;
6. global technical stability and coherence;
7. locked held-out stimulus evaluation.

This is a partial order, not a mandatory total order. Independent branches may be
run in parallel. A joint campaign is allowed when separate families are genuinely
non-identifiable, but it must declare why the split fails, which parameters can
compensate for one another, how capacity is controlled, and which ablations or
local checks preserve interpretability.

The ordinary loop is **calibrate locally, validate, then freeze**. A downstream
failure does not automatically reopen accepted ancestors.

### Minimum-capacity and sharing policy

The preferred evidence hierarchy is:

1. direct measurement in the represented biological scope;
2. documented transfer from a sufficiently close source;
3. a parameter shared by a biologically justified class;
4. a small local vector;
5. an individual parameter only when simpler sharing is contradicted by evidence.

Class labels are proposed sharing keys, not proof that all members are identical.
Sharing level is selected using independent local evidence and complexity-aware
acceptance criteria. Failure of a campaign must remain a result: the runner may
not silently add dimensions, widen routing envelopes, relax anatomical
boundaries, or escalate to a behavior objective. A material capacity increase is
a new versioned model decision supported by residual diagnostics.

When no calibrated value is available, a declared fallback may use a measured
homologue, accepted class value, documented generic prior, or remain unresolved.
Every fallback preserves its origin and uncertainty; no fallback is silently
promoted to a biological measurement.

### Reconstructibility and uncertainty

The canonical source of a calibration result is the recipe: immutable input
identifiers, rules, scope, model family, objectives, optimizer, seeds, budget,
acceptance gates and code version. Parameter files are immutable derived
artifacts and convenient caches.

Deterministic campaigns should reproduce their semantic output exactly. For
stochastic or non-identifiable campaigns, reproducibility means reproducing the
declared acceptance statistics and admissible solution domain within tolerances;
it does not require the same optimum bit for bit.

Every result separates a selected reference from the scientifically admissible
set. Uncertainty may be represented by confidence bounds, a finite accepted
ensemble, samples, or a fitted distribution. A full Bayesian posterior is not
required when a simpler representation preserves the uncertainty relevant to
claims and downstream campaigns.

### Freeze and reopen protocol

Freezing a family records its parameter-set identifier, evidence and scenario
hashes, topology boundary, acceptance result and descendants. Reopening it
requires a new campaign version and an explicit diagnostic reason. Descendants
are marked stale until their sensitivity is shown to be irrelevant or they are
revalidated. The previous accepted set remains available for rollback.

Held-out behavior protocols remain outside this DAG's fitting edges. Inspecting a
held-out result and then changing a family contaminates that protocol version as
defined by ADR 0005.

### Physical feedback

The default embodied feedback path remains motor output → actuator → MuJoCo body
and world → physical sensor → sensory box. A direct output-to-input shortcut is
allowed only for a documented biological pathway or as an explicitly labelled
surrogate validated against the physical path. It cannot conceal a behavioral
controller.

## Consequences

- The first calibration implementation milestone is the parameter-family
  inventory and dependency DAG, followed by a minimal autonomous runner.
- Local evidence can constrain large repeated families without one intellectual
  decision per instance.
- Negative results can identify an inadequate model, missing variable, incorrect
  routing or insufficient evidence without forcing a more expressive model.
- Several parameter sets may be equally acceptable; the numerically best trial is
  not automatically the scientific reference.
- Global optimization remains possible, but only after local constraints have
  reduced the space or an explicit identifiability argument justifies fusion.

## Revision

This ADR fixes invariants, not optimizer choices or one permanent campaign order.
A different factorization is permitted when the data require it, provided the DAG,
capacity, exposure, lineage, uncertainty and reopening consequences remain
explicit.

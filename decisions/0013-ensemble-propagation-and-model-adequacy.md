# ADR 0013 — Ensemble propagation and early model-adequacy checks

- Status: accepted
- Date: 2026-10-03

## Context

The first executable signed MaleCNS model deliberately compresses central
dynamics into twelve shared parameters: nine transmitter-class efficacies and
three global temporal parameters. A technical pilot retained 32 sampled vectors,
and a timestep-refinement constraint retained 31. Raw motor-terminal responses
vary strongly across those members.

This model is useful as a minimum-capacity executable hypothesis, but transmitter
class is not evidence that all neurons or synapses of that class share one
efficacy, nor that all neurons share one time constant, gain and bias. Repeatedly
narrowing this ensemble using isolated-CNS engineering criteria could consume
substantial effort while testing precision inside an inadequate model class.
Conversely, immediately adding per-neuron or per-edge parameters would destroy
identifiability and interpretability.

Peripheral routing, transfer, basal sources and neutral embodied stability also
contain information about model adequacy. They should not be forced to wait for a
single central reference when a bounded central ensemble can be propagated.

## Decision

### The twelve-parameter model remains a provisional capacity hypothesis

`model.malecns_typed_signed_rate.v0` is the smallest currently executable signed
central model, not the accepted dimensionality of fly neural dynamics. Its
sharing assumptions remain an explicit high-impact risk. Technical stability and
numerical convergence may reject candidates, but cannot validate the biological
adequacy of the sharing scheme.

After cheap execution, pathology and numerical-portability gates, isolated-CNS
refinement pauses unless new independent evidence directly constrains a central
family. A high survivor count or strong downstream dispersion is a reason to
propagate uncertainty and test model adequacy, not to invent progressively more
central-only gates.

### A singleton central parameter set is not a prerequisite

Local sensory, basal and motor work may proceed with an accepted finite ensemble,
sample set or distribution of central uncertainty. Campaigns declare whether
their peripheral result is:

- shared across every central member;
- robust over a declared central distribution;
- conditioned on a central member or cluster; or
- jointly identified because a local/central split is demonstrably impossible.

Every scheduled cross-product member is accounted for. When evaluating all
members is inexpensive, use all of them. If it is expensive, a deterministic,
preregistered stratification may be used for development, followed by confirmation
over the full relevant ensemble before promotion. Visual appeal, named behavior
or held-out results cannot select the subset.

The current 31 members are a finite pilot representation, not an exhaustive list
of all valid central solutions or a posterior distribution. Their recipe, bounds,
sampling method and filtering lineage remain attached to every descendant.

### Model capacity is challenged at explicit checkpoints

Local and hybrid campaigns report residuals by transmitter class, neuron class,
anatomical region and interface sector when those labels are available. A
capacity revision is considered when residuals are systematic, ensemble members
require mutually incompatible interface parameters, or no member satisfies
independent local and neutral closed-loop constraints.

A revision may introduce class-, region- or cell-type parameters before any
individual-neuron or edge residual. It requires a new model version, a counted
degree-of-freedom increase, the diagnostic that motivated it, comparison with the
simpler model, and revalidation of descendants. Failure never silently widens the
model.

### Basal input and tonic output are explicit calibration objects

Olfactory, gustatory and thermo-hygrosensory basal sources are calibrated from
declared evidence or neutral-condition statistics, with uncertainty and no
behavioral objective. Residual nominal sources follow the same rule.

Persistent motor tone needed to support a body cannot be hidden in a generic
gain. Before fitting, it must be assigned explicitly to its scientific meaning:
central bias/dynamics, a motor-transfer offset or a new tonic-output family. If
flat-ground stability is used to fit it, the lineage is labelled trained technical
embodied stability. It cannot support a claim that quiet standing emerged without
training. No exact pose, gait, sequence or external stabilizing controller is
allowed under that technical label.

### Calibration order remains a partial order

The immediate program shifts from repeated central-only elimination to parallel
local-interface and basal evidence work plus ensemble-aware pilots. Joint or
hybrid campaigns are allowed when compensation is measured and reported. Each
records participating families, frozen and variable ancestors, losses by target,
member-level results, failure classes, uncertainty, model-risk implications and
the next decision checkpoint.

## Consequences

- The 31-member central ensemble is preserved and propagated; no requirement
  exists to reduce it to one member before interface calibration.
- The twelve-parameter model receives no biological-capacity claim from technical
  stability or timestep convergence.
- Local evidence can reduce interface uncertainty and simultaneously reveal that
  the central sharing model is inadequate.
- Neutral embodied fitting is permitted, but its trained technical nature and any
  tonic-output mechanism remain visible throughout the lineage.
- More compute may be required across an ensemble, but premature precision and
  arbitrary central-member selection are avoided.

## Revision

This decision does not freeze the current ensemble size, central model or campaign
order. It freezes the requirement to preserve uncertainty, expose capacity risk
and version any model expansion. New evidence may justify returning to isolated
central calibration or replacing the finite ensemble representation.


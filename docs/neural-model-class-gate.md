# Neural model-class gate

## Purpose and claim boundary

This gate asks whether the central MaleCNS runtime may remain a continuous-rate
model or must move to a spike/event representation before model-dependent
calibration is scaled. It is deliberately smaller than a calibration campaign.
It does not fit physiology, optimize a behavior, select a member of the earlier
rate ensemble, or accept the LIF reference as the final biological model.

The fixed-delay LIF candidate is defined in
`calibration/models/malecns-lif-fixed-delay-v0.yaml`. Source-derived constants,
the behavior-exposed published unitary weight, numerical choices and
engineering-only load values are separated there. The executable protocol is
`calibration/campaigns/neural-model-class-lif-feasibility-v0.yaml`.

## First bounded result

The accepted engineering result is
`calibration/runner/neural-model-class-lif-feasibility-v0.yaml`. It establishes:

- independent NumPy and Torch implementations agree exactly on a fixed four-node
  recurrent graph, including emitted spikes, membrane and synaptic states,
  refractory state, two-step transmission delay and delivered-event counts;
- all 166,700 canonical neuron rows and all 25,582,938 directed runtime edges are
  visited by the outgoing-graph audit; their structural weights account for
  124,177,617 published synaptic contacts;
- the additional outgoing CSR occupies 205,330,308 bytes on disk before runtime
  allocator overhead;
- under deterministic synthetic loads of 1, 10 and 50 spikes/s/neuron, every
  expected edge event is delivered and the state remains finite;
- the generic Torch implementation runs at approximately 0.03--0.05 times real
  time at a 0.1 ms step on the measured CPU/GPU paths; CUDA reserves about 0.34 GB
  on the available RTX 4060 Laptop GPU.

These figures are implementation measurements, not a lower bound on an optimized
event kernel. The GPU is not currently a decisive accelerator: at low load the
CPU path is comparable, while CUDA becomes only modestly faster at the highest
tested event load. The dominant lesson is that memory capacity is comfortable but
the step/event scheduling formulation needs optimization if near-real-time use is
required. No claim about calibrated recurrent activity follows because the load
uses forced spikes and deliberately tiny engineering-only event weights; the
engine supports recurrent spikes, and that path is exercised by the small graph,
but the full-graph load generated no endogenous spikes.

Run the reproducible diagnostic with:

```text
neural_model_gate.bat
```

The launcher reports progress, writes heavy provenance under
`runs/calibration/neural-model-class-lif-feasibility-v0/`, refreshes the compact
tracked result and pauses before closing. `-Quick` is available for a short
integration check. `-Backend cpu`, `cuda`, `auto` or `both` may be passed through
to the PowerShell launcher.

## Geometry and delay data decision

The current flat connectome weight table contains `body_pre`, `body_post` and
aggregated synapse count; it contains no cable path or accepted edge delay. The
official morphology and synapse resources are therefore additional data, not
columns that the existing runtime has omitted.

An inventory of the official MaleCNS v1.0 resources found approximately 9.30 GB
of SWC objects (211,573 objects), 6.8 GB of synapse-partner data, 12.7 GB of
synapse-point data and 2.7 GB of T-bar neurotransmitter predictions. A first
path-length experiment would therefore need roughly 16.1 GB for SWCs plus
partners, while the broader bundle is roughly 31.5 GB before derived caches.
Those downloads are intentionally not part of the first gate.

Geometry alone does not determine physiological delay. A morphology-aware model
would additionally need a spike-initiation convention, neurite/compartment
interpretation, path extraction, conduction-velocity evidence, units and an
uncertainty policy. Consequently, the next delay step is a small morphology subset
only if a preregistered temporal probe is sensitive to plausible fixed-delay
variation. Downloading the complete bundle first would not answer the critical
question cheaply.

## What remains before the gate closes

The scientific model-class gate remains open. The next bounded work is:

1. preregister model-independent technical probes shared by the rate comparator
   and event candidate, including explicit information-loss metrics;
2. lock one source-backed circuit-level reference that is not used to choose the
   compared parameters;
3. decide whether the current generic event kernel needs optimization before the
   scientific comparison, keeping kernel performance separate from model class;
4. issue a recorded `go`, `revise` or `stop` decision; only then resume basal and
   interface calibrations whose native units depend on the central model.

Morphology-aware delays, compartmental models and optimized custom GPU kernels are
possible revisions, not silently assumed requirements. Each is opened only by a
measured failure or sensitivity result.

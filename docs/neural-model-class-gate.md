# Neural model-class gate

## Purpose and claim boundary

This gate asks whether the central MaleCNS runtime may remain a continuous-rate
model or must move to a spike/event representation before model-dependent
calibration is scaled. It is deliberately smaller than a calibration campaign.
It does not fit physiology, optimize a behavior, select a member of the earlier
rate ensemble, or accept the LIF reference as the final biological model.

The retained first fixed-delay implementation is defined in
`calibration/models/malecns-lif-fixed-delay-v0.yaml`. A pinned-source audit found
that it copied the published constants but not three execution semantics: the
published reset clears `g`, the refractory clause freezes both `v` and `g`, and
the source requests Brian2's `linear` integrator. The v0 benchmark remains a valid
measurement of the code that ran, but it is no longer the comparator for future
scientific gate work.

The corrected comparator is
`calibration/models/malecns-lif-source-aligned-v1.yaml`, with executable protocol
`calibration/campaigns/neural-model-class-source-fidelity-v1.yaml`. It pins source
commit `91bdd1e7dcf193f3e7ca5a8933497fcef63b7960`, verifies source file hashes,
implements the coupled linear state update, clears `g` on a generated spike and
freezes the differential state while refractory. A dedicated Python 3.10 / Brian2
2.5.1 environment now checks scheduler boundaries without changing the project's
Python 3.12 environment. The check exposed two one-step defects: delivery was
integrated too early and refractory release occurred too late. After correction,
the tracked result matches Brian2 on integration, reset, refractory eligibility
and delayed delivery with a maximum state error of `1.42e-14` mV. This closes
scheduler conformance only, not LIF physiology or the constants.

## Retained v0 result and corrected v1 result

The historical v0 engineering result is
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

The replacement result is
`calibration/runner/neural-model-class-source-fidelity-v1.yaml`. It repeats the
source lock, independent NumPy/Torch recurrent graph, exhaustive edge sweep and
CPU/GPU forced-load benchmark under the corrected reset/refractory/integration
semantics. On the same machine it remains in the same engineering regime: roughly
0.04--0.06 times real time for the measured CPU loads and about 0.04 times real
time on CUDA. Thus the correction changes semantic fidelity, not the conclusion
that the generic kernel requires optimization for near-real-time use.

Run the current reproducible diagnostic with:

```text
neural_model_source_fidelity.bat
```

The launcher reports progress, writes heavy provenance under
`runs/calibration/neural-model-class-source-fidelity-v1/`, refreshes the compact
tracked result and pauses before closing. `-Quick` is available for a short
integration check. `-Backend cpu`, `cuda`, `auto` or `both` may be passed through
to the PowerShell launcher.

Run `setup_brian2_reference.bat` once to reconstruct the isolated historical
runtime, then `brian2_conformance.bat` to reproduce the scheduler comparison.
The environment and heavy traces remain under ignored `runs/`.

## Temporal information-loss probes

`campaign.neural_model_class_temporal_probes.v1` freezes a 5 ms rate bin and a
0.1 ms event resolution before execution. Three pairs have identical rate
vectors but different event traces: phase within one bin, opposite ordering of
two channels, and 1.8 versus 3.6 ms arrival delay. Minimal quiescence, finiteness
and refractory checks also pass.

This is a representational capacity result, not evidence that every MaleCNS
population needs the destroyed information. Run `temporal_model_probes.bat` to
reproduce it. The locked aBN1 comparison remains necessary to connect model class
to an independent biological observation.

## Independent circuit-reference transfer audit

The first circuit candidate is the antennal mechanosensory pathway evaluated by
Shiu et al. independently of their sugar-to-MN9 unit-weight fit. Its useful
reference is neural and qualitative: JO-CE robustly activated aBN1 experimentally,
whereas JO-F did not despite direct structural input from both populations. It is
not a request to train grooming or reproduce the paper's firing-rate table.

`audit_circuit_reference.bat` reconstructs the identity transfer from pinned
primary supplements and systematic FlyWire annotations, then scans the full
MaleCNS edge table. The current result is deliberately **partial**:

- aBN1 maps to two MaleCNS `SAD093` neurons;
- aDN1 and aDN2 map to bilateral `DNg62` and `DNge078` pairs;
- two of three pinned aBN2 FlyWire types (`CB1740`, `CB1779`) map to one ambiguous
  four-cell MaleCNS candidate set, while `CB3129` has no resolved match;
- all four required structural relation classes are non-empty: JON→aBN1 has 197
  edges / 1,038 contacts, JON→resolved-aBN2 has 38 / 103, aBN1→aDN has 6 / 712,
  and resolved-aBN2→aDN has 14 / 294.

The source workbook also contains 146 named JON rows while the article declares
147 activated JONs. The audit preserves this one-cell discrepancy; it does not
invent the missing identity. The compact tracked result is
`calibration/runner/antennal-grooming-circuit-transferability-result-v0.yaml`.
The narrow anatomical lock remains in v1. Its common `spikes/s` metric was not
defined for a continuous-rate candidate, so no candidate was executed under it.
The corrected representation-neutral protocol is
`calibration/evidence/antennal-abn1-model-class-reference-v2.yaml`. Figure 5g
measures aBN1 directly, so aBN2, aDNs, motor output, body physics and grooming are
explicitly outside that protocol. This is a scientifically valid exclusion, not
an invented aBN2 identity: the unresolved `CB3129` mapping still blocks a whole
grooming-circuit claim. The lock records 20--220 Hz in 20 Hz increments, 1-second
trials, 30 trials per condition, the exact source commit, the two MaleCNS `SAD093`
aBN1 cells and the separate JO-CE/JO-F structural counts. The qualitative
direction JO-CE > JO-F is fixed. Event spikes/s and rate activity are never
compared numerically; only JO-CE versus JO-F contrasts within a representation
are common. The same seeded master schedules feed event spikes and 5 ms rate-bin
counts, with three preregistered rate bridge scales. The primary output archive
is available only as a 4.2 GB ZIP, so it was not downloaded to invent a numerical
MaleCNS amplitude threshold.

`lock_abn1_reference.bat` reconstructs this pre-output lock from the pinned data
and writes `calibration/runner/antennal-abn1-reference-lock-v1.yaml`. It verifies
335 JO-C/E sources, 78 JO-F sources, two `SAD093` aBN1 targets, then 150 edges /
899 contacts and 40 edges / 131 contacts respectively. It executes no neural
candidate and cannot be used as a fit.

Using this circuit to select a model exposes antennal grooming for that lineage.
It therefore cannot later support a held-out emergence claim; looming, optomotor
and unrelated lateralized responses remain available for final evaluation.

`run_abn1_gate_pilot.bat` executes the bounded v2 rehearsal. The accepted pilot
contains 70 rows on the complete canonical graph: sham plus 20/120/220 Hz, one
seed, the event comparator, and three retained rate members under three input
bridges. Event aBN1 responses were 28, 167.5 and 230 spikes/s/neuron for JO-CE and
zero for JO-F. Every one of the nine rate member/bridge series also had a positive
JO-CE-minus-JO-F contrast at all three frequencies. These are descriptive pilot
results, not the locked 30-trial decision and not cross-model amplitude evidence.

The pilot also caught two implementation hazards before a long run: a benchmark
load weight (`0.0001 mV`) was initially wired where the source model's unitary
weight (`0.275 mV`) belonged, and a CPU Torch tensor could scale its shared NumPy
CSR buffer in place. Both now have regression coverage; the source-fidelity
throughput benchmark was rerun after the buffer fix. The current unbatched full
extrapolation is about 8.5 GPU-hours for event LIF plus 7.8 GPU-hours for the rate
ensemble (64,860 units total). Full execution is therefore gated on a verified
batched/resumable executor and an information-value review: the pilot suggests
aBN1 may confirm capability for both classes without distinguishing them.

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

1. review whether completing aBN1 is worth its measured cost given that all ten
   pilot series share the expected direction;
2. either implement a verified batched/resumable full executor or preregister a
   second independent circuit whose observation depends on temporal structure;
3. issue a recorded population-scoped `go`, `revise`, typed/hybrid or `stop`
   decision; only then resume basal and
   interface calibrations whose native units depend on the central model.

Morphology-aware delays, compartmental models and optimized custom GPU kernels are
possible revisions, not silently assumed requirements. Each is opened only by a
measured failure or sensitivity result.

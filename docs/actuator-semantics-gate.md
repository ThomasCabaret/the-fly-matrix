# FlyBody actuator-semantics gate

This gate separates three possible causes of embodied motion: the MaleCNS
controller, the local motor-transfer box, and the FlyBody/MuJoCo surrogate. It is
technical and behavior-naive. It does not fit a pose, gait or named response.

## Frozen local probe

`actuator_semantics_gate.bat` executes
`campaign.actuator_semantics_gate.v0`. The procedure resolves and hashes every
actuator's address, target joint, transmission, gain, bias, activation dynamics,
gear and limits. From identical resets in the standard flat-ground scene, it
then compares each of the 102 channels with a matched zero-command trajectory:

- a 1 ms impulse at `0.005` model-input units;
- a 10 ms step at the same command;
- 30 ms of zero-command release;
- a one-step `0.02` saturation probe against the fixed `[-0.01, 0.01]` force
  range.

The procedure optimizes no parameter and reads no behavior target. Full traces
are written below `runs/calibration/actuator-semantics-gate-v0/`; the compact,
versioned result is
`calibration/runner/actuator-semantics-gate-v0.yaml`.

## Current result and its boundary

Run `actuator-semantics-20261005T055452Z` passed the local open-loop stage:

- all 102 actuators are joint transmissions with fixed unit gain, no bias and no
  internal activation dynamics;
- all 102 are force-limited and none is control-limited;
- a `0.005` command produces a `0.005` actuator force on every channel;
- the saturation probe clips to magnitude `0.01` on every channel;
- all 102 channels produce a nonzero target-joint displacement relative to the
  matched passive trajectory.

This demonstrates an especially transparent direct-motor abstraction: MuJoCo is
not hiding a position or velocity servo, nor an actuator-side activation filter.
It does **not** validate muscle physiology, motor-neuron transfer, a MaleCNS
closed loop or any behavior.

The standard reset is also not a symmetric load reference. Only four of six legs
report ground contact at the final passive checkpoint. The median absolute
left/right response difference is small, but a few leg pairs are large outliers
(maximum relative difference about `0.874`). These differences can arise from
contact and configuration, so they are retained as a diagnostic rather than
explained away or treated as neural asymmetry.

## Remaining closure test

The global gate remains open. Its next version must freeze one command trace that
was produced without a named behavior objective, keep motor transfer and body
mechanics fixed, and compare:

1. the trace replayed open-loop into FlyBody;
2. the accepted physically closed MaleCNS/body execution from which the trace
   was obtained;
3. a symmetric load-controlled pose for homolog response attribution.

The comparison must report which state stabilization is supplied by passive
mechanics and sensory feedback. It must not add a synthetic pose controller. If
the direct-motor surrogate supplies too much or too little causal structure, the
result is a new explicit actuator or muscle-model version, not a retuned hidden
gain.

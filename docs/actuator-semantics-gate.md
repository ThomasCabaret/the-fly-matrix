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

## Causal closure result

`actuator_attribution_gate.bat` executes the preregistered
`campaign.actuator_causal_attribution.v1`. It optimizes zero parameters, exposes
no behavior target and compares the same generic perturbation under three
branches: zero-command passive mechanics, the unperturbed command trace frozen
and replayed open-loop, and live MaleCNS feedback. A separate tethered fixture
removes ground contact and probes all 102 channels individually.

Run `actuator-attribution-20261005T105731Z` passed every declared invariant:

- the repeated closed-loop command and state errors are respectively below
  `2.33e-13` and `1.98e-12`;
- replaying the frozen commands reproduces the unperturbed physical state exactly;
- lateral and angular perturbations alter the live commands, with peak L2 changes
  of `3.48e-7` and `2.72e-7`;
- the resulting closed-versus-open final physical-deviation ratios are only
  `1.000001734` and `1.000002171`.

The last observation is important: the current uncalibrated MaleCNS path does
react, but its physical contribution is essentially negligible at this scale and
horizon. The result does not show stabilization, destabilization or biological
feedback control. Passive mechanics and the frozen baseline command trace explain
almost the whole measured response.

In the tethered no-ground fixture, all 102 motors produce a nonzero local
response. Across 41 homologous pairs, the median relative difference is
`2.79e-6` and the maximum is `4.87e-5`. The earlier `0.874` ground-scene outlier
therefore reflected contact or configuration, not an intrinsic left/right motor
contract asymmetry.

The causal gate is now accepted for a narrow purpose: the 102 direct MuJoCo
motors may remain frozen as an explicit surrogate in initial short-horizon work.
This closes neither muscle nor tendon fidelity, does not validate random motor
transfer values or the rate comparator, and supports no stability or behavior
claim. A change to actuator semantics reopens the gate; a claim requiring muscle,
compliance or local-reflex fidelity requires a new model version.

## Conditional force bridge

`motor_actuator_bridge_envelope.bat` keeps that accepted direct-motor contract
frozen and probes only the bounded front-leg candidate scope. The ten selected T1
tibia-flexor bodies expose 110 accepted candidate routes to 22 left/right
front-leg motors. Nine commands per motor produce 198 tethered trials; all
commands equal the reported actuator force exactly and every motor exceeds the
locked `1e-9` radian local-response threshold at the grid floor of `1e-6`.
Consequently the actual detectability thresholds are left-censored rather than
claimed as identified.

The one-cell force slopes are then used only as conditional diagnostic inputs.
They admit three reported gains between `4.3788e-5` and `1.0471e-3`
command/µN, where the weakest force reaches the conservative observed detection
floor and the strongest reaches half of the fixed `0.01` force limit. No member
is preferred. The interval preserves a runnable engineering sensitivity path but
does not supply muscle insertion geometry, moment arms or a physical conversion
from micronewtons to joint torque. Body motion may not select among its members.

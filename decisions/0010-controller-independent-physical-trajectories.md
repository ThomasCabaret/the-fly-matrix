# ADR 0010 — Controller-independent physical trajectories

## Status

Accepted.

## Context

The project needs three related execution modes without three unrelated stacks:

1. headless closed-loop simulation that records an inspectable result;
2. direct live presentation, even when computation cannot sustain wall-clock time;
3. interactive playback of a result regardless of the controller that created it.

A neural trace alone is not a physical replay. Actuator commands still require
MuJoCo integration, and rerunning those commands later is sensitive to the exact
body model and initial state. Conversely, a movie is easy to watch but cannot be
interrogated with a free camera and carries little scientific provenance.

## Decision

The stable presentation boundary is a versioned **physical trajectory**. Its
required data are timestamps, complete MuJoCo `qpos` and `qvel`, ordered actuator
commands, the physical-model contract, and provenance metadata. Producers may add
named sensory and neural diagnostic arrays. The player ignores producer-specific
diagnostics and accepts every archive satisfying this contract.

Both recorded and live modes use the same FlyBody construction and the same
passive viewer shell. In recorded mode the player applies physical frames to a
fresh presentation model. In live mode the closed-loop producer advances the
model already attached to that viewer. This avoids a generic streaming framework
while preserving a common frame and presentation boundary.

The initial closed-loop producer executes, at every neural tick:

1. current joint, contact and retinal observations from MuJoCo;
2. every declared sensory, basal, transduction and routing box;
3. one persistent CUDA MaleCNS step;
4. declared motor routing and transduction;
5. a visibly declared numerical command guard;
6. enough native MuJoCo substeps to cover the neural interval.

For the v0 profile, the neural interval is 5 ms and the native physical interval
is 0.1 ms, hence 50 physical substeps per neural step. Vision is sampled every
neural tick by default. A configured `vision_stride` may hold the previous retinal
sample for engineering experiments, but its value is recorded and cannot be
mistaken for an accepted biological sampling rate.

## Replay contents

The v1 archive records:

- full generalized positions and velocities;
- the 102 applied actuator commands;
- the 102 actuator forces;
- 102 joint positions and 102 joint velocities in declared order;
- six native ground-contact records;
- head and thorax local contact forces;
- 1,442 active retinal samples;
- compact neural summaries;
- code, profile, graph and physical-model identities.

The complete 166,700-neuron state is deliberately not stored at every tick.
Special diagnostic runs may add it separately when justified.

## Scientific status

This architecture introduces no behavioral controller. The current temporal rule,
interface parameters and motor coefficients remain deterministic engineering
placeholders. The `tanh(raw) * command_scale` envelope protects the uncalibrated
physics run and is not a physiological model. Successful execution is an
integration result, not a behavioral or calibration claim.

## Consequences

- A trajectory can be rendered later with a free camera and arbitrary playback
  speed without rerunning MaleCNS.
- Another controller or future calibrated runtime can emit the same physical
  trajectory schema without changing the player.
- Live and recorded execution share body construction, viewer controls and
  interface code.
- Exact producer reproduction still requires the recorded code, data, parameters
  and seeds; visual playback requires only a compatible physical-model contract.
- Performance bottlenecks can be attributed separately to sensors/interfaces,
  neural execution and physics.

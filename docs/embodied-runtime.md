# Embodied MaleCNS runtime and physical replay

## What is implemented

The embodied runtime closes the executable loop:

```text
MuJoCo state and rendered retina
  -> declared sensory/basal boxes
  -> 17,884 MaleCNS inputs
  -> persistent CUDA MaleCNS state
  -> 815 motor neurons
  -> declared motor boxes
  -> 102 guarded FlyBody commands
  -> 50 native MuJoCo substeps
  -> new MuJoCo state and rendered retina
```

This is a real computationally closed loop with no external behavioral controller.
It is not calibrated. All temporal and interface values use the versioned
`BENCHMARK ONLY / UNCALIBRATED` profile, and the command envelope is an engineering
safety guard.

The current body path explicitly creates all 102 channels as classical MuJoCo
`MOTOR` actuators. It does not use position or velocity servos. This prevents a
hidden position controller in the present configuration, but direct joint
actuation is still a surrogate for muscle activation, compliance and local reflex
dynamics. Its causal contribution is an open gate under ADR 0015, not accepted
motor physiology.

## Three user modes

`closed_loop_record.bat` calculates one second headlessly and writes a physical
trajectory below `runs/closed-loop/`. Optional PowerShell arguments can change the
duration or vision stride, for example:

```text
closed_loop_record.bat -Duration 5 -VisionStride 1
```

`physical_replay.bat` opens the most recent physical trajectory. It does not rerun
the controller. Mouse controls come from MuJoCo; Space pauses, R restarts, `-` and
`+` change playback speed, and Q or Escape closes the window. A particular archive
can be selected with:

```text
physical_replay.bat -ReplayPath runs\closed-loop\<run-id>\physical-trajectory.npz
```

`closed_loop_live.bat` executes the same closed loop directly inside the viewer.
It may display slowly because retinal rendering and computation occur before each
new physical frame. Closing the viewer stops the run. Add `-RecordLive` to retain
the current episode as a physical trajectory.

All launchers print progress, preserve the non-calibrated claim label and pause
before their console closes.

## Portable replay contract

The player depends on `the_fly_matrix.physical_trajectory` schema v1, not on the
MaleCNS producer. A valid archive supplies full `qpos`, `qvel`, timestamps, ordered
commands and a matching FlyBody contract. Optional named sensory arrays and neural
summaries remain available for audit but do not affect presentation.

The player rejects a trajectory when dimensions, actuator identities, joint order
or the physical contract hash differ. It never silently presents a trajectory on
another body model.

## Measured reference run

Run `closed-loop-20260927T124854Z`, produced from engine commit `add05df`, executed
200 closed-loop ticks and 10,000 native MuJoCo steps. One simulated second took
16.854 wall-clock seconds on the local machine, a ratio of 0.0593x real time.

- live sensors and interface boxes: 8.079 s;
- recurrent MaleCNS execution and transfer: 2.799 s;
- MuJoCo stepping: 2.072 s;
- initialization and remaining overhead: approximately 3.9 s.

Vision was recomputed on every 5 ms neural tick. The 200-frame trajectory is
971,225 bytes and was successfully replayed against a fresh FlyBody instance.
This measured result supersedes guesses: the isolated neural kernel is faster than
real time, but the complete vision-rich v0 loop is currently about 17 times slower
than real time. Offline execution and interactive replay therefore remain the
normal path until profiling and optimization close that gap.

## Boundaries and next work

- The run demonstrates execution, not plausible behavior.
- The 5 ms neural step has not been biologically accepted.
- Input and motor parameters are seeded placeholders and cannot be promoted.
- Actuator addressing is validated, but command-to-force/state semantics and the
  stabilization contributed by FlyBody/MuJoCo have only passed the local
  open-loop stage of the actuator attribution gate. All 102 direct motors have a
  hashed low-level contract and matched-passive impulse/step/release result; the
  frozen-trace open-loop versus closed-feedback comparison remains open. See
  `docs/actuator-semantics-gate.md`.
- Scientific interface revalidation remains independently blocking.
- Optimize only after profiling; likely targets are retinal rendering, repeated
  box assembly and GPU/CPU synchronization.
- Calibration should inject versioned parameter bundles into this loop rather than
  create a second execution engine.

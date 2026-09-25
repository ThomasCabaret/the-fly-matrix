# Diagnostic physical viewer

`diagnostic_viewer.bat` is an isolated, explicitly non-scientific tool for
learning the MuJoCo interface and exercising the FlyBody physics loop in real
time before the MaleCNS temporal runtime exists.

## What it is

The tool creates a deterministic 64-state recurrent signal processor. It reads
the 102 joint positions and velocities, updates a small seeded random recurrent
graph, and emits 102 bounded actuator values through the exact FlyBody actuator
addresses. It has no anatomical mapping, no behavioral target, no fitted value,
and no relation to the MaleCNS graph.

The viewer displays a permanent warning:

```text
DIAGNOSTIC TOY CNS — NOT MALECNS / NOT CALIBRATION
```

It bypasses `cns.malecns`, `adapter.motor.routing`, and
`adapter.motor.transduction`. Its motion must never be used as evidence for a fly
behavior, connectome function, calibration result, or closed-loop validation.

## Launch

Double-click `diagnostic_viewer.bat` or run:

```powershell
.\diagnostic_viewer.bat
```

The default run continues at real-time speed until the MuJoCo window is closed.
For interactive fluidity it uses a diagnostic physics timestep of 0.5 ms, a
100 Hz toy-controller rate and a 30 FPS viewer. The scientific model's native
0.1 ms timestep is not changed on disk and can be requested explicitly. On the
development machine, this default profile sustains approximately real-time
playback after the viewer has opened.
Useful optional arguments are:

```powershell
.\diagnostic_viewer.bat -Duration 20
.\diagnostic_viewer.bat -Seed 42 -Amplitude 0.002
.\diagnostic_viewer.bat -PhysicsTimestep 0.0001 -ControlSubsteps 100
.\diagnostic_viewer.bat -Speed 0 -Duration 5 -Headless
```

`Amplitude` is hard-limited to `(0, 0.01]`. `Speed 0` removes wall-clock
throttling. Headless mode requires a finite duration.

## Viewer controls

- left mouse drag: rotate the camera;
- right mouse drag: pan the camera;
- mouse wheel: zoom;
- Space: pause or resume the diagnostic controller and physics;
- R or Backspace: reset physics and the toy signal state;
- Q or Escape: exit; closing the window also exits.

The left and right MuJoCo panels are native inspection controls. They may be used
to inspect bodies, joints, contacts, rendering options, and the current model, but
do not change the scientific project state.

## Output and reproducibility

Each run writes `runs/diagnostic-viewer/latest.json` with the seed, toy graph size,
explicitly bypassed components, physical/control step counts, command bounds,
wall time, simulated time, and real-time factor. The entire `runs/` tree is ignored
by Git.

This tool is not a calibration campaign and never creates or promotes a parameter
set. Its constants exist only inside the diagnostic namespace.

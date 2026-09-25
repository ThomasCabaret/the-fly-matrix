# ADR 0006 — Isolated physical viewer diagnostic

- Status: accepted
- Date: 2026-09-25

## Context

The full MaleCNS graph is structurally wired but does not yet have a temporal
dynamics implementation. The physical body, exact actuator addresses, joint-state
feedback, and MuJoCo engine are already executable. A real-time viewer is useful
for learning the physical interface and validating its ergonomics before CNS
optimization or calibration.

ADR 0005 forbids an external behavioral controller from being used as a shortcut
around MaleCNS in scientific calibration or evaluation. A body-only diagnostic is
still useful if it is technically and semantically impossible to confuse with the
scientific path.

## Decision

1. A toy recurrent signal processor may drive FlyBody only inside the dedicated
   `the_fly_matrix.diagnostics` namespace and `diagnostic_viewer.bat` launcher.
2. It may read physical joint state and write exact actuator addresses, but it
   explicitly bypasses MaleCNS, motor routing, and motor transduction.
3. It has no anatomical structure, behavioral target, learned value, or promoted
   parameter set. Seeded random constants are diagnostic implementation details.
4. The console, viewer overlay, documentation, and run summary continuously label
   it `NOT MALECNS / NOT CALIBRATION`.
5. Its output cannot support any claim about connectome function, fly behavior,
   calibration, emergence, or closed-loop scientific validation.
6. Diagnostic runs live under ignored `runs/diagnostic-viewer/`. They do not enter
   the calibration registry or ledger scores.
7. Shared code is limited to the already tested physical API and exact actuator
   address interface. No diagnostic controller logic enters the scientific
   runtime classes.

## Consequences

- The MuJoCo viewer, camera navigation, physical stability, and real-time loop can
  be explored immediately.
- Visible motion is expected to be arbitrary and potentially violent; it is not a
  project success beyond exercising the physical engine.
- Replacing the toy processor with a temporal MaleCNS runtime is a separate,
  reviewable change.
- If diagnostic logic is ever reused by calibration or evaluation code, this ADR
  is violated and the affected result is contaminated.

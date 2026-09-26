# Real MaleCNS execution benchmark

## Purpose

The next engineering milestone is a reproducible execution benchmark for the real
166,700-neuron canonical MaleCNS graph and its 25,582,938 runtime edges. It is a
prerequisite for calibration infrastructure and for the first visibly embodied
run driven by MaleCNS rather than by the isolated diagnostic controller.

This milestone measures execution readiness. It does not select physiological
parameters, validate disputed scientific mappings, or make a behavioral claim.
Any provisional dynamics profile used by the benchmark must be versioned and
labelled `BENCHMARK ONLY / UNCALIBRATED` and must never become a promoted
parameter set implicitly.

## Required benchmark paths

The first implementation should provide:

1. a deterministic CPU reference kernel used for correctness;
2. a GPU sparse propagation kernel over the same ordered graph;
3. both full-connectome and declared induced-subgraph runs;
4. fixed seeds and an explicit benchmark-only temporal update rule;
5. separate timing for data loading, graph transfer, warm-up and steady-state
   stepping;
6. peak host and device memory, neural steps per second and simulated time per
   wall-clock second;
7. CPU/GPU agreement checks within declared numerical tolerances;
8. export of compact neural summaries, actuator commands and physical state traces;
9. offline replay of recorded physical traces so rendering and camera navigation
   do not constrain neural execution speed.

The benchmark must enter and leave MaleCNS through the declared boxes. It may use
arbitrary reproducible parameters at their declared ports, but it must not inject
terminal activity downstream of a missing box or reuse the fake CNS from
`diagnostic_viewer.bat`.

## First visible real-connectome run

After the benchmark kernel is trustworthy, a short uncalibrated run should couple
the real MaleCNS graph to MuJoCo through the current explicit interfaces. It may
run slower than real time and be inspected through an offline replay. Its purpose
is to demonstrate the actual execution path and expose performance or numerical
failures, not to demonstrate plausible fly behavior.

The run report must state the dynamics profile, parameter origins, seed, simulated
duration, wall-clock duration, backend, hardware, peak memory, commit, input
hashes and every bypass or unresolved interface. A chaotic, silent or saturated
result is an honest baseline.

## Acceptance gate before calibration campaigns

The execution benchmark is ready when:

- the CPU reference and GPU path traverse the same canonical graph;
- determinism and CPU/GPU tolerances are tested;
- performance and memory are measured on the available machine rather than
  estimated;
- a short real-connectome trace can be produced and replayed;
- benchmark-only dynamics and parameters cannot be mistaken for calibrated ones;
- the scientific wiring revalidation remains independently visible and blocking
  for affected interface parameter families.

Only measured results should determine whether interactive closed-loop execution
is realistic. Offline simulation plus replay is the required fallback and not a
failure mode.

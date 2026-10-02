# Calibration runner

The minimal runner executes a versioned job without making scientific decisions
between trials. Its purpose is to move repeated execution, accounting and failure
collection outside agent interaction while keeping every scientific choice in a
small reviewable record.

## Contract

A job declares its mode (`validation`, `fit`, or `evaluation`), target and
parameter-family identifiers, parent parameter sets, topology boundaries,
immutable input hashes, evaluator identifier, trials, seeds, budget, scenario
splits and locked acceptance gates. The runner validates this contract before it
creates a run directory.

Evaluators are registered in Python together with their permitted modes and
record kinds. A YAML file cannot invoke an arbitrary shell command, import an
arbitrary callable, or reuse an infrastructure validator as a fitting evaluator.
Adding an evaluator is therefore a code change with tests, not a hidden
capability granted by a campaign file.

For each scheduled trial the runner writes one immutable JSON result with one of
four states:

- `accepted`: every trial gate passed;
- `rejected`: execution completed but at least one gate failed;
- `error`: the evaluator or gate raised an exception;
- `skipped_budget_exhausted`: the trial remained scheduled but the declared wall
  budget had already expired.

The summary must account for every scheduled trial. Rejected and error trials are
retained rather than discarded. Acceptance may require all trials or a declared
minimum admissible count, a maximum error count and exact repetition consistency.
The semantic result hash excludes timestamps and timings so independent runs can
be compared.

## Leakage and topology guards

Jobs in `fit` or `validation` mode cannot name a `held_out` or
`behavior_held_out` scenario. `evaluation` mode requires
`optimization_exposure: evaluation_only`. A behavior-targeted job or target also
requires an explicit user-authorization reference.

Every routed or transferred parameter family in a job must carry its accepted
semantic topology hash. The runner compares it with the family registry before
execution. Immutable input files are restricted to the project tree and verified
by SHA-256. These checks prevent a campaign from silently widening its candidate
envelope or reading a different dataset.

## Outputs and reproducibility

Heavy and per-trial outputs live under `runs/calibration/runner/` and remain out
of Git. Each run contains the exact job snapshot, one file per trial and a summary
with:

- exhaustive status counts;
- locked-gate results and metrics;
- nondeterministic repetition groups;
- configuration, input and semantic-result hashes;
- Git commit, worktree cleanliness, Python version and platform;
- topology boundaries and behavior exposure.

Compact accepted validation or campaign conclusions belong in versioned records
under `calibration/`. The mutable `latest.json` file is only a convenience pointer,
never the canonical result.

## Current validation

`calibration_runner_check.bat` executes
`runner_validation.peripheral_parameter_compiler.v0`. It schedules the three
peripheral compiler contracts twice, for six trials total. The test uses only
ephemeral uniform simplexes and unit transfers and is labelled `NOT CALIBRATION`.
It validates the runner and compiler boundary; it accepts no fly parameter.

The accepted infrastructure result is recorded in
`calibration/runner/validation-result-v0.yaml`. The next extension should register
one local-interface or technical evaluator and a real campaign record. It must not
weaken the topology, lineage, exposure or exhaustive-accounting checks.

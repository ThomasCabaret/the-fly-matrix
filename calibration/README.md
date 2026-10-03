# Calibration registry

This directory is the compact, versioned source of truth for calibration. The
canonical rules are in `docs/calibration-methodology.md` and ADR 0005.

## Contents

- `state.yaml`: current phase, promoted references, readiness, blockers, and next
  action;
- `targets/`: versioned technical, local-interface, behavioral, and held-out
  objectives;
- `_templates/`: minimum schemas for parameter families, scopes, campaigns,
  parameter sets, and evaluations;
- `parameter_families/`: 19 versioned family records plus an exhaustive index;
- `dependency-dag.yaml`: the validated partial order between those families;
- `model-risks.yaml`: explicit high-impact capacity hypotheses, evidence,
  escalation triggers and next review points;
- `evaluation_candidates/`: prospective observation catalogs that are neither
  locked held-out protocols nor runnable evaluations;
- `evidence/`: deterministic evidence-transfer recipes;
- `diagnostics/`: preregistered non-fitting sweeps used to characterize unknown
  models without selecting or promoting values;
- `compilers/`: hash-locked contracts that compile logical parameter families
  into runtime vectors without choosing or fitting their values;
- `runner/`: immutable runner jobs plus compact accepted infrastructure results;
- `scopes/`: reusable local and closed-loop scopes;
- `campaigns/`, `parameter_sets/`, and `evaluations/`: compact immutable lineage
  records. The first accepted dependency is the transmitter/sign prior.

Heavy outputs belong in ignored `runs/calibration/`: traces, videos, checkpoints,
optimizer histories, and temporary datasets. A versioned record references them
with a path plus checksum or stable content identifier when the result matters.

## Invariants

- No record uses a single ambiguous `calibrated: true` flag.
- Every fitted value has a scope, origin, lineage, command, and result.
- Every behavior exposure propagates through descendants.
- `evaluation_only` scenarios never select parameters. Once inspected and used to
  change the system, that protocol version is contaminated.
- Calibration changes parameters, not hidden topology. Structural changes return
  to the wiring ledger.
- Routing and transfer remain separate logical families even when a runtime vector
  stores their product. A compiler may expand them only inside a frozen candidate
  envelope and must not infer sharing, routes, gains, offsets, or dynamics.
- Negative results and blockers remain visible in compact form.
- Parameter families and campaigns form an explicit dependency DAG; accepted
  upstream families are frozen before their values are consumed downstream.
- Sharing starts at the smallest justified capacity. Extra degrees of freedom,
  joint campaigns and reopened families require versioned reasons.
- A selected reference is distinct from the admissible solution set; uncertainty
  survives as bounds, an ensemble or a distribution when one value is not
  identifiable.
- Deterministic recipes reproduce semantic values exactly; stochastic recipes
  reproduce predeclared acceptance statistics and admissible domains.

Start from a template, assign a stable identifier, and link the new record from
`state.yaml` or its parent object. Unknown cases should be represented honestly
and may justify a new ADR rather than being forced into an existing category.
The dependency and reopening contract is in ADR 0012.

Run `calibration_status.bat` to validate that the family files, inventory counts,
reciprocal dependency declarations, and acyclic DAG agree. A successful result
means that the unknowns are accounted for; it does **not** mean any value has been
fitted or accepted.

Run `compile_calibration_evidence.bat` to rebuild the frozen MaleCNS transmitter
and typed sign-prior dependency. Its zero sign code means “unknown or
context-dependent”, never “zero synaptic effect”. Derived tables remain outside
Git under `data/derived/calibration/`; the recipe, semantic hash, counts, campaign,
evaluation, and parameter-set lineage are versioned here.

Run `parameter_compiler_check.bat` to verify the proprioceptive,
mechanosensory, and motor factorization contracts. It hash-checks the accepted
candidate manifests and expands explicit in-memory test simplexes twice. The test
values are deliberately synthetic, are never persisted, and accept no scientific
parameter. The motor contract is intentionally asymmetric: 3,746 logical
group-to-actuator routes expand to 7,849 terminal-to-actuator runtime slots.

Run `calibration_runner_check.bat` to exercise the autonomous runner. Its current
six-trial job validates infrastructure only: topology and input hashes, exact
trial accounting, locked gates, repetition consistency and held-out isolation.
Per-trial artifacts remain under ignored `runs/calibration/runner/`. See
`docs/calibration-runner.md` for the execution and leakage contract.

Run `characterize_signed_dynamics.bat` to execute the seven preregistered
full-graph regimes of the signed MaleCNS candidate. The job records silence,
activity, saturation, class distributions and perturbation response. Its gates
only verify execution, finiteness, terminal accounting and CPU/GPU agreement;
diagnostic outcomes never select a regime or create a parameter set.
The compact result
`runner/central-unfitted-characterization-result-v0.yaml` points to two clean
runs with the same semantic hash and records both permitted and forbidden claims.

Run `fit_signed_dynamics_pilot.bat` for the first real technical fitting pilot.
It reconstructs 32 Sobol candidates over the twelve shared central parameters and
evaluates each on three train plus two local-validation scenarios. The accepted
result is deliberately an ensemble: 32/32 candidates passed, so
`parameter_sets/central-technical-dynamics-pilot-ensemble-v0.yaml` records broad
technical admissibility and non-identifiability, with no selected or frozen member.

Run `central_ensemble_sensitivity.bat` to measure whether those 32 admissible
members are interchangeable at the 815 raw MaleCNS motor terminals. Three new
synthetic terminal patterns are each paired with a sham from the same initial
state, and only stimulated-minus-sham central activity is compared. Motor
transfer, physics and behavior are excluded. The reproduced v0 result is high
sensitivity in both output pattern and amplitude; it forbids arbitrary member
selection and points to an independent non-behavioral central constraint.

Run `constrain_central_timestep_v1.bat` to apply the first such constraint. It
compares the same 400 ms full-CNS response at 5.0, 2.5 and 1.25 ms, including the
815-neuron motor subset, without executing transfer, body, world or behavior. V0
is retained as a superseded methodological result: it exposed harmless ordering
jitter below 1e-4. V1 declared that numerical floor before execution and changed
none of the material tolerances. Two clean v1 runs reproduce the same semantic
hash and retain 31/32 candidates; candidate 30 fails both full-state convergence
limits. The output is an unfrozen filtered ensemble, not physiology and not a
reference selection.

The twelve-parameter central model and its 31-member surviving ensemble are now
governed by ADR 0013. They are a minimum-capacity hypothesis and a finite pilot
representation, not an accepted biological dimensionality or a prerequisite to
local calibration. Further central-only narrowing pauses unless new independent
evidence is available. Local, basal and hybrid campaigns should propagate the
ensemble explicitly and report whether interface parameters are shared,
ensemble-robust, member-conditioned or jointly identified.

The first prospective behavior catalog is
`evaluation_candidates/emergent-behavior-catalog-v0.yaml`. It records localized
and hierarchical grooming, looming, lateralization, optomotor responses and
structured spontaneous activity, plus sham and topology-control requirements.
Nothing in that catalog has been run or locked, and it must not influence fitting
or model selection. A selected item becomes `evaluation_only` only through a new
immutable protocol with sources, seeds, metrics and thresholds.

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
- Model risk identifiers, their ADR references and every model
  `critical_risk_refs` entry resolve during `calibration_status.bat`; a dangling
  scientific-risk reference is a registry error.
- Embodied campaigns freeze actuator semantics and cannot use flexible peripheral
  layers to hide central or mechanical error without an identifiability plan.

Start from a template, assign a stable identifier, and link the new record from
`state.yaml` or its parent object. Unknown cases should be represented honestly
and may justify a new ADR rather than being forced into an existing category.
The dependency and reopening contract is in ADR 0012.

Run `calibration_status.bat` to validate that the family files, inventory counts,
reciprocal dependency declarations, acyclic DAG, risk identifiers, decision
references and model-risk references agree. A successful result
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

Run `compile_basal_evidence.bat` for the first local evidence gate. It accounts
for all 2,212 declared basal source channels covering 6,041 terminals, verifies
the four frozen wiring-input hashes and derives 211 annotation partitions. The
result accepts evidence coverage only: 286 channels have qualitative partition
support, 31 labellar channels have partial numerical evidence that cannot yet be
mapped to functional MaleCNS cells, and every residual source remains unresolved.
It emits exactly zero parameter values. Published baselines are in spikes per
second, whereas the current runtime consumes a whole-input normalized activity;
the missing explicit unit bridge is therefore a blocking result, not a reason to
copy rates into the model.

The twelve-parameter central model and its 31-member surviving ensemble remain a
reproducible engineering result under ADR 0013, but ADR 0014 now places a more
fundamental gate before their scientific propagation. The rate model has no spike
events, refractory state, synaptic event kernel, or transmission delay. It is
retained as an engineering comparator, not the default biological model.
The comparison is now closed by ADR 0016 with `revise`: neither homogeneous
candidate is promoted, and model-dependent basal/interface work proceeds only for
populations handled by `target.population_dynamics_assignment.v0`. Evidence
inventories and reusable runner infrastructure remain valid.

The initial `neural_model_gate.bat` result is retained as a v0 throughput record,
but a pinned-source review found mismatched reset, refractory and integration
semantics. Run `neural_model_source_fidelity.bat` for the current v1 engineering
gate. It verifies the exact source commit and hashes, compares independent
NumPy/Torch source-aligned semantics on a recurrent small graph, accounts for
every canonical outgoing edge, and measures bounded CPU/GPU loads at 1, 10 and 50
forced spikes/s/neuron. The compact result is
`runner/neural-model-class-source-fidelity-v1.yaml`; heavy traces remain under
`runs/calibration/`. Passing it proves source alignment and execution feasibility,
not physiology or behavior. The later direct scheduler campaign found and fixed
two one-step boundary errors, then established Brian2 2.5.1 agreement on the
preregistered fixtures. Reconstruct its isolated runtime with
`setup_brian2_reference.bat` and run `brian2_conformance.bat`.

Run `temporal_model_probes.bat` for the frozen representation-capacity probes.
At 5 ms resolution the rate representation aliases the tested intra-bin phase,
cross-channel order and sub-bin delay pairs; the event trace distinguishes them.
These probes alone do not select a model class. The global gate is now closed by
ADR 0016 as a `revise` decision: an event-capable typed/hybrid architecture is
accepted, but zero population assignments and zero physiological values are
promoted. The downstream target is `target.population_dynamics_assignment.v0`.

Run `audit_circuit_reference.bat` to audit the first independent circuit candidate
without fitting it. The procedure pins the Shiu supplement and FlyWire annotation
commit, transfers systematic cell types to MaleCNS, and scans the complete edge
table. aBN1/aDN1/aDN2 map exactly and the required structural paths are present;
the result remains partial because one of three aBN2 FlyWire types (`CB3129`) has
no resolved MaleCNS match and the other two collapse to a four-cell candidate set.
The complete grooming mapping remains partial. The narrower aBN1-only model-class
reference is nevertheless locked in
`evidence/antennal-abn1-model-class-reference-v1.yaml`: aBN2/aDN/motor/body scopes
are explicitly excluded because the source figure scores aBN1 directly. The
20--220 Hz, 1-second, 30-trial protocol and JO-CE > JO-F direction are fixed before
candidate execution. No unsupported numerical tolerance or model-class decision
is emitted. Using it for model selection exposes antennal grooming for that
lineage and prevents a later held-out emergence claim.

Run `lock_abn1_reference.bat` to reconstruct that lock from the pinned raw
annotations, complete MaleCNS edge table and source checkout. It must reproduce
335 JO-C/E, 78 JO-F, two `SAD093` aBN1 cells, then 150 edges / 899 contacts and
40 edges / 131 contacts respectively. The command does not simulate either
candidate and therefore cannot inspect or select an output.

`target.actuator_semantics_gate.v0` is complete as a bounded surrogate gate. Run
`actuator_attribution_gate.bat` reproduces its behavior-naive passive, frozen
open-loop and live-feedback comparison plus a tethered 102-channel symmetry
fixture. The command trace reproduces unperturbed physics exactly; live feedback
reacts to both generic perturbations but changes final physical deviation by only
about two parts per million. The direct `MOTOR` contract may therefore remain
frozen for initial short-horizon work, while muscle, tendon, compliance and local
reflex fidelity remain explicit exclusions. The result fits no parameters and
supports no behavior or stability claim.

The first prospective behavior catalog is
`evaluation_candidates/emergent-behavior-catalog-v0.yaml`. It records localized
and hierarchical grooming, looming, lateralization, optomotor responses and
structured spontaneous activity, plus sham and topology-control requirements.
Nothing in that catalog has been run or locked, and it must not influence fitting
or model selection. A selected item becomes `evaluation_only` only through a new
immutable protocol with sources, seeds, metrics and thresholds.
The current advisory preference is mirrored localized leg contact, conditional on
tactile resolution, actuator attribution and mechanism coverage; this is not a
protocol lock.

Run `population_dynamics_assignment.bat` to rebuild the first local typed/hybrid
assignment. The hash-locked recipe accounts for 36 front-leg FeCO afferents and
10 T1 tibia-flexor motor neurons plus their accepted terminal routes. Type-level
intracellular/EMG evidence makes event capability mandatory for the motor pool;
the available FeCO calcium/kinematic evidence does not identify native event
versus graded dynamics, so that population remains `dual_unresolved`. The pass
emits zero values and inspects no body trajectory or named behavior. Its accepted
partial result is recorded in
`evaluations/population-dynamics-front-leg-accounting-v0.yaml`.

Run `local_conversion_contract.bat` to validate the executable boundaries of
that first local scope. The command exercises both admissible FeCO outputs
(`graded_activity` and `event_intensity_hz`), seeded intensity-to-event sampling,
a causal event-to-force motor kernel, and a separate biological-force to MuJoCo
direct-motor bridge. Its constants are synthetic software fixtures: the command
fits and promotes zero values, changes no topology, and sees no body trajectory
or named behavior. Source availability, exact limitations and file locks are in
`evidence/front-leg-local-conversion-sources-v0.yaml`; the accepted contract-only
result is in `evaluations/front-leg-local-conversion-contract-v0.yaml`.

The motor source repository is about 48.76 GB and the FeCO analysis repository
contains scripts rather than its numerical measurement arrays. The missing FeCO
tables are now located in the 2025 Dryad deposit as a checksum-locked 2 MB processed
subset; the one-cell-per-class motor pilot is now locally verified at about 860 MB. Run
`prepare_local_source_data.bat` after setting `DRYAD_BEARER_TOKEN` locally when a
fresh clone needs the bytes. The
script removes that credential before Dryad redirects to object storage, reports
every blocked/deferred file and never downloads the large motor archives unless
`--include-large-motor-pilot` is passed explicitly.

The motor path is also preregistered before those bytes arrive. The ten selected
MaleCNS bodies each retain the three article classes as candidates, represented
compactly as an unselected 3^10 upper bound (59,049 joint assignments) rather
than a fabricated crosswalk or probability distribution. After the explicit
download, run `inspect_motor_pilot.bat`: it verifies every archive, rejects path
traversal, encryption and duplicate normalized members, then inventories ZIP
directories and at most 128 header bytes per member without extracting anything.
This produces a schema inventory, not a fit. The current workspace completed that
inventory; it does not need to reacquire the archives.

Run `motor_source_contract.bat` without a Dryad token to reconstruct what the
pinned public motor code actually establishes. It hash-checks five source files,
accounts for all 23 active cells (7 fast, 7 intermediate, 9 slow), and verifies
the 194 trials selected by the one-cell-per-class pilot plus the aggregate
force/spike filters and force-probe units. It fits and promotes zero values. In
particular, the snapshot neither exposes the raw MAT variable schema nor defines
a temporal bi-exponential twitch kernel; those remain separate post-download
gates rather than assumptions hidden in the executable candidate.

The aggregate path is now executable with `parse_motor_spike_force_pilot.bat`
followed by `fit_motor_spike_force_pilot.bat`. The parser ports two table-building
scripts recovered from historical commit
`ebe1e5008fc5f76954cea3973aa30b103ec3fa9a`; it accounts for all 194 trials and
keeps source exclusions explicit. The slow zero-intercept line is labelled source
reproduction; applying the same low-capacity form to fast and intermediate is a
diagnostic extension. Resampling describes aggregate rows within each selected
cell, not raw trials, class or body uncertainty. All three fits are complete and
preserve the expected class ordering, but promote zero values and identify neither
a temporal twitch kernel nor the ten-body class crosswalk.

Run `fit_motor_twitch_temporal_pilot.bat` for the separate raw-trace shape
diagnostic. It applies the recovered single-spike alignment and source filters,
then compares the executable peak-normalized bi-exponential family with five
trial-held-out folds. The current pilot retains 18 fast and 15 intermediate
neutral-position single-spike traces. The fast selected cell supports a relatively
narrow shape envelope, the intermediate result is weak and broad, and the slow
archive has no isolated single-spike trial. The design was informed by exploratory
inspection and each held-out trace is normalized by its own measured peak, so this
is shape adequacy within two cells—not absolute-force prediction, population
calibration or a promoted runtime kernel.

Run `feco_observation_contract.bat` without any Dryad token to reproduce the pinned
public activation/GCaMP source paths. It detects rather than reconciles the source's
80/90-degree claw centering and 5/50-degree-per-second hook/club threshold
differences. It fits zero values and cannot distinguish native spikes from graded
activity: calcium remains a separate observation proxy. The accepted result is
`evaluations/feco-calcium-observation-source-v0.yaml`.

Run `fit_feco_calcium_observation.bat` after acquiring the three exact FeCO
Parquet tables. The campaign compares seven explicit claw/hook/club source and
boundary paths with leave-one-animal-out folds. Every trial/ROI on fixed predictor paths is
convolved separately; those paths fit an affine scale/offset, while the public
claw fit recipes estimate five polynomial coefficients through the pinned padded
GCaMP convolution. The exact public concatenation and a boundary-safe per-trial
port are both reported. Every fit uses training animals only, and held-out calcium is not
used for normalization. The exact tables now complete all 86 biological folds
across the seven candidates with zero blocked folds. The resulting observation-space
ensemble remains unpromoted: it selects no source path, runtime unit or native
event/graded representation. Its synthetic tests validate accounting and leakage
barriers only; the biological residual summary lives in
`evaluations/feco-calcium-held-out-fit-v0.yaml`.

Do not bulk-download the 48.76 GB motor repository or infer defaults from article
prose. The ten selected MaleCNS tibia-flexor motor body IDs still lack a
source-backed fast/intermediate/slow crosswalk, so class assignments remain an
explicit ensemble rather than a silent per-neuron label.

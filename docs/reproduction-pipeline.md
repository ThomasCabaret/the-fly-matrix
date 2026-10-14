# Fresh-clone reconstruction pipeline

This runbook is the canonical operational path from a Git checkout to a usable
The Fly Matrix workspace. It describes commands and dependencies, not scientific
claims. The compact ledgers, policies, campaign definitions and accepted result
summaries are versioned; raw data, generated caches, environments and heavy run
outputs are not.

## What "reconstructed" means

There are three distinct readiness levels. Do not collapse them into one setup
claim.

| Level | Result | Available from a fresh clone? |
|---|---|---|
| Structural runtime | MaleCNS data, generated interface manifests, executable wiring, MuJoCo body and audit reports | Yes, by following the mandatory path below |
| Scientific-history replay | Re-execution of a selected versioned diagnostic or calibration campaign, including its ignored heavy outputs | Yes, campaign by campaign, after acquiring that campaign's declared inputs |
| Calibrated reference fly | One promoted parameter set that can be loaded as the biological project reference | **No.** `calibration/state.yaml` currently has no `reference_parameter_set_id` or `last_promoted_parameter_set_id` |

Git already contains the current scientific status, recipes, hashes and compact
results. Re-running every historical campaign is not required to use or continue
the project. It is required only when independently reproducing that campaign's
evidence or replacing one of its accepted compact records.

## What is deliberately outside Git

| Location | Contents | Reconstruction |
|---|---|---|
| `.venv/` | Python 3.12 environment | `setup.bat` |
| `data/raw/` | Immutable upstream bytes | `download_data.bat`, then optional source-specific acquisition |
| `data/derived/` | Inventories, route matrices, caches and generated summaries | `run_analysis.bat` and the relevant campaign command |
| `runs/` | Traces, replays, checkpoints, isolated reference environments and temporary source checkouts | Re-run the named command; see campaign records |
| `reports/generated/` | HTML, DOT and wiring-map products | `dashboard.bat`, `build_preview.bat` or `wiring_map.bat` |
| `ui/wiring-map/node_modules/` and `dist/` | Local web dependencies and build | `wiring_map.bat` |
| `.env` | Short-lived access tokens | Copy `.env.example`; fill only locally |

The checkout is therefore the recipe and compact audit trail, not a binary
snapshot of one workstation.

## Prerequisites

The supported convenience path is Windows. Install:

- Git;
- Python 3.12, or the official `uv.exe` in `PATH` or `tools/uv/` so that
  `setup.bat` can obtain Python 3.12;
- Graphviz in `PATH` for DOT reports;
- Node.js/npm only for the interactive wiring map;
- an NVIDIA driver and GPU only for CUDA campaigns or performance reproduction.

The Python dependency profiles are:

```text
setup.bat                    development and tests
setup.bat -Profile audit     MaleCNS table audit tools
setup.bat -Profile body      FlyGym and MuJoCo
setup.bat -Profile full      audit + body + MuJoCo Warp backend
```

Use the `full` profile for the complete local project. PyTorch CUDA is separate
because its correctness must be checked on the actual GPU.

## Mandatory path to a structural runtime

Run these commands from the repository root, in order:

```text
setup.bat -Profile full
setup_gpu.bat                 # required for GPU work; omit on a CPU-only machine
download_data.bat
run_analysis.bat
wiring_revalidation.bat
calibration_status.bat
dashboard.bat
```

Their roles are deliberately separate:

1. `setup.bat` creates `.venv`, installs the selected dependencies and runs the
   unit tests. It does not install CUDA PyTorch.
2. `setup_gpu.bat` installs the pinned CUDA build and refuses success until a real
   CUDA calculation has run.
3. `download_data.bat` downloads the four token-free core inputs, checks their
   declared byte sizes and records their SHA-256 values: annotations,
   neurotransmitters, the weighted edge table and the optic column supplement.
   Their declared total is about 1.03 GiB.
4. `run_analysis.bat` regenerates local inventories and wiring manifests and runs
   the structural smoke test. It also runs the two remote neuPrint audits when a
   neuPrint token is present; their absence does not invalidate local generation.
5. `wiring_revalidation.bat` independently reconstructs the four accepted fine
   wiring families from rules and sources. This is the scientific topology gate,
   not a redundant smoke test.
6. `calibration_status.bat` checks the versioned calibration registry and DAG. It
   confirms accounting consistency, not calibrated values.
7. `dashboard.bat` regenerates and opens the project-status report.

Then run the relevant verification surface:

```text
status.bat
run_wiring_smoke.bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
verify_install.bat            # complete full-profile + NVIDIA workstation only
```

`verify_install.bat` intentionally checks CUDA, Warp, FlyBody, MuJoCo and
Graphviz. It is expected to fail on a CPU-only or reduced-profile installation;
that does not make the structural data pipeline invalid.

At this point the uncalibrated integration paths are available:

```text
connectome_benchmark.bat
closed_loop_record.bat
physical_replay.bat
closed_loop_live.bat
diagnostic_viewer.bat         # isolated fake controller; never scientific evidence
```

The benchmark and both closed-loop modes execute the structural MaleCNS path but
remain uncalibrated. `physical_replay.bat` only presents a trajectory previously
recorded by any compatible producer. None of these outputs may be described as
fly behavior.

## Credentials and optional remote inputs

Neither token is required for the mandatory core download.

### neuPrint

1. Sign in at <https://neuprint.janelia.org>.
2. Open the account menu, choose **Account**, and copy the personal token.
3. Copy `.env.example` to `.env` and set
   `NEUPRINT_APPLICATION_CREDENTIALS`.

This enables the remote population and ROI comparisons in `run_analysis.bat`.
It does not download the core MaleCNS tables.

### Dryad

Dryad file bytes currently require a bearer token even for the public files used
by the local calibration chain. The token is short-lived (currently about ten
hours), so it is normal to renew it before a later replay.

1. Sign in at <https://datadryad.org> and open the account page.
2. Create an API account if none exists. Keep its application ID and secret out
   of Git and project files.
3. Generate a bearer token on the account page. The official client-credentials
   procedure is documented at
   <https://github.com/datadryad/dryad-app/blob/main/documentation/apis/api_accounts.md>.
4. Copy `.env.example` to `.env` if necessary and set only
   `DRYAD_BEARER_TOKEN=<access_token>`.

The downloader removes the Authorization header before Dryad redirects to object
storage. `.env` is ignored by Git. Never put the application secret, bearer token
or a token-producing command containing the secret in a tracked script.

## Current local-chain source acquisition

The current front-leg chain uses a source subset that is intentionally smaller
than the complete upstream repositories:

```text
prepare_local_source_data.bat
```

This obtains and verifies the complete processed FeCO subset (about 2 MB) and
small motor documentation/anatomy metadata. It does **not** download the motor
archives by default. To reproduce the raw motor pilot diagnostics, explicitly
run:

```text
prepare_local_source_data.bat --include-large-motor-pilot
```

That opt-in adds three one-cell archives totaling exactly 860,357,945 bytes
(about 821 MiB). The complete upstream motor repository is about 48.76 GB and is
not required or downloaded by this project. Re-running either command first
verifies existing files by exact size and SHA-256, so an expired token is not a
problem when the required bytes are already present.

## Calibration replay versus continuation

The compact result YAML files for completed work are already in Git. The commands
below are grouped by dependency; they are not a demand to rerun the entire
history after every clone.

### Registry and reusable infrastructure

These require the mandatory structural runtime:

```text
calibration_status.bat
compile_calibration_evidence.bat
parameter_compiler_check.bat
calibration_runner_check.bat
signed_dynamics_contract_check.bat
```

They reconstruct registries, priors and executable contracts. Passing them does
not promote physiological values.

### Current typed local chain

The dependency order for the current active frontier is:

```text
population_dynamics_assignment.bat
local_conversion_contract.bat

feco_observation_contract.bat
prepare_local_source_data.bat
fit_feco_calcium_observation.bat

motor_source_contract.bat
prepare_local_source_data.bat --include-large-motor-pilot
inspect_motor_pilot.bat
parse_motor_spike_force_pilot.bat
fit_motor_spike_force_pilot.bat
fit_motor_twitch_temporal_pilot.bat

actuator_semantics_gate.bat
actuator_attribution_gate.bat
motor_actuator_bridge_envelope.bat
front_leg_chain_envelope.bat
front_leg_intermediate_dynamics.bat
front_leg_uncertainty_panel.bat
```

The blank lines denote partly independent branches, not required pauses. The
tracked compact records show that these v0 commands have already been executed in
the current project history. Their current products remain candidate ensembles
or technical diagnostics; they are not a promoted end-to-end parameter set.

The factorized local-chain step is reproducible with
`front_leg_chain_envelope.bat`. Its downstream rules-first pass,
`front_leg_intermediate_dynamics.bat`, accounts for every one of the 150 new
intermediates. Two annotated tibia-extensor motor bodies acquire a source-backed
event requirement; 148 remain explicit `dual_unresolved` alternatives. The
transmitter prior is joined only for audit and never selects native dynamics.
`front_leg_uncertainty_panel.bat` then rebuilds the accepted tractable propagation
policy without reducing the scientific uncertainty. It emits 50 deterministic,
balanced profiles covering all pairwise binary states, accepts all 24 FeCO
alternatives as an unselected set, and preserves the motor split between 1,024
fast/intermediate assignments with diagnostic kernels and 58,025 slow-containing
blocked assignments. A fresh clone must stop at that same frontier rather than
inventing a global rate/LIF default, a preferred hash profile or a slow motor
kernel.

Run `embodied_measurement_contract_v1.bat` next to reproduce the completed
short-horizon measurement gate. It executes three passive physical episodes and
validates true COM, joint limits, physical jerk, contacts/forces, a declared
direct-MOTOR work proxy, failure masks and paired recovery. It fits zero values
and chooses zero thresholds or profiles. Then run
`neutral_embodied_pilot_schedule.bat` to reconstruct the versioned 120-tuple,
240-episode readiness panel. That command validates complete small-axis coverage,
the balanced motor subset and explicit unscheduled/blocked accounting; it does
not execute the physical campaign. Then run
`neutral_embodied_adapter_sentinel.bat`. It rechecks the immutable schedule and
executes four fixed tuples as eight paired MuJoCo episodes through the diagnostic
motor event→force→route→direct-MOTOR path. It must reproduce the registered pass,
but it deliberately leaves FeCO transduction and the typed intermediate-CNS
populations dormant. Finally run
`neutral_embodied_full_chain_sentinel.bat`. The same four fixed tuples must pass
through the scheduled FeCO source functions and native representation, all 150
typed local intermediates, ten event motor bodies, the frozen physical adapter
and eight paired MuJoCo episodes. This remains an implementation probe: its
round-robin FeCO projection, normalized weights, unresolved-sign candidate and
neural constants are explicit diagnostic fixtures with zero promotion. Then run
`neutral_embodied_full_chain_panel.bat`; it must account for all 120 scheduled
tuples and 240 paired episodes and reproduce the compact execution result without
using physical output to select a candidate. The accepted run is 120/120 with
zero error, non-finite pair or skip. This closes only scheduled local execution
robustness. The next step in `calibration/state.yaml` replaces diagnostic fixtures
through declared parameter families; it is not yet a stability or behavior claim.

Then run `neutral_embodied_declared_envelope.bat`. It reconstructs the next exact
240-tuple schedule from the passed panel plus three declared replacement axes:
81 FeCO channel-group routing profiles, 64 unknown-sign profiles and 12 numeric
profiles. All 120 previous tuples are retained twice. The command requires no
network token and performs no neural or physical execution; its tracked compact
result proves schedule accounting and pairwise coverage only. A fresh clone must
not call this a calibrated parameter set. Then run
`neutral_embodied_declared_neural_sentinel.bat`. It executes all 240 rows through
the bounded neural corridor, with zero MuJoCo episode, and reproduces the
registered consumption pass for all routing, sign and numeric profiles plus the
incoming-L1 and isolated-axis oracles. This still selects and promotes nothing.
Then run `neutral_embodied_declared_closed_loop_sentinel.bat`. It performs the
first actual causal physical gate for the declared envelope: bilateral front-knee
geometry is converted to the anatomical FeCO angle at every 0.1 ms physics step,
then persistent FeCO, typed-population, delay, motor-twitch and direct-MOTOR state
is executed for 16 deterministic fixed-stride tuples as 32 paired episodes. The
tracked pass includes five nonzero routed commands and no unscoped actuator
output. It still performs zero fit, selection, stability acceptance or behavior
exposure. The next historical frontier was exhaustive physical execution of all
240 declared members under this same frozen causal contract. The corresponding
command is
`neutral_embodied_declared_closed_loop_panel.bat`. Its current versioned result
is intentionally a failed gate: 237 rows complete both branches, while rows 029,
041 and 149 are stopped before an over-limit direct-MOTOR command is applied.
All 16 sentinel trace pairs reproduce under model reuse, and no command is
clipped. Re-running this command reproduces the failure; it is not the current
continuation action. To continue the project, first create and lock the bounded
command-limit diagnostic named in `calibration/state.yaml`, then run it before
defining any technical narrowing rule.

The bounded continuation command
`neutral_embodied_command_limit_diagnostic.bat` is now completed and versioned.
It reproduces all six failed branches twice, localizes their first finite limit
crossing at 63.4--103.6 ms and never applies the offending command. It still does
not define a rejection rule. The active frontier is the smallest preregistered
factor-isolation panel plus a technical pathology policy that accounts for all
240 rows; consult `calibration/state.yaml` before adding that campaign.

That factor panel now exists as
`neutral_embodied_command_factor_isolation.bat` and is intentionally versioned as
a failed gate. It accounts 24/24 probes: all six middle-gain probes complete, but
ten of eighteen numeric-ablation probes still cross the frozen command limit.
Re-running it must reproduce the failure; do not change its criterion or clip the
commands. It also exposes that each numeric profile in the historical schedule is
paired with only one gain, so that schedule cannot estimate their independent
main effects.

Run `neutral_embodied_command_pathology_policy.bat` to reproduce the accepted
exact-schedule policy. It performs no physical simulation: it hash-checks the
failed factor result and exhaustive lineage, then regenerates the 240-row policy
CSV. The expected result admits 237 exact rows to the next technical gate and
blocks rows 029, 041 and 149. No broad factor domain is rejected, no row is
selected or promoted, and any unseen combination must execute the same command
guard fail-closed. The current continuation action is the behavior-naive stability
and identifiability gate named in `calibration/state.yaml`.

That gate is now reproducible with
`neutral_embodied_feedback_identifiability.bat`. It uses the frozen panel only to
partition diagnostic workload, never to select a candidate: 172 admitted rows
whose routed command was exactly zero remain silent/non-informative, and all 65
active rows receive four branches with exact native-step command replay. The
expected result is 260 finite episodes, 64 physically identifiable feedback
effects and one non-identifiable active row (`declared_tuple_028`), with the three
prior command blocks unchanged. Re-running it must not reinterpret effect size as
fitness or stability.

The separately preregistered continuation is reproduced with
`neutral_embodied_feedback_nonamplification.bat`. It executes 65 active rows under
four new mirrored perturbations in exact open-loop replay and live feedback, plus
the paired unperturbed controls: 650 physical episodes in total. The expected
result retains exactly rows 129, 141 and 238 as an unranked finite local technical
ensemble; 61 rows are mixed or amplifying and row 028 remains non-identifiable.
This output can seed separately versioned local sensory, motor and basal freeze
campaigns, but it is not the calibrated reference fly, whole-body stability,
physiology or behavior. All three members must be propagated until independent
local evidence can discriminate them.

The next deterministic step is
`front_leg_member_conditioned_freeze_boundary.bat`. It verifies the frozen parent
hashes and exact schedule, reconstructs all three survivors as indivisible
sensory-central-motor bundles, and writes a semantic hash for each. It performs no
optimization, ranking or independent family freeze. It also records the six basal
families as not exercised rather than silently assigning zero. The following
whole-body technical sentinel must consume all three bundles plus a separately
preregistered low-capacity basal grid. Once it emits a replay/viewable preview,
the pipeline stops for a user checkpoint before any visual-inspection-driven
parameter change.

Run `basal_low_capacity_readiness.bat` to reproduce the shape-only basal gate. It
accounts for six families, 2,212 channels and 6,041 terminal bodies, but emits no
numeric value. Then run `basal_population_reachability.bat`. It verifies the
frozen graph and source tables, computes one exact directed closure per family,
and assigns every neuron reached by their union either the twelve already
accepted exact event requirements or `dual_unresolved`. The accepted result is
166,431/166,700 reached neurons and 25,582,574 internal edges exhaustively
partitioned by endpoint disposition. Derived full tables remain ignored under
`data/derived/`; the compact result and evaluation are versioned. This closes
accounting only: all 6,041 source unit bridges remain non-executable and no
whole-MaleCNS typed/hybrid runtime or basal value is accepted.

### Historical neural-model gate

The rate/LIF global gate is closed with `revise` and is not a prerequisite to
repeat before continuing the typed/hybrid architecture. Its historical replay is
still available for audit. Some commands require a pinned external source
checkout under the ignored `runs/` tree:

```text
git clone https://github.com/philshiu/Drosophila_brain_model runs\reference-source\Drosophila_brain_model
git -C runs\reference-source\Drosophila_brain_model checkout 91bdd1e7dcf193f3e7ca5a8933497fcef63b7960
neural_model_source_fidelity.bat
setup_brian2_reference.bat
brian2_conformance.bat
temporal_model_probes.bat
audit_circuit_reference.bat
lock_abn1_reference.bat
run_abn1_gate_pilot.bat
```

The source checkout and isolated Python 3.10/Brian2 environment live under
`runs/` and are deliberately not versioned. Campaign YAML files provide the
authoritative commits, hashes, budgets and claims. Other historical central
diagnostics are enumerated in `calibration/README.md` and `PROJECT_STATE.md`;
they are not part of the current fresh-clone critical path. The isolated Brian2
setup currently requires the official `uv.exe` specifically at `tools/uv/uv.exe`,
even when the main environment was created with another Python installation.

## Updating this runbook

Whenever a new non-versioned prerequisite is introduced, update this file in the
same commit as the consuming command or campaign. At minimum record:

- whether it is mandatory, optional, historical or current-frontier;
- acquisition command, expected size and credential requirement;
- producing command and output location for generated artifacts;
- predecessor commands and whether a tracked compact result already exists;
- what a successful run proves and what it explicitly does not prove.

If a future complete parameter set is promoted, add its exact reconstruction
order here and update `calibration/state.yaml`. Until then, no setup script or
README may imply that a calibrated reference fly can be reconstructed.

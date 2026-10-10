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
```

The blank lines denote partly independent branches, not required pauses. The
tracked compact records show that these v0 commands have already been executed in
the current project history. Their current products remain candidate ensembles
or technical diagnostics; they are not a promoted end-to-end parameter set.

The next scientific step is the one in `calibration/state.yaml:next_action`:
propagate the retained FeCO alternatives, unresolved motor body-class assignments,
accepted route candidates and conditional actuator gains through one minimal
frozen sensor-CNS-motor chain. No versioned command yet claims that this step is
complete. A fresh clone must therefore stop at the same frontier rather than
inventing a default.

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

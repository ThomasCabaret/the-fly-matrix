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
- `evidence/`: deterministic evidence-transfer recipes;
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

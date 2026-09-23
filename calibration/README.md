# Calibration registry

This directory is the compact, versioned source of truth for calibration. The
canonical rules are in `docs/calibration-methodology.md` and ADR 0005.

## Contents

- `state.yaml`: current phase, promoted references, readiness, blockers, and next
  action;
- `targets/`: versioned technical, local-interface, behavioral, and held-out
  objectives;
- `_templates/`: minimum schemas for new scopes, campaigns, parameter sets, and
  evaluations;
- future `campaigns/`, `parameter_sets/`, and `evaluations/`: compact records added
  when experiments begin.

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

Start from a template, assign a stable identifier, and link the new record from
`state.yaml` or its parent object. Unknown cases should be represented honestly
and may justify a new ADR rather than being forced into an existing category.

# Rules-first, exception-aware automation

## Purpose

The Fly Matrix should preferentially turn repeated scientific and engineering
work into small, explicit procedures. A procedure applies versioned rules,
produces derived artifacts, checks its own invariants, and reports the cases it
could not explain. Human or agent attention is then spent on new decisions and
exceptions rather than on repeating deterministic work.

This is a direction of travel, not a requirement to build a framework before
every task. Automation is useful only while its expected cost is lower than the
manual work, review risk, or future repetition it replaces. A one-off, genuinely
ambiguous case may be handled directly as long as its decision and provenance are
recorded in the normal registries.

## The preferred loop

For work that is sufficiently regular or repeated:

1. Freeze and identify the input snapshot, scope, and relevant source versions.
2. Express the smallest useful rule set. Each material rule has a stable ID,
   version, applicability conditions, priority where needed, provenance or
   engineering rationale, and known assumptions.
3. Run in inspection or dry-run mode before changing canonical derived outputs
   when the operation is risky or broad.
4. Apply the rules mechanically and generate the manifests, candidates,
   parameter trials, or other derived artifacts.
5. Check cardinalities, exclusivity, invariants, reproducibility, and drift from
   the previous accepted run.
6. Emit a compact summary plus a complete machine-readable exception report.
7. Triage exceptions as a rule gap, data-quality problem, scientific ambiguity,
   implementation defect, or explicitly accepted special case.
8. Refine the rules and rerun only while doing so remains more economical and
   clearer than resolving the remaining cases directly.

This loop is iterative. A first rule set is allowed to be incomplete; its job is
also to reveal what the current model of the data failed to anticipate.

## Accounting and exception contract

Every item in the declared scope must end a run in exactly one accountable class:

- `applied`: one rule produced the expected result;
- `excluded`: an explicit, justified exclusion rule applies;
- `blocked`: required information or authority is missing;
- `exception`: the procedure encountered an unmodelled or inconsistent case.

No unmatched item may silently disappear, and no broad fallback may silently turn
an exception into an accepted scientific relation. Useful exception categories
include:

- no rule matched;
- several incompatible rules matched;
- rule priority or source claims conflict;
- an invariant, cardinality, unit, or schema check failed;
- an input changed since the rule was validated;
- a fallback or proxy was required;
- an expected category became empty or unexpectedly large;
- the result differs materially from the previous accepted run.

An exception may be acknowledged, but its record must contain the item or scope,
reason, disposition, owner or next action, and—when appropriate—an expiry or rule
version that should trigger review. “Zero unexpected exceptions” is a meaningful
acceptance gate; “zero exceptions” is not always necessary.

Each run should report at least:

- input and rule-set identifiers or hashes;
- counts and proportions by outcome and by rule;
- invariant results and determinism/replay status;
- conflicts, unmatched cases, fallbacks, and acknowledged exceptions;
- a bounded set of representative examples plus the path to the full report;
- comparison with the previous accepted run;
- the exact command, duration, result, and next action.

## Scientific review packets

When interpretation is required, automation should prepare a compact review
packet rather than ask a person or agent to rediscover the whole dataset. A packet
contains the relevant source claims, local data facts, current rule result,
alternatives, uncertainty, affected counts, and downstream consequences. The
reviewer decides only what cannot be derived safely. The decision becomes a
versioned rule, exclusion, or explicit unresolved record and can then be applied
to every matching case.

This pattern must not launder judgment into code. A generated candidate is still
a candidate; a green execution report is not scientific validation; and an
engineering rule retains that provenance even when it covers thousands of items.

## Application to wiring revalidation

The revalidation pipeline should automate inventories, selectors, candidate-set
construction, cardinality and overlap checks, current-versus-independent diffs,
terminal accounting, manifest generation, and report production. Scientific
review remains necessary for functional boundaries, biological grouping,
adequacy of proxies, source interpretation, and genuinely new exception classes.

The current prewiring must be comparison output, not the construction recipe.
Rules reconstructed from raw versioned data and primary sources should report all
differences from it, including unchanged, added, removed, unsupported, and
ambiguous relations.

The executable implementation is described in
[`wiring-revalidation.md`](wiring-revalidation.md). `wiring_revalidation.bat`
runs the versioned input/output rules, produces exhaustive group decisions and
exception packets, and keeps relation families blocked until an independent
candidate builder exists. The procedure is allowed to reach zero unexpected
exceptions while retaining explicit expected blockers.

## Application to runtime and calibration

Runtime and calibration should use the same pattern at a different level. A
versioned campaign declares parameter scope, bounds, sharing rules, seeds,
metrics, acceptance gates, exposure policy, and stop conditions. The runner then
executes trials, rejects invalid states, records failures, compares CPU/GPU or
reference implementations, ranks results under the declared metrics, and emits a
reproducible report without requiring an agent call per trial.

Human or agent intervention is reserved for a new failure class, contradictory
objectives, a scientific interpretation, a phase transition, or a change to the
permitted claim. Held-out and behavioral-exposure rules from the calibration
methodology remain mandatory and cannot be weakened by automation.

## Proportionality and stopping rule

Choose the lightest mechanism that closes the current feedback loop: a validation
function may be enough; then a script; then a declarative rule table; only then a
larger reusable engine if repetition warrants it. Do not generalize hypothetical
cases before they occur unless the cost of an error is high.

Stop investing in automation when the remaining cases are few, irreducibly
scientific, or cheaper to resolve and record directly. Conversely, automate early
when a rule affects many records, will be rerun across dataset versions, guards a
dangerous invariant, or enables large offline computation without model quota.

The success criterion is not the amount of automation. It is that repeated work
is reproducible, surprises are visible, scientific judgment is concentrated and
traceable, and the project can state why nothing in the declared scope was lost.

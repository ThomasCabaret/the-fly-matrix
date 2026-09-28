# Rules-first wiring revalidation

## Purpose

`wiring_revalidation.bat` reconstructs the reviewed interface populations from
raw, versioned MaleCNS data, applies a versioned rule set, and compares the result
with executable prewiring. It can run all workstreams or only one direction:

```text
wiring_revalidation.bat
wiring_revalidation.bat -Direction input
wiring_revalidation.bat -Direction output
```

The procedure never calibrates parameters and never promotes scientific status
automatically. A successful accounting run means that the declared scope was
fully explained by the rules. It does not mean that every candidate relation is
biologically accepted.

## Iterative loop

The intended loop is deliberately simple:

1. reconstruct a declared scope from raw data without consulting current
   scientific manifests;
2. apply the smallest versioned rules justified by data or sources;
3. classify every item as `applied`, `excluded`, `blocked`, or `exception`;
4. compare the independent result with prewiring only after reconstruction;
5. inspect new exception classes and add or correct a rule when justified;
6. rerun until no unexpected exception remains, while preserving legitimate
   scientific blockers;
7. stop automating when the remaining cases are rare or irreducibly scientific.

A broad fallback is not an acceptable way to reach zero exceptions. A known
missing independent builder is reported as `blocked`, whereas an unanticipated
data shape or conflicting rule is an `exception`.

## Rules v1

The canonical first rule set is
[`wiring/revalidation/rules-v1.yaml`](../wiring/revalidation/rules-v1.yaml). It
independently reconstructs from the raw annotation table:

- 6,098 visual input terminals and 6,098 terminal groups;
- 1,454 proprioceptive terminals in 262 annotation-backed groups;
- 4,291 mechanosensory terminals in 323 annotation-backed groups;
- 815 motor outputs in 441 lossless type/side groups.

The rules classify terminal dispositions and distinguish dataset observations,
source-supported candidates, engineering candidates and proxies. The 2,628
published R7/R8 body-to-optic-column relations are reconstructed directly from
the official workbook and compared relation by relation.

Rules v1 intentionally do **not** by itself regenerate complete fine candidate
matrices. The first companion builder now handles motor output; proprioception,
mechanosensation and vision remainder remain explicit blockers. Their current
executable manifests are comparison baselines, not construction recipes.

## Motor-output clean builder

[`motor-output-v1.yaml`](../wiring/revalidation/motor-output-v1.yaml) and its
empty, versioned singular-exception table reconstruct the motor candidate
envelope without opening `motor-actuator-candidates.parquet`. The clean build
uses only raw MaleCNS annotations, canonical-neuron flags and the independently
inventoried FlyBody actuator surface. It groups all 815 terminals losslessly into
441 type/side groups, produces 3,746 group-to-actuator candidates and expands to
7,849 terminal-to-actuator relations. Ten groups whose effectors are absent or
unknown remain explicit `sink` terminals.

The finalized semantic topology hash is
`0cd753e02283e42f3bf963e3fe223b7728b1a343da5b2db78e6414d4de8c5ca3`.
A second empty-destination build reproduced it. Only then was executable
prewiring opened: all 7,849 relations matched, with no addition, removal or
duplicate. Negative side/appendage constraints, mirrored candidate capacities
and coverage of all 102 actuators passed. This validates a bounded candidate
topology, not an exact muscle crosswalk and not any of the 7,849 transfer gains.

`wiring_revalidation.bat -Direction output` performs this complete sequence and
reports motor output as `independently_validated`. The global review remains
`in_progress` until the three input fine families have equivalent builders.

## Target clean-build contract

The next builders must write each fine family into an empty output root from
declared sources, rules, and a versioned singular-exception table. Independent
construction must not import the current candidate matrix, current relation IDs,
or a hand-maintained derivative of them. The current matrix is opened only after
the independent result and its semantic hash have been finalized.

The generated topology is a bounded candidate envelope. Reports distinguish
structural routing degrees of freedom from continuous transfer-function degrees
of freedom. No universal candidate-count threshold is imposed, but each builder
must justify its locality boundary and expose any group whose capacity could mix
unrelated anatomy or encode a global policy. Such a group remains blocked even
when the runtime can execute it.

## Output contract

Each run writes under `data/derived/wiring-revalidation/<run-id>/`:

- `summary.json`: hashes, counts, gates, workstream status and next action;
- `group-decisions.parquet`: every independently reconstructed group, matched
  rules, provenance class, disposition and current comparison;
- `exceptions.json`: every unexpected or conflicting case;
- `blocked-review-packets.json`: known scientific gaps and their next actions.

For a fine-family acceptance run, the summary additionally reports counts by
relation/provenance class, candidate-set mean, quantiles and maximum, discrete and
continuous degrees of freedom, negative-constraint violations, symmetry and
topography checks, singular-exception count, masked-gold performance when valid,
and the canonical semantic topology hash.

`data/derived/wiring-revalidation/latest.json` points to the latest run. The
human report is regenerated at
`reports/generated/wiring-revalidation.html`. These derived artifacts are ignored
by Git; the rules, code, tests, validation record and compact project status are
versioned.

## Acceptance boundary

The global `scientific_wiring_revalidation` may become
`independently_validated` only when every affected candidate relation has also
been independently generated and classified as `exact`,
`source_supported_candidate`, `engineering_candidate`, `proxy`, `unsupported` or
`removed`, with source claims and tests. Terminal equality, zero exceptions and a
green smoke test are necessary evidence but not sufficient acceptance.

Acceptance also requires a repeated clean build with the same semantic hash,
explicit negative constraints, bounded local candidate capacity, and a compiled
runtime path. A family may be topologically accepted while still marked
`not_ready_for_calibration` when its remaining parameters have no credible local
identification route; that missing route must be visible rather than repaired by
expanding the candidate envelope.

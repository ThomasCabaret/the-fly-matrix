# Drosophila Virtual Fly — Project Contract

## 1. Mission

Build an end-to-end, physically embodied Drosophila simulation in which the measured connectome is the main computational substrate.

Target loop:

physical simulated world -> physical sensor variables -> sensory receptor activity -> identified sensory afferents -> MaleCNS connectome dynamics -> identified motor neurons -> muscles or low-level body actuators -> physical body dynamics -> updated physical world.

The scientific goal is not to make a fly-shaped agent behave like a fly by any means available. The goal is to determine how far a behaviorally meaningful virtual fly can be obtained when the experimentally measured connectome carries the computation, while every non-connectomic adapter is kept as small, local, low-capacity, anatomically constrained, and independently calibratable as possible.

A successful system must remain interpretable even when it fails. It must always be possible to state which part of the loop is anatomical data, which part is measured physiology, which part is an inferred parameter, which part is a simplifying adapter, and which part is still unknown.

## 2. Ideal reference model

The ideal project would contain:

- one physical sensor for every biological receptor;
- a known one-to-one mapping from every physical receptor to its sensory axon in the connectome;
- a known local transfer function from receptor stimulus to neural activity;
- a completely specified dynamical model on the MaleCNS graph;
- a known one-to-one mapping from every motor output to its biological muscle or motor unit;
- a known local transfer function from motor-neuron activity to muscle force;
- a physical body with those muscles and realistic mechanics.

In that ideal limit there is no behavioral controller outside the connectome. The only free quantities are biologically local dynamical parameters.

The real project is an approximation to this ideal model. Every departure from it must be explicit.

## 3. Core scientific constraint: do not hide the behavior in adapters

Non-connectomic components must never become substitute controllers.

An adapter is acceptable only if its information and computational capacity are restricted to the local interface it represents.

Acceptable examples:

- local light intensity and recent local history -> firing of a photoreceptor class;
- local joint angle, strain, velocity or vibration -> firing of a proprioceptor class;
- a small anatomically constrained permutation between candidate receptors and candidate afferent axons;
- motor-neuron activity for one anatomical muscle group -> activation or torque of the corresponding physical actuator;
- constant or stochastic baseline activity for a deliberately disabled sensory modality.

Unacceptable shortcuts:

- image -> learned network -> walk left;
- whole-CNS state -> learned policy -> body joint targets;
- sensory history -> gait phase;
- a generic controller trained to imitate walking and then presented as connectome-generated locomotion;
- any adapter that has access to global task state when its biological counterpart is local.

Prefer a visible failure to an opaque controller that makes the demonstration look successful.

## 4. Main data substrate

### 4.1 MaleCNS v1.0

Use the 2026 complete male Drosophila central nervous system connectome as the primary nervous-system scaffold.

Published resource characteristics:

- about 166,700 neurons spanning brain, optic lobes and ventral nerve cord;
- about 11,700 neuron types;
- a continuous brain-to-VNC connectome;
- sensory axons included where they enter the CNS;
- synaptic-resolution chemical connectivity;
- extensive cell-type, nerve, neurotransmitter and peripheral-class annotations;
- CC-BY licensed dataset;
- programmatic access through neuPrint and downloadable tables/skeletons.

Audit the current MaleCNS v1.0 files directly rather than trusting third-party counts copied into this document.

Primary access:

- https://male-cns.janelia.org/
- https://male-cns.janelia.org/download/
- neuPrint dataset: male-cns:v1.0
- paper: https://doi.org/10.1016/j.cell.2026.08.015
- official analysis repository: https://github.com/flyconnectome/2025malecns

### 4.2 Physical body and world

Use an existing MuJoCo-based fly body rather than building mechanics from scratch unless a missing structure forces an extension.

Relevant substrates:

- FlyGym / NeuroMechFly v2: https://github.com/NeLy-EPFL/flygym
- FlyGym documentation: https://neuromechfly.org/
- NeuroMechFly v2 paper: https://doi.org/10.1038/s41592-024-02497-y
- FlyBody / MuJoCo Menagerie: https://github.com/google-deepmind/mujoco_menagerie/tree/main/flybody

The current FlyBody model exposes articulated structures and low-level actuators for legs, wings, head, antennae, proboscis-related structures and abdomen. Halteres are present mechanically but require a specific audit for active control. These are abstract mechanical actuators, not a complete biological muscle model.

The body layer can therefore be used as an engineering substrate, but the biological motor interface between MaleCNS motor neurons and those actuators remains part of the research problem.

## 5. Adapter taxonomy

Every nontrivial interface outside the fixed connectome must belong to one of the following categories.

### Type A — basal clamp

Purpose: disable a sensory modality without performing an artificial neural ablation.

For the initial project, deliberately clamp:

- olfaction;
- gustation;
- temperature/humidity sensing.

The clamp injects biologically plausible baseline activity into the corresponding peripheral populations.

Important details:

- olfactory receptor neurons generally have nonzero spontaneous activity; zero spikes is not equivalent to clean neutral air;
- gustatory receptor neurons generally have very low spontaneous activity, so near-zero stochastic activity is a reasonable starting approximation;
- thermo/hygrosensory steady-state firing is less completely characterized; treat this clamp as higher uncertainty and model a stable neutral environment rather than arbitrary zeroing.

These clamps reduce project scope. They must not be used to improve behavior.

Useful references:

- taste spontaneous activity: https://pmc.ncbi.nlm.nih.gov/articles/PMC10656072/
- thermo/hygrosensory organization: https://pmc.ncbi.nlm.nih.gov/articles/PMC5600489/
- modern thermosensation review: https://pmc.ncbi.nlm.nih.gov/articles/PMC13359671/

### Type B — sensory transduction adapter

Purpose: convert a physical variable available from the simulated world/body into receptor activity.

Examples:

- retinal irradiance -> photoreceptor activity;
- contact force or bristle deformation -> mechanosensory firing;
- joint angle, velocity, vibration or strain -> proprioceptor firing.

The adapter must be local, low-dimensional and reusable across homologous receptor classes whenever physiology permits.

### Type C — sensory routing adapter

Purpose: handle cases where a group of physical receptors and a group of connectome afferents are known to correspond, but the exact point-to-point assignment is unknown.

Allowed free variables should normally be limited to:

- a small permutation or assignment among anatomically plausible candidates;
- sparse local routing;
- optionally a local gain or confidence weight.

Never allow this to become an unrestricted dense matrix from all sensors to all CNS neurons.

If two groups are known anatomically not to mix, represent them as separate adapters.

### Type D — central dynamical parameterization

Purpose: turn the static MaleCNS graph into a dynamical nervous system.

Potential free quantities include:

- synaptic gain families;
- neuron time constants;
- resting or bias terms;
- thresholds or nonlinearities;
- short local delays;
- adaptation terms;
- parameters shared by cell type, neurotransmitter class or connection family.

Start with the lowest-capacity model that can sustain biologically plausible activity.

Do not begin with one independent arbitrary weight per synapse unless later evidence demonstrates that such freedom is required.

### Type E — motor routing adapter

Purpose: map MaleCNS motor neurons to biological muscles or motor groups when the anatomical assignment is incomplete.

Use anatomically restricted candidate sets and sparse or discrete routing rather than a generic learned decoder.

Where a motor-neuron-to-muscle mapping is already known, fix it and remove that degree of freedom.

### Type F — motor transduction / group-effect adapter

Purpose: convert activity of biological motor neurons or muscle groups into the low-level physical actuators exposed by the current body model.

This is necessary because current MuJoCo fly bodies are largely joint, torque or position actuated rather than driven by a complete set of biological muscles.

The adapter must remain local to an anatomical effector and model only the missing neuromuscular/mechanical transformation. It must not know the global behavioral objective.

Long-term, replace these adapters with explicit muscle models where adequate data exist.

### Completion rule across adapter types

Wiring completeness means exhaustive executable coverage, not perfect biological
resolution. Every terminal channel must be assigned exactly one disposition:
exact mapping, parameterized local adapter, basal clamp, declared physical proxy,
explicit no-effect sink, or unresolved blocker. Only the last category is a
dangling wire.

A smoke test may inject arbitrary parameters and declared box inputs. It must not
stand in for a missing adapter by injecting that adapter's output directly into a
MaleCNS afferent or an internal port. Such direct injections remain wiring debt
even when deterministic and clearly labelled.

Adapter policy must also be coherent across a functional sector. Known and
unknown visual assignments, for example, should traverse the same visual sensor,
transduction and routing stack: published assignments may be fixed while unknown
assignments remain parameterized inside that stack. A poorly documented retinal
subset must not be converted into an unrelated basal clamp unless an explicit
biological boundary justifies the different treatment.

## 6. Current qualitative interface picture

This is a working audit, not an authoritative final count. Regenerate it directly from MaleCNS v1.0 plus the chosen body model and maintain a machine-readable audit.

Input side:

- Vision: simulated visual capture exists. A substantial retinal/column mapping exists. Remaining routing and phototransduction details must be audited.
- Touch/mechanosensation: simulated contact forces exist. Peripheral receptor-to-axon identity is incomplete at full point-to-point resolution. Local transduction and routing adapters are required.
- Proprioception: joint state and forces exist in the mechanical simulation. Receptor classes and many anatomical groupings are known. Exact receptor-to-axon identity is incomplete in several groups. Local transduction and routing adapters are required.
- Olfaction: clamp to basal for the first project.
- Gustation: clamp to basal for the first project.
- Thermo/hygro: clamp to a stable neutral baseline for the first project.

Output side:

- MaleCNS contains annotated motor populations.
- Many leg motor neurons have explicit muscle associations, but the mapping is not complete.
- Wing, haltere, head, abdomen and proboscis mappings vary in completeness and must be audited against MaleCNS plus external atlases.
- FlyBody exposes useful articulated effectors, but these are abstract actuators rather than a complete muscle layer.
- Therefore motor routing and motor transduction/group-effect adapters remain necessary.

Previous coarse planning estimates were:

- 3 deliberate basal-clamp modules;
- on the order of 30 to 60 local sensory routing/transduction groups, depending on anatomical granularity;
- on the order of 15 to 20 local motor-routing groups;
- on the order of 13 to 15 motor group-to-physical-actuator transformations.

These are planning-scale estimates only. Replace them with reproducible counts from the datasets before large-scale fitting.

## 7. Reusable calibration sources

Prefer independent physiological data to target-behavior training whenever possible.

### Whole-brain / central dynamics

Shiu et al., Nature 2024:
A whole-brain leaky-integrate-and-fire model constrained by the fly connectome and transmitter identity produced experimentally validated sensorimotor predictions with a low-capacity dynamical model.

- https://doi.org/10.1038/s41586-024-07763-9

This is a strong baseline for central dynamics and for the philosophy of using the connectome rather than a learned generic controller.

Li et al., bioRxiv 2026:
A connectome-constrained whole-brain model was fitted to spontaneous calcium activity. Training used spontaneous activity, while several properties not used as training targets emerged afterward.

- https://www.biorxiv.org/content/10.64898/2026.08.21.745055v1.full

This is particularly relevant to calibrating a stable resting regime without training locomotion or grooming.

### Vision

Lappalainen et al., Nature 2024:
A connectome-constrained visual network with 64 cell types and only 734 free parameters was trained on a motion-computation objective and recovered detailed neural response properties not directly used as training targets.

- https://doi.org/10.1038/s41586-024-07939-3

Use FlyVis and related published data where appropriate rather than rebuilding vision without cause.

### Proprioception

Femoral chordotonal organ work:
The Drosophila FeCO contains about 150 sensory neurons per leg divided into functional classes encoding position, motion and vibration, with substantial connectomic and physiological characterization.

- https://doi.org/10.1038/s41467-025-59302-3

These data are useful for calibrating local mechanical-state-to-neural-activity adapters independently of global behavior.

### Body and biomechanics

NeuroMechFly v2 provides experimental walking kinematics, sensory geometry, contact and joint observables, visual and olfactory simulation infrastructure, and published trained models/data.

- https://doi.org/10.1038/s41592-024-02497-y
- https://github.com/NeLy-EPFL/flygym

Use behavioral kinematics cautiously: they are suitable for calibrating mechanics, but target behaviors reserved for evaluation must not leak into controller or neural calibration.

## 8. Calibration philosophy

Preferred training/calibration targets are behavior-poor physiological constraints.

Good targets include:

- stable non-exploding resting activity;
- plausible firing-rate or activity distributions;
- plausible temporal autocorrelation and population correlation structure;
- known local sensory transfer curves;
- known responses of selected receptor classes;
- known local motor-neuron physiology;
- return to baseline after small perturbations;
- known neural responses to specific descending stimulation;
- existence of locomotor rhythmic regimes where such regimes are known experimentally.

Avoid directly training on the behavioral sequence later claimed as emergent.

If grooming is a held-out demonstration, do not use grooming trajectories, grooming labels, grooming phase, known grooming-specific motor sequences, or a controller trained to imitate grooming during calibration.

The strongest result is a complex held-out behavior that appears after calibrating only generic physiology and unrelated responses.

## 9. Parameter minimization and sharing

At every stage, prefer the smallest plausible parameterization.

Order of preference:

1. measured fixed value;
2. fixed value transferred from a close physiological dataset;
3. parameter shared by a biological cell, receptor or muscle class;
4. parameter shared by homologous left/right structures;
5. small local parameter vector;
6. local sparse/discrete routing uncertainty;
7. individual connection parameter only when evidence shows it is required.

Track parameter count by module and adapter type.

Reducing free parameters is scientifically valuable even if optimization becomes harder.

## 10. Mandatory provenance and anti-leakage ledger

Every adapter and every trainable parameter family must have a machine-readable manifest entry containing at least:

- unique module ID;
- adapter type A through F;
- anatomical region;
- input channel set;
- output channel set;
- evidence source;
- mapping status: exact, type-level, group-level or unknown;
- transfer-function status: measured, borrowed, fitted or unknown;
- number of free continuous parameters;
- number of free discrete routing parameters;
- parameter-sharing rule;
- calibration dataset;
- behaviors present in that calibration dataset;
- held-out behaviors that must not influence the module;
- confidence level;
- known limitations;
- replacement path if a better anatomical or physiological dataset becomes available.

This ledger is part of the scientific output, not only project documentation.

Any behavior shown as emergent must be auditable against this ledger.

## 11. Required engineering properties

The system should be modular enough that each of the following can be replaced independently:

- connectome dataset;
- central neuron model;
- sensory transduction model;
- sensory routing;
- basal clamps;
- motor routing;
- motor transduction;
- body model;
- calibration objective.

The end-to-end simulation must support deterministic replay when random seeds and data versions are fixed.

Log at minimum:

- complete version hashes for code and datasets;
- all free parameters;
- all random seeds;
- sensory inputs;
- selected CNS activity summaries;
- motor-neuron outputs;
- actuator commands;
- body state and contacts;
- optimization losses;
- which data were used for training versus evaluation.

## 12. Suggested scientific progression

Do not define initial success as “the fly walks”.

Stage 1: the complete graph loads and runs locally with a low-capacity dynamical model.

Stage 2: the CNS supports a stable, biologically plausible resting regime.

Stage 3: basal clamps and visual, mechanosensory and proprioceptive interfaces are connected.

Stage 4: the body is in closed loop with the nervous system without a behavioral controller.

Stage 5: known simple neural or sensorimotor perturbations produce qualitatively correct responses.

Stage 6: motor output produces physically meaningful motion, even if coordination is poor.

Stage 7: freeze all parameters and evaluate held-out perturbations and behaviors.

Stage 8: only after the held-out protocol is fixed should complex outcomes such as stable locomotion, grooming, takeoff or recovery from perturbation be interpreted.

A negative result is acceptable if it localizes the missing mechanism.

## 13. What counts as a scientifically useful result

Strong result: a complex neural or physical behavior not present in calibration data appears after fitting only generic physiological constraints.

Very strong result: the model predicts the effect of a neural perturbation or ablation that is later confirmed biologically.

Useful negative result: the CNS develops the expected neural rhythm but the embodied fly fails because a specific peripheral adapter or mechanical mapping is inadequate.

Weak result: the fly reproduces a behavior that was directly used as a training target.

Invalid for the main scientific claim: a generic learned policy outside the connectome generates the behavior.

## 14. Important known limitations

Do not assume the MaleCNS chemical connectome is the complete causal nervous system.

Potentially missing or incompletely represented mechanisms include:

- electrical coupling / gap junctions;
- diffuse neuromodulation and peptide signaling;
- detailed synaptic physiology;
- intracellular dynamics;
- some peripheral receptor identities;
- some motor-neuron-to-muscle assignments;
- complete biological muscle mechanics.

Represent these first as explicit uncertainty, not silently as an unconstrained neural network.

## 15. Existing projects worth inspecting, but not blindly adopting

- therealfly: https://github.com/fruitflydev/therealfly
  Useful because it explicitly attempts to close MaleCNS to FlyBody without inserting a conventional behavioral controller. Treat it as an engineering reference and source of audit ideas, not as validated biological truth.

- FlyGym / NeuroMechFly: https://github.com/NeLy-EPFL/flygym
  Primary physics and sensory engineering substrate.

- FlyBody / MuJoCo Menagerie: https://github.com/google-deepmind/mujoco_menagerie/tree/main/flybody
  Useful articulated full-body model and actuator inventory.

- MaleCNS official repository: https://github.com/flyconnectome/2025malecns
  Prefer official annotations and notebooks over manually copied counts.

- Shiu whole-brain model: https://doi.org/10.1038/s41586-024-07763-9
  Low-capacity whole-brain dynamical baseline.

- FlyVis / visual model: https://doi.org/10.1038/s41586-024-07939-3
  Evidence and potentially reusable visual-processing component.

## 16. First task for the implementation agent

Before optimizing any behavior, produce a reproducible interface audit.

For every sensory and motor group:

- enumerate the relevant MaleCNS neurons;
- enumerate corresponding physical sensors/effectors available in the body model;
- state whether mapping is exact, type-level, group-level or absent;
- state whether a measured transfer function exists;
- state which adapter type is required;
- count free routing and continuous parameters under the proposed minimal parameterization;
- identify independent calibration datasets;
- identify which target behaviors would be contaminated by using those data.

Then regenerate the architecture graph and adapter ledger from that audit.

Only after this audit should large-scale parameter fitting begin.

## 17. Guiding principle

The central question is not:

“Can software make a virtual fly behave like a fly?”

It is:

“How much behavior appears when the experimentally measured fly connectome is placed between physically meaningful inputs and outputs, while every missing interface is represented by the smallest independently justifiable adapter?”

Preserve that distinction throughout the project.

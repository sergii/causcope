# Atlerror Lab

Atlerror Lab contains two complementary kinds of reproducible validation:

1. **Mechanism labs** test diagnostic mechanisms encoded by the semantic knowledge base.
2. **Investigation labs** test whether an investigator can move from incomplete incident context toward useful evidence without violating investigation invariants.

The goal is not to prove universal truths from one synthetic environment. Experiments produce empirical evidence that supports, contradicts, or leaves a diagnostic claim inconclusive under a recorded environment. Investigation scenarios separately test investigation behavior and ordering.

## Mechanism lab contract

An empirical check has three layers:

1. `claims/**/*.yaml` - a stable, machine-addressable statement derived from a hypothesis.
2. `experiments/**/*.yaml` - a manifest that references the claim and declares how to run a fixture.
3. `lab/**` - fixture code that creates a controlled physical intervention and emits `EmpiricalEvidence` JSON.

Run an experiment with:

```bash
python scripts/run_lab.py experiments/memory/retention-ruby.yaml
```

The generic runner:

1. validates the experiment manifest;
2. builds the declared Docker image;
3. runs the fixture with declared resource constraints;
4. parses evidence JSON from the fixture;
5. validates the evidence schema;
6. verifies experiment and claim references;
7. checks the expected result;
8. writes the result under `lab-results/`.

## Investigation lab contract

Investigation scenarios live under:

```text
lab/investigation/**/scenario.yaml
```

A scenario contains:

- incomplete initial incident context;
- hidden oracle facts;
- optional red herrings;
- an expected first scoping dimension;
- required and forbidden investigation behaviors.

Run the deterministic baseline with:

```bash
python scripts/run_investigation_lab.py \
  lab/investigation/checkout-client-version/scenario.yaml
```

The first baseline does not claim to be an AI benchmark yet. It verifies that the same machine-readable incident context used by future agents produces the expected deterministic scoping move. Agent adapters can later consume the identical scenario contract and score multi-step behavior.

## Principles

- Prefer the smallest environment that can reproduce the mechanism.
- Use real operating-system/runtime behavior rather than mocked measurements when practical.
- Record environment and intervention explicitly.
- Treat results as evidence, not proof.
- Keep experiments deterministic enough for CI when possible.
- Add semantic concepts only when a real measurement or diagnostic distinction requires them.
- Keep hidden scenario truth separate from information available to the investigator.
- Treat correlation and cohort differences as investigation clues, not causal proof.

## Evidence semantics

Mechanism-lab results are deliberately limited to:

- `supports`
- `contradicts`
- `inconclusive`

A successful synthetic experiment does not establish production frequency, impact, or exclusivity of a cause.

Investigation-lab evaluation is separate. It can score whether an investigator scopes first, finds useful cohort differences, gathers discriminating evidence, avoids unsupported causal attribution, and verifies the original incident scope.

## Current experiments

Mechanism labs include examples such as:

- Ruby retained objects -> live heap and RSS growth
- Ruby busy loop -> near-one-core CPU utilization with user-space dominance

Investigation labs currently include:

- checkout client-version regression with a nearby backend deploy red herring

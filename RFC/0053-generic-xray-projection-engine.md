# RFC 0053: Declarative Concrete System X-Ray projection engine

- Status: Proposed
- Date: 2026-09-14
- Scope: Generalize RFC 0051 and RFC 0052 projection semantics without weakening evidence boundaries

## Summary

RFC 0051 and RFC 0052 prove the Concrete System X-Ray model across two qualitatively different mechanisms:

```text
D2.2 database deadlock
  generic knowledge
  x revision-bound code/resource facts
  x exact runtime executions
  x PostgreSQL evidence
  -> causal confirmation

Q2.1-style duplicate side effect
  generic knowledge
  x revision-bound retry/effect facts
  x exact runtime executions
  x provider effect evidence
  x idempotency counterfactual
  -> causal confirmation
```

The proofs revealed a repeated orchestration pattern. The mechanism-specific Python scripts currently own both domain predicates and the generic epistemic progression. That is acceptable for proving the first slices, but it does not scale: a third failure family should not require a new bespoke projection state machine merely to express joins over sourced facts and evidence.

This RFC introduces a small declarative X-Ray profile plus a deterministic rule engine.

```text
sourced facts + runtime evidence + profile rules
                  |
                  v
          deterministic joins
                  |
                  v
       highest justified stage
```

The engine does not replace source adapters, generic failure knowledge, provider schemas, or domain-specific evidence collection. It replaces repeated projection orchestration.

## Design principle

The profile describes **what must match**. The engine owns **how matching and epistemic advancement work**.

A profile contains:

- canonical catalog code and hypothesis;
- named input document kinds;
- identity groups that must remain aligned;
- ordered stages;
- row-selection clauses over input collections;
- explicit variable bindings and joins;
- equality, inequality, ordering and unordered-set constraints;
- bounded cardinality requirements.

The engine has no D2.2, PostgreSQL, Sidekiq, payment or idempotency-specific code.

## Incremental proof bindings

Stages are evaluated in order and carry their successful bindings forward.

```text
PRECONDITIONS_PRESENT
  binds code_path_a, code_path_b, resource_a, resource_b

RISK_DETECTED
  must reuse those exact code paths

CONTENTION_OBSERVED
  preserves the same proof binding

EVENT_OBSERVED
  preserves the same proof binding

CAUSAL_DIAGNOSIS_CONFIRMED
  must bind exact runtime/provider participants back to it
```

This is deliberately different from evaluating each stage as an unrelated boolean. A later stage cannot silently switch to another code path, trace, transaction, job identity or dependency.

The engine has a hard solution bound. A rule that explodes beyond that bound fails instead of consuming unbounded resources or silently truncating semantic possibilities.

## Inputs remain typed and source-owned

The profile declares expected document kinds, for example:

```yaml
inputs:
  static:
    kind: concrete_system_facts
    required: true
  runtime:
    kind: concrete_runtime_facts
    required: false
  canonical:
    kind: runtime_evidence
    required: false
```

An X-Ray profile does not redefine those contracts.

Likewise, the PostgreSQL correlation artifact from RFC 0051 and the duplicate-side-effect effect artifact from RFC 0052 remain their own strict evidence contracts. The generic engine consumes them but does not absorb their schemas.

## Optional evidence and partial progression

Only the revision-bound static input is required by the first profiles. Runtime and incident evidence may be absent.

That permits the same profile to answer progressively:

```text
static only
  -> PRECONDITIONS_PRESENT

+ runtime execution
  -> RISK_DETECTED

+ incident evidence
  -> EVENT_OBSERVED

+ exact cross-layer correlation
  -> CAUSAL_DIAGNOSIS_CONFIRMED
```

Missing optional evidence prevents advancement. It does not become `absent` and does not falsify the mechanism.

## Identity groups

Profiles explicitly state identities that must match when the corresponding inputs are present.

Examples:

```text
system_id:
  static == runtime == concrete correlation

revision:
  static == runtime == concrete correlation

incident_id:
  runtime == canonical evidence == concrete correlation
```

Identity mismatch is an error, not a lower-confidence match.

This preserves the existing rule:

```text
similar evidence from another incident or revision
!=
evidence for this concrete causal path
```

## Rule language

The v0 language is intentionally small.

A clause selects rows from one named document path:

```yaml
- source: static
  path: facts
  where:
    relation: accesses_before
  bind:
    resource_a: subject
    resource_b: object
    code_left: context.code_path
```

A later clause can require an exact prior binding:

```yaml
- source: static
  path: facts
  where:
    relation: accesses_before
    subject:
      var: resource_b
    object:
      var: resource_a
```

Supported v0 expression forms are:

- literal equality;
- exact variable equality;
- exact list construction from prior variables;
- one-of previously bound variables;
- inequality;
- literal one-of.

Supported cross-binding constraints are:

- `eq`;
- `neq`;
- `lt` for deterministic canonical orientation;
- `set_eq` for unordered participant pairs.

Profiles may also require exact/minimum/maximum row cardinality.

This is a bounded relational matcher, not a general programming language.

## D2.2 profile

`xray/profiles/d2-2.yaml` expresses the full RFC 0051 progression.

The structural stage joins two `accesses_before` facts in reverse resource order. Runtime risk joins an observed code-path overlap. Canonical evidence advances the proof through lock contention and deadlock-event observation. Confirmation then requires exact runtime executions, exact PostgreSQL participants, the two directed wait-for edges, the correlated victim and SQLSTATE `40P01`.

No D2.2-specific predicate exists in `scripts/xray_engine.py`.

## Duplicate-side-effect profile

`xray/profiles/duplicate-side-effect.yaml` expresses the RFC 0052 progression.

The static stage joins:

```text
code symbol -> job -> external dependency
```

with retry and bounded missing-idempotency attributes already produced by the source enrichment.

Later stages bind the exact timeout attempt, retry execution, two provider effects, canonical duplicate-side-effect observation and protected idempotency counterfactual.

No payment-specific predicate exists in `scripts/xray_engine.py`.

## Parity requirement

The first version does not delete the mechanism-specific projection scripts.

They remain regression oracles while the abstraction stabilizes.

CI runs both live proofs and requires:

```text
legacy D2.2 final state
== generic D2.2 final state
== CAUSAL_DIAGNOSIS_CONFIRMED

legacy duplicate-effect final state
== generic duplicate-effect final state
== CAUSAL_DIAGNOSIS_CONFIRMED
```

CI also tampers with discriminating evidence and requires the generic engine to stop at `EVENT_OBSERVED` instead of confirming causality.

Once the declarative engine survives further slices, old projection scripts may be reduced to compatibility wrappers or removed in a separate change.

## What remains domain-specific

The engine deliberately does not make raw telemetry meaningful by itself.

Domain-specific work still includes:

- extracting revision-pinned code facts;
- Rails-aware enrichment;
- normalizing OTel spans into concrete runtime facts;
- pgBot/PostgreSQL evidence collection;
- provider audit/effect evidence;
- safe read-only probes;
- schemas for concrete correlation artifacts.

Those layers decide what was observed and with what provenance. The X-Ray profile only composes typed facts into an inspectable proof progression.

## Security and safety

The generic engine is pure evaluation. It executes no shell commands, SQL, HTTP requests, probes, remediation or arbitrary profile code.

Profiles cannot name Python callbacks or executables.

This keeps a strong boundary:

```text
provider / adapter
  -> obtains evidence under its own safety contract

X-Ray engine
  -> pure deterministic composition only
```

## Non-goals

RFC 0053 does not introduce:

- a Turing-complete rule language;
- arbitrary Python callbacks in profiles;
- probabilistic reasoning;
- automatic remediation;
- replacement of canonical knowledge/rules;
- replacement of provider schemas;
- a universal graph database;
- fuzzy identity matching;
- temporal-nearest correlation;
- interpretation of missing evidence as healthy/absent.

## Acceptance criteria

The first generic engine is accepted when:

1. both RFC 0051 and RFC 0052 can reach their confirmed states through YAML profiles;
2. the engine contains no mechanism-specific branches;
3. profile inputs preserve their existing source schemas and provenance boundaries;
4. system/revision/incident identity mismatches fail closed;
5. variable bindings persist across epistemic stages;
6. missing optional evidence stops advancement without inventing absence;
7. tampered discriminating evidence cannot reach causal confirmation;
8. generic and legacy projections agree on the final state in both live integration proofs;
9. no OpenAI API or LLM is required for evaluation.

## Consequence for the next failure slice

A third X-Ray mechanism should first attempt to reuse:

```text
existing generic knowledge
+ existing/new source facts
+ existing/new evidence adapters
+ one declarative X-Ray profile
```

A new mechanism-specific projection script should be considered a design failure unless the new slice exposes a capability that cannot be represented safely by the bounded v0 matcher.

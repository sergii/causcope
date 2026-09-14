# RFC 0049: Revision-bound concrete runtime execution projection

- Status: Proposed
- Date: 2026-09-14
- Scope: WP-5/WP-6 of RFC 0045, first D2.2 runtime composition slice

## Summary

RFC 0047 established direct repository facts from Rubydex. RFC 0048 added conservative Rails-aware static inference and can derive an opposing resource-order precondition for D2.2.

The next missing fact is not another static relationship. It is whether the two concrete code paths actually executed at overlapping times for the same pinned application revision.

This RFC introduces a narrow derived contract:

```text
OpenTelemetry spans
  + explicit concrete code-symbol binding
  + exact concrete-system identity
  + exact repository revision
  -> concrete_runtime_facts
  -> execution intervals
  -> temporal overlap
  -> D2.2 X-Ray risk projection
```

This contract is a revision-bound runtime projection. It is not a new generic ontology layer and it does not replace canonical `runtime_evidence`.

## Why canonical runtime evidence is not enough by itself

Causcope's existing runtime evidence contract is incident-scoped and observation-centric. It is appropriate for canonical statements such as database latency, lock contention or deadlock errors.

The X-Ray slice needs a different identity:

```text
code:CheckoutService#call
```

bound to:

```text
system: rubydex-fixture
revision: fixture-revision
```

and to an observed execution interval.

Creating a generic observation such as `observation.runtime.code_execution` would force concrete repository identities into the global diagnostic ontology. That is the wrong boundary.

Therefore this RFC keeps concrete runtime execution as a derived system/revision-scoped projection.

## Input binding contract

An OTel span participates only when it explicitly carries:

```text
causcope.code_symbol
causcope.system_id
causcope.revision
```

The code symbol MUST already exist in the supplied `concrete_system_facts` document and MUST be a `code_symbol` entity.

The system ID and revision MUST exactly match the static document.

A mismatch fails closed.

No fuzzy symbol matching, file-name matching, span-name guessing, current-branch guessing or revision aliasing is allowed in v0.

## Execution fact

A concrete execution records:

- concrete code-symbol ID;
- start/end timestamps;
- duration;
- trace ID;
- span ID;
- OpenTelemetry provenance;
- pinned concrete system and revision at document level.

It means only:

> An explicitly bound OTel span for this concrete code symbol and revision was observed during this interval.

It does not prove every call to that symbol is traced and it does not make unobserved paths absent.

## Temporal overlap

For two distinct concrete code-symbol executions:

```text
max(left.start, right.start) < min(left.end, right.end)
```

implies a positive observed span overlap.

The projection records the overlap duration in milliseconds.

This is evidence that the traced execution intervals overlapped. It is not evidence that:

- both paths held database locks simultaneously;
- both were inside database transactions for the entire spans;
- the inferred static resource order was the exact PostgreSQL lock-acquisition order;
- a wait-for edge existed;
- a wait-for cycle existed;
- a deadlock occurred.

## Uncertainty rule

The absence of a matching overlap in one supplied trace sample is `unknown`, not `absent`.

Reason:

```text
not observed in this sample
  !=
never executes concurrently
```

Likewise, an unannotated span is ignored as unbound evidence rather than converted into a negative execution fact.

## D2.2 derived projection

This RFC adds a deterministic projection over RFC 0048 static facts plus `concrete_runtime_facts`.

For the first slice:

```text
structural_precondition = opposing accesses_before paths
runtime_concurrency     = matching concrete path overlap
```

The derived states are:

```text
no supported structural precondition
  -> UNKNOWN

structural precondition only
  -> PRECONDITIONS_PRESENT

structural precondition + observed path overlap
  -> RISK_DETECTED
```

`RISK_DETECTED` is deliberately not `OBSERVED` deadlock.

The projection keeps:

```text
deadlock_event: unknown
```

until database evidence establishes the event.

## Fixture proof

The fixture contains two static paths from RFC 0048:

```text
CheckoutService#call()
  accounts -> ledger_entries

SettlementJob#perform()
  ledger_entries -> accounts
```

The runtime fixture binds two OTel spans to those exact concrete symbols and the same pinned revision:

```text
CheckoutService#call
  12:01:03.100 -> 12:01:03.480

SettlementJob#perform
  12:01:03.220 -> 12:01:03.620
```

Expected deterministic overlap:

```text
260 ms
```

Expected X-Ray result:

```text
D2.2
structural_preconditions: present
runtime_concurrency: observed
risk_state: RISK_DETECTED
deadlock_event: unknown
```

## Determinism

The CI workflow MUST:

1. build direct Rubydex facts;
2. add Rails static enrichment;
3. project OTel concrete runtime facts twice;
4. require byte-identical runtime outputs;
5. build the D2.2 X-Ray projection twice;
6. require byte-identical X-Ray outputs;
7. reject a deliberately mismatched revision;
8. assert that runtime overlap never becomes an observed deadlock.

No LLM or OpenAI API is used.

## Relationship to pgBot and database evidence

This RFC stops before the database-event layer.

The next composition slice should add existing PostgreSQL/pgBot evidence without making the concrete runtime contract database-specific:

```text
Rubydex + Rails
  -> static D2.2 structural precondition

OTel
  -> concrete execution + overlap

pgBot / PostgreSQL
  -> lock waits / blockers / deadlock evidence

Causcope
  -> epistemic D2.2 progression
```

A likely progression is:

```text
PRECONDITIONS_PRESENT
  -> RISK_DETECTED
  -> EVENT_OBSERVED
  -> CAUSAL_DIAGNOSIS_CONFIRMED
```

The exact names after `RISK_DETECTED` remain deferred until the database-evidence composition proves the required distinctions.

## Security and trust boundary

The projection is read-only.

It does not execute application code, database queries or remediation. It consumes already supplied static facts and OTLP JSON.

Concrete symbol binding is treated as asserted instrumentation metadata and is validated against the pinned static model. A span cannot create a new code symbol or silently move evidence to another revision.

## Non-goals

This RFC does not provide:

- automatic Rails tracing instrumentation;
- fuzzy source/span symbol resolution;
- distributed causal inference from timing alone;
- exact PostgreSQL lock identity;
- deadlock confirmation;
- persistence of the X-Ray risk state as ontology;
- a general temporal graph database;
- model-generated execution facts.

## Next work

1. Compose the D2.2 X-Ray projection with existing pgBot/PostgreSQL runtime evidence.
2. Distinguish lock contention from a concrete deadlock event without overclaiming causality.
3. Connect database evidence back to concrete transactions/resources where the source provides enough identity.
4. Prove the state progression through a live deadlock fixture.
5. Reuse the same concrete runtime execution contract for the duplicate-side-effect vertical slice.

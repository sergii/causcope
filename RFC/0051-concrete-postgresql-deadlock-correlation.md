# RFC 0051: Concrete PostgreSQL deadlock correlation

- Status: Proposed
- Date: 2026-09-14
- Scope: WP-5/WP-6 completion for the first D2.2 Concrete System X-Ray slice

## Summary

RFC 0048 establishes a revision-pinned structural D2.2 precondition. RFC 0049 binds exact code symbols to observed OTel executions. RFC 0050 composes canonical database contention and deadlock-event evidence, but deliberately stops at `EVENT_OBSERVED` because a database-wide event is not proof that the concrete code paths in the X-Ray model caused it.

This RFC adds the missing discriminating proof:

```text
revision-pinned static D2.2 precondition
  + exact concrete OTel executions
  + exact OTel execution -> PostgreSQL backend correlation
  + observed mutual PostgreSQL wait-for cycle
  + SQLSTATE 40P01 on one exact participant
  -> CAUSAL_DIAGNOSIS_CONFIRMED
```

The confirmation is a derived projection. It does not introduce a new global ontology state.

## Why the previous stage was insufficient

The RFC 0050 projection can say:

```text
EVENT_OBSERVED
```

when canonical evidence contains an observed database deadlock error. That means a deadlock happened in the selected application-database scope.

It does not answer:

```text
which concrete application executions participated?
```

or:

```text
is this the same D2.2 path pair found by the static X-Ray?
```

Without that binding, causal confirmation would be an overclaim.

## Correlation boundary

The live proof uses an explicit PostgreSQL `application_name` correlation token:

```text
cs:<otel-trace-id>:<otel-span-id>
```

The monitor reads this value from `pg_stat_activity`. Causcope accepts the database participant only when the trace/span pair exactly matches one revision-bound execution in `concrete_runtime_facts`.

No fuzzy symbol matching, stack-name guessing or temporal-nearest inference is allowed.

A production system may use a different trustworthy correlation channel, for example:

- trace context propagated through a database instrumentation layer;
- a connection/session tag;
- an exact request/job execution identifier mapped to the trace span;
- provider-native correlation metadata.

The semantic requirement is exact identity, not `application_name` specifically.

## Live wait-for proof

The integration lab creates the same concrete resource order described by the static fixture:

```text
CheckoutService#call()
  accounts -> ledger_entries

SettlementJob#perform()
  ledger_entries -> accounts
```

Each database session:

1. is bound to one exact OTel execution;
2. acquires its first concrete resource;
3. attempts the second resource;
4. becomes blocked by the other participant.

Before PostgreSQL resolves the deadlock, a read-only monitor calls:

```sql
pg_blocking_pids(pid)
```

for both backends and requires the directed edges:

```text
A waits for B
B waits for A
```

That is the concrete two-participant wait-for cycle.

The database then aborts one of those exact participants with:

```text
SQLSTATE 40P01
```

## Concrete database evidence contract

The new derived contract records:

- concrete system and revision;
- incident identity;
- exact OTel execution ID, trace ID and span ID for each PostgreSQL participant;
- exact concrete code symbol and static transaction identity;
- PostgreSQL backend PID and DB-visible correlation token;
- revision-pinned resource order used by the live proof;
- directed waiter/blocker edges;
- the observed wait event;
- deadlock victim and SQLSTATE.

This is not generic runtime evidence. It is a narrow evidence artifact used to prove exact cross-layer identity.

The same live probe also emits existing canonical `runtime_evidence`:

```text
observation.database.lock_wait_time = observed
observation.database.deadlock_error = observed
```

so RFC 0050 remains the generic database-evidence projection.

## Confirmation rule

`CAUSAL_DIAGNOSIS_CONFIRMED` is reachable only when all of the following are true:

1. RFC 0050 already reached `EVENT_OBSERVED` from canonical database evidence;
2. concrete system, revision and incident identities match across all inputs;
3. both database participants map exactly to OTel executions;
4. those executions are the same concrete code paths in one D2.2 structural precondition;
5. each participant maps to the expected static transaction identity;
6. each participant's controlled resource order matches the revision-pinned static access-order fact;
7. PostgreSQL exposes both wait directions between those exact backends;
8. one of those exact participants is aborted with SQLSTATE `40P01`.

If any binding is missing or inconsistent, confirmation fails closed.

## Epistemic progression

The complete first vertical slice is now:

```text
PRECONDITIONS_PRESENT
  static opposing resource order

RISK_DETECTED
  + exact concurrent OTel execution

CONTENTION_OBSERVED
  + canonical database lock-wait evidence

EVENT_OBSERVED
  + canonical PostgreSQL deadlock event

CAUSAL_DIAGNOSIS_CONFIRMED
  + exact execution/backend correlation
  + observed mutual wait-for cycle
  + 40P01 on an exact participant
```

These are derived projection states, not persisted probability scores.

## What confirmation means

The proof is sufficient to say:

> These exact revision-bound application executions formed the observed PostgreSQL deadlock cycle.

It does not claim that Causcope reconstructed every PostgreSQL lock object or lock mode.

The Rails `accesses_before` facts remain deterministic static inferences. The direct causal proof comes from the exact participant binding plus the observed mutual wait-for cycle and PostgreSQL's own deadlock detector outcome.

## Security and execution model

The diagnostic part remains read-only:

- `pg_stat_activity`;
- `pg_blocking_pids`;
- runtime evidence inspection.

The lab intentionally creates a deadlock to validate the contract. That intervention belongs to the empirical test harness, not to an autonomous production diagnostic provider.

Production Causcope MUST NOT create lock cycles merely to test a hypothesis.

## Fail-closed cases

The verifier explicitly rejects:

- trace/span identity tampering;
- a broken or self-referential wait edge;
- cross-incident evidence;
- revision mismatch;
- unknown execution IDs;
- code-symbol mismatch;
- transaction mismatch;
- resource-order mismatch;
- deadlock victim outside the correlated participant set;
- non-`40P01` victim outcome.

## Non-goals

This RFC does not add:

- fuzzy trace-to-database correlation;
- a universal SQL parser;
- every PostgreSQL lock type;
- production deadlock generation;
- probabilistic causal confirmation;
- automatic remediation;
- persistence of a global `CONFIRMED` ontology record.

## Next work

The first D2.2 vertical slice is complete at proof-of-concept level.

The next architecture test should move to the second domain promised by RFC 0045: duplicate external/business side effects. That slice should reuse the same three-layer model:

```text
static concrete structure
  + observed runtime execution
  + domain-specific evidence
  -> concrete risk / diagnosis / verification
```

and prove that Concrete System X-Ray is not database-specific.

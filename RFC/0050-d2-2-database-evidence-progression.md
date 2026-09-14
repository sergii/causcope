# RFC 0050: D2.2 database evidence progression

- Status: Proposed
- Date: 2026-09-14
- Scope: WP-5/WP-6 of RFC 0045, database-evidence composition after RFC 0049

## Summary

RFC 0048 can establish a concrete structural D2.2 precondition. RFC 0049 can bind exact concrete code symbols to OpenTelemetry execution intervals and derive observed runtime overlap.

That is enough for:

```text
RISK_DETECTED
```

but still not enough to say that the database is contending or that a deadlock event occurred.

This RFC composes the existing canonical `runtime_evidence` layer into the same D2.2 X-Ray progression:

```text
concrete static precondition
  + concrete runtime overlap
  + canonical database lock evidence
  + canonical database deadlock evidence
  -> deterministic D2.2 epistemic projection
```

No new database observation ontology is introduced.

## Reused canonical observations

The first slice reuses:

```text
observation.database.lock_wait_time
observation.database.deadlock_error
```

`observation.database.lock_wait_time` can come from the existing pgBot adapter mapping for `wait_lock_contention`.

`observation.database.deadlock_error` represents an explicitly classified database deadlock event such as PostgreSQL SQLSTATE `40P01`.

The source-specific vocabulary remains outside the D2.2 projection.

## Scope

Database evidence is resolved through the existing runtime evidence resolver using:

```text
boundary.application.database
```

and, when supplied by the caller, exact scope attributes such as:

```text
service=checkout-api
dependency=postgresql
```

The projection does not invent aliases or broaden scope.

Every runtime evidence document MUST carry the same incident ID as the concrete X-Ray projection. Cross-incident evidence fails closed.

Freshness, future evidence, scope filtering and contradictory active evidence remain owned by the existing runtime evidence resolver.

## Progression

The deterministic stages are:

```text
PRECONDITIONS_PRESENT
  static opposing resource order exists

RISK_DETECTED
  static precondition + concrete runtime path overlap

CONTENTION_OBSERVED
  RISK_DETECTED + canonical database lock-wait evidence

EVENT_OBSERVED
  canonical database deadlock error observed
```

The projection deliberately stops there.

## Why EVENT_OBSERVED is not CONFIRMED

A database can report a real deadlock while Causcope still lacks proof that the exact concrete code paths from RFC 0048 caused that event.

The current database evidence is scoped to the application-database boundary, not yet to the concrete transactions/resources:

```text
tx:CheckoutService#call():...
tx:SettlementJob#perform():...
db:public.accounts
db:public.ledger_entries
```

Therefore:

```text
EVENT_OBSERVED
  !=
CAUSAL_DIAGNOSIS_CONFIRMED
```

The projection returns:

```text
causal_diagnosis: unconfirmed
```

until a later slice provides concrete linkage or an equivalent discriminating proof.

## pgBot role

pgBot remains a PostgreSQL diagnostic instrument.

For this slice:

```text
wait_lock_contention
  -> pgbot adapter
  -> observation.database.lock_wait_time = observed
  -> CONTENTION_OBSERVED
```

The D2.2 projection never consumes the source finding ID directly.

This keeps the architecture:

```text
source-specific finding
  -> canonical runtime evidence
  -> Causcope diagnostic projection
```

## Deadlock event fixture

The contract test also supplies canonical runtime evidence for:

```text
observation.database.deadlock_error = observed
measurement.value = 40P01
boundary = boundary.application.database
```

This proves only the composition boundary. The fixture is explicitly experiment/synthetic evidence and does not pretend to be a live pgBot result.

The expected progression is:

```text
base X-Ray
  risk_state: RISK_DETECTED

+ pgBot lock evidence
  epistemic_state: CONTENTION_OBSERVED
  deadlock_event: unknown
  causal_diagnosis: unconfirmed

+ canonical 40P01 evidence
  epistemic_state: EVENT_OBSERVED
  deadlock_event: observed
  causal_diagnosis: unconfirmed
```

## Absence semantics

An active canonical `absent` deadlock observation is preserved as absent for the selected scope.

It does not erase:

- the static precondition;
- concrete runtime overlap;
- previously derived latent risk.

This preserves the distinction between:

```text
mechanism can occur
```

and:

```text
this event was observed in the selected evidence window
```

## Determinism

The integration workflow MUST:

1. build Rubydex concrete system facts;
2. add conservative Rails enrichment;
3. build revision-bound OTel runtime facts;
4. derive the RFC 0049 D2.2 X-Ray projection;
5. translate a pgBot lock-contention fixture through the existing pgBot adapter;
6. derive `CONTENTION_OBSERVED` twice and require byte-identical output;
7. add canonical deadlock-event evidence;
8. derive `EVENT_OBSERVED` twice and require byte-identical output;
9. assert causal diagnosis remains unconfirmed;
10. reject cross-incident evidence.

No LLM or OpenAI API is used.

## Non-goals

This RFC does not add:

- source-specific pgBot semantics to D2.2;
- a new lock/deadlock ontology;
- inferred PostgreSQL wait-for graph edges;
- transaction PID/backend identity mapping;
- exact row-lock identity;
- automatic causal confirmation;
- remediation;
- probabilistic scoring.

## Next work

The next proof should link live PostgreSQL evidence to concrete execution identity strongly enough to distinguish:

```text
real deadlock happened somewhere in the scoped database
```

from:

```text
these concrete application transactions formed the deadlock cycle
```

Candidate evidence includes transaction/application correlation IDs, backend PID or trace-linked SQL spans, concrete resource identity and an observed wait-for cycle. Only then should `CAUSAL_DIAGNOSIS_CONFIRMED` become reachable.

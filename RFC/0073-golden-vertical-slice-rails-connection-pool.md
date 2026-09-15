# RFC 0073: Golden vertical slice - Rails connection-pool exhaustion

- Status: In progress
- Date: 2026-09-15
- Scope: Stop expanding platform surface temporarily and prove one product-shaped Causcope investigation from a user-visible Rails latency symptom to a verified causal diagnosis.

## Decision

The next Causcope milestone is not another generic lifecycle, MCP surface, provider abstraction, or architectural-recommendation capability.

It is one golden vertical slice:

```text
Rails developer
  -> "checkout is slow"
  -> concrete Rails revision
  -> exact request execution
  -> exact ActiveRecord pool interaction
  -> runtime pool evidence
  -> independent PostgreSQL control
  -> causal X-Ray progression
  -> verified root cause
  -> human-readable Causcope diagnosis
```

The first mechanism is D3.1 application-side database connection-pool exhaustion.

## Why this slice

This mechanism demonstrates Causcope's product thesis better than a subsystem-specific diagnostic command.

A slow request can coexist with:

```text
SQL execution near baseline
PostgreSQL still accepting an independent connection
ActiveRecord pool saturated
request blocked on pool checkout
```

No single narrow instrument owns the complete explanation. Rails runtime evidence identifies the concrete pool interaction. PostgreSQL evidence distinguishes database-wide capacity failure. OpenTelemetry binds the affected request. Causcope joins those facts and decides whether the causal diagnosis is justified.

The intended product distinction is:

```text
PostgreSQL instrument -> knows PostgreSQL
OpenTelemetry          -> knows traces
Rails runtime          -> knows the ActiveRecord pool
Causcope               -> knows how these facts answer the debugging question
```

## Existing machinery reused

This slice must reuse, not replace:

- portable Rails repository scanning;
- revision-bound Concrete System Facts;
- portable Rails OpenTelemetry integration and concrete OTLP receiver;
- exact ActiveRecord pool runtime binding;
- the generic declarative X-Ray engine;
- `xray.d3_1.concrete_connection_pool_exhaustion`;
- independent PostgreSQL capacity control;
- existing fail-closed identity semantics.

No new causal-ranking algorithm is introduced by this RFC.

## Product projection

`scripts/rails_pool_vertical_slice.py` is the first bounded human-facing projection over the existing D3.1 proof.

Given the three canonical inputs already produced by the live Rails proof:

```text
concrete_system_facts
concrete_runtime_facts
resource_pool_runtime_evidence
```

it runs the existing declarative X-Ray profile and renders:

```text
Problem
Status
Root cause
Concrete scope
Evidence
Rejected nearby explanations
Blast radius
Verification
```

The projection must not infer facts that the bounded proof does not establish.

In particular, the first slice explicitly prints:

```text
Blast radius
  not established by this bounded slice
```

rather than inventing affected-user or affected-request counts.

## Required causal proof

A confirmed result requires the existing D3.1 progression to reach:

```text
PRECONDITIONS_PRESENT
RUNTIME_EXECUTION_OBSERVED
POOL_SATURATED
CHECKOUT_WAIT_OBSERVED
DATABASE_CAPACITY_DISTINGUISHED
CAUSAL_DIAGNOSIS_CONFIRMED
```

The human-facing root cause is emitted only at `CAUSAL_DIAGNOSIS_CONFIRMED`.

Anything weaker remains explicitly unconfirmed.

## Nearby explanations

The slice may reject a nearby explanation only when the corresponding existing evidence supports that rejection.

`slow SQL execution as the primary explanation` is rejected only when query latency stayed near baseline.

`PostgreSQL-wide connection admission exhaustion` is rejected only when the independent PostgreSQL control remained reachable.

If the database-capacity control is unavailable or negative, Causcope must stop at the weaker epistemic state. It must not convert unavailable evidence into absence.

## Verification

The causal claim is stronger than correlation because the existing D3.1 proof includes recovery:

```text
pool slot released
  -> checkout wait returns to baseline
  -> request latency returns to baseline
```

The projection exposes this verification instead of merely saying that pool saturation and latency occurred together.

## Golden acceptance scenario

The live Rails CI proof should ultimately exercise this exact product path:

```text
1. scan the Rails revision;
2. start the concrete OTLP receiver;
3. start the Rails application with the portable integration;
4. create real pool contention with pool capacity = 1;
5. capture the affected request and exact pool interaction;
6. prove PostgreSQL still accepts an independent connection;
7. run the unchanged D3.1 X-Ray profile;
8. feed the same real artifacts to the golden vertical-slice projection;
9. require a confirmed application-side pool-exhaustion diagnosis;
10. verify the human output names the concrete code symbol and pool and rejects only evidence-backed alternatives.
```

No hand-written diagnosis fixture may substitute for steps 1-8 in the live acceptance proof.

## Product front door follow-up

This RFC deliberately does not build another parallel CLI architecture.

Once the golden projection is proven against the live Rails lab, the next product step is to route the existing RFC 0059 front door through it:

```text
causcope why "checkout is slow"
```

The target experience is:

```text
problem statement
  -> persisted investigation
  -> concrete evidence acquisition
  -> competing/nearby explanations
  -> safe discriminating evidence
  -> causal diagnosis
  -> verification
```

`why`, `evidence`, `hypotheses`, and unified `next` remain projections over canonical state. They must not become a second reasoning engine.

## Freeze rule

Until this slice is green end to end, new work should normally not add:

- another MCP surface;
- another generic lifecycle;
- another recommendation-session abstraction;
- another provider unless the slice cannot be completed without it;
- SaaS/UI work;
- autonomous remediation;
- additional X-Ray mechanisms.

An exception requires showing that the missing capability blocks this vertical slice.

## Definition of done

The milestone is done when a clean Rails/PostgreSQL environment can demonstrate, from real runtime behavior:

```text
user-visible slow request
  -> exact Rails execution
  -> exact ActiveRecord pool
  -> pool saturation
  -> checkout wait
  -> PostgreSQL-wide exhaustion distinguished
  -> recovery
  -> CAUSAL_DIAGNOSIS_CONFIRMED
  -> product-shaped human diagnosis
```

The output must also preserve explicit unknowns. In particular, blast radius remains unknown until a separate evidence source establishes it.

After this milestone, the repository README should promote this scenario as the primary product proof and demote the original high-CPU ontology example to a semantic example.

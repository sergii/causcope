# RFC 0065: Evidence-gated database read-model recommendation

- Status: Implemented bounded proof
- Date: 2026-09-15
- Scope: Prove that PostgreSQL performance evidence can gate an architectural recommendation without granting the database instrument architectural authority

## Summary

RFC 0064 introduced architecture recommendations as a layer downstream from diagnosis and defined the evidence shape expected from trustworthy normalization or denormalization advice.

This RFC implements the first bounded projection for:

```text
recommendation.database.denormalize_read_model
```

The projection deliberately does not implement an automatic advisor.

Its purpose is to answer a narrower question:

> Do we currently have enough evidence and context to surface a denormalized read-model candidate, and how mature is the evidence for its claimed benefit?

The progression is:

```text
fresh PostgreSQL query-latency evidence
  + exact target resource
  -> problem evidence present

+ workload context
- business/consistency semantics
  -> INSUFFICIENT_CONTEXT

+ business semantics
+ maintenance strategy
+ cost model
+ verification plan
+ expected or unknown benefit
  -> EXPERIMENT_REQUIRED

+ planner/benchmark improvement
  -> ESTIMATED_BENEFIT

+ measured before/after improvement
  -> READY_FOR_HUMAN_REVIEW
```

Even the final state requires human approval and never authorizes a schema or application change.

## Provider boundary

pgbot remains a deterministic PostgreSQL evidence provider.

In this proof its `query_slowdown` finding is translated by the existing adapter into:

```text
observation.database.query_latency = observed
```

Causcope uses that observation as problem evidence.

It does not interpret the pgbot finding as:

```text
normalize this table
```

or:

```text
denormalize this read path
```

The architectural decision requires additional information outside PostgreSQL telemetry.

## Exact resource target

RFC 0040 introduced provider instances bound to concrete resource targets.

The projection requires an exact provider instance and subject resource:

```text
provider.pgbot.orders-prod
  -> db.orders.prod
```

A pgbot instance bound to another PostgreSQL database cannot support the recommendation even if it reports the same finding type.

The proof also compares the database identity reported by the pgbot context with the database identity of the topology resource.

Therefore:

```text
same instrument
+ same finding type
!=
same concrete target
```

Target mismatch fails closed.

## Freshness

The recommendation context includes an explicit `evaluation_time`.

The canonical runtime evidence is accepted only when:

```text
observed_at <= evaluation_time < expires_at
```

A stale `query_slowdown` does not become historical permission for a current architectural recommendation.

If no active matching query-latency evidence exists, the state is:

```text
NO_PROBLEM_EVIDENCE
```

## Workload context

A slow query alone is not sufficient.

The bounded context records:

```text
query object
request/read path
read frequency
whether the query contribution is dominant, material, or unknown
```

Zero read frequency or unknown contribution remains insufficient context.

The projection does not infer workload dominance from PostgreSQL severity or confidence.

## Business and consistency context

To progress beyond `INSUFFICIENT_CONTEXT`, the system must provide explicit semantics for:

```text
source of truth
consistency invariant
staleness budget
```

This is intentionally outside pgbot's authority.

For example, duplicated order shipping data may be an intentional historical snapshot rather than a normalization defect. Database duplication is not enough to infer data ownership or mutability semantics.

## Maintenance strategy

A denormalized projection has a write path and new failure modes. The bounded contract therefore requires:

```text
update strategy
retry semantics
partial-failure strategy
reconciliation strategy
```

Supported strategy labels include same-transaction writes, transactional outbox, CDC projections, materialized-view refresh, database triggers, periodic reconciliation, or an explicitly described alternative.

The first proof uses a transactional outbox and requires idempotent consumer processing plus drift reconciliation.

## Cost is part of the recommendation

The context must expose at least:

```text
write amplification
operational complexity
new failure modes
```

Storage cost may also be provided.

Causcope must not present the read benefit while hiding synchronization and operational cost.

## Benefit evidence maturity

RFC 0065 distinguishes benefit basis explicitly.

### Unknown or reasoned expectation

```text
basis = unknown | expected
-> EXPERIMENT_REQUIRED
```

An expected improvement is a reason to test the candidate, not evidence that the candidate works.

### Planner experiment or benchmark

```text
basis = planner_experiment | benchmark
+ after < before
-> ESTIMATED_BENEFIT
```

This is stronger than an unsupported expectation but is not called a measured production improvement.

### Measured before/after result

```text
basis = measured
+ after < before
-> READY_FOR_HUMAN_REVIEW
```

The proof calculates the improvement from explicit before/after values and preserves the evidence reference.

### No demonstrated improvement

```text
after >= before
-> BENEFIT_NOT_DEMONSTRATED
```

Causcope does not keep the recommendation alive merely because it was plausible before the experiment.

## Verification and rollback

A mature candidate requires a verification plan with:

```text
experiment
success criteria
rollback path
```

The proof uses shadow reads: compute the existing source aggregation and the proposed projection for the same request, compare correctness, measure read latency, and keep the original path behind a feature flag.

This makes the recommendation falsifiable.

## Projection states

The bounded state model is:

```text
NO_PROBLEM_EVIDENCE
INSUFFICIENT_CONTEXT
EXPERIMENT_REQUIRED
BENEFIT_NOT_DEMONSTRATED
ESTIMATED_BENEFIT
READY_FOR_HUMAN_REVIEW
```

These are evidence-maturity states, not execution states and not probabilities.

No state means `apply_change`.

## Proof fixture

The proof uses:

```text
resource topology
  db.orders.prod
  provider.pgbot.orders-prod -> db.orders.prod

pgbot query_slowdown
  query:orders-summary
  120 ms baseline -> 380 ms observed

workload
  GET /reports/orders-summary
  120 reads/minute
  dominant contribution

candidate
  materialized projection

consistency
  orders + order_line_items remain source of truth
  <= 5 s allowed projection lag
  transactional outbox
  idempotent consumer
  periodic drift reconciliation

measured experiment
  380 ms -> 42 ms
```

The measured fixture therefore reaches `READY_FOR_HUMAN_REVIEW` while still requiring explicit human approval.

## Negative proofs

The verifier also proves:

```text
slow query + missing semantics
  -> INSUFFICIENT_CONTEXT

expected benefit
  -> EXPERIMENT_REQUIRED

planner experiment
  -> ESTIMATED_BENEFIT

no before/after improvement
  -> BENEFIT_NOT_DEMONSTRATED

stale pgbot evidence
  -> NO_PROBLEM_EVIDENCE

pgbot provider bound to the wrong database
  -> rejected
```

## Normalization boundary

This RFC implements only a denormalized read-model gate.

A future normalization slice must require a different semantic proof, such as:

```text
mutable duplicated fact
+ shared ownership/source-of-truth semantics
+ divergent update paths or observed inconsistency
+ write/repair cost
-> normalization candidate
```

It must not infer a normalization defect from repeated column values alone.

## Non-goals

RFC 0065 does not add:

- automatic normalization;
- automatic denormalization;
- schema migration generation;
- autonomous write-capable remediation;
- architectural authority to pgbot;
- a universal architecture score;
- a claim that a benchmark equals production measurement;
- a claim that read improvement outweighs consistency cost without explicit context.

## Result

The intended architectural chain is now:

```text
provider-targeted PostgreSQL evidence
  -> canonical observation
  -> workload problem
  -> explicit domain/consistency context
  -> bounded design candidate
  -> experiment
  -> benefit evidence
  -> maintenance cost
  -> verification + rollback
  -> human review
```

No OpenAI API is used.

# RFC 0064: Causally justified architecture advice

- Status: Implemented foundation
- Date: 2026-09-15

## Summary

Causcope currently answers two separate questions well:

```text
What happened?
  -> observations and causal diagnosis

What should I inspect next?
  -> ranked read-only probes and safe instrument routing
```

A useful diagnostic system should also be able to answer a third question without collapsing into a generic best-practice linter:

```text
Given the evidence and the confirmed or strongly supported mechanism,
what architectural change is worth considering?
```

This RFC introduces `architectural_recommendation` as a distinct ontology kind for causally justified architecture advice.

The core rule is:

> A recommendation is downstream from diagnosis. It is not evidence, not a hypothesis, not a causal mechanism, and not an executable remediation instruction.

## Why a separate ontology kind

Architecture advice has different semantics from the existing concept kinds.

```text
observation
  = what was measured

hypothesis
  = a possible explanation

probe
  = a diagnostic question or measurement action

architectural_recommendation
  = a design change worth considering after causal support exists
```

Putting architecture advice into `hypothesis` would contaminate root-cause ranking. Putting it into `probe` would confuse learning with changing the system. Putting it into free-form remediation text would lose machine-readable trade-offs and evidence requirements.

The existing causal ranking engine filters candidate roots to `kind == hypothesis`. Therefore an `architectural_recommendation` cannot silently become a root-cause candidate.

## Reusable knowledge versus concrete recommendation instance

The ontology entry describes reusable knowledge:

```yaml
id: recommendation.database.denormalize_read_model
kind: architectural_recommendation
recommendation_domain: data_model
supported_by:
  - hypothesis.latency.database
  - observation.database.query_latency
tradeoffs:
  - dimension: read_latency
    direction: improves
    note: ...
  - dimension: write_complexity
    direction: worsens
    note: ...
human_approval_required: true
```

It must not contain invented measurements for an unknown system.

A future recommendation projection creates a concrete recommendation instance for a specific system, revision, workload, and evidence set. That instance is where measured benefit, consistency requirements, operational cost, missing assumptions, and verification belong.

This separation prevents reusable knowledge from being confused with a claim about the current system.

## Causal support

`supported_by` identifies ontology concepts that can form the semantic basis for considering the recommendation. It does not mean that the recommendation is automatically justified whenever one referenced concept exists in the repository.

A recommendation projection must combine:

```text
active incident/workload evidence
+
ranked or confirmed causal mechanism
+
relevant concrete system facts
+
business/data semantics when required
+
recommendation support contract
```

Only then may it present the recommendation as applicable to the current system.

This preserves an important distinction:

```text
knowledge says a design change can help under certain conditions
!=
those conditions are proven in this system
```

## pgbot boundary

pgbot can be an excellent deterministic PostgreSQL evidence provider, but it is not the authority for business semantics or architectural trade-offs.

As of pgbot v0.8.1, its documented scope is PostgreSQL diagnostics and performance: `inspect` produces findings-first health analysis, `lint` performs schema-only checks, `advise` proposes planner-validated missing indexes with HypoPG, and `ask` / `explain` add an AI interpretation layer over deterministic findings. The v0.8.1 documentation does not claim a dedicated normalization or denormalization analyzer. Therefore normalization and denormalization remain Causcope-level architectural reasoning rather than pgbot capabilities.

Reference: [pgbot v0.8.1 documentation](https://github.com/pgrundev/pgbot/blob/v0.8.1/README.md).

Useful pgbot evidence can include:

```text
query latency
query frequency
join shape
indexes
locks
relation size
scan behavior
planner estimates
```

That evidence can support the statement:

```text
this workload is expensive in PostgreSQL
```

It cannot by itself prove:

```text
this schema should be normalized
```

or:

```text
this data should be denormalized
```

Causcope owns the broader reasoning boundary by combining provider evidence with system structure, runtime behavior, domain semantics, and explicit consistency requirements.

## Normalization requires business semantics

Repeated values do not automatically prove a normalization defect.

Example:

```text
orders.shipping_address
```

may look like duplicated customer-address data, but it can intentionally be a historical snapshot of where the order was shipped at purchase time.

A normalization recommendation therefore requires enough context to distinguish at least:

```text
mutable shared fact
historical snapshot
copy for audit/legal history
cache/projection
accidental duplicate source of truth
```

Without that context the correct state is `insufficient_context`, not a normalization recommendation.

Useful evidence may include functional dependencies, ownership/source-of-truth rules, divergent update paths, observed inconsistent values, write amplification, and domain assertions supplied by the application or operator.

## Denormalization requires workload and freshness semantics

A denormalization recommendation requires more than a slow query.

Example:

```text
repeated aggregation of thousands of orders
```

may justify a stored total, materialized view, read model, or projection only after the system can answer:

```text
How often is the read executed?
How expensive is the current computation?
What latency/SLO is being missed?
How frequently do source rows change?
How fresh must the derived value be?
How will updates be propagated?
What happens when propagation fails?
How is drift detected and repaired?
What write amplification and operational burden are acceptable?
```

## Concrete recommendation evidence contract

A good concrete recommendation should be explainable as this chain:

```text
problematic workload/query
  -> proposed structural change
  -> expected or measured benefit
  -> consistency invariant
  -> update/maintenance strategy
  -> allowed staleness
  -> write + operational cost
  -> verification experiment
```

A future recommendation projection should therefore emit a shape conceptually equivalent to:

```yaml
recommendation: recommendation.database.denormalize_read_model
subject:
  resource: db.orders.prod
  revision: <git revision>

problem:
  workload: <query fingerprint / concrete read path>
  evidence:
    - <query latency evidence>
    - <frequency or request contribution evidence>

proposed_change:
  type: materialized_projection
  description: <bounded design candidate>

benefit:
  basis: measured | planner_experiment | benchmark | expected
  metrics:
    - name: read_latency
      before: <measured value when known>
      after: <measured/experimental value when known>
  unknowns: []

consistency:
  invariant: <what must remain true>
  source_of_truth: <resource/entity>
  update_strategy: synchronous | asynchronous | database_materialized_view | unknown
  staleness_budget: <explicit value or unknown>
  reconciliation: <strategy or unknown>

cost:
  write_amplification: <measured/expected/unknown>
  storage: <measured/expected/unknown>
  operational_complexity: <description>
  new_failure_modes: []

verification:
  experiment: <before/after or shadow validation>
  success_criteria: []
  rollback: <plan>

missing_assumptions: []
human_approval_required: true
```

The exact schema can evolve, but these semantic sections are mandatory for trustworthy data-model advice.

## Expected versus measured benefit

Causcope must distinguish:

```text
measured
planner-predicted
benchmark-derived
reasoned expectation
unknown
```

A planner estimate is not a measured production win. A synthetic benchmark is not a production guarantee. If no trustworthy numeric estimate exists, the recommendation should say so instead of manufacturing a percentage.

The strongest recommendation path is:

```text
problematic query
  -> candidate change
  -> safe experiment
  -> measured improvement
  -> maintenance cost measured or bounded
  -> human decision
```

## Consistency maintenance is part of the recommendation

For denormalized state, maintenance is not an implementation footnote. It is part of the design decision.

The recommendation must make explicit whether consistency is maintained by, for example:

```text
same-transaction write
transactional outbox + consumer
CDC/projection pipeline
materialized view refresh
database trigger
periodic reconciliation
```

and what happens on retry, duplicate delivery, partial failure, lag, and repair.

A recommendation that claims the read benefit while hiding this cost is incomplete.

## Trade-offs

The reusable recommendation exposes coarse trade-off directions:

```text
read latency       improves
read complexity    improves
write complexity   worsens
consistency risk   worsens
```

The concrete projection adds system-specific evidence and magnitude where available.

The contract deliberately does not expose a fake universal score or probability.

## No causal edges from recommendations

An architectural recommendation is not a cause of the incident being diagnosed.

Recommendation concepts MUST NOT be connected into the causal graph merely so they appear in reverse-cause traversal.

The intended flow is downstream:

```text
runtime evidence
  -> causal ranking
  -> supported mechanism
  -> concrete context
  -> recommendation projection
```

not:

```text
recommendation
  -> causal edge
  -> symptom
```

## Human decision boundary

All architectural recommendations require:

```yaml
human_approval_required: true
```

Changes such as normalization, denormalization, materialized projections, database splits, or altered consistency semantics can change domain behavior, operational burden, cost, and failure modes. Telemetry alone cannot authorize those changes.

The product flow is:

```text
observe
-> reason
-> recommend
-> show causal basis
-> show expected/measured benefit
-> show consistency and maintenance cost
-> show verification plan
-> human decision
```

## First ontology entry

The initial implementation adds:

```text
recommendation.database.denormalize_read_model
```

It is supported by existing database-latency knowledge but does not become applicable from query latency alone. The future projection must require additional workload and concrete-system conditions before surfacing it for a real system.

The inverse normalization recommendation should be added only when Causcope has enough semantics/evidence for duplicated mutable state, ownership, divergent updates, write amplification, or observed inconsistency. It must not infer a normalization defect from repeated column values alone.

## Non-goals

This RFC does not add:

- automatic schema migration;
- automatic normalization or denormalization;
- architecture recommendations as root-cause candidates;
- recommendation ranking by invented probability;
- provider-specific architectural authority;
- generic style advice detached from workload evidence;
- write-capable autonomous remediation.

## Next slice

The next bounded implementation should project one concrete PostgreSQL read-path recommendation and prove the full chain:

```text
query/workload evidence
  -> causally supported performance problem
  -> candidate read-model change
  -> EXPLAIN/planner or benchmark experiment
  -> benefit evidence
  -> explicit consistency strategy and staleness budget
  -> maintenance cost
  -> verification criteria
```

If required business or consistency context is missing, the projection must return insufficient context rather than an architectural recommendation.

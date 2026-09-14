# RFC 0062: Causally justified architecture advice

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

The existing causal ranking engine already filters candidate roots to `kind == hypothesis`. Therefore an `architectural_recommendation` cannot silently become a root-cause candidate.

## Contract

`schema/concept.schema.json` adds:

```text
kind = architectural_recommendation
```

Such a concept must declare:

```yaml
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

The initial recommendation domains are:

```text
data_model
storage
availability
scalability
observability
deployment
integration
```

Trade-off direction is deliberately coarse and auditable:

```text
improves
worsens
mixed
```

The contract does not expose a fake probability or universal score.

## Causal support

`supported_by` identifies ontology concepts that can form the semantic basis for considering the recommendation. It does not mean that the recommendation is automatically justified whenever one referenced concept exists in the repository.

A future recommendation projection must combine:

```text
active incident evidence
+
ranked or confirmed causal mechanism
+
relevant concrete system facts
+
recommendation support contract
```

Only then may it present the recommendation as applicable to the current system.

This preserves an important distinction:

```text
knowledge says a design change can help under certain conditions
!=
those conditions are proven in this incident
```

## Database normalization and denormalization

Normalization and denormalization are the motivating examples because neither is a universally correct state.

A PostgreSQL instrument such as pgbot can provide deterministic local facts:

```text
query latency
query frequency
join shape
indexes
locks
relation size
scan behavior
```

Causcope can combine those facts with broader system evidence and topology.

For example:

```text
dominant request latency
+
confirmed database contribution
+
repeated expensive relational assembly
+
read-heavy access pattern
+
acceptable freshness semantics
      |
      v
consider a denormalized read model
```

The recommendation must expose the changed trade-off:

```text
read latency       improves
read complexity    improves
write complexity   worsens
consistency risk   worsens
```

The inverse class of recommendation, normalizing duplicated mutable state into a single source of truth, should be added when Causcope has ontology and provider evidence for state duplication, divergent update paths, write amplification, or observed state divergence. The ontology should not invent those facts merely to make a normalization recommendation available.

## No causal edges from recommendations

An architectural recommendation is not a cause of the incident being diagnosed.

Therefore recommendation concepts MUST NOT be connected into the causal graph merely so they appear in reverse-cause traversal.

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

This is intentional even when Causcope can later generate migration plans or validation experiments.

Changes such as:

```text
normalize a data model
denormalize a read path
split a database
introduce a materialized view
change consistency semantics
change deployment topology
```

can alter domain semantics, operational burden, cost, and failure modes. Telemetry alone cannot authorize those changes.

The product flow is therefore:

```text
observe
-> reason
-> recommend
-> show causal basis
-> show trade-offs
-> human decision
```

## First ontology entry

The initial implementation adds:

```text
recommendation.database.denormalize_read_model
```

It is supported by the existing database-latency hypothesis and query-latency observation, but it does not become applicable from query latency alone. A future recommendation projection will require additional workload and concrete-system conditions before surfacing it for a real system.

## Non-goals

This RFC does not add:

- automatic schema migration;
- automatic denormalization;
- recommendation ranking by invented probability;
- generic style advice detached from runtime evidence;
- architecture recommendations as root-cause candidates;
- write-capable autonomous remediation.

## Next slice

The next useful implementation after the ontology foundation is a recommendation projection that consumes a completed diagnosis plus concrete facts and emits:

```text
recommendation
causal basis
supporting evidence
missing assumptions
expected benefit dimensions
cost/risk dimensions
verification plan
```

That projection should begin with one bounded database case rather than a broad architecture-advisor surface.

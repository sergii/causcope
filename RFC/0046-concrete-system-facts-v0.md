# RFC 0046: Concrete System Facts v0

- Status: Draft implementation slice
- Date: 2026-09-14
- Parent roadmap: RFC 0045

## Summary

RFC 0045 identified the primary X-Ray gap as a sourced representation of one concrete system. This RFC defines the smallest executable contract needed to start the D2.2 predictive-deadlock vertical slice without expanding the generic ontology or misusing incident `runtime_evidence`.

The new document kind is:

```text
concrete_system_facts
```

It describes repository/configuration facts that can exist before an incident and remain pinned to a concrete system revision.

It is intentionally separate from:

- generic ontology concepts;
- incident runtime evidence;
- incident context;
- provider capability discovery;
- causal conclusions.

## Why a separate fact layer

A generic semantic concept such as:

```text
system_entity.database
boundary.application.database
hypothesis.database.deadlock
```

is reusable across systems.

A concrete fact such as:

```text
CheckoutService#call writes public.accounts
```

belongs to one codebase/revision.

A runtime observation such as:

```text
checkout-api currently waits on a PostgreSQL lock
```

belongs to one incident/time window.

Collapsing these layers would make provenance, staleness and uncertainty ambiguous.

The intended separation is:

```text
Generic knowledge
  hypothesis / prediction / cause / claim

Concrete system facts
  repository/configuration structure at revision R

Runtime evidence
  observed incident facts at time T
```

## Contract

A `concrete_system_facts` document contains:

- `system_id`;
- a pinned `revision`;
- sourced concrete `entities`;
- sourced relationships in `facts`;
- explicit limitations.

Every entity and fact records certainty and provenance.

Initial certainty values are deliberately small:

```text
direct
inferred
```

Unknown state is represented by absence of an assertion plus explicit limitations where relevant. An unresolved static reference MUST NOT be converted into an absent fact.

## Local entity identity

Concrete entities use local, provider-neutral identifiers rather than canonical ontology IDs.

Examples:

```text
code:CheckoutService#call
tx:checkout
db:public.accounts
```

The identity is meaningful only with the enclosing `system_id` and `revision`.

Current entity kinds are restricted to what the first slices need:

```text
code_symbol
transaction
data_resource
service
job
external_dependency
```

This list is not a replacement for generic `SystemEntity`. It is an instance/fact vocabulary.

## Fact relations

The initial relation vocabulary is:

```text
calls
contains
executes_in
reads
writes
maps_to
accesses_before
depends_on
```

This is intentionally not a general-purpose knowledge graph relation registry.

For D2.2, the important relation is:

```text
accesses_before
```

which states a sourced static ordering precondition such as:

```text
public.accounts
  accesses_before
public.ledger_entries

context:
  code_path: CheckoutService#call
  transaction: checkout
```

An opposite order in another code path is a structural deadlock **precondition**, not an observed deadlock.

## Provenance

Every fact records its source.

Initial provenance types are:

```text
static_analysis
source
declared_config
generated
```

An inferred fact MUST identify the deterministic deriving rule.

Example:

```yaml
certainty: inferred
provenance:
  source_type: generated
  name: rails-static-enrichment
  rule: rails.transaction_resource_order.v0
  reference: app/services/checkout_service.rb:10-11
```

This gives downstream reasoning a clear distinction between:

```text
Rubydex resolved this symbol/reference directly
```

and:

```text
Causcope inferred Rails framework meaning from sourced code facts
```

## Revision semantics

Static system facts are pinned to a revision rather than an incident TTL.

The first revision modes are:

```text
git
opaque
```

A code/deploy change can therefore invalidate or supersede facts without rewriting historical evidence.

Future work may add a system-fact freshness/projection policy, but v0 does not pretend static repository facts are timeless.

## Rubydex boundary

The WP-3 spike established that Rubydex is suitable for direct semantic facts such as:

- declaration identity;
- source location;
- owner/membership;
- ancestors/descendants;
- resolved constant references;
- resolved method-reference targets when available.

Rails transaction, table-write and ordered-resource semantics generally require deterministic Rails-aware enrichment.

Therefore the v0 contract is provider-neutral. It does not expose Rubydex-native node types.

## D2.2 structural projection

This slice includes a deliberately narrow projection:

```text
path A: X accesses_before Y
path B: Y accesses_before X
```

When the paths differ, Causcope can report:

```text
opposing_access_order_precondition
```

The projection MUST also say:

```text
deadlock_observed: false
```

because static order alone proves neither runtime overlap nor a wait-for cycle.

The next vertical slice must combine this structural precondition with runtime and PostgreSQL evidence before upgrading epistemic state.

## Semantic validation beyond JSON Schema

The executable validator additionally enforces:

- unique entity IDs;
- unique fact IDs;
- all subject/object/context references resolve;
- inferred entities and facts name their deriving rule;
- `accesses_before` connects data resources;
- its transaction context references a transaction;
- its code path references a code symbol/job.

These rules are deterministic and fail closed.

## Non-goals

v0 does not attempt to model:

- arbitrary source ASTs;
- a complete call graph;
- control-flow graphs;
- exact PostgreSQL row locks;
- runtime concurrency;
- actual deadlocks;
- all Rails callbacks/metaprogramming;
- a graph database;
- probabilistic causal inference.

## Next slice

The immediate next proof is:

```text
concrete_system_facts
  -> opposing access-order precondition

+
OTel/runtime
  -> both paths execute / overlap evidence

+
pgBot/PostgreSQL
  -> lock/wait/deadlock evidence

=
D2.2 epistemic projection
```

Only after this works should the fact vocabulary grow.

# Current product state

Status: Living projection

This document answers:

> What can Causcope actually do now, and what is still architecture or planned work?

It is descriptive rather than aspirational.

## Summary

Causcope is no longer only a troubleshooting ontology or a collection of empirical labs.

The repository contains a deterministic investigation substrate with:

```text
semantic knowledge
claims + empirical experiments
causal ranking
next-probe ranking
runtime evidence
persistent Investigation/scoping state
exact runtime relationships
resource topology
provider capability discovery
instrument routing
workspace provider bindings
safe read-only execution
revision-bound evidence acquisition
crash-recoverable evidence + diagnosis commits
bounded autonomous investigation
CLI / HTTP / MCP projections
Concrete System / X-Ray projections
Rails / OpenTelemetry / PostgreSQL / pgbot evidence paths
```

The current product direction remains:

> Agent First, not Agent Only.

The local product is the first execution surface. Dashboard, Cloud, Relay, Slack/PagerDuty-style integrations, Helm, and private deployment should project the same investigation contracts later.

## Strongest proofs

### Rails D3.1 confirmed causal proof

`RFC/0075-golden-vertical-slice-rails-connection-pool.md` is implemented.

The bounded live proof demonstrates:

```text
slow request
  -> revision-bound Rails system facts
  -> exact code symbol
  -> exact ActiveRecord pool
  -> measured checkout wait
  -> OpenTelemetry request identity
  -> independent PostgreSQL capacity control
  -> generic D3.1 X-Ray progression
  -> recovery evidence
  -> CAUSAL_DIAGNOSIS_CONFIRMED
```

Blast radius remains unknown unless a separate evidence source proves affected-user/request counts.

That is intentional: unknown evidence stays unknown.

### Generic local acquisition loop

The human-facing command:

```text
causcope why
```

can consume canonical diagnosis state, expose the next discriminator, resolve the exact operational target, route to a configured provider, and keep acquisition explicit:

```text
causcope why --acquire
```

The bounded acquisition loop is:

```text
diagnosis revision N
  -> ranked read-only probe
  -> exact target
  -> provider instance
  -> InstrumentRouter
  -> explicit authorization
  -> read-only evidence acquisition
  -> durable journal
  -> atomic evidence + diagnosis commit
  -> revision N + 1
  -> rerank
```

The path is proven with both captured `pgbot_file` evidence and live `pgbot_cli` execution.

`pgbot_cli` is deliberately constrained to:

```text
pgbot inspect --json
```

It is not a generic subprocess runner. The DSN is resolved only through a named environment variable and database identity is revalidated on every read.

### Rails/PostgreSQL system bootstrap

`RFC/0079-agent-first-rails-postgresql-bootstrap.md` is implemented.

```bash
causcope bootstrap . \
  --database app_production \
  --database-url-env CAUSCOPE_PRODUCTION_DATABASE_URL
```

creates:

```text
.causcope/concrete-system-facts.json
.causcope/resource-topology.yaml
.causcope/pgbot-postgresql.yaml
.causcope/provider-bindings.yaml
```

The command discovers system/configuration facts and provider routing only.

It does not manufacture runtime evidence or diagnosis.

Multi-database applications require explicit pool selection rather than guessing.

### Observed Rails incident bootstrap

`RFC/0080-observed-rails-incident-bootstrap.md` is implemented for the first bounded slice.

The product path is now:

```text
causcope bootstrap
  -> system knowledge + exact DB target + provider binding

causcope why "checkout is slow"
  -> create/resume Investigation

causcope runtime start
  -> bind OTLP receiver to the same Investigation

reproduce observed request
  -> concrete runtime facts
  -> exact request / trace / ActiveRecord pool interaction

causcope runtime seed
  -> runtime evidence revision 1
  -> runtime relationships
  -> diagnosis revision 1
  -> exact target
  -> next discriminator
```

The first seed requires explicit objectives:

```text
request latency threshold
pool checkout-wait threshold
```

and emits two observations from the same trace and scope:

```text
observation.http.request_latency
observation.database.connection_pool_wait_time
```

For the proven slice, the request-latency diagnosis ranks these empirically grounded alternatives:

```text
1. hypothesis.database.connection_pool_exhaustion
2. hypothesis.latency.database
```

and the existing deterministic probe ranker chooses:

```text
probe.database.measure_query_latency
```

as the next discriminator.

This is candidate ranking, not confirmed root cause.

The exact target path is preserved:

```text
request observation
  -> trace
  -> runtime used_resource relationship
  -> pool:active_record.primary
  -> explicit topology binding
  -> exact PostgreSQL resource
```

No provider is routed from natural-language similarity or from the assumption that the app has only one database.

## Current product front door

### No diagnostic evidence yet

```text
causcope why "something is wrong"
```

creates or resumes durable scoping state and asks the next unresolved question.

It does not invent a diagnosis from text.

### Diagnosis available

When `.causcope/diagnosis.json` exists, `why` projects:

```text
target
ranked hypotheses
supporting observations
contradictions
next probe
exact target resolution when proven
selected provider or explicit routing stop
```

The snapshot is identity-checked against the current Investigation.

### Explicit evidence acquisition

Plain `why` remains non-mutating with respect to live provider reads.

```text
causcope why --acquire
```

is the explicit boundary for one bounded evidence acquisition step.

Safety properties include:

```text
stale revision -> fail closed
route drift -> fail closed
provider drift -> fail closed
wrong target -> fail closed
cross-Investigation evidence -> fail closed
partial execution failure -> no partial canonical commit
no new canonical evidence -> fail closed
```

## Current CLI/product commands

Important implemented surfaces include:

```text
causcope bootstrap
causcope investigate
causcope next
causcope answer
causcope status
causcope report
causcope why
causcope why --acquire
causcope runtime start
causcope runtime seed
causcope rails install
causcope rails run
```

The same repository also contains HTTP/MCP and autonomous-agent machinery beneath these product projections.

## Semantic core

State: **implemented and actively expanding**

Includes:

- symptoms and mechanism domains;
- observations, hypotheses, probes and capabilities;
- predictions and falsifiers;
- claims and empirical experiments;
- causal graph;
- diagnostic catalog codes;
- runtime evidence schemas;
- deterministic causal ranking;
- deterministic probe ranking.

The knowledge base is not complete across every failure domain, but it is already sufficient for real product-shaped proofs.

## Evidence and providers

State: **implemented for several bounded paths**

Current adapters/providers include:

```text
OpenTelemetry
Prometheus
structured logs
Rails runtime evidence
pgbot/PostgreSQL
selected local read-only executors
```

Workspace pgbot bindings include:

```text
pgbot_file
pgbot_cli
```

Provider breadth is not the immediate goal. A complete causal loop is preferred over accumulating adapters without a concrete investigation use case.

## Agent integration

State: **substantial machinery implemented**

The repository already contains:

- MCP resources and tools;
- agent-plan projections;
- next-probe selection;
- safe read-only probe execution;
- provider capability discovery;
- exact target-aware routing;
- bounded autonomous investigation;
- multi-target execution sets;
- durable journals and cross-process claims;
- workflow recovery;
- verification machinery.

The remaining work is increasingly product consolidation and ergonomics rather than inventing an agent architecture.

## Dashboard

State: **planned, not yet implemented as the shared product surface described in `docs/`**

Dashboard remains important and should be an early second surface after the local agent path becomes coherent.

It must project canonical Investigation state instead of introducing another diagnosis model.

## Managed Cloud

State: **architecture documented, implementation intentionally deferred**

Relevant documents:

```text
docs/architecture/cloud-component-model.md
docs/architecture/deployment-model.md
```

Cloud is expected to provide managed ingestion, collaboration, orchestration, history, policy and enterprise integration surfaces around the same core.

The local product must not depend on Cloud for reasoning.

## Managed SaaS integrations

State: **planned product architecture**

Current priority set includes:

```text
GitHub App
PagerDuty
Sentry
Slack
Generic Webhook API

then:
Datadog
Teams
Telegram
```

These are signal, evidence, incident-system and communication adapters around the same Investigation core.

## Relay / enterprise deployment

State: **architecture documented, not yet productized**

Target forms include:

```text
same Causcope runtime in daemon/Relay role
Docker image
systemd
Helm chart
private/on-prem deployment later
```

Relay should remain a capability-constrained customer-side evidence plane, not a second reasoning implementation and not a remote arbitrary shell.

## Trust Manifest / Trust Diff

State: **directional architecture, not yet canonical machine-readable schema**

The model is documented in:

```text
docs/architecture/trust-access-blast-radius.md
```

The intended model covers:

```text
Principal
Credential
Capability
Action
Resource
Scope
Data
Boundary
Consequence
Control
```

with multidimensional blast radius, declared-vs-effective access, Trust Diff and access drift.

## Investigation vs Incident identity

State: **compatibility design proposed**

`RFC/0076-investigation-case-and-incident-compatibility.md` defines `Investigation` as the intended Causcope-owned case object while preserving current `incident_context` / `incident_id` storage during migration.

The current Rails runtime/bootstrap path still uses those compatibility identifiers.

No silent breaking rename has been authorized.

## RFC identity governance

State: **implemented guardrail, historical cleanup deferred**

`RFC/0077-rfc-identity-governance.md` plus:

```text
vocabulary/rfc-id-exceptions.yaml
scripts/validate_rfc_ids.py
```

prevent new unregistered RFC-number collisions while grandfathering known historical pairs.

## What is no longer the main gap

For the bounded Rails/PostgreSQL path, these links are now proven:

```text
system discovery
  -> topology/provider setup

observed request
  -> canonical revision-1 evidence
  -> ranked alternatives
  -> next discriminator
  -> exact target

exact target
  -> safe provider route
  -> explicit acquisition
  -> canonical evidence N + 1
  -> rerank
```

Therefore the immediate problem is no longer “how do we get into the investigation loop at all?”

## Immediate product gaps

The highest-value gaps are now ergonomic and breadth-related:

```text
1. reduce the number of commands needed to observe/reproduce/seed one local Investigation;
2. represent service objectives/baselines as explicit machine-readable configuration so thresholds do not always come from CLI flags;
3. connect the first observed revision more directly to `why` without weakening explicit authorization boundaries;
4. make the Rails D3.1 confirmed X-Ray proof and generic persisted Investigation path converge further;
5. add additional symptom/transport bootstrap paths only for concrete use cases;
6. keep Dashboard/Cloud/Relay contracts compatible while remaining secondary to the agent core.
```

A likely next UX progression is:

```text
causcope why "checkout is slow"
  -> knows configured objectives
  -> guides/starts bounded observation session
  -> receives runtime facts
  -> seeds revision 1 automatically when the evidence contract is satisfied
  -> presents alternatives + next discriminator
  -> asks for explicit acquisition authorization when a provider read is needed
```

The key constraint is that fewer commands must not mean weaker provenance or heuristic target guessing.

## Guardrail

A new abstraction should be treated skeptically unless it moves this path forward:

```text
problem
  -> scope
  -> observe
  -> evidence
  -> discriminate
  -> diagnose
  -> verify
```

Causcope currently needs product integration, ergonomics, additional proven knowledge coverage, and human surfaces more than additional conceptual layers.

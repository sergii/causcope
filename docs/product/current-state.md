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
workspace objectives
exact runtime relationships
resource topology
provider capability discovery
instrument routing
workspace provider bindings
safe read-only execution
revision-bound evidence acquisition
crash-recoverable evidence + diagnosis commits
bounded runtime observation orchestration
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

### Workspace objectives

`RFC/0081-workspace-incident-objectives.md` is implemented for the current bounded Rails/PostgreSQL incident bootstrap.

```bash
causcope objectives set . \
  --request-latency-ms 200 \
  --pool-wait-ms 50
```

persists explicit user-declared comparison boundaries in:

```text
.causcope/objectives.yaml
```

The current contract covers:

```text
observation.http.request_latency
observation.database.connection_pool_wait_time
```

Causcope does not invent numeric defaults and does not silently treat a single incident trace as a learned baseline.

### Observed Rails incident bootstrap

`RFC/0080-observed-rails-incident-bootstrap.md` is implemented for the first bounded slice.

The lower-level path is:

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

The first seed uses explicit request-latency and pool-wait objectives and emits two observations from the same trace and scope:

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

### Bounded runtime observation session

`RFC/0082-bounded-runtime-observation-session.md` is implemented for the first local orchestration slice.

The manual receiver/application/seed lifecycle can now be composed as:

```bash
causcope runtime observe . -- <bounded-application-command>
```

The command:

```text
validates workspace objectives before execution
starts the existing OTLP receiver
waits for receiver readiness
launches the command through the existing revision-bound Rails runtime wrapper
captures exact concrete runtime facts
stops the receiver
runs the existing incident seed
persists diagnosis revision 1
```

The first slice deliberately accepts only a command that exits on its own with status `0`.

Safety behavior is proven for:

```text
missing objectives -> application command not started
non-zero application exit -> no seed
no explicitly bound runtime facts -> no seed
standard seed exact-target constraints remain authoritative
```

This local explicit application-command surface is not a generic Cloud/Relay remote-execution capability.

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
causcope objectives set
causcope objectives show
causcope investigate
causcope next
causcope answer
causcope status
causcope report
causcope why
causcope why --acquire
causcope runtime start
causcope runtime seed
causcope runtime observe
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
- bounded local runtime observation orchestration;
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

The local `runtime observe -- <command>` UX must not be reused as a generic remote-shell transport.

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

workspace objectives
  -> explicit comparison boundaries

bounded local observation
  -> exact runtime facts
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

Therefore the immediate problem is no longer “how do we get into the investigation loop at all?” or “how do we coordinate receiver + bounded command + seed manually?”

## Immediate product gaps

The highest-value gaps are now:

```text
1. compose bounded observation directly from `causcope why` so the product front door can guide/launch it;
2. define interactive long-running Rails server observation only with explicit lifecycle and signal semantics;
3. converge the generic persisted Investigation path further with the confirmed D3.1 X-Ray proof;
4. support additional symptom bootstrap shapes only when backed by concrete empirical knowledge;
5. add runtime/provider targets only for concrete investigation use cases;
6. begin the shared Dashboard projection once the local Investigation UX is coherent enough to visualize;
7. keep Cloud/Relay contracts compatible while remaining secondary to the Agent First core.
```

A likely next UX progression is:

```text
causcope why "checkout is slow"
  -> knows configured objectives
  -> offers/launches bounded observation
  -> receives exact runtime facts
  -> seeds revision 1 through the existing contract
  -> presents alternatives + next discriminator
  -> asks for explicit acquisition authorization when a provider read is needed
```

The key constraint is that fewer commands must not mean weaker provenance, heuristic target guessing, or hidden execution authority.

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

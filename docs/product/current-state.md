# Current product state

Status: Living projection

This document answers:

> What can Causcope actually do now, and what is still architecture or planned work?

It is descriptive rather than aspirational.

## Summary

Causcope is no longer only a troubleshooting ontology or collection of empirical labs.

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

The product direction remains:

> Agent First, not Agent Only.

The local agent is the first execution surface. Dashboard, Cloud, Relay, Slack/PagerDuty-style integrations, Helm, and private deployment should project the same Investigation contracts later.

For the shortest description of the current local UX, see:

```text
docs/product/local-agent-flow.md
```

## Strongest proofs

### Rails D3.1 confirmed causal proof

`RFC/0075-golden-vertical-slice-rails-connection-pool.md` is implemented.

The live proof demonstrates:

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

Unknown evidence stays unknown.

### Generic local acquisition loop

The persisted Investigation path can expose the next discriminator, resolve the exact operational target, route to a configured provider, and keep provider acquisition explicit:

```bash
causcope why
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

`pgbot_cli` is constrained to:

```text
pgbot inspect --json
```

It is not a generic subprocess runner. The DSN is resolved through a named environment variable and database identity is revalidated on every read.

## Local Agent First product path

### System bootstrap

`RFC/0079-agent-first-rails-postgresql-bootstrap.md` is implemented.

```bash
causcope bootstrap . \
  --database app_production \
  --database-url-env CAUSCOPE_PRODUCTION_DATABASE_URL
```

creates the revision-bound system facts, resource topology, pgbot adapter, and provider binding.

It does not manufacture runtime evidence or diagnosis.

Multi-database applications require explicit pool selection rather than guessing.

### Workspace objectives

`RFC/0081-workspace-incident-objectives.md` is implemented for the current Rails/PostgreSQL slice.

```bash
causcope objectives set . \
  --request-latency-ms 200 \
  --pool-wait-ms 50
```

persists explicit `user_declared` comparison boundaries in:

```text
.causcope/objectives.yaml
```

The current contract covers:

```text
observation.http.request_latency
observation.database.connection_pool_wait_time
```

Causcope does not invent numeric defaults and does not silently treat one incident trace as a learned baseline or SLO.

### Observed incident bootstrap

`RFC/0080-observed-rails-incident-bootstrap.md` is implemented.

The lower-level path remains available:

```text
causcope runtime start
  -> exact concrete runtime facts

causcope runtime seed
  -> runtime evidence revision 1
  -> runtime relationships
  -> diagnosis revision 1
  -> exact target
  -> next discriminator
```

For the proven slow-request slice, the first diagnosis ranks:

```text
1. hypothesis.database.connection_pool_exhaustion
2. hypothesis.latency.database
```

and chooses:

```text
probe.database.measure_query_latency
```

as the next discriminator.

This is ordinal candidate ranking, not causal confirmation.

### Bounded observation primitive

`RFC/0082-bounded-runtime-observation-session.md` is implemented.

```bash
causcope runtime observe . -- <bounded-application-command>
```

composes:

```text
workspace-objective validation
  -> OTLP receiver lifecycle
  -> revision-bound Rails runtime wrapper
  -> explicit bounded application command
  -> exact runtime snapshot
  -> existing incident seed
  -> diagnosis revision 1
```

The application command must exit on its own with status `0` in the first slice.

Missing objectives, non-zero command exit, missing bound runtime facts, or failed exact-target resolution do not create a diagnosis.

### Product front door with observation

The bounded observation primitive is now composed directly from `causcope why`:

```bash
causcope why "checkout is slow" \
  --observe . \
  -- <bounded-application-command>
```

This is now a proven product path.

The wrapper:

```text
creates/resumes the Investigation
  -> defaults workspace to <rails-root>/.causcope when not supplied
  -> delegates to existing runtime observe
  -> persists the ordinary canonical evidence + diagnosis artifacts
  -> re-enters the normal causcope why renderer
```

It does not add a second reasoning engine or a new diagnosis format.

It does not auto-run provider evidence acquisition.

Observation and acquisition remain separate authorization boundaries:

```text
--observe
  -> explicit local bounded application command

--acquire
  -> explicit ranked read-only diagnostic provider operation
```

They cannot be combined in one invocation.

A second initial `--observe` is rejected if `diagnosis.json` already exists; the Investigation should then continue through normal `why` / `why --acquire` semantics.

## Exact-target invariant

The current Rails/PostgreSQL path preserves:

```text
request observation
  -> exact trace
  -> runtime used_resource relationship
  -> exact ActiveRecord pool
  -> explicit topology runtime binding
  -> exact PostgreSQL resource
  -> ranked probe
  -> eligible provider instance
```

No provider is routed from natural-language similarity or from the assumption that an application has only one database.

## Current product front door

The primary implemented surfaces now include:

```text
causcope bootstrap
causcope objectives set
causcope objectives show
causcope why "<problem>"
causcope why "<problem>" --observe <rails-root> -- <bounded-command>
causcope why
causcope why --acquire
```

Lower-level/debugging surfaces remain available:

```text
causcope investigate
causcope next
causcope answer
causcope status
causcope report
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

The knowledge base is not complete across every failure domain, but it is sufficient for real product-shaped proofs.

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

Provider breadth is not the immediate goal. Complete investigations are preferred over adding adapters without concrete use cases.

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

The remaining work is increasingly product consolidation, knowledge coverage, and ergonomics rather than inventing an agent architecture.

## Dashboard

State: **planned, not yet implemented as the shared product surface described in docs**

Dashboard remains an important early second surface now that the bounded local path is coherent enough to visualize.

It must project canonical Investigation state instead of introducing another diagnosis model.

## Managed Cloud

State: **architecture documented, implementation intentionally deferred**

Relevant documents:

```text
docs/architecture/cloud-component-model.md
docs/architecture/deployment-model.md
```

Cloud is expected to provide managed ingestion, collaboration, history, orchestration, policy, and enterprise integrations around the same core.

The local product must not depend on Cloud for reasoning.

## Managed SaaS integrations

State: **planned product architecture**

Priority set currently includes:

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

These are signal, evidence, incident-system, and communication adapters around the same Investigation core.

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

Relay remains a capability-constrained customer-side evidence plane, not a second reasoning implementation and not a remote arbitrary shell.

The local `runtime observe -- <command>` / `why --observe -- <command>` UX is explicitly **not** a precedent for generic Cloud or Relay remote command execution.

## Trust Manifest / Trust Diff

State: **directional architecture, not yet canonical machine-readable schema**

The model is documented in:

```text
docs/architecture/trust-access-blast-radius.md
```

It covers the direction for:

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

with multidimensional blast radius, declared-vs-effective access, Trust Diff, and access drift.

## Investigation vs Incident identity

State: **compatibility design proposed**

`RFC/0076-investigation-case-and-incident-compatibility.md` defines `Investigation` as the intended Causcope-owned case object while preserving current `incident_context` / `incident_id` storage during migration.

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

problem statement
  -> Investigation
  -> bounded observation
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

Therefore the immediate problem is no longer how to enter the investigation loop from the product front door.

## Immediate product gaps

The highest-value gaps are now:

```text
1. decide whether interactive long-running Rails observation is worth adding and define explicit lifecycle/signal semantics first;
2. converge the generic persisted Investigation path further with the confirmed D3.1 X-Ray proof;
3. support additional symptom bootstrap shapes only when backed by concrete empirical knowledge;
4. add runtime/provider targets only for concrete investigation use cases;
5. begin a read-only shared Dashboard projection of canonical Investigation state;
6. keep Cloud/Relay contracts compatible while remaining secondary to the Agent First core.
```

The important change is that Dashboard work can now begin as a **projection problem**, not as an excuse to invent another backend reasoning model.

## Guardrail

A new abstraction should be treated skeptically unless it advances this path:

```text
problem
  -> scope
  -> observe
  -> evidence
  -> discriminate
  -> diagnose
  -> verify
```

Causcope currently needs product ergonomics, broader empirical knowledge coverage, convergence of generic and confirmed diagnosis paths, and human/team projections more than additional conceptual layers.

# Current product state

Status: Living projection

This document maps the repository as it exists today to the agent-first product roadmap. It is intentionally descriptive rather than aspirational.

It should answer:

> What can Causcope actually do now, and what is still only architecture or planned work?

## Summary

Causcope is no longer only a troubleshooting ontology or a collection of empirical labs.

The repository already contains a deterministic investigation substrate with:

```text
semantic knowledge
runtime evidence
causal ranking
next-probe ranking
safe read-only execution
provider capability discovery
instrument routing
exact runtime target resolution
workspace provider bindings
revision-bound evidence acquisition
crash-recoverable evidence + diagnosis commit
MCP and HTTP projections
persistent investigation/scoping state
bounded autonomous investigation
Concrete System / X-Ray projections
Rails and PostgreSQL evidence providers
```

The strongest current product proof is the Rails D3.1 golden vertical slice.

A second product proof closes a generic local read-only loop through `causcope why --acquire`, and the first live process-backed provider path now executes `pgbot inspect --json` under a narrow binding contract.

## Proven product slice

`RFC/0075-golden-vertical-slice-rails-connection-pool.md` is an implemented proof.

The live CI path demonstrates:

```text
user-visible slow request
  -> revision-bound Rails scan
  -> exact Rails code symbol
  -> exact ActiveRecord pool
  -> real pool saturation
  -> measured checkout wait
  -> OpenTelemetry request identity
  -> independent PostgreSQL capacity control
  -> generic D3.1 X-Ray progression
  -> recovery evidence
  -> CAUSAL_DIAGNOSIS_CONFIRMED
  -> product-shaped human diagnosis
```

The bounded proof explicitly keeps blast radius unknown because it has no evidence source establishing affected-user/request counts.

That behavior is intentional and product-defining: unknown evidence remains unknown rather than being guessed.

## Product front door

The repository exposes:

```text
causcope why "checkout is slow"
```

as a thin product front door over existing investigation contracts.

### No diagnostic evidence yet

`causcope why` creates or resumes the same local investigation/scoping state used by the existing Investigator and presents the next unresolved scoping question.

It does not invent a root cause from the problem statement.

### Generic workspace diagnosis available

When the workspace contains:

```text
.causcope/diagnosis.json
```

`causcope why` consumes the existing canonical `diagnosis_snapshot` and exposes:

```text
target
leading hypothesis
supporting observations
contradictions
next ranked probe
selected instrument or explicit routing stop
```

It reuses the existing probe ranking and InstrumentRouter. It does not implement another diagnosis engine.

The diagnosis snapshot is identity-checked against the local investigation. A snapshot for another `incident_id` fails closed instead of being silently attached to the current case.

### Exact operational target resolution

When the workspace additionally contains:

```text
runtime-evidence.json
runtime-relationships.json
resource-topology.yaml
```

`causcope why` can reuse the existing runtime-target resolution contract:

```text
active observation
  -> exact trace
  -> runtime resolved relationship
  -> concrete runtime resource
  -> topology runtime binding
  -> exact operational target
```

For example:

```text
observation.database.query_latency
  -> trace-1
  -> pool:active_record.primary
  -> db.orders.prod
```

If the exact target cannot be proven, Causcope preserves the unresolved state rather than routing a target-specific provider heuristically.

### Workspace provider binding

`RFC/0078-workspace-provider-bindings.md` defines the workspace runtime binding contract:

```text
.causcope/provider-bindings.yaml
```

Implemented pgbot drivers are:

```text
pgbot_file
pgbot_cli
```

`pgbot_file` binds a topology-declared provider instance to an already-produced pgbot JSON report.

`pgbot_cli` is the first live process-backed binding. It is deliberately not a generic command runner. The executable shape is fixed to:

```text
pgbot inspect --json
```

The database URL is referenced by environment-variable name in the workspace and is supplied to the child only as `DATABASE_URL`; raw credentials are not stored in the binding or passed in command-line arguments.

Plain `causcope why` does not run the CLI. It may check that `pgbot` exists and the configured environment variable is present, but the database read occurs only after explicit acquisition authorization.

The deterministic routing path is:

```text
diagnosis
  -> ranked next probe
  -> exact operational target
  -> topology provider instance
  -> runtime provider binding
  -> InstrumentRouter
  -> selected safe instrument
```

A proven test resolves `pool:active_record.primary` to `db.orders.prod` and selects:

```text
provider.pgbot.orders-prod
```

for the canonical read-only query-latency probe.

Both pgbot bindings verify database identity. The identity check is repeated on every evidence read, so changing a report or receiving a live CLI result for the wrong database cannot be silently relabeled as evidence for the selected target.

The live CLI proof additionally verifies that a report-bearing pgbot exit code `2` is accepted, that the command shape remains exactly `pgbot inspect --json`, and that the configured DSN is not emitted by Causcope.

### Explicit evidence acquisition

Plain `causcope why` remains read-only.

The user must explicitly opt in to evidence acquisition:

```text
causcope why "database requests are slow" --acquire
```

`--acquire` does not add a second executor. It projects the current investigation through the existing target-aware execution-set machinery.

The current bounded product path is:

```text
current diagnosis revision N
  -> top-ranked read-only probe
  -> exact runtime target resolution
  -> configured provider instance
  -> current safe route
  -> one ready execution set
  -> explicit --acquire authorization
  -> revalidate incident + revision + route + provider
  -> execute read-only provider
  -> canonical evidence
  -> execution-set journal
  -> crash-recoverable evidence + diagnosis commit
  -> evidence revision N + 1
  -> one causal rerank
```

The product wrapper therefore inherits the existing execution safety properties:

```text
stale revision -> fail closed
route drift -> fail closed
provider drift -> fail closed
wrong target -> fail closed
provider evidence without exact target provenance -> fail closed
member failure -> no partial incident-state commit
no new canonical evidence -> fail closed
```

The first `why --acquire` product proof is intentionally bounded to exactly one ready execution set. If there are zero or multiple ready sets, the command stops instead of choosing implicitly.

The proof demonstrates:

```text
evidence revision 7
  -> exact db.orders.prod target
  -> provider.pgbot.orders-prod
  -> probe.database.measure_query_latency
  -> new pgbot-backed canonical evidence
  -> durable member_succeeded journal event
  -> one atomic Causcope state transition
  -> durable set_committed journal event
  -> evidence revision 8
  -> rerank_count = 1
```

The same proof now runs through both replayed `pgbot_file` evidence and a live `pgbot_cli` process boundary.

This means the generic local product can complete a real read-only investigation step from the same human-facing command instead of stopping at provider selection.

### Canonical Rails D3.1 artifacts available

The same command can still consume the bounded D3.1 proof inputs directly:

```text
Concrete System Facts
Concrete Runtime Facts
Resource-pool Runtime Evidence
```

and delegate to the already-proven Rails D3.1 product projection.

That specialized path can reach `CAUSAL_DIAGNOSIS_CONFIRMED` because it includes the stronger D3.1 causal verification contract.

Current product composition is therefore:

```text
causcope why
  -> investigation/scoping state
  OR
  -> generic diagnosis_snapshot
       -> probe ranking
       -> exact target resolution when available
       -> InstrumentRouter
       -> workspace provider bindings when configured
       -> explicit --acquire
       -> canonical evidence revision N + 1
       -> diagnosis rerank
  OR
  -> Rails D3.1 concrete proof
       -> generic X-Ray engine
       -> confirmed product diagnosis
```

## Roadmap mapping

### Semantic core

State: **implemented and actively expanding**

Includes:

- symptom/mechanism catalog;
- canonical semantic IDs;
- predictions and falsifiers;
- claims and empirical experiments;
- causal graph;
- diagnostic catalog codes;
- runtime evidence contracts;
- deterministic causal ranking.

This area is mature enough to support product proofs but not complete across all failure domains.

### Local Investigator

State: **implemented for scoping, diagnosis projection, routing, and bounded read-only acquisition**

Implemented:

```text
causcope investigate
causcope next
causcope answer
causcope status
causcope report
causcope why
causcope why --acquire
```

Scoping is durable under `.causcope/`.

`why` can consume generic diagnosis state, expose the next discriminating probe, resolve exact operational targets when the required runtime identity artifacts exist, select configured provider instances, and explicitly execute one current ready read-only execution set.

It still does not automatically create the initial diagnosis/evidence/topology state from only a natural-language problem statement.

### Agent integration

State: **substantial machinery implemented**

Existing repository work includes:

- MCP resources and tools;
- agent-plan projections;
- next-probe selection;
- safe read-only probe execution;
- bounded autonomous investigation;
- workflow recovery/journaling;
- provider capability discovery;
- instrument routing;
- exact target-aware routing;
- multi-target execution sets;
- durable execution-set journals;
- crash recovery for evidence acquisition.

The remaining work is product consolidation and ergonomic use of this machinery, not inventing agent support from scratch.

### Real local evidence providers

State: **implemented for several bounded paths**

Existing providers/adapters include:

- Prometheus;
- OpenTelemetry;
- pgbot/PostgreSQL;
- Rails repository/runtime evidence;
- structured logs;
- selected local probe executors.

Workspace provider bindings now support:

```text
pgbot_file - replay/captured deterministic reports
pgbot_cli  - live `pgbot inspect --json` with env-referenced DB credentials
```

Provider breadth is not the immediate goal. Complete product-shaped investigations are preferred over adding more adapters without a demonstrated use case.

### Dashboard

State: **not implemented as the shared product surface described in `docs/`**

The dashboard remains the next major human/team surface after the agent/local investigation loop is sufficiently coherent.

It must project canonical investigation state rather than introduce another diagnosis model.

### Managed Cloud

State: **architecture documented, implementation intentionally deferred**

Logical responsibilities are described in:

```text
docs/architecture/cloud-component-model.md
docs/architecture/deployment-model.md
```

There is no requirement for the current local product to depend on Causcope Cloud.

### Managed SaaS integrations

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

These are delivery, signal, evidence, and communication adapters around the same investigation core.

### Relay / enterprise deployment

State: **architecture documented, not yet productized**

Target forms include:

```text
same Causcope runtime in daemon/Relay role
Docker image
systemd
Helm chart
private/on-prem deployment later
```

The intended security model is capability-based, read-only first, customer-controlled credentials, outbound connectivity where possible, and no arbitrary remote shell.

### Trust Manifest / Trust Diff

State: **directional architecture, not yet canonical schema**

The model is documented under:

```text
docs/architecture/trust-access-blast-radius.md
```

It should become machine-readable only through a focused RFC/schema slice, not by treating the current prose example as a stable standard.

### Investigation vs Incident identity

State: **compatibility design proposed**

`RFC/0076-investigation-case-and-incident-compatibility.md` proposes `Investigation` as the Causcope-owned case object while preserving existing `incident_context`/`incident_id` data during migration.

No breaking storage rename has been authorized yet.

### RFC identity governance

State: **validator implemented, historical cleanup deferred**

`RFC/0077-rfc-identity-governance.md` defines the direction.

The repository contains:

```text
vocabulary/rfc-id-exceptions.yaml
scripts/validate_rfc_ids.py
```

and CI prevents new unregistered numeric collisions while grandfathering the known historical pairs.

## Immediate product gap

The previous two gaps are now closed for bounded local slices:

```text
safe target-aware provider route
  -> explicit canonical evidence acquisition
  -> reranked diagnosis

logical pgbot provider instance
  -> live process-backed read-only PostgreSQL evidence
```

The largest remaining product gap is **bootstrap and setup**, not the investigation loop itself.

Today Causcope can already do:

```text
current canonical diagnosis
  -> next discriminator
  -> exact operational target
  -> configured provider
  -> explicit safe acquisition
  -> new canonical evidence
  -> rerank
```

But a new user still has to prepare several artifacts before that loop can start:

```text
initial runtime evidence
initial diagnosis snapshot
runtime relationships
resource topology
provider bindings
```

The next product problem is therefore:

> How does `causcope why "something is wrong"` bootstrap enough concrete system context and initial evidence from an actual project/environment to enter the already-working loop?

For a local Rails/PostgreSQL slice, this should primarily reuse existing work:

```text
repository scan
portable Rails runtime
OTLP receiver
runtime relationship extraction
resource topology
configured pgbot/PostgreSQL provider
```

rather than invent another bootstrap engine.

Secret resolution beyond a local named environment variable also remains a deployment concern. Future Relay/cloud paths should map logical credential references to customer-controlled secret stores without changing the investigation semantics.

## Current priority

Near-term work should therefore favor:

```text
1. keep `causcope why` read-only by default and `--acquire` explicitly mutating investigation evidence;
2. bootstrap a local Rails/PostgreSQL workspace from the existing scan/runtime/provider machinery;
3. make the Rails D3.1 live proof reachable through the same persisted workspace path;
4. reduce the number of hand-created `.causcope/` artifacts needed before the first useful diagnosis;
5. add another provider transport only when bootstrap or a concrete investigation requires it;
6. keep Dashboard/Cloud architecture compatible but secondary.
```

## Guardrail

A new abstraction should be treated skeptically unless it is required to move this path forward:

```text
problem
  -> scope
  -> evidence
  -> discriminate
  -> diagnose
  -> verify
```

Causcope currently needs bootstrap, integration, and product consolidation more than additional conceptual layers.

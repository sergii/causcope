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
MCP and HTTP projections
persistent investigation/scoping state
bounded autonomous investigation
Concrete System / X-Ray projections
Rails and PostgreSQL evidence providers
```

The strongest current product proof is the Rails D3.1 golden vertical slice.

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

`RFC/0078-workspace-provider-bindings.md` adds the first small runtime binding contract:

```text
.causcope/provider-bindings.yaml
```

The first supported driver is `pgbot_file`, which binds a topology-declared provider instance to an already-produced pgbot report through the existing `PgbotAutonomousProbeProvider`.

This closes the current deterministic path:

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

Provider selection does not itself execute the provider. `why` reports the handoff while preserving the existing execution/authorization boundary.

The pgbot binding also verifies database identity. A pgbot report for a different database is rejected instead of being relabeled as evidence for the selected target.

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

State: **implemented for scoping and increasingly productized for diagnosis/routing**

Implemented:

```text
causcope investigate
causcope next
causcope answer
causcope status
causcope report
causcope why
```

Scoping is durable under `.causcope/`.

`why` can now consume generic diagnosis state, expose the next discriminating probe, resolve exact operational targets when the required runtime identity artifacts exist, and select configured provider instances through the existing router.

It does not yet automatically create all required evidence artifacts from only a natural-language problem statement.

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
- exact target-aware routing.

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

Workspace provider bindings currently support only the initial `pgbot_file` driver. Other provider transports should be added only as concrete product slices require them.

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

The largest remaining gap has moved again.

Causcope can now deterministically join:

```text
canonical diagnosis
  -> next probe
  -> exact operational target
  -> configured provider instance
```

The next gap is turning that safe routing decision into a coherent **evidence-acquisition/resume loop from the same user-facing command**, without weakening the existing execution policy.

Today, the repository already has safe read-only execution, autonomous loops, agent-plan state, and provider execution APIs. The work is to compose those existing contracts behind the product front door rather than create another executor.

The desired next progression is:

```text
causcope why
  -> investigation
  -> current diagnosis
  -> next discriminator
  -> exact target
  -> safe instrument
  -> explicit execution authorization
  -> new canonical evidence
  -> re-diagnosis
  -> verification or next discriminator
```

For external providers, future binding drivers also need practical secret/transport resolution without storing raw credentials in the workspace contract.

## Current priority

Near-term work should therefore favor:

```text
1. keep `causcope why` as the product-level projection;
2. reuse the existing safe execution/session machinery for the selected next probe;
3. compose returned evidence into the canonical workspace and re-run diagnosis;
4. add the next provider binding driver only when required by a real slice;
5. make the Rails D3.1 live proof reachable through the same persisted workspace path;
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

Causcope currently needs integration and product consolidation more than additional conceptual layers.

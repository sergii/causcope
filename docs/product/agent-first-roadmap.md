# Agent-first roadmap

Status: Product direction

## Objective

Sequence Causcope so that the unique investigation value is validated before investing heavily in cloud infrastructure, while preserving a clean path to dashboard, collaboration, managed integrations, and enterprise deployment.

The roadmap principle is:

> Agent first, not agent only.

## Current repository state

The phases below describe **product sequencing**, not a claim that all earlier phases are still unimplemented.

As of 2026-09-15 the repository already contains substantial machinery for the agent-first direction, including:

```text
runtime evidence
causal ranking
recommended next probes
safe read-only probe execution
MCP resources/tools
agent-plan projections
provider/capability discovery
autonomous bounded read-only investigation
investigation scoping/session state
Concrete System / X-Ray projections
Rails and PostgreSQL provider work
```

In particular, the accepted autonomous read-only investigation loop already reuses deterministic ranking and probe contracts rather than introducing another diagnosis engine.

The current product-shaped milestone is the in-progress golden Rails D3.1 connection-pool vertical slice, which deliberately pauses generic platform expansion to prove one end-to-end diagnosis from a user-visible problem to verified causal evidence.

Therefore the roadmap should increasingly ask:

> Which existing machinery needs to be connected, simplified, hardened, or projected into a coherent user experience?

rather than repeatedly inventing another generic subsystem.

## Phase 0 - Strengthen the semantic core

Continue expanding and validating the existing knowledge model through concrete vertical slices.

Focus areas:

- symptoms and failure mechanisms;
- predictions and falsifiers;
- deterministic probes;
- executable labs;
- runtime evidence;
- causal ranking;
- investigation dimensions;
- action risk and approval metadata;
- coverage reporting;
- human-learning projections from the same canonical knowledge.

The goal is not to model all failures top-down. The goal is to grow through tested mechanisms that improve real diagnosis.

## Phase 1 - Useful local Investigator

Make Causcope useful to one engineer without cloud.

Target experience:

```text
causcope investigate "checkout intermittently fails"
```

Causcope should:

1. scope the problem;
2. identify candidate mechanism families;
3. show what is known and unknown;
4. inspect available capabilities;
5. recommend the best next discriminating question or probe;
6. execute safe read-only probes where permitted;
7. ingest the resulting evidence;
8. update candidate hypotheses;
9. explain why the next action is useful;
10. produce a durable report.

First useful capabilities should prioritize common local development and debugging contexts:

```text
git.read
filesystem/logs.read
Docker inspect
PostgreSQL diagnostic read
Prometheus query
OpenTelemetry evidence
```

Much of the underlying machinery already exists. The product task is to converge it behind a coherent front door and prove complete vertical slices.

## Phase 2 - Agent integration

Expose the same Investigator cleanly to coding and operational agents.

Primary surface:

```text
MCP
```

Potential agent-facing operations:

```text
start investigation
read investigation state
get next question
record answer
list candidate hypotheses
list available capabilities
recommend next probe
execute approved read-only probe
record evidence
render diagnosis
```

The agent should not receive a giant unstructured troubleshooting book and be expected to reason from scratch. It should interact with explicit machine-readable state and deterministic operations.

Success criterion:

> An external agent can advance an investigation without reimplementing Causcope semantics.

This phase is already partially implemented and should be consolidated rather than restarted.

## Phase 3 - Real local probes and golden vertical demonstrations

Build several complete demonstrations where Causcope moves from symptom to discriminating evidence.

Recommended slices:

### PostgreSQL concurrency

```text
transaction failed / latency
  -> lock contention
  -> deadlock
  -> serialization failure
  -> connection pool exhaustion
```

### Network path

```text
connection failed / latency
  -> DNS
  -> refused/reset/timeout
  -> TLS verification/negotiation/mTLS
```

### Messaging

```text
missing/duplicate asynchronous effect
  -> redelivery
  -> ACK before durable effect
  -> duplicate publication
  -> poison message
```

These slices should prove that Causcope can reduce ambiguity rather than only describe failure modes.

The current golden slice is Rails + ActiveRecord D3.1 connection-pool exhaustion. Finish and simplify that user journey before broadening the surface again.

## Phase 4 - Dashboard

Build the first shared visual surface after the investigation engine is useful locally.

The dashboard is important and should not be deferred indefinitely.

Initial dashboard scope:

```text
investigation list
current status
scope / blast radius
observations and evidence
candidate hypotheses
ruled-out hypotheses
causal paths
next recommended probe
changes near onset
timeline
capabilities and denied probes
report/history
```

The dashboard must consume canonical investigation projections and must not introduce parallel reasoning logic.

The first dashboard may run locally or in a minimal hosted environment before a fully mature multi-tenant SaaS exists.

## Phase 5 - First managed cloud vertical slice

Introduce Causcope Cloud around the already-proven core.

Suggested first integration set:

```text
GitHub App
PagerDuty
Sentry
Slack
Generic Webhook API
```

End-to-end flow:

```text
PagerDuty incident
      |
      v
Causcope Investigation
      |
      +-> Sentry evidence
      +-> GitHub change context
      +-> canonical reasoning
      |
      v
Slack thread + Dashboard
```

This slice should work without private database or Kubernetes access.

## Phase 6 - Broader SaaS evidence and communication

Add high-value integrations such as:

```text
Datadog
Prometheus / OTel managed ingestion
Microsoft Teams
Telegram
BugSnag
additional incident systems
```

Goals:

- richer evidence;
- better change correlation;
- stronger team workflows;
- easier SMB onboarding;
- dogfooding in real incidents.

At this stage Causcope may also begin proactive investigations from selected detectors, while keeping incident creation policy separate:

```text
signal/anomaly
  -> Investigation
  -> evidence and impact assessment
  -> maybe formal incident
```

## Phase 7 - Customer-side daemon / Relay

Promote the same runtime into an enterprise-managed deployment role.

Expected packaging:

```text
Docker image
Helm chart
systemd/binary deployment
```

Primary requirements:

- outbound-only connection where possible;
- mutually authenticated control channel;
- declared capabilities;
- local policy;
- read-only collectors first;
- structured/minimized evidence;
- no arbitrary remote shell;
- local credentials remain customer-controlled;
- auditable probe execution.

First private evidence vertical should likely be PostgreSQL because the repository already has rich database failure semantics and pgbot can become one concrete adapter/tool.

Second likely vertical: Kubernetes.

## Phase 8 - Enterprise control plane

Add capabilities that large organizations expect:

```text
SSO/SAML
SCIM
RBAC
organization/service inventory
audit logs
retention controls
data residency
Relay fleet health
policy management
integration health
approval workflows
security export / Trust Manifest
```

This is also where SOC 2 and other assurance work becomes increasingly important for sales and procurement.

Architecture should support this phase early, but implementation should follow demonstrated product value.

## Phase 9 - Recommendations and controlled remediation

Only after read-only diagnosis is reliable:

```text
Observe
  -> Investigate
      -> Recommend
          -> Act with policy / approval
```

Examples:

- propose rollback;
- propose feature-flag disable;
- propose restart;
- propose scale adjustment;
- propose queue replay;
- propose DB remediation.

Mutation should be modeled separately from diagnostic access because the integrity and availability blast radius is substantially larger.

## Backlog themes

The roadmap should eventually become issue-level work under the following themes:

```text
CORE
  semantic coverage
  schemas
  causal reasoning
  probe ranking

INVESTIGATOR
  session state
  scoping
  reporting
  verification

AGENT
  MCP
  capability discovery
  safe execution
  agent UX

COLLECTORS
  PostgreSQL
  git/GitHub
  Docker
  logs
  Prometheus
  OTel
  Kubernetes

DASHBOARD
  investigation UI
  evidence graph
  timeline
  history

CLOUD
  tenancy
  auth
  persistence
  event ingestion
  orchestration

INTEGRATIONS
  PagerDuty
  Sentry
  GitHub
  Slack
  Datadog
  Teams
  Telegram

TRUST
  capability manifest
  Trust Manifest
  Trust Diff
  access drift
  audit

ENTERPRISE
  Helm
  Relay
  SSO/SCIM
  retention
  data residency
  private deployment

REMEDIATION
  approvals
  action policies
  rollback/restart/etc.
```

## Near-term allocation

Until the agent core proves useful on real debugging tasks, a reasonable allocation is:

```text
~80%  Knowledge + Investigator + Agent + real probes / golden slices
~20%  Cloud/dashboard/enterprise architecture and compatibility
~0%   heavy multi-tenant SaaS infrastructure unless required to validate a specific product slice
```

This is a sequencing heuristic, not a permanent organizational rule.

## Decision guardrails

Before implementing a cloud feature, ask:

1. Does it validate the investigation engine or only wrap it?
2. Can the same need be tested locally first?
3. Will it reuse canonical state and schemas?
4. Does it introduce a new trust boundary?
5. Can it be postponed without blocking diagnosis quality?

Before implementing a core feature, ask:

1. Does it reduce uncertainty in a real investigation?
2. Is the reasoning auditable?
3. Can it be tested through an executable lab or real evidence?
4. Can a human and an agent both consume it?
5. Does it avoid vendor lock-in at the semantic layer?
6. Does an equivalent generic abstraction already exist and merely need product integration?

## Product destination

The long-term product can include all of the following without contradicting the agent-first strategy:

```text
Causcope local agent
Causcope CLI
Causcope MCP server
Causcope Dashboard
Causcope Cloud
Causcope Slack/Teams apps
Causcope GitHub App
Causcope managed integrations
Causcope Relay
Causcope Helm chart
Causcope Docker image
Causcope private/on-prem deployment
```

They should be multiple ways to operate and distribute one investigation system, not separate products with separate truth models.

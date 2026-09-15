# Integration model

Status: Directional architecture

## Goal

Causcope should integrate with existing operational systems without requiring customers to replace them.

The integration model separates four roles that are often incorrectly collapsed into one "source of truth":

```text
Signal source
Incident system of record
Evidence provider
Communication surface
```

Causcope should be the system of record for **normalized investigation state, evidence references/provenance, hypotheses, causal reasoning, probe history, and diagnosis**.

Causcope is not automatically the authoritative source of the underlying raw fact. For example:

```text
CPU metric value                -> Datadog / Prometheus
Sentry error event              -> Sentry
PostgreSQL lock state           -> PostgreSQL
commit / PR                     -> GitHub
paging / acknowledgement state  -> PagerDuty
normalized investigation state  -> Causcope
```

This distinction prevents Causcope from pretending to replace source systems while still allowing it to own diagnosis.

## Operational roles

### Signal source

A system or human reports that something happened.

Examples:

- Datadog monitor;
- Prometheus/Alertmanager alert;
- Sentry issue/event;
- BugSnag error;
- CloudWatch alarm;
- Kubernetes event;
- synthetic monitor;
- customer report;
- engineer message;
- Causcope detector.

A signal does not automatically imply that a formal incident exists.

### Incident system of record

A system owns paging, acknowledgement, escalation, ownership, severity, and incident lifecycle.

Examples:

- PagerDuty;
- ServiceNow;
- Jira Service Management;
- Datadog Incident Management;
- other enterprise incident systems.

Causcope should normally integrate with the customer's existing incident authority rather than replace it initially.

### Evidence provider

A system can answer investigation questions or provide contextual observations.

Examples:

- GitHub;
- PostgreSQL;
- Kubernetes;
- Prometheus;
- OpenTelemetry;
- Datadog;
- Sentry;
- logs;
- deployment systems;
- pgbot;
- cloud APIs;
- local diagnostic tools.

An evidence provider may also be a signal source, but the roles are logically distinct.

### Communication surface

A place where humans receive updates or interact with Causcope.

Examples:

- Slack;
- Microsoft Teams;
- Telegram;
- Mattermost;
- Google Chat;
- Discord;
- email;
- dashboard;
- CLI/agent conversation.

Communication surfaces should not own canonical reasoning state.

## Trigger modes

An Investigation can begin in several ways. These modes should normalize into the same investigation contract rather than creating separate workflows.

```text
1. External incident
   PagerDuty / ServiceNow / JSM incident already exists

2. Observability or error signal
   Datadog / Prometheus / Sentry / BugSnag / CloudWatch

3. Human request
   CLI, dashboard, Slack/Teams/Telegram, coding agent

4. Infrastructure/runtime event
   Kubernetes, database, queue, host, deployment system

5. Causcope detector
   proactive anomaly or known-pattern detection
```

The trigger creates or updates an Investigation. It does not necessarily create a formal incident.

## Investigation vs incident promotion

Causcope needs an explicit policy boundary between investigation and incident lifecycle.

Examples:

```text
Sentry issue
  -> Causcope Investigation
  -> low blast radius
  -> no PagerDuty incident
```

```text
Causcope detector
  -> Investigation
  -> customer impact confirmed
  -> severity threshold crossed
  -> create or attach PagerDuty incident according to customer policy
```

```text
PagerDuty P1
  -> existing formal incident
  -> create/attach Causcope Investigation immediately
```

Promotion criteria may eventually include:

- customer impact;
- blast radius;
- severity;
- duration;
- service criticality;
- confidence/evidence quality where formally defined;
- customer policy;
- human approval requirements.

Causcope should not hard-code a universal rule that every anomaly or issue is an incident.

## Canonical investigation object

Causcope should model its own `Investigation` or equivalent case object rather than equating every signal with an incident.

Conceptually:

```text
Investigation CS-4821
  trigger
    Datadog monitor 934829

  external incidents
    PagerDuty P123ABC

  related signals
    Sentry issue 982347
    Kubernetes OOMKilled event
    PostgreSQL lock wait spike
    deploy sha a92e31f

  scope
  observations
  evidence
  hypotheses
  diagnosis
  timeline
  recommendations
  verification
```

An Investigation may exist without a formal incident, and a formal incident may trigger an Investigation.

## Signal, context, observation, and evidence

These concepts must remain distinct.

```text
Signal
  something reported or emitted

Context
  relevant surrounding information, not yet causal evidence

Observation
  concrete fact measured or reported about a scoped system

Evidence
  an observation interpreted in relation to a hypothesis or investigation question
```

Example:

```text
GitHub deploy at 13:37
```

is initially change context. It does not become evidence that the deploy caused the incident merely because the timestamps are close.

This preserves the existing Causcope rules:

```text
context != evidence
correlation != causality
difference != cause
```

## Canonical event normalization

Vendor events should be normalized before they influence reasoning.

Conceptual event kinds:

```text
alert
incident
error
anomaly
change
deployment
human_report
resolution
```

Illustrative envelope:

```json
{
  "source": "datadog",
  "external_id": "123456789",
  "kind": "alert",
  "status": "triggered",
  "severity": "critical",
  "service": "checkout-api",
  "environment": "production",
  "started_at": "...",
  "fingerprint": "...",
  "labels": {
    "region": "eu-west-1"
  },
  "links": [],
  "summary": "Elevated HTTP 5xx rate"
}
```

Vendor-specific payloads remain provenance. Canonical observations and investigation state remain vendor-neutral.

## Change events are first-class evidence context

Causcope should ingest changes as aggressively as failures.

Examples:

```text
deploy
commit
pull request
feature flag change
configuration change
Terraform apply
database migration
Kubernetes rollout
dependency version change
cloud resource change
```

A change is not automatically a cause. It is context that can become evidence only through additional support.

The reasoning model must preserve:

```text
correlation != causality
context != evidence
change near onset != root cause
```

## Initial integration priorities

### Agent-first / local priority

The first integrations should maximize investigation quality with minimal product infrastructure:

```text
Git / GitHub context
PostgreSQL
local logs
Docker
Prometheus / OpenTelemetry where available
MCP to coding agents
```

These validate the core reasoning loop.

### First managed-cloud priority

A useful first hosted integration set is:

```text
GitHub App
PagerDuty
Sentry
Slack
Generic Webhook API
```

Rationale:

```text
PagerDuty
  tells Causcope that an operational incident exists

Sentry
  provides concrete application failures

GitHub
  provides change and deploy context

Causcope
  correlates and investigates

Slack
  communicates with humans
```

### Next managed integrations

```text
Datadog
OpenTelemetry / Prometheus ingestion
Microsoft Teams
Telegram
BugSnag
Mattermost / Google Chat / Discord as demand justifies
```

Telegram has higher value for founders and SMB than its enterprise ranking suggests and is useful for dogfooding.

Slack and Microsoft Teams are expected to be higher-priority enterprise communication surfaces.

## Communication behavior

Use one Causcope application per communication platform rather than separate notification and conversational bots.

The same Slack app should support:

```text
Causcope -> humans
humans -> Causcope
```

Example flow:

```text
Causcope
Investigating elevated checkout errors.

Incident: PD-1842
Service: checkout-api
Environment: production

Collecting evidence from Sentry, GitHub and available runtime sources.
```

Then update the same investigation thread:

```text
Initial evidence
- 5xx isolated to checkout-api
- new Sentry issue started after deploy
- no matching traffic increase
```

Human:

```text
@Causcope what changed?
```

Causcope renders an answer from canonical investigation state.

The communication integration must not implement independent reasoning logic.

## Ranking and confidence presentation

Causcope should not present pseudo-precise probabilities such as `73%` unless the value is empirically calibrated against confirmed outcomes.

The current deterministic core is better represented through ordinal ranking and explicit factors:

```text
Leading hypothesis: database connection pool exhaustion
Supporting evidence: 4
Contradicting evidence: 1
Unknown discriminators: 2
Why ranked first: ...
```

A future qualitative or numeric confidence model may be added only after its semantics are explicit and testable. Product surfaces must not invent confidence labels independently of the core.

## Non-invasive adoption

Causcope should not require customers to remove existing operational paths.

Good adoption path:

```text
Datadog -> PagerDuty
       \-> Causcope

or

Datadog -> PagerDuty -> Causcope
```

Causcope can then publish investigation results back to:

```text
Slack
PagerDuty notes
Dashboard
```

If Causcope is unavailable, existing detection and paging should continue to work.

## Generic webhook

A generic webhook/event ingestion endpoint is high leverage because many tools can integrate without a dedicated adapter.

Conceptually:

```text
POST /v1/events
```

The endpoint should preserve original provenance while mapping payloads into canonical event/observation contracts.

Dedicated integrations remain valuable when they provide:

- authentication lifecycle;
- richer API reads;
- installation health;
- bidirectional updates;
- resource discovery;
- better normalization;
- permission introspection.

## Managed vs private evidence

Cloud-accessible providers:

```text
GitHub
PagerDuty
Sentry
Datadog
other SaaS APIs
```

usually do not require Causcope Relay.

Private providers:

```text
PostgreSQL
private Kubernetes
internal Prometheus
private logs
internal services
```

may require the local agent or Relay deployment role.

This distinction allows the hosted product to deliver useful investigation before requesting private-network access.

## Source-of-truth matrix

There is no single universal source of truth. Authority is per dimension.

Example:

```text
Raw telemetry              Datadog / Prometheus / source system
Application error event    Sentry / BugSnag
Runtime state               PostgreSQL / Kubernetes / source system
Detection                   Datadog or another detector
Paging / acknowledgement   PagerDuty
ITSM / compliance record   ServiceNow
Code/change history        GitHub
Investigation / diagnosis  Causcope
Conversation               Slack
```

Causcope should preserve external identifiers and synchronization state instead of attempting to own every operational lifecycle.

## Reactive to proactive evolution

The integration architecture should support gradual evolution without changing the Investigation model:

```text
Phase A
external incident -> Causcope investigation

Phase B
multiple external signals -> correlation -> investigation

Phase C
Causcope/local detectors -> proactive investigation -> maybe incident

Phase D
continuous causal understanding and safe recommendation
```

Detection is therefore an optional producer of investigations, not the definition of Causcope itself.

## Design rule

> Causcope does not need to own detection to own diagnosis.

This keeps the product focused and allows adoption alongside mature observability and incident-management stacks.

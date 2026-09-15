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

Causcope itself should be the system of record for **investigation state, evidence, hypotheses, causal reasoning, and diagnosis**.

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
- email;
- dashboard;
- CLI/agent conversation.

Communication surfaces should not own canonical reasoning state.

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
```

Telegram has higher value for founders and SMB than its enterprise ranking suggests and is useful for dogfooding.

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

## Confidence presentation

Avoid pseudo-precision such as `73%` unless confidence is empirically calibrated.

Prefer:

```text
Leading hypothesis: database connection pool exhaustion
Confidence: medium-high
Supporting evidence: 4
Contradicting evidence: 1
Unknowns: 2
```

The underlying model should expose why a hypothesis is ranked, not only a score.

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
Detection                 Datadog
Paging / acknowledgement  PagerDuty
ITSM / compliance record  ServiceNow
Code/change history       GitHub
Investigation / diagnosis Causcope
Conversation              Slack
```

Causcope should preserve external identifiers and synchronization state instead of attempting to own every operational lifecycle.

## Design rule

> Causcope does not need to own detection to own diagnosis.

This keeps the product focused and allows adoption alongside mature observability and incident-management stacks.

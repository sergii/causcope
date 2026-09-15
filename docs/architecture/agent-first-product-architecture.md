# Agent-first product architecture

Status: Directional architecture

## Thesis

Causcope is **agent first, not agent only**.

The first useful product is a deterministic investigation engine and machine-readable troubleshooting knowledge base that can run locally or near the system being investigated. It should help a human engineer or autonomous agent move from an observed symptom to discriminating evidence without requiring a Causcope SaaS account.

Cloud, dashboard, team collaboration, Slack/Teams, PagerDuty, Datadog, Sentry, managed history, and enterprise controls remain important product surfaces. They should reuse the same investigation contracts and reasoning engine rather than introducing a second diagnosis implementation.

## Product layers

```text
                         PRODUCT SURFACES

       CLI        MCP        IDE        Dashboard        Slack/Teams
        |          |          |             |                |
        +----------+----------+-------------+----------------+
                                   |
                                   v
                     Investigation API / Contracts
                                   |
                                   v
                     Causcope Investigation Engine
                                   |
                 +-----------------+-----------------+
                 |                                   |
                 v                                   v
          Semantic Knowledge                  Runtime Evidence
      symptoms / mechanisms /             observations / scope /
      hypotheses / predictions /           provenance / freshness
      probes / rules / claims
                 |                                   |
                 +-----------------+-----------------+
                                   |
                                   v
                         Capability Providers

       git   PostgreSQL   logs   Docker   Kubernetes   Prometheus
       OTel  Sentry       Datadog GitHub  PagerDuty    other tools
```

The semantic and investigation layers are the core. Product surfaces and evidence providers are replaceable adapters.

## Core responsibilities

### 1. Knowledge layer

The knowledge layer describes reusable troubleshooting semantics:

- symptoms;
- failure mechanisms;
- observations;
- hypotheses;
- predictions;
- probes;
- claims;
- experiments;
- rules;
- causal relationships;
- falsifiers;
- capabilities required to gather evidence;
- action risk and approval metadata.

The knowledge layer does not depend on a specific vendor, transport, dashboard, or LLM.

### 2. Investigation engine

The investigation engine owns the state machine:

```text
problem statement / signal
  -> scope the incident
  -> classify observations
  -> enumerate candidate mechanisms
  -> compare predictions with known evidence
  -> choose the best discriminating question or probe
  -> gather new evidence
  -> update hypothesis state
  -> repeat
  -> diagnosis / contributing factors
  -> mitigation recommendation
  -> verification
```

Known reasoning should be deterministic and auditable. An LLM may help with interpretation, mapping unknown inputs, summarization, and proposing uncovered hypotheses, but should not be required to rediscover encoded diagnostic logic.

### 3. Agent runtime

The agent runtime turns investigation decisions into safe interaction with a real environment.

Conceptually:

```text
causcope investigate
causcope diagnose
causcope next
causcope probe
causcope serve --mcp
causcope daemon
```

The exact implementation language is not fixed by this document, but a single distributable binary remains desirable for local, server, and customer-environment deployments.

The runtime should expose capabilities, not arbitrary command execution.

Example:

```text
available:
  git.read
  postgres.inspect_activity
  postgres.inspect_locks
  logs.read
  docker.inspect

unavailable:
  kubernetes.read
  postgres.write
  shell.arbitrary
```

The investigation engine chooses among known probes based on the capabilities actually available.

## Why agent first

Agent-first provides the shortest route to validating the unique Causcope value:

> Can encoded troubleshooting knowledge reliably reduce uncertainty and choose the next useful diagnostic action?

A local agent can validate this against Docker, PostgreSQL, Rails, logs, git history, and reproducible labs without first building:

- multi-tenant SaaS;
- OAuth installation flows;
- enterprise billing;
- SOC 2 program infrastructure;
- team dashboards;
- PagerDuty incident synchronization;
- Slack threading;
- customer VPC networking.

If the investigation loop is weak, those integrations do not create product value. If the loop is strong, those integrations become delivery and evidence channels around an already useful engine.

## Agent first does not mean CLI only

The product should not assume that every user will remain in a terminal.

Expected surfaces include:

```text
today / first
  CLI
  MCP
  local agent
  IDE / coding-agent integration

next
  dashboard
  investigation history
  shared evidence and timelines
  Slack / Teams
  PagerDuty / incident systems

later
  managed cloud
  hybrid enterprise relay
  private deployment
  approval workflows
  controlled remediation
```

A dashboard is still a first-class product surface because teams need shared state, history, auditability, navigation, comparisons, configuration, and trust controls. The decision is sequencing, not rejection of dashboards.

## Same core everywhere

A central architecture rule is:

> No product surface may invent a separate investigation model.

The same semantic IDs, evidence contracts, investigation session, causal ranking, probe definitions, and capability declarations should be reused by:

```text
CLI
MCP
HTTP API
agent harness
dashboard
Slack/Teams
PagerDuty annotations
Causcope Cloud
customer-side Relay
```

A cloud deployment should create and advance the same investigation state that a local CLI would.

## Relay is a deployment role, not a second brain

Enterprise customers may require investigation code to run inside their network or Kubernetes cluster. In that case the local runtime can operate in a managed daemon role called **Causcope Relay**.

```text
Causcope Cloud
     |
     | approved investigation request
     v
Causcope Relay
inside customer environment
     |
     +-> PostgreSQL read-only collector
     +-> Kubernetes read-only collector
     +-> internal metrics/logs
     +-> local tools such as pgbot
     |
     v
structured evidence
     |
     v
Causcope Cloud
```

Where practical, Relay should reuse the same binary, schemas, collector protocol, and capability system as the local agent.

The Relay should not accept arbitrary shell generated by cloud AI. It should execute versioned, declared, policy-approved collectors and return structured evidence.

## Cloud responsibilities

Causcope Cloud is expected to add capabilities that are valuable for organizations but unnecessary for the first local investigation product:

- persistent investigation history;
- multi-user collaboration;
- dashboard and visualization;
- organization/service topology;
- managed integrations;
- event/webhook ingestion;
- incident correlation;
- notifications;
- Slack/Teams interaction;
- PagerDuty/ServiceNow/JSM synchronization;
- audit logs;
- policy management;
- Relay fleet management;
- SSO/SCIM and enterprise identity;
- retention and data-residency controls;
- fleet and integration health;
- future approval/remediation workflows.

Cloud should orchestrate the core, not replace it.

## Read before write

The product progression should preserve a strict distinction:

```text
Observe
  -> Investigate
      -> Recommend
          -> Act
```

The first product should optimize for read-only evidence gathering and diagnosis. Mutation and remediation introduce substantially larger security, availability, and compliance blast radius and should arrive only with explicit policy and approval semantics.

## Product test

A feature belongs in the core if it remains useful when all hosted integrations are removed.

Examples that belong in the core:

- symptom/mechanism ontology;
- evidence contracts;
- causal graph;
- hypothesis ranking;
- next-probe selection;
- incident scoping;
- capabilities;
- action risk model;
- investigation state.

Examples that normally belong above the core:

- Slack rendering;
- PagerDuty webhook handling;
- Sentry OAuth;
- dashboard navigation;
- team membership;
- billing;
- Relay fleet orchestration.

## Current strategic decision

For the near term:

- implementation effort should prioritize Knowledge + Investigator + Agent + real probes;
- cloud architecture should be documented and kept compatible, but not become a prerequisite for core progress;
- dashboard should follow a demonstrably useful investigation engine and should visualize the same canonical state;
- enterprise deployment constraints should shape capability and trust contracts now, even if enterprise distribution is implemented later.

# Cloud component model

Status: Directional architecture, not an implementation priority

## Purpose

Record the expected managed-cloud component boundaries so the agent-first core can evolve without accidentally making future Cloud, Dashboard, or Relay integration impossible.

This document does not imply that these services should be implemented now.

## High-level model

```text
External systems
PagerDuty / Sentry / Datadog / GitHub / Webhooks
                    |
                    v
             Ingress Gateway
                    |
                    v
          Provider Adapters
                    |
                    v
               Normalizer
                    |
                    v
          Canonical Event Stream
                    |
          +---------+---------+
          |                   |
          v                   v
   Correlation Layer     Investigation Store
          |                   |
          +---------+---------+
                    |
                    v
        Investigation Orchestrator
                    |
                    v
          Causcope Core / Engine
                    |
        +-----------+-----------+
        |                       |
        v                       v
Evidence / Capability      Output Adapters
Routing                    Slack / Teams /
        |                  PagerDuty / UI
        v
Local Agent / Relay
        |
PostgreSQL / Kubernetes / internal systems
```

The exact process/service decomposition may change. The logical responsibilities should remain distinct.

## Components

### Ingress Gateway

Responsibilities:

- receive provider webhooks/events;
- authenticate the sender;
- enforce payload and rate limits;
- preserve raw provider provenance;
- provide idempotency/deduplication boundaries;
- hand off without embedding diagnostic reasoning.

### Provider Adapters

Responsibilities:

- understand vendor-specific identities and payloads;
- map provider concepts into canonical events;
- perform provider-specific API reads when authorized;
- expose integration health and permission information.

Examples:

```text
PagerDuty adapter
Sentry adapter
GitHub App adapter
Datadog adapter
Generic webhook adapter
```

### Normalizer

Responsibilities:

- convert vendor events into canonical Causcope event/observation contracts;
- preserve original IDs and source provenance;
- normalize service, environment, region, time, status and event kind where possible;
- reject ambiguous transformations rather than silently fabricating semantics.

### Correlation Layer

Responsibilities:

- associate signals with an existing Investigation when justified;
- identify probable duplicates;
- correlate service/time/scope/change context;
- never promote time correlation alone to causality.

Correlation feeds investigation. It does not replace the causal reasoning engine.

### Investigation Store

Responsibilities:

- canonical Investigation identity;
- external incident links;
- scope/context;
- observations/evidence references;
- hypotheses and ranking snapshots;
- probe history;
- timeline;
- verification state;
- audit/provenance metadata.

The storage implementation must preserve the same logical contracts used by local `.causcope/` state.

### Investigation Orchestrator

Responsibilities:

- create or resume an Investigation;
- request the next reasoning step from the core;
- determine which evidence capability can satisfy a requested probe;
- coordinate asynchronous provider/API reads;
- request approved Relay collectors;
- persist resulting evidence;
- advance the same state machine used locally.

The orchestrator is not an LLM agent that invents a parallel diagnosis process.

### Causcope Core / Investigation Engine

Responsibilities remain transport-independent:

```text
semantic lookup
candidate mechanism selection
prediction/falsifier evaluation
causal ranking
next-probe selection
risk/action metadata
verification semantics
```

Cloud should call the core rather than reimplement it.

### Evidence / Capability Router

Responsibilities:

- maintain available evidence providers and capabilities for an Investigation scope;
- select an authorized provider for a known probe;
- distinguish managed SaaS evidence from private Relay evidence;
- enforce customer policy before execution;
- record which capability/provider actually produced the result.

Example:

```text
probe: postgres.inspect_locks

possible providers:
  local causcope runtime
  enterprise Relay
  approved pgbot adapter

not satisfied by:
  arbitrary cloud SQL execution
```

### Relay Control Channel

Responsibilities:

- mutually authenticate Cloud and customer runtime;
- receive structured approved probe requests;
- expose advertised capabilities and health;
- return structured evidence;
- preserve local-policy denial as a valid result;
- avoid customer inbound firewall requirements where possible.

The Relay must not expose arbitrary remote shell semantics.

### Output / Communication Adapters

Responsibilities:

- project canonical Investigation state into Slack/Teams/Telegram/dashboard/incident notes;
- accept supported human interaction and translate it into canonical investigation commands;
- avoid maintaining a separate state machine per channel.

### Dashboard API

Responsibilities:

- expose investigation projections;
- evidence/causal graph views;
- timeline/history;
- capability/trust state;
- configuration and policy surfaces;
- team/organization views.

The dashboard remains a projection over canonical state, not the owner of diagnosis logic.

## Incident lifecycle boundary

Cloud may receive a formal incident or may start with a weaker signal.

```text
signal
  -> Investigation
  -> evidence / impact assessment
  -> policy decision
  -> optionally create/attach formal incident
```

Incident creation and escalation policy should be separate from causal reasoning.

## Failure isolation

Causcope should be adoptable without becoming part of the customer's critical paging path.

For example:

```text
Datadog -> PagerDuty
       \-> Causcope
```

or:

```text
Datadog -> PagerDuty -> Causcope
```

If Causcope Cloud is unavailable, existing monitoring and paging should continue.

## Implementation sequencing

Do not decompose these logical responsibilities into many microservices prematurely.

A first Cloud implementation may be a modular monolith containing several of these modules.

Split deployment units only when justified by scaling, security, ownership, or lifecycle boundaries.

# RFC 0040: Resource topology and provider instances

- Status: Proposed
- Date: 2026-09-15

## Summary

Causcope already separates three concerns:

```text
causal reasoning
  -> semantic probe ranking
  -> instrument routing
```

RFC 0037 introduced pgbot as a specialized PostgreSQL diagnostic provider. RFC 0038 added provider capability discovery. RFC 0039 added deterministic routing between canonical probes and concrete instruments.

The next production boundary is target identity.

A real system does not have one generic `postgresql` dependency. It may have many PostgreSQL clusters, databases, replicas, regions, services, observability backends, and execution locations. A diagnostic instrument must therefore be bound to an explicit resource target before its evidence may enter a scoped diagnosis.

This RFC introduces:

```text
Resource Registry
    +
Dependency Topology
    +
Provider Type
    +
Provider Instance
    +
Execution Location / Runner
    +
Target Binding
```

The central rule is:

> Causcope reasons about semantic resources and observations. Providers and runners are execution details bound to explicit targets.

## Motivation

The current pgbot provider shape is intentionally narrow:

```yaml
id: provider.pgbot.postgresql
scope:
  attributes:
    service: checkout-api
    dependency: postgresql
```

That is sufficient for a single integration proof, but it is not sufficient for production systems such as:

```text
checkout-api -> orders-db
checkout-api -> payments-db
users-api    -> users-db
inventory    -> inventory-db
```

or:

```text
postgres-cluster-a
postgres-cluster-b
postgres-cluster-c
```

Without explicit target identity, Causcope cannot safely answer:

```text
Which PostgreSQL instance should pgbot inspect?
Which Prometheus endpoint contains metrics for this service?
Which Sumo Logic dataset should be searched?
Which runner has network reachability to the resource?
Does this evidence belong to the currently diagnosed dependency?
```

String labels such as `dependency=postgresql` are not enough.

## Decision

Introduce a first-class resource topology model and make provider instances target-bound.

The conceptual pipeline becomes:

```text
incident symptom
      |
      v
causal diagnosis
      |
      v
semantic probe ranking
      |
      v
resource topology resolution
      |
      v
instrument router
      |
      v
provider instance + runner + target
      |
      v
read-only execution
      |
      v
canonical runtime_evidence
      |
      v
causal re-ranking
```

Topology resolution does not modify causal ranking. It determines where a ranked probe may be executed safely and meaningfully.

## Resource identity

Each diagnosable infrastructure or application target has a stable semantic resource ID.

Example:

```yaml
resources:
  - id: service.checkout.prod
    kind: application_service
    environment: production
    attributes:
      name: checkout-api

  - id: db.orders.prod
    kind: postgresql_database
    environment: production
    attributes:
      cluster: pg-orders-prod
      database: orders
      region: eu-central-1

  - id: db.payments.prod
    kind: postgresql_database
    environment: production
    attributes:
      cluster: pg-payments-prod
      database: payments
      region: eu-central-1
```

Stable resource identity is semantic. Credentials, DSNs, API tokens, private IPs, and other secrets MUST NOT be part of the resource ID.

## Dependency topology

Relationships between resources are explicit edges.

Example:

```yaml
relationships:
  - from: service.checkout.prod
    relation: depends_on
    to: db.orders.prod

  - from: service.checkout.prod
    relation: depends_on
    to: db.payments.prod
```

The topology answers questions such as:

```text
Which resources can plausibly participate in this incident scope?
Which dependency does a selected database probe refer to?
Which telemetry backend covers this service or resource?
Which runner can reach that target?
```

Topology is execution context, not causal proof. A `depends_on` edge means the resource is in scope for investigation, not that it caused the incident.

## Provider type versus provider instance

A provider type describes an instrument implementation and its semantic capabilities.

Example:

```text
provider_type.pgbot.postgresql
provider_type.prometheus
provider_type.sumologic
provider_type.tempo
```

A provider instance is a configured, target-bound deployment of that provider type.

Example:

```yaml
id: provider.pgbot.orders-prod
type: provider_type.pgbot.postgresql
target: db.orders.prod
runner: runner.eu-central-1.prod
```

and:

```yaml
id: provider.pgbot.payments-prod
type: provider_type.pgbot.postgresql
target: db.payments.prod
runner: runner.eu-central-1.prod
```

Provider type answers:

```text
What can this instrument know or measure?
```

Provider instance answers:

```text
Which concrete target can this configured instrument inspect from this execution location?
```

## pgbot multi-PostgreSQL model

pgbot is treated as a read-only diagnostic client, not a distributed daemon and not a source of global Causcope state.

For multiple PostgreSQL targets:

```text
Causcope
   |
   v
Instrument Router
   |
   v
pgbot provider type
   |
   +-> provider.pgbot.orders-prod   -> db.orders.prod
   +-> provider.pgbot.payments-prod -> db.payments.prod
   +-> provider.pgbot.users-prod     -> db.users.prod
```

There is no pgbot-to-pgbot synchronization requirement.

Each execution is bound to exactly one explicit PostgreSQL target unless the provider contract explicitly supports a broader cluster-level target.

Causcope synchronizes and owns:

```text
resource identity
incident identity
scope
probe identity
provider provenance
observation identity
evidence revision
time
```

It does not synchronize pgbot processes.

## Execution location / runner

Providers may require network-local execution.

Introduce an execution location abstraction:

```yaml
id: runner.eu-central-1.prod
kind: edge_runner
capabilities:
  - outbound_postgresql
  - https
network_domains:
  - vpc.prod.eu-central-1
```

A runner is responsible for executing approved read-only instruments in an environment where the target is reachable.

Conceptually:

```text
                    Causcope control plane
                            |
              +-------------+-------------+
              |                           |
      runner.eu-central-1          runner.us-east-1
              |                           |
         +----+----+                 +----+----+
         |         |                 |         |
       PG-A      PG-B              PG-C      PG-D
```

The runner is not a second reasoning engine. It does not rank hypotheses and does not decide what probe to perform. It executes an already selected, policy-approved diagnostic action and returns evidence plus provenance.

## Target binding

A routing candidate is eligible only when all required bindings are explicit.

For a direct provider:

```text
canonical probe is read_only
AND provider type advertises the probe
AND provider instance targets the selected resource
AND provider instance is available
AND runner is available when required
AND runner can reach the target
AND semantic diagnosis scope is compatible with the resource
```

No heuristic relabeling is allowed.

Evidence collected from `db.orders.prod` must not silently become evidence for `db.payments.prod` merely because both are PostgreSQL.

## Resource-scoped diagnosis

Scopes should evolve from coarse string labels toward stable resource references.

Instead of only:

```yaml
attributes:
  service: checkout-api
  dependency: postgresql
```

prefer a shape conceptually equivalent to:

```yaml
subjects:
  - service.checkout.prod
  - db.orders.prod
boundaries:
  - boundary.application.external_dependency
```

Human-readable attributes may remain as projections, but machine routing should rely on stable identities.

This RFC does not require immediate replacement of the existing scope contract. A compatibility layer may project stable resource IDs into the current normalized scope until a dedicated scope schema revision is introduced.

## Provider discovery

RFC 0038 capability discovery remains valid but should be split conceptually into two layers:

```text
provider type capabilities
  -> semantic capabilities shared by all instances

provider instance capabilities
  -> target binding
  -> runner binding
  -> current availability
  -> reachability
  -> credential readiness
```

Example:

```yaml
provider_type:
  id: provider_type.pgbot.postgresql
  probes:
    - probe.database.inspect_lock_waits
    - probe.database.measure_query_latency

provider_instance:
  id: provider.pgbot.orders-prod
  type: provider_type.pgbot.postgresql
  target: db.orders.prod
  runner: runner.eu-central-1.prod
  availability:
    state: available
```

## Logs, metrics, traces, and direct probes

This topology model is deliberately provider-neutral.

Examples:

```text
probe.http.measure_error_rate
  -> provider.prometheus.prod
  -> target service.checkout.prod

probe.application.find_error_events
  -> provider.sumologic.prod
  -> target service.checkout.prod

probe.request.inspect_trace
  -> provider.tempo.prod
  -> target service.checkout.prod

probe.database.inspect_lock_waits
  -> provider.pgbot.orders-prod
  -> target db.orders.prod
```

Causcope therefore does not need a generic `read_logs()` abstraction.

The semantic abstraction remains:

```text
probe -> observation
```

while provider adapters own the backend-specific operation:

```text
PromQL
Sumo query
Loki query
trace lookup
SQL/catalog inspection
local file read
journald query
```

## OpenTelemetry

OpenTelemetry should initially be treated as telemetry transport/instrumentation rather than as one universal query backend.

Typical flow:

```text
application
   -> OTLP
   -> OpenTelemetry Collector
   -> Prometheus / Tempo / Loki / vendor backend
```

Causcope normally queries the actual backend through its provider.

A future OTel Collector exporter may push selected observations into Causcope evidence ingress, but that is a different transport mode and is not required by this RFC.

## Evidence ownership

External instruments may maintain local caches or history, but Causcope owns the diagnostic evidence timeline.

For pgbot, local history or baseline state may be used as an input signal, but it is not the distributed source of truth for Causcope.

The durable model is:

```text
instrument current result
      |
      v
adapter normalization
      |
      v
runtime_evidence
      |
      +-> incident history
      +-> evidence revisions
      +-> temporal correlation
      +-> causal re-ranking
```

This keeps external instruments replaceable and prevents Causcope correctness from depending on local instrument state synchronization.

## Secret handling

Resource topology contains identities and non-secret metadata only.

Secrets are resolved at execution time by the runner or provider transport.

Forbidden in topology records:

```text
plaintext database passwords
API tokens
private keys
full secret-bearing DSNs
```

Provider instances may reference an opaque credential binding, for example:

```yaml
credentials_ref: secret.postgresql.orders-prod.readonly
```

The secret backend and secret transport remain outside the causal model.

## Failure semantics

Routing must distinguish at least:

```text
resource_unknown
resource_not_in_scope
provider_type_missing
provider_instance_missing
provider_unavailable
runner_unavailable
target_unreachable
credentials_unavailable
scope_mismatch
no_safe_available_instrument
```

These are execution-planning failures, not falsifying evidence.

For example:

```text
pgbot cannot connect to db.orders.prod
```

must not become:

```text
lock contention absent
```

It is insufficient evidence with explicit execution provenance.

## Discovery sources

The resource registry may eventually be populated from multiple sources:

```text
static configuration
Kubernetes API
cloud provider APIs
Terraform state / plan projections
service catalog
OpenTelemetry resource attributes
runtime discovery
operator input
```

This RFC does not choose one authoritative discovery mechanism.

The first implementation should prefer explicit deterministic configuration and strict validation. Automatic discovery may be layered on later while preserving stable resource identity.

## Minimal implementation slice

The first implementation should remain deliberately small.

Add:

```text
schema/resource-topology.schema.json
examples/topology/shop.yaml
scripts/resource_topology.py
```

with support for:

1. resource records with stable IDs and kinds;
2. explicit `depends_on` relationships;
3. runner records;
4. provider type and provider instance records;
5. exact provider-instance target binding;
6. lookup of provider instances for one target resource;
7. validation of missing or duplicate IDs;
8. validation that all topology references resolve;
9. deterministic serialization and ordering.

Then extend `instrument_router` so a ranked probe may be routed with:

```text
probe + diagnosis scope + target resource
```

rather than only:

```text
probe + diagnosis scope
```

## First end-to-end proof

Extend the existing shop scenario to contain two PostgreSQL dependencies:

```text
checkout-api
   +-> orders-db
   +-> payments-db
```

Create a lock-contention incident only on `orders-db`.

The proof must demonstrate:

```text
request failure symptom
  -> competing hypotheses
  -> database lock-wait probe selected
  -> topology resolves orders-db as the investigated target
  -> router selects provider.pgbot.orders-prod
  -> pgbot inspects only orders-db
  -> lock-wait observation is bound to db.orders.prod
  -> evidence cannot affect db.payments.prod scope
  -> lock-contention hypothesis for orders-db re-ranks first
```

A negative safety assertion should prove that the payments provider result cannot be substituted or relabeled into the orders scope.

## Non-goals

This RFC does not add:

- automatic infrastructure discovery;
- dynamic plugin installation;
- write/remediation operations;
- distributed pgbot synchronization;
- provider preference learning;
- automatic credential distribution;
- a new causal scoring policy;
- broad heuristic scope inheritance;
- a universal telemetry query language;
- mandatory OpenTelemetry adoption.

## Consequences

Causcope becomes able to distinguish:

```text
What should I learn?
    -> semantic probe ranking

Which real resource should I inspect?
    -> resource topology

Which configured instrument can inspect it?
    -> provider instance discovery

Where can that instrument safely run?
    -> runner binding

What did the instrument observe?
    -> canonical runtime_evidence

What does that observation imply?
    -> causal re-ranking
```

This is the missing boundary between the current single-target integration and a real distributed production environment.

## Follow-up work

After this RFC is implemented, the next high-value provider slices are:

1. Prometheus metrics provider;
2. one log-search provider such as Sumo Logic or Loki;
3. one trace provider such as Tempo;
4. Kubernetes diagnostic provider;
5. automatic topology enrichment from OpenTelemetry resource attributes or Kubernetes metadata.

These providers should reuse the same resource, provider-instance, runner, target-binding, and evidence contracts rather than inventing provider-specific routing models.

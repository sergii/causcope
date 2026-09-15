# Bootstrap product state

Status: Implemented initial system-bootstrap slice

This document is the product projection of `RFC/0079-agent-first-rails-postgresql-bootstrap.md`.

## Product boundary

Causcope now distinguishes two different bootstrap problems:

```text
system bootstrap
  -> what exists?
  -> what exact resources are known?
  -> which safe evidence providers can inspect them?

incident bootstrap
  -> what was actually observed for this Investigation?
  -> which runtime identity connects the symptom to an exact resource?
  -> what evidence is sufficient to create the first diagnosis snapshot?
```

The first problem is implemented for a bounded Rails/PostgreSQL local-agent slice.

The second remains the next product-integration step.

## Implemented command

```bash
causcope bootstrap ./my-rails-app \
  --database app_production \
  --database-url-env CAUSCOPE_PRODUCTION_DATABASE_URL
```

The command reuses the existing Rails scanner and writes:

```text
.causcope/
  concrete-system-facts.json
  resource-topology.yaml
  pgbot-postgresql.yaml
  provider-bindings.yaml
```

It does not query PostgreSQL and does not create runtime evidence or diagnosis.

## Generated path

The deterministic setup path is:

```text
Rails repository
  -> revision-bound concrete system facts
  -> selected ActiveRecord PostgreSQL pool
  -> explicit pool -> PostgreSQL target runtime binding
  -> local runner
  -> exact pgbot provider instance
  -> pgbot_cli binding
  -> named environment-variable secret boundary
```

This removes hand-written topology/provider setup from the first local product path without adding a new reasoning layer.

## Safety behavior

The initial bootstrap slice deliberately fails closed.

If one PostgreSQL pool exists, it may be selected automatically.

If several PostgreSQL ActiveRecord pools exist, the user must specify:

```text
--pool-config <config_name>
```

The expected database identity is also explicit:

```text
--database <database_name>
```

Later live pgbot evidence is revalidated against that topology identity before it can enter the Investigation.

The workspace stores only the name of the environment variable that resolves the DSN. Raw database credentials are not written to bootstrap artifacts.

## Why runtime evidence is not generated here

Repository/config discovery can prove that a Rails service has a declared ActiveRecord pool and that the pool is intended to map to a specific PostgreSQL target.

It cannot prove that a current request is slow, that a lock exists, that connections are saturated, or that a particular database mechanism caused an observed symptom.

Therefore bootstrap explicitly reports:

```text
runtime_evidence_created: false
diagnosis_created: false
```

That is a product invariant, not an incomplete implementation detail.

## Exact-target requirement for the next slice

Current runtime target resolution intentionally requires:

```text
active observed evidence
  -> exact trace identity
  -> runtime used_resource relationship
  -> concrete runtime resource
  -> explicit topology runtime binding
  -> exact operational target
```

The next incident-bootstrap slice must preserve this rule. It should not route a provider merely because the application has only one database or because a hypothesis "looks database-related".

The likely composition path is:

```text
causcope why "<problem>"
  -> Investigation/scoping state

portable Rails runtime + OTLP
  -> concrete runtime facts
  -> exact runtime relationships

canonical observed evidence with trace identity
  -> diagnosis revision 1
  -> exact target resolution
  -> existing provider routing
  -> existing `why --acquire` loop
```

The remaining design problem is therefore how to project the first observed runtime signal into canonical evidence while preserving provenance and exact runtime identity.

## Relationship to future Cloud and Relay

No bootstrap-specific reasoning should be added to Cloud or Relay.

Future deployment surfaces should produce or transport the same contracts:

```text
Concrete System Facts
Resource Topology
Provider Bindings / Capability declarations
Runtime Evidence
Runtime Relationships
Diagnosis Snapshot
```

A Helm chart, Relay daemon, Dashboard, or managed Cloud setup wizard may automate how these contracts are discovered and configured, but the Investigation engine should see the same semantic objects.

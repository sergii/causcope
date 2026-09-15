# RFC 0078: Workspace provider bindings

- Status: Implemented initial slice
- Date: 2026-09-15

## Decision

Causcope may bind a topology-declared provider instance to an existing runtime provider through a small workspace-local configuration file:

```text
.causcope/provider-bindings.yaml
```

This file does not define topology, causal semantics, probe ranking, or execution policy.

It only answers:

> Which already-declared provider instance can this Causcope runtime actually instantiate, and from which local transport/configuration?

The first supported binding driver is:

```text
pgbot_file
```

which binds an RFC 0040 `pgbot` provider instance to an already-produced pgbot JSON report through the existing `PgbotAutonomousProbeProvider`.

## Why this boundary exists

Resource topology already declares logical operational objects:

```text
provider type
provider instance
target resource
runner
credentials_ref
```

But an `InstrumentRouter` also needs a runtime provider object capable of exposing availability/capabilities and, when authorized, collecting evidence.

Previously those runtime bindings were assembled directly in tests or narrow proof scripts.

The workspace binding file makes that final runtime join explicit without creating another provider model.

## Contract

Example:

```yaml
schema_version: "0.1"
kind: provider_bindings
bindings:
  - provider_instance: provider.pgbot.orders-prod
    driver: pgbot_file
    adapter: ./pgbot-postgresql.yaml
    context: ./pgbot-orders.json
```

Paths are resolved relative to `provider-bindings.yaml`.

The canonical schema is:

```text
schema/provider-bindings.schema.json
```

## Authority boundaries

The binding file is not allowed to redefine:

- provider instance target;
- provider type;
- runner;
- network domain;
- canonical probe risk;
- semantic scope;
- provider capability identity.

Those remain owned by topology, canonical knowledge, and the provider implementation.

A binding is accepted only when the configured driver matches the topology provider type.

## Identity safety

The initial pgbot binding additionally checks database identity when the topology target declares a `database` attribute.

For example:

```text
topology target database = orders
pgbot report database    = app_production
```

must fail closed rather than relabel the report as evidence for `orders`.

This prevents a configured provider instance from silently attaching evidence from the wrong PostgreSQL database to an exact operational target.

## Secrets

The binding contract contains no raw credentials.

Topology may retain a logical `credentials_ref`, but secret resolution is outside this initial slice.

Future network-backed drivers should reference environment variables, secret-manager references, Relay-local credentials, or another explicit secret boundary. They must not require embedding bearer tokens or database passwords in this file.

## Relationship to `causcope why`

When the workspace contains:

```text
diagnosis.json
runtime-evidence.json
runtime-relationships.json
resource-topology.yaml
provider-bindings.yaml
```

`causcope why` can reuse the existing pipeline:

```text
diagnosis snapshot
  -> ranked next probe
  -> exact runtime target resolution
  -> topology provider instance
  -> workspace runtime binding
  -> InstrumentRouter
  -> selected safe instrument or explicit stop
```

No new causal ranking or routing algorithm is introduced.

## Initial limitations

The first contract intentionally supports only `pgbot_file`.

It does not yet:

- invoke pgbot itself;
- resolve credentials;
- define Prometheus HTTP bindings;
- define Relay/cloud provider registration;
- authorize write operations;
- bypass exact target or scope checks.

Additional drivers should extend this contract only when a product slice requires them.

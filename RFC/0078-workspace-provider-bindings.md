# RFC 0078: Workspace provider bindings

- Status: Implemented
- Date: 2026-09-15

## Decision

Causcope may bind a topology-declared provider instance to an existing runtime provider through a small workspace-local configuration file:

```text
.causcope/provider-bindings.yaml
```

This file does not define topology, causal semantics, probe ranking, or execution policy.

It only answers:

> Which already-declared provider instance can this Causcope runtime actually instantiate, and from which local transport/configuration?

The implemented pgbot binding drivers are:

```text
pgbot_file
pgbot_cli
```

Both instantiate the existing `PgbotAutonomousProbeProvider`; they differ only in how a versioned pgbot JSON context is supplied.

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

Replay/file binding:

```yaml
schema_version: "0.1"
kind: provider_bindings
bindings:
  - provider_instance: provider.pgbot.orders-prod
    driver: pgbot_file
    adapter: ./pgbot-postgresql.yaml
    context: ./pgbot-orders.json
```

Live CLI binding:

```yaml
schema_version: "0.1"
kind: provider_bindings
bindings:
  - provider_instance: provider.pgbot.orders-prod
    driver: pgbot_cli
    adapter: ./pgbot-postgresql.yaml
    database_url_env: CAUSCOPE_ORDERS_DATABASE_URL
    timeout_seconds: 30
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

## `pgbot_file`

`pgbot_file` binds an RFC 0040 `pgbot` provider instance to an already-produced pgbot JSON report through the existing `PgbotAutonomousProbeProvider`.

It is useful for replayable tests, captured reports, and deterministic offline investigation.

The file is checked for readability, supported pgbot JSON contract version, and exact database identity before it can be selected as an available provider.

Database identity is also revalidated on every evidence read so replacing the file after routing cannot silently attach evidence from another database.

## `pgbot_cli`

`pgbot_cli` is the first live process-backed provider binding.

It deliberately does not define a generic command runner.

The only executable shape is:

```text
pgbot inspect --json
```

Causcope does not accept arbitrary pgbot subcommands, flags, shell fragments, or executable paths from the workspace binding.

The implementation resolves `pgbot` from `PATH`, executes it without a shell, applies a bounded timeout, and accepts pgbot diagnostic/report exit codes `0`, `1`, and `2` when stdout contains a valid JSON report.

Transport/usage failures are rejected.

Plain `causcope why` remains non-invasive: provider discovery may verify that `pgbot` exists and the configured environment variable is present, but it does not run `pgbot inspect` or query PostgreSQL. The CLI process is launched only through explicit evidence acquisition such as `causcope why --acquire`.

## Identity safety

Both pgbot drivers check database identity when the topology target declares a `database` attribute.

For example:

```text
topology target database = orders
pgbot report database    = app_production
```

must fail closed rather than relabel the report as evidence for `orders`.

For `pgbot_cli`, this validation happens on the actual live acquisition result. Therefore a provider that was routable before execution still cannot commit evidence if the live report identifies another database.

This prevents a configured provider instance from silently attaching evidence from the wrong PostgreSQL database to an exact operational target.

## Secrets

The binding contract contains no raw credentials.

For `pgbot_cli`, `database_url_env` contains only the name of an environment variable. At execution time Causcope reads that variable and passes its value to the child process as `DATABASE_URL`.

The DSN is not passed as a command-line argument and is not written to the workspace binding.

The supplier also removes `PGBOT_DATABASE_URL` from the child environment when supplying the explicit `DATABASE_URL` binding, preventing ambiguous credential precedence in this path.

Provider errors intentionally do not echo the connection string or child stderr into Causcope error messages.

Topology may retain a logical `credentials_ref`; mapping that logical reference to environment variables, a secret manager, or Relay-local credentials remains a separate deployment concern.

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

With explicit acquisition:

```text
causcope why --acquire
  -> revalidate current revision and exact route
  -> run the selected read-only provider
  -> validate live target identity
  -> canonical runtime evidence
  -> crash-recoverable evidence + diagnosis commit
  -> rerank
```

No new causal ranking, routing, or execution algorithm is introduced.

## Proof

The `pgbot_cli` CI proof uses a fake `pgbot` executable and verifies all of the following:

```text
plain why does not invoke pgbot
selected provider = provider.pgbot.orders-prod
explicit --acquire invokes exactly: pgbot inspect --json
DATABASE_URL reaches the child only through the configured environment binding
PGBOT_DATABASE_URL is removed from the child environment
report exit code 2 with valid JSON is accepted
canonical evidence is committed
routing.target_resource = db.orders.prod
routing.instrument_id = provider.pgbot.orders-prod
evidence revision 7 -> 8
rerank_count = 1
connection string is not printed by Causcope
```

A second case routes the provider successfully, then returns a live report claiming database `payments` while topology requires `orders`. Acquisition fails closed and diagnosis remains at evidence revision 7.

## Non-goals

RFC 0078 does not add:

- arbitrary subprocess execution;
- raw SQL execution;
- write-capable database operations;
- generic secret storage;
- Prometheus HTTP bindings;
- Relay/cloud provider registration;
- remediation authorization;
- bypasses for exact target or scope checks.

Additional drivers should extend this contract only when a concrete product slice requires them.

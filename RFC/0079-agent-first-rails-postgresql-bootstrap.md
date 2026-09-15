# RFC 0079: Agent-first Rails/PostgreSQL workspace bootstrap

- Status: Implemented initial slice
- Date: 2026-09-15

## Decision

Add a bounded product command:

```text
causcope bootstrap <rails-root>
```

for the first Rails/PostgreSQL local-agent slice.

The command composes existing Causcope contracts. It does not introduce a new diagnosis engine, topology model, provider model, or runtime evidence format.

Its first responsibility is **system bootstrap**:

```text
Rails repository
  -> existing revision-bound `causcope scan`
  -> select one PostgreSQL ActiveRecord pool
  -> resource topology
  -> exact pool -> PostgreSQL target runtime binding
  -> local pgbot provider instance
  -> `pgbot_cli` workspace provider binding
```

The command deliberately does **not** create runtime evidence or a diagnosis merely because the application is Rails and uses PostgreSQL.

## System bootstrap is not incident bootstrap

Causcope must preserve this boundary:

```text
system bootstrap
  knows what exists and what can be inspected

incident bootstrap
  knows what was actually observed for one investigation
```

System bootstrap may establish:

- repository revision;
- application/framework identity;
- declared ActiveRecord pools;
- one explicitly selected PostgreSQL database identity;
- explicit runtime resource binding;
- local runner capability;
- pgbot provider instance;
- secret reference boundary through an environment-variable name.

It must not manufacture:

- affected requests or users;
- current latency;
- lock contention;
- connection saturation;
- runtime trace relationships;
- a leading hypothesis;
- root cause;
- blast radius.

Those require observation.

## Initial command

Example:

```bash
causcope bootstrap ./my-rails-app \
  --database app_production \
  --database-url-env CAUSCOPE_PRODUCTION_DATABASE_URL
```

The first slice writes:

```text
.causcope/
  concrete-system-facts.json
  resource-topology.yaml
  pgbot-postgresql.yaml
  provider-bindings.yaml
```

No raw database URL is stored in these files.

`provider-bindings.yaml` contains only the environment-variable name that will resolve the read-only DSN when explicit evidence acquisition is authorized.

## Why `bootstrap` rather than `init`

`init` commonly implies creating an empty configuration skeleton.

This command performs deterministic discovery and composition over a real application repository, so `bootstrap` describes the behavior more accurately.

It is also intentionally narrower than installation:

- `causcope bootstrap` prepares Causcope system knowledge and provider routing;
- `causcope rails install` installs portable Rails runtime instrumentation;
- `causcope why` owns investigation/scoping and diagnosis projection;
- `causcope why --acquire` explicitly authorizes one bounded read-only evidence step.

## Pool selection

The bootstrap command never guesses among multiple PostgreSQL pools.

If the Rails scan finds exactly one PostgreSQL ActiveRecord pool, it may select it.

If multiple PostgreSQL pools exist, bootstrap stops and requires:

```text
--pool-config <config_name>
```

For example:

```bash
causcope bootstrap . \
  --environment multi_database \
  --pool-config replica \
  --database app_replica \
  --database-url-env APP_REPLICA_DATABASE_URL
```

This avoids silently binding a runtime `primary` or `replica` pool to the wrong operational database.

## Database identity

The initial slice requires an explicit expected database identity:

```text
--database <name>
```

This value is placed in the topology target and is later revalidated against live pgbot output by the existing target-validated provider binding.

Therefore:

```text
bootstrap target database = orders
live pgbot database        = payments
```

fails closed during evidence acquisition.

The bootstrap command itself does not connect to PostgreSQL.

## Secret boundary

The initial live provider uses RFC 0078 `pgbot_cli`.

The workspace stores:

```yaml
database_url_env: CAUSCOPE_PRODUCTION_DATABASE_URL
```

not:

```yaml
database_url: postgresql://user:password@host/database
```

The actual DSN remains process/environment-local and is supplied to the constrained `pgbot inspect --json` child process only when the user explicitly requests acquisition.

## Generated topology

The initial topology is intentionally small:

```text
Rails service
  -> PostgreSQL database

ActiveRecord pool
  -> exact runtime binding -> PostgreSQL database

local runner
  -> provider.pgbot.<database>
  -> exact PostgreSQL database
```

It is a starting system projection, not a claim that the entire production topology has been discovered.

Future topology enrichment may come from runtime traces, Kubernetes, cloud APIs, service catalogs, Git metadata, or explicit configuration, but those sources must preserve provenance and must not silently rewrite this bounded projection.

## Multi-database and enterprise direction

This first local slice intentionally supports one selected PostgreSQL target per bootstrap invocation.

That is sufficient to remove hand-written topology/provider setup from the golden local path without prematurely designing a fleet configuration language.

Later the same contracts can be rendered from:

- multiple Rails database configs;
- Helm values;
- Kubernetes discovery;
- Causcope Relay capability advertisement;
- managed Cloud configuration;
- enterprise service catalogs.

The core objects do not change.

## Relationship to Agent First

The product progression becomes:

```text
causcope bootstrap
  -> knows system + available safe instrument

causcope why "checkout is slow"
  -> creates/resumes Investigation
  -> scopes what is unknown

runtime observation
  -> canonical evidence + relationships
  -> diagnosis snapshot

causcope why
  -> next discriminator
  -> exact target
  -> selected provider

causcope why --acquire
  -> explicit read-only observation
  -> new canonical evidence
  -> rerank
```

This keeps the first useful product local and agent-friendly while preserving the same topology, provider, evidence, and trust boundaries needed later by Dashboard, Cloud, Relay, Helm, and enterprise deployment modes.

## Initial limitations

The first slice does not:

- install Rails runtime instrumentation;
- start an OTLP receiver;
- create an Investigation automatically;
- generate runtime evidence;
- generate runtime relationships;
- generate an initial diagnosis snapshot;
- discover arbitrary infrastructure;
- handle several PostgreSQL targets in one generated topology;
- execute pgbot during bootstrap;
- store database credentials;
- enable write/remediation capabilities.

These are deliberate boundaries, not missing implicit behavior.

The next bootstrap slice should compose the existing portable Rails runtime and runtime relationship projections so that observed runtime facts can enter the already-working `causcope why` loop with fewer manual artifacts.

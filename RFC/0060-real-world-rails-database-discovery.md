# RFC 0060: Real-world Rails database discovery

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Make portable Rails static discovery degrade safely on real database configuration patterns without executing repository ERB or inventing multi-pool identity

## Summary

RFC 0057 proved a portable Rails repository provider against a bounded Causcope fixture. RFC 0059 then exposed that provider through the product CLI.

Testing the workflow against pinned revisions of Lobsters and Mastodon found that the original scanner was still narrower than ordinary Rails repositories:

```text
Lobsters
  config/database.yml.sample
  SQLite
  primary + cache + queue + rack_attack

Mastodon
  config/database.yml
  PostgreSQL
  primary + replica
  runtime-dependent ERB for pool capacity
```

The old scanner either rejected these repositories or collapsed their database topology to one primary pool.

RFC 0060 changes the failure boundary from whole-document rendering to field-level knowledge.

## Invariants

The provider keeps these rules:

```text
repository ERB is never executed
unresolved config != absent config
unknown pool capacity != unlimited pool
multiple configured pools != permission to choose primary
sample config != deployed config
static pool API use != runtime Rails role/shard identity
```

The X-Ray engine is unchanged.

## Database config discovery

By default the Rails provider checks, in order:

```text
config/database.yml
config/database.yml.sample
config/database.yml.example
```

An explicit path can be supplied with:

```bash
causcope scan . --database-config config/my_database.yml
```

Using a sample/example/alternate file emits a limitation stating that the source may describe repository defaults rather than the deployed configuration.

## Partial safe ERB handling

The provider still renders only bounded simple environment access forms that it already understands.

For remaining ERB, it distinguishes value expressions from structural Ruby.

### Value expression

Example:

```yaml
pool: <%= ENV["DB_POOL"] || Sidekiq.default_configuration[:concurrency] || 5 %>
```

Causcope does not execute the expression.

The entire value is replaced internally with an unresolved marker before `YAML.safe_load`. The marker can flow through YAML anchors and merges, but it is never emitted as a concrete fact.

This allows independent fields such as the following to remain known:

```yaml
adapter: postgresql
replica: true
```

### Structural ERB

Example:

```erb
<% if some_runtime_condition %>
production:
  ...
<% end %>
```

This can change the shape of the configuration tree. The provider fails closed rather than executing or guessing the result.

## Multiple database configs

For an environment containing multiple Rails database configurations, the provider emits one ActiveRecord resource pool per config:

```text
pool:active_record.primary
pool:active_record.replica
pool:active_record.cache
pool:active_record.queue
...
```

Each known adapter produces a config-scoped external database dependency.

Examples:

```text
production.primary -> PostgreSQL primary dependency
production.replica -> PostgreSQL replica dependency

production.primary -> SQLite primary dependency
production.cache   -> SQLite cache dependency
```

A `replica: true` declaration is preserved as a direct config attribute.

## Database technology is not a scanner gate

The static provider no longer requires PostgreSQL.

That requirement belonged to the first concrete D3.1 diagnostic profile, not to the generic concrete-system model.

A SQLite pool can therefore be represented truthfully even though the current PostgreSQL-specific D3.1 profile does not apply to it.

This separates:

```text
what the application is
```

from:

```text
which diagnostic profile can reason about it
```

## Code-to-pool binding

For exactly one configured database pool, the existing conservative relationship remains:

```text
explicit ActiveRecord connection_pool / with_connection API
  -> that only configured pool
```

For multiple configured pools, the provider retains the code symbol but does not emit a `code -> pool` relationship.

The code entity records that its pool assignment is unresolved because generic ActiveRecord pool calls do not prove the active role or shard.

A later Rails semantic/runtime provider can advance this using explicit role/config identity.

## Product runtime guard

RFC 0058 runtime instrumentation currently supports exactly one ActiveRecord resource pool.

`causcope rails install` and `causcope rails run` now validate this constraint from the static contract and fail before modifying or launching the application when multiple pools are present.

This turns a late Rails boot failure into an explicit product capability boundary:

```text
static multi-pool discovery: supported
portable multi-pool runtime binding: not yet supported
```

## Compatibility

The original single-PostgreSQL D3.1 fixture retains:

```text
pool:active_record.primary
dependency:postgresql
configured_capacity
checkout_timeout_seconds
explicit code -> pool relationships
```

so the existing generic D3.1 X-Ray proof does not require profile or engine changes.

## Validation

The portable Rails provider tests now model the external patterns discovered in the compatibility spike:

1. single PostgreSQL configuration with resolved capacity;
2. unresolved arbitrary Ruby in one value position, which remains unknown and is never executed;
3. structural ERB, which fails closed and is never executed;
4. Lobsters-like `database.yml.sample` with four SQLite configs;
5. Mastodon-like PostgreSQL primary/replica configuration with runtime-dependent pool capacity;
6. explicit alternate database config selection;
7. product runtime installation refusal for a multi-pool contract before any target-repository mutation.

The exact upstream repositories and pinned revisions that motivated these cases are recorded in `research/rails-external-compatibility-spike.md`.

## Next milestone

Static topology is now capable of representing the two external repository shapes, but the runtime boundary is clear.

The next Rails runtime slice should establish exact pool identity for roles/shards/configs, ideally from runtime ActiveRecord connection metadata rather than configuration-name heuristics:

```text
request execution
  -> exact ActiveRecord pool/config identity
  -> exact role/shard
  -> OTLP span attributes
  -> matching concrete resource_pool
```

Only after that should multi-database applications be allowed through `causcope rails install`.

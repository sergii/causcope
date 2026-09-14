# Rails external compatibility spike

Date: 2026-09-15

This spike tests the assumptions behind the portable Rails provider against real third-party Rails repositories rather than extending the Causcope-owned fixture again.

The external repositories are research inputs, not runtime dependencies. The compatibility tests in Causcope use small deterministic local fixtures that preserve the relevant configuration shapes. Exact upstream revisions are recorded here so the observations are reproducible.

## Lobsters

Repository: https://github.com/lobsters/lobsters

Pinned revision: `812f9c8c14fb3b66e1f9186ba059ea695471780b`

Relevant files:

- https://github.com/lobsters/lobsters/blob/812f9c8c14fb3b66e1f9186ba059ea695471780b/Gemfile
- https://github.com/lobsters/lobsters/blob/812f9c8c14fb3b66e1f9186ba059ea695471780b/config/database.yml.sample

Observed repository shape:

```text
Rails application
  database config committed as config/database.yml.sample
  production:
    primary
    cache
    queue
    rack_attack
  adapter: sqlite3
```

This exposed three assumptions in RFC 0057:

1. requiring a committed `config/database.yml` excludes repositories that intentionally commit only a sample;
2. collapsing a Rails environment to `primary` hides configured pools that are part of the real application architecture;
3. requiring PostgreSQL in the static scanner confuses one diagnostic profile's scope with the generic concrete-system model.

A sample file is weaker evidence than a deployed config. Causcope can use it as repository-declared architecture only when it carries an explicit limitation that it may not describe the deployed environment.

## Mastodon

Repository: https://github.com/mastodon/mastodon

Pinned revision: `4a7ad772cc9a47264c6aea79b74b0778baf1dc0d`

Relevant files:

- https://github.com/mastodon/mastodon/blob/4a7ad772cc9a47264c6aea79b74b0778baf1dc0d/config/database.yml
- examples of explicit `ActiveRecord::Base.connection_pool` usage exist under `app/workers` and `app/lib` at the same revision.

Observed production database shape:

```text
production:
  primary:
    adapter: postgresql
  replica:
    adapter: postgresql
    replica: true
```

The common pool capacity is not a literal. It is computed by ERB that can inspect Sidekiq runtime state and environment values:

```text
DB_POOL || Sidekiq concurrency || MAX_THREADS || fallback
```

Other database fields also use Ruby expressions such as chained environment fallbacks and `to_json`.

The RFC 0057 parser correctly refused to execute this Ruby, but its all-or-nothing behavior meant one unresolved value prevented discovery of literal facts such as:

```text
adapter = postgresql
config names = primary, replica
replica = true
```

That is unnecessarily lossy.

## Resulting parser rule

The safe parser now distinguishes two ERB classes.

### Value ERB

An expression contained entirely in one YAML value position is never executed. If it is not one of the already-bounded simple environment forms, the value is replaced by an internal unresolved placeholder before YAML parsing.

This permits unaffected literals and YAML aliases/merges to remain discoverable.

Example:

```text
adapter: postgresql                         -> known
pool: <%= arbitrary Ruby expression %>     -> unknown
replica: true                              -> known
```

The placeholder itself is never emitted as a concrete fact.

### Structural ERB

ERB that can add, remove, or rearrange YAML structure remains a hard failure.

Examples include control flow around mapping entries or a standalone ERB directive.

Causcope does not execute it and does not guess what repository structure would result.

## Multiple database configurations

Each selected Rails environment database config is now represented separately:

```text
pool:active_record.primary
pool:active_record.replica
pool:active_record.cache
...
```

Each pool receives its own config-scoped database dependency when the adapter is known.

The scanner no longer rejects SQLite or other literal adapters merely because the existing D3.1 X-Ray profile is PostgreSQL-specific. A generic concrete-system fact may exist even when a particular diagnostic profile does not apply.

## Pool assignment remains conservative

A real multi-database Rails application introduces another identity problem.

Seeing this source code:

```ruby
ActiveRecord::Base.connection_pool.with_connection do
  # ...
end
```

does not by itself prove whether the execution uses the configured `primary`, `replica`, another role, or a shard. Role selection can be established outside that method.

Therefore:

```text
one configured pool + explicit pool API
  -> code -> pool relationship may be emitted

multiple configured pools + generic pool API
  -> code symbol is retained
  -> concrete pool assignment remains unknown
```

This preserves the existing epistemic invariant that static proximity is not permission to invent runtime identity.

## Runtime boundary discovered by the spike

RFC 0058 runtime instrumentation still requires exactly one ActiveRecord resource pool.

Static discovery can now describe Lobsters-like or Mastodon-like multi-database topology, but the current portable runtime cannot safely bind a request to one of those pools without Rails role/shard/config identity.

`causcope rails install` therefore fails early for a multi-pool static contract before modifying the target repository.

The next runtime milestone should solve pool identity explicitly rather than silently selecting `primary`.

# RFC 0057: Portable Rails repository provider

- Status: Implemented proof
- Date: 2026-09-14
- Scope: Turn the Rails / ActiveRecord D3.1 fixture integration into a repository scanner that can be pointed at another Rails application without executing application code

## Summary

RFC 0056 proved that Causcope can consume a real Rails / ActiveRecord connection pool while preserving the generic D3.1 X-Ray contract.

This RFC packages the static side of that integration as a portable command:

```text
causcope scan ./my-rails-app
```

The command emits revision-bound `concrete_system_facts` into:

```text
./my-rails-app/.causcope/concrete-system-facts.json
```

unless an explicit `--output` is provided.

The first provider is Rails.

## Provider discovery

`causcope scan` currently recognizes Rails when the target root contains both:

```text
Gemfile
config/application.rb
```

The Rails provider then requires `config/database.yml`.

The CLI can derive:

- revision from `git rev-parse HEAD`;
- repository identity from `git remote.origin.url`;
- system ID from the repository directory name.

All three may be supplied explicitly for detached source trees and CI environments.

## Bounded database configuration rendering

A portable scanner must treat repository content as untrusted source input.

Therefore the provider does **not** evaluate `database.yml` with Ruby ERB.

It only recognizes a bounded subset:

```text
ENV.fetch("NAME", "literal-default")
ENV.fetch("NAME")
ENV["NAME"]
```

Values may be supplied through:

```text
--env-file deployment.yml
--env DB_POOL=10
```

Any remaining ERB causes the scan to fail closed.

This means:

```text
configuration discovery
!=
executing repository configuration code
```

CI includes an adversarial `database.yml` containing a `system(...)` ERB expression and proves that the expression is rejected rather than executed.

## Concrete topology

When PostgreSQL is configured, the provider emits at least:

```text
service:<system>
  depends_on -> pool:active_record.primary

pool:active_record.primary
  depends_on -> dependency:postgresql
```

The pool carries source-owned attributes when they can be resolved:

```text
technology = active_record
adapter = postgresql
environment = production
configured_capacity = <resolved pool size>
checkout_timeout_seconds = <resolved timeout>
```

Unknown values remain absent rather than being replaced by invented defaults.

## Explicit code-path discovery

The provider parses `app/**/*.rb` with Ruby `Ripper`.

It emits a `code_symbol -> pool` fact only when the method AST contains explicit ActiveRecord pool APIs such as:

```text
connection_pool
with_connection
```

For example:

```text
code:PoolController#work()
  depends_on -> pool:active_record.primary
```

This is intentionally conservative.

A method that merely contains:

```ruby
User.first
```

is **not** currently claimed to depend on the pool by the portable static provider, even though ActiveRecord will normally use a connection at runtime.

The relationship remains unknown until a later semantic provider or runtime evidence proves it.

The invariant is:

```text
absence of explicit static evidence
!=
absence of database use
```

## CLI boundary

The existing incident-investigation CLI remains unchanged.

`bin/causcope` routes only the `scan` command to `scripts/causcope_scan.py`, while all existing investigation commands continue through `scripts/causcope_cli.py`.

This keeps the portable scanner independently evolvable until the command surface stabilizes.

## Validation

`Validate portable Rails provider` verifies:

- the existing Rails fixture can be scanned as if it were an external repository;
- emitted facts satisfy the canonical Concrete System Facts schema;
- ActiveRecord pool configuration is resolved from a bounded environment contract;
- explicit pool-using methods become concrete code symbols;
- an implicit ActiveRecord query is not overclaimed as a proven code-to-pool edge;
- unsupported ERB fails closed and is never executed;
- the canonical concrete-system validator accepts the emitted document.

## What this proves

Causcope no longer needs fixture-specific file arguments to discover the static ActiveRecord resource boundary.

The reusable path is now:

```text
arbitrary Rails repository
        |
        v
causcope scan
        |
        v
revision-bound Concrete System Facts
        |
        + later runtime provider / OTel
        v
generic D3.1 X-Ray profile
        v
generic X-Ray engine
```

## What remains

This RFC deliberately packages only the static repository side.

The next provider work should make runtime instrumentation portable as well:

1. ship a small Rails integration/initializer instead of fixture-owned controller instrumentation;
2. capture ActiveRecord pool telemetry for arbitrary requests;
3. export the native OpenTelemetry span through a real OTLP exporter/receiver path;
4. preserve exact system, revision, incident, trace, span and pool identity across that path.

A later semantic enrichment layer can use Rubydex or another deterministic Ruby backend to prove implicit ActiveRecord query paths without requiring explicit `connection_pool` calls in source.

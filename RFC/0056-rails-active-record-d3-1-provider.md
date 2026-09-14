# RFC 0056: Rails / ActiveRecord D3.1 provider

- Status: Implemented proof
- Date: 2026-09-14
- Scope: Prove that the concrete D3.1 X-Ray contract works with a real Rails / ActiveRecord connection pool without changing the generic X-Ray engine

## Summary

RFC 0055 bound D3.1 to a concrete Python application and `psycopg_pool`. This RFC replaces the application technology while preserving the mechanism and the X-Ray proof contract.

```text
Rails application revision
  + database.yml / deployment configuration
  + ActiveRecord connection pool
  + native OpenTelemetry span identity
  + ActiveRecord pool statistics
  + independent PostgreSQL control session
  = the same concrete D3.1 proof
```

The generic `scripts/xray_engine.py` remains unchanged.

## Profile generalization

The RFC 0055 profile accidentally encoded `psycopg_pool` as part of the D3.1 mechanism. That was provider detail rather than causal semantics.

The concrete D3.1 profile now matches a generic `resource_pool`, binds its declared `attributes.technology`, and requires runtime evidence to report the same technology.

This keeps the important invariant:

```text
static pool identity + technology
must equal
runtime pool identity + technology
```

while allowing different pool implementations to participate in the same mechanism proof.

The existing Python / `psycopg_pool` proof remains a regression test for the generalized profile.

## Rails static provider

`scripts/rails_connection_pool_concrete_facts.rb` is a bounded deterministic extractor for the Rails fixture.

It verifies:

- the concrete `PoolController#work` method exists in valid Ruby source;
- the path uses `ActiveRecord::Base.connection_pool` and `with_connection`;
- `config/database.yml` selects PostgreSQL;
- pool capacity and checkout timeout are resolved from a checked-in deployment environment contract;
- the exact revision is attached to all emitted concrete facts.

It emits:

```text
service:rails-connection-pool-app
  contains -> code:PoolController#work()

code:PoolController#work()
  depends_on -> pool:active_record.primary

pool:active_record.primary
  depends_on -> dependency:postgresql
```

The resource pool carries typed configuration attributes:

```text
technology = active_record
adapter = postgresql
configured_capacity = 1
checkout_timeout_seconds = 5
```

## Runtime provider

The fixture is a real Rails API application served by Puma with more request threads than database-pool slots.

The measured path uses the actual `ActiveRecord::ConnectionAdapters::ConnectionPool`. The provider reads the real `connection_pool.stat` surface and records `size`, `busy`, and `waiting` during contention.

A holder request occupies the only pool slot. A second request executes the concrete `PoolController#work` path and waits for checkout. While that request is waiting, the provider opens a separate `PG.connect` session and successfully queries PostgreSQL.

This distinguishes application-owned pool saturation from database-wide connection admission exhaustion.

## OpenTelemetry identity

`PoolController#work` creates a native OpenTelemetry SDK span and attaches:

- `causcope.code_symbol`;
- `causcope.system_id`;
- `causcope.revision`.

The bounded provider serializes that server-created span identity and timing into OTLP JSON for the existing `scripts/otel_concrete_runtime_facts.py` adapter.

The important evidence source is the native span identity. This proof does not yet exercise a network OTLP exporter or collector, and the runtime evidence explicitly records that limitation.

## Causal progression

The same profile from RFC 0055 is used:

```text
PRECONDITIONS_PRESENT
  -> RUNTIME_EXECUTION_OBSERVED
  -> POOL_SATURATED
  -> CHECKOUT_WAIT_OBSERVED
  -> DATABASE_CAPACITY_DISTINGUISHED
  -> CAUSAL_DIAGNOSIS_CONFIRMED
```

No Rails-specific projection Python or Ruby exists.

## Fail-closed controls

CI proves that confirmation is rejected when:

- runtime pool technology differs from the revision-pinned static pool technology;
- trace identity is changed;
- observed capacity differs from configured capacity;
- the independent PostgreSQL control becomes unavailable;
- runtime revision differs from the static revision.

## What this proves

Causcope can consume a production-shaped Rails resource boundary without changing the causal engine:

```text
provider-specific facts and measurements
        -> generic concrete contracts
        -> generic D3.1 profile
        -> generic X-Ray engine
```

The mechanism is therefore no longer tied to the original Python fixture.

## What remains

This is still a bounded repository fixture, not a user application. The next useful step is packaging the static and runtime ActiveRecord providers so they can be pointed at an arbitrary Rails repository/process with minimal instrumentation.

A later proof should also replace the local OTLP serialization bridge with an actual OpenTelemetry exporter/collector path while preserving the same concrete identity checks.

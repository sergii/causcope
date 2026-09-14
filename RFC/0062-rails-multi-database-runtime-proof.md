# RFC 0062: Rails multi-database runtime proof

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Prove that one Rails request can resolve an intentionally ambiguous static multi-database topology into multiple exact runtime resource-pool interactions

## Summary

RFC 0060 made the static Rails provider honest about multi-database applications. When an application exposes both `primary` and `replica`, a generic `connection_pool` call is not assigned to either pool without exact role or configuration evidence.

RFC 0061 added runtime checkout events bound to the actual ActiveRecord `ConnectionPool` object.

RFC 0062 proves the two layers compose correctly:

```text
static source
  PoolController#multi_pool()
  pool:active_record.primary
  pool:active_record.replica
  code -> specific pool = unknown

runtime execution
  same trace/span
    -> pool:active_record.primary / writing / default
    -> pool:active_record.replica / reading / default
```

Runtime evidence resolves the concrete interaction for that execution without retroactively pretending the static source alone knew the answer.

## Fixture shape

The existing Rails connection-pool lab keeps its original single-pool `production` environment and adds a separate `multi_database` environment:

```yaml
multi_database:
  primary:
    adapter: postgresql
    ...
  replica:
    adapter: postgresql
    replica: true
    ...
```

Both configurations point to the same PostgreSQL test server and database. This is deliberate: the proof is about application resource-pool identity, not PostgreSQL replication behavior.

`ApplicationRecord` configures Rails routing only in the `multi_database` environment:

```ruby
connects_to database: {
  writing: :primary,
  reading: :replica
}
```

The ordinary `production` D3.1 proof therefore remains a single-pool experiment.

## One request, two pools

`PoolController#multi_pool` explicitly executes:

```text
connected_to(role: writing)
  -> ApplicationRecord.connection_pool.with_connection

connected_to(role: reading, prevent_writes: true)
  -> ApplicationRecord.connection_pool.with_connection
```

Each block performs a read-only `pg_backend_pid()` query.

The request returns its concrete trace and span identity plus the two PostgreSQL backend ids so the workflow can prove the pools opened distinct physical connections even though both target the same database server.

## Static expectation

The product scanner runs against `RAILS_ENV=multi_database` semantics and must emit exactly:

```text
pool:active_record.primary
  config_name = primary

pool:active_record.replica
  config_name = replica
  replica = true
```

It must also emit the concrete code symbol:

```text
code:PoolController#multi_pool()
```

but must not emit either:

```text
code:PoolController#multi_pool() -> pool:active_record.primary
code:PoolController#multi_pool() -> pool:active_record.replica
```

The code symbol carries:

```text
pool_assignment = unresolved_multiple_configs
```

That is the correct static answer.

## Runtime expectation

The portable Rails runtime observes the actual `ConnectionPool#checkout` calls inside the same request span.

The receiver must project exactly two interactions for that concrete execution:

```text
pool:active_record.primary
  config_name = primary
  role = writing
  shard = default

pool:active_record.replica
  config_name = replica
  role = reading
  shard = default
```

Both interactions must share:

- execution id;
- code symbol;
- trace id;
- span id;
- pinned system id and revision through their parent runtime document.

The primary and replica PostgreSQL backend ids must differ, demonstrating that the two ActiveRecord pools are not merely two labels over one checked-out connection.

## Epistemic meaning

This RFC establishes an important asymmetry:

```text
static ambiguity
+
exact runtime evidence
=
runtime-resolved concrete interaction
```

It does **not** mean:

```text
runtime observation
=> static source was unambiguous all along
```

The static model remains unchanged. The runtime document records what happened in this execution.

This distinction matters for Rails routing because role, shard, request context, middleware, and application logic can select a pool dynamically.

## Why no D3.1 confirmation in this RFC

The current generic D3.1 static precondition still expects a sourced static `code_symbol -> resource_pool` relation before causal progression begins.

RFC 0062 intentionally does not manufacture that relation just because runtime later resolves the interaction.

The proof therefore stops at exact runtime resource-use identity rather than changing X-Ray stage semantics in the same slice.

This exposes the next design question cleanly:

> How should a declarative X-Ray profile consume stronger runtime evidence that resolves a relationship which static analysis could only leave ambiguous?

That should be solved generically, not as a Rails exception.

## Invariants

RFC 0062 preserves:

```text
multiple configured pools != code uses every pool
role name != static code-to-pool proof
same PostgreSQL server != same application pool
runtime use of primary != static default to primary
runtime use of replica != static proof that all reads use replica
one observed request != universal routing behavior
```

Unobserved routing remains unknown.

## CI proof

The dedicated workflow:

1. starts PostgreSQL 17;
2. scans the fixture through `causcope scan` for `multi_database`;
3. proves static ambiguity is retained;
4. starts the concrete OTLP receiver;
5. starts the Rails application with the portable runtime;
6. executes one `/multi-pool` request;
7. finds the exact bound execution;
8. requires exactly two pool interactions on that execution;
9. verifies primary/writing/default and replica/reading/default identities;
10. verifies distinct PostgreSQL backend ids.

The existing single-pool Rails D3.1 workflow remains green and continues to reach `CAUSAL_DIAGNOSIS_CONFIRMED`.

## Next slice

The next useful generic feature is a runtime-resolved relationship projection:

```text
static candidate entities
+
exact runtime interaction
-> runtime-resolved code -> resource relationship
```

That projection must remain explicitly runtime-scoped and must not be written back as an unconditional static fact.

A declarative X-Ray profile should then be able to require either a strong static relationship or an exact runtime-resolved relationship according to the mechanism's evidence policy.

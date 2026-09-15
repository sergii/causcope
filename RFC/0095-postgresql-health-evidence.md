# RFC 0095: Direct PostgreSQL health evidence

Status: Implemented proof
Date: 2026-09-16

## Context

The bounded autonomous Investigation loop can now execute several safe evidence acquisitions in one `causcope why` invocation. Its PostgreSQL evidence breadth is still narrow: pgbot supplies deterministic positive findings, but important live discriminators such as exact blocking chains, current long-running transactions, and current vacuum/autovacuum pressure are not guaranteed to exist as pgbot findings.

These are database runtime facts. Causcope should not force pgbot to become a generic query transport, and it should not treat the absence of a pgbot finding as negative evidence.

## Decision

Add a separate read-only provider:

```text
provider.postgresql.health
instrument = postgresql
transport = postgresql_catalog
```

It supports three canonical diagnostic questions:

```text
probe.database.inspect_lock_waits
  -> adds blocking-chain evidence to the existing lock-wait question
probe.database.inspect_long_running_transactions
probe.database.inspect_vacuum_health
```

Blocking chains deliberately reuse the existing lock-wait probe instead of introducing a competing semantic probe. This preserves the established discriminator identity while making its direct PostgreSQL implementation richer.

The provider is intentionally distinct from `provider.pgbot.postgresql`.

```text
pgbot
  -> deterministic analyzer findings
  -> positive-finding semantics
  -> no finding means insufficient evidence

postgresql health provider
  -> bounded catalog snapshot
  -> complete point-in-time read
  -> an empty successful result can support absent evidence
```

Neither provider is causal authority. Causcope owns the semantic question, exact target, evidence composition, reranking, and verification.

## Blocking chains

The provider reads current activity metadata and `pg_blocking_pids(pid)`. It reconstructs blocker-to-blocked paths and retains maximal dependency chains. It does not collect SQL query text.

The existing `probe.database.inspect_lock_waits` now also produces:

```text
observation.database.blocking_chain
```

The direct PostgreSQL provider maps that probe to `blocking_chain` and `lock_wait_event`; it does not claim to measure `lock_wait_time`, which remains available to other instruments that can measure duration correctly.

The lock-contention hypothesis treats a current blocking chain as strong supporting evidence and a complete snapshot with no chain as decreasing evidence. `pg_blocking_pids` can report both hard blockers and sessions ahead in the lock wait queue, so the provider describes a blocking dependency chain, not an inferred business-level ownership relationship.

## Long-running transactions

The provider reads `pg_stat_activity.xact_start` for current client backends and compares transaction age with an explicit collection threshold. The default is 60 seconds.

The threshold is provider policy, not universal pathology. Evidence preserves the threshold and maximum observed transaction age so later reasoning can distinguish "old enough to inspect" from "proven root cause".

The canonical observation is:

```text
observation.database.long_running_transaction
```

No SQL text is required. `idle in transaction` remains visible through session state because an idle transaction can still retain locks or an old snapshot.

## Vacuum and autovacuum health

The provider reads `pg_stat_user_tables`, `pg_class.reltuples`, `pg_class.reloptions`, and current autovacuum settings.

For PostgreSQL versions before the max-threshold setting exists, the effective dead-tuple trigger is:

```text
vacuum_trigger =
  autovacuum_vacuum_threshold
  + autovacuum_vacuum_scale_factor * pg_class.reltuples
```

Per-table reloptions override global threshold and scale-factor settings. When `autovacuum_vacuum_max_threshold` exists, the provider also applies its global or per-table cap unless disabled with `-1`.

The provider emits two distinct observations:

```text
observation.database.vacuum_pressure
observation.database.autovacuum_disabled
```

Crossing the effective vacuum trigger means a table currently has maintenance pressure. It does not prove that autovacuum is broken. Explicit routine-autovacuum disablement is separate configuration evidence. Even with routine autovacuum disabled, PostgreSQL can still launch vacuum work for transaction-ID wraparound prevention.

## Exact target and privacy

Every emitted evidence instance binds:

```text
scope.attributes.target_resource = exact PostgreSQL resource
```

The provider source also records the exact target resource and database identity. The collector excludes SQL query text, connection URLs, credentials, and application row contents. Only bounded catalog metadata, counts, ages, configuration, and relation statistics become evidence.

## Provider binding

Workspace provider bindings gain:

```yaml
- provider_instance: provider.postgresql-health.orders-prod
  driver: postgresql_health
  database_url_env: ORDERS_DATABASE_URL
  long_transaction_seconds: 60
  scope:
    boundaries:
      - boundary.application.database
    attributes:
      service: orders-api
      dependency: postgresql
```

The exact target resource comes from the provider instance in resource topology and is attached to runtime evidence by the provider. The database URL remains environment-only.

## Safety

The collector starts its PostgreSQL transaction with `SET TRANSACTION READ ONLY`. All supported probes are canonical `read_only` probes. The slice authorizes no `VACUUM`, cancellation, termination, lock release, configuration change, or remediation.

## Verification

The proof has two layers:

1. deterministic unit tests for semantic projection, target binding, complete-snapshot absent evidence, blocking-chain reconstruction, and separation of vacuum pressure from autovacuum disablement;
2. a live PostgreSQL test that creates a real blocked transaction and a table with per-table autovacuum disabled, then verifies the collector sees the blocking chain, the long-running transaction, and the effective table configuration without leaking SQL text.

## Non-goals

This RFC does not yet claim historical blocking-chain reconstruction, long-transaction business impact without correlation to an affected execution, autovacuum worker starvation or saturation from trigger crossing alone, table/index bloat measurement, automatic remediation, or replacement of pgbot.

A later slice can add worker saturation/starvation only when it has evidence that distinguishes "eligible for vacuum" from "unable to receive sufficient vacuum work" over time.

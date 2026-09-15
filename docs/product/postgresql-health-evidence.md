# PostgreSQL health evidence

Causcope has two complementary PostgreSQL evidence paths:

```text
pgbot
  deterministic analyzer findings
  positive finding -> canonical evidence
  no finding -> insufficient evidence

provider.postgresql.health
  bounded read-only PostgreSQL catalog snapshot
  complete successful snapshot -> observed or absent evidence
```

The direct PostgreSQL health provider currently answers three bounded questions:

```text
probe.database.inspect_lock_waits
  -> lock-wait event + blocker-chain structure
probe.database.inspect_long_running_transactions
probe.database.inspect_vacuum_health
```

Blocking chains extend the existing lock-wait question instead of creating a competing probe identity. The direct provider intentionally does not claim `lock_wait_time` because its point-in-time catalog snapshot does not measure lock-wait duration precisely.

It reads current session/blocker metadata, transaction age, user-table statistics, and effective autovacuum settings. It does not collect SQL query text, application rows, connection URLs, or credentials.

Vacuum trigger crossing is represented as `observation.database.vacuum_pressure`, not as proof that autovacuum is broken. Explicit routine-autovacuum disablement is a separate `observation.database.autovacuum_disabled` fact.

Every evidence instance is bound to the exact PostgreSQL topology target through `scope.attributes.target_resource`, so multi-database Investigations do not collapse independent database states into one evidence partition.

See RFC 0095 for the full contract and safety boundary.

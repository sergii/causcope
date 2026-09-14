# RFC 0036: Live pgbot PostgreSQL integration

- Status: Implemented integration slice
- Date: 2026-09-14

## Summary

RFC 0034 proved the semantic adapter with fixtures. This slice removes the pgbot fixture from the integration boundary and runs a pinned pgbot release against a real PostgreSQL 17 instance.

The live path is:

```text
PostgreSQL 17
  -> real pgbot v0.8.1 inspect --format=json
  -> pgbot adapter
  -> canonical Causcope runtime evidence

PostgreSQL 17
  -> real timed client query
  -> OTLP/HTTP JSON trace payload
  -> OpenTelemetry adapter
  -> canonical Causcope runtime evidence

both evidence streams
  -> deterministic composition
  -> one semantic scope
  -> live diagnosis snapshot
```

The purpose is not to reproduce pgbot. It is to prove that an external deterministic domain instrument can feed Causcope from a live system while Causcope continues to own normalization, scope, cross-source composition, causal reasoning, probes, and verification.

## Live failure signal

The integration database runs with a deliberately small connection ceiling and temporary load sessions. pgbot observes the live database while the connection count is above its saturation threshold and must emit the real `connection_saturation` finding.

That finding is normalized to:

```text
observation.database.connection_utilization
```

No fixture or hand-written pgbot finding is involved in this path.

## Live trace signal

After the saturation capture, the temporary holder sessions are stopped and the harness executes a real PostgreSQL query with a controlled delay. The harness records the actual start and end nanosecond timestamps and emits an OTLP/HTTP JSON client span with PostgreSQL semantic attributes.

The existing OpenTelemetry adapter normalizes that measured span to:

```text
observation.database.query_latency
```

The trace is therefore generated from a real database interaction rather than loaded from the static PostgreSQL trace fixture used by RFC 0034.

## Shared semantic scope

Both adapters are required to produce the same Causcope scope:

```yaml
boundaries:
  - boundary.application.external_dependency
attributes:
  service: checkout-api
  dependency: postgresql
```

Composition is valid because both sources describe the same dependency boundary, not merely because both contain the word PostgreSQL.

## Upstream contract pinning

The pgbot adapter now declares the upstream JSON schema versions it accepts explicitly:

```yaml
accepted_schema_versions:
  - "1.2.0"
```

The live workflow pins pgbot to `v0.8.1`, whose machine-readable contract is schema `1.2.0`.

An unsupported pgbot schema version fails closed before findings are normalized. We do not silently accept a future breaking upstream contract and hope that fields still mean the same thing.

## Read-only boundary

The live PostgreSQL instance creates a dedicated `pgbot_ro` login with `pg_monitor` and no application write grants. The pgbot run is deterministic and does not use an AI key.

The test workload uses a separate application role. The load is intentionally created by the lab harness, never by pgbot or by the adapter.

## Files

```text
lab/pgbot-live/compose.yml
lab/pgbot-live/init.sql
scripts/live_postgresql_trace.py
scripts/verify_pgbot_live_integration.py
.github/workflows/pgbot-live.yml
```

The workflow also exercises the existing:

```text
scripts/pgbot_adapter.py
scripts/opentelemetry_trace_adapter.py
scripts/runtime_evidence_composition.py
scripts/live_diagnosis.py
```

## Assertions

The live integration fails unless all of the following are true:

1. a real pgbot run returns schema version `1.2.0`;
2. pgbot observes an unsuppressed `connection_saturation` finding from the live database;
3. the pgbot adapter produces `observation.database.connection_utilization`;
4. a real delayed PostgreSQL query produces a trace that becomes `observation.database.query_latency`;
5. pgbot and trace evidence retain distinct provenance;
6. both evidence streams compose into one semantic partition;
7. the composed partition reaches the live diagnosis engine.

## Non-goals

This slice does not yet:

- run pgbot as an autonomous Causcope probe executor;
- import every pgbot finding;
- use the pgbot MCP server;
- model source unavailable/reset/cold-window states directly in runtime evidence;
- instrument a production application with an OpenTelemetry SDK;
- treat pgbot severity as Causcope causal weight.

## Next slice

The next useful step is to register pgbot as an optional read-only diagnostic provider behind Causcope's existing capability and probe boundaries. That would let the investigator select a PostgreSQL-specific instrument when a database hypothesis needs discrimination, while keeping execution allowlisted, scoped, auditable, and bounded by the autonomous read-only investigation loop.

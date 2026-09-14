# RFC 0055: Concrete D3.1 connection-pool X-Ray proof

- Status: Implemented proof
- Date: 2026-09-14
- Scope: Bind the D3.1 connection-pool mechanism to one exact application revision, code path, request trace, resource pool and PostgreSQL control without changing the generic X-Ray engine

## Summary

RFC 0054 proved that the generic RFC 0053 X-Ray engine can express application connection-pool exhaustion from controlled empirical evidence without mechanism-specific projection Python.

This RFC advances D3.1 from a generic lab proof to a Concrete System X-Ray proof.

```text
revision-pinned application source + deployment config
        |
        v
concrete code path -> concrete resource pool -> PostgreSQL
        |
        + exact request trace
        + observed pool saturation
        + checkout wait
        + request latency
        + fast post-checkout SQL
        + independent PostgreSQL control session
        + recovery after pool release
        |
        v
CAUSAL_DIAGNOSIS_CONFIRMED
```

The generic `scripts/xray_engine.py` is unchanged.

## Concrete static model

`scripts/python_connection_pool_concrete_facts.py` is a bounded deterministic extractor for the existing Python/psycopg_pool fixture.

It reads two source-owned inputs:

- `lab/database-connection-pool/app.py`;
- `lab/database-connection-pool/compose.yml`.

The extractor verifies rather than assumes that:

- `Handler.do_GET` exists in the Python AST;
- the handler actually calls `pool.connection(...)`;
- `POOL_SIZE` is sourced from the `POOL_SIZE` environment variable;
- `ConnectionPool(min_size=POOL_SIZE, max_size=POOL_SIZE, ...)` binds capacity to that setting;
- the concrete Compose app service declares the configured pool size;
- the app depends on a PostgreSQL service.

It emits revision-bound `concrete_system_facts` with four concrete entities:

```text
service:database-connection-pool-app
code:Handler#do_GET()
pool:application_database
dependency:postgresql
```

and the topology:

```text
service
  contains -> code:Handler#do_GET()

code:Handler#do_GET()
  depends_on -> pool:application_database

pool:application_database
  depends_on -> dependency:postgresql
```

The pool entity carries typed configuration attributes such as `configured_capacity` and `checkout_timeout_seconds`.

To support concrete configuration without stringly-typed numeric comparisons, the `concrete_system_facts` contract now permits scalar entity/context attributes and adds the generic entity kind `resource_pool`. Existing string attributes remain valid.

## Exact runtime request binding

The fixture application now accepts explicit trace/span identity for the measured `/work` request and returns server-side timing metadata only when those headers are present.

The server binding contains:

- `system_id`;
- revision;
- canonical concrete code symbol;
- trace ID;
- span ID;
- request start/end wall-clock timestamps.

The live probe converts that server-observed execution into OTLP JSON and passes it through the existing `scripts/otel_concrete_runtime_facts.py` adapter.

That adapter independently checks that the span refers to a known code symbol in the same concrete system and exact revision.

Therefore:

```text
request happened
!=
this concrete code path happened
```

unless trace identity, code-symbol identity, system identity and revision all agree.

## Resource-pool runtime evidence

`schema/resource-pool-runtime-evidence.schema.json` introduces a strict source-owned runtime contract for bounded resource pools.

The first provider is `lab/database-connection-pool/concrete_probe.py`.

It records:

- concrete pool identity;
- configured and observed capacity;
- busy slots and utilization;
- exact traced request identity;
- checkout wait;
- request latency;
- dependency query latency;
- PostgreSQL backend identity used by the traced request;
- an independently opened direct PostgreSQL control connection and its backend identity;
- baseline measurements;
- recovery measurements;
- deterministic discriminating assertions.

Raw process output is not promoted into canonical evidence.

## PostgreSQL control

The concrete probe opens a direct PostgreSQL session while the application-owned pool is saturated.

This is intentionally separate from the saturated application pool.

The proof therefore distinguishes:

```text
application pool has no free slots
```

from:

```text
PostgreSQL cannot admit another session
```

The profile additionally requires the traced request's PostgreSQL backend identity to differ from the independent control backend identity.

A successful control does not claim that PostgreSQL has unlimited capacity. It proves only that database-wide connection admission exhaustion was not observed in the measured causal window.

## Declarative progression

`xray/profiles/d3-1-concrete-connection-pool.yaml` defines the concrete progression.

### PRECONDITIONS_PRESENT

The pinned revision must contain a concrete code path that depends on a bounded `psycopg_pool` resource pool, and that pool must depend on PostgreSQL.

### RUNTIME_EXECUTION_OBSERVED

A concrete OTel execution for the exact code symbol must join to the resource-pool evidence by trace ID and span ID.

The configured capacity from static facts must equal the observed runtime pool capacity.

### POOL_SATURATED

The exact pool must be observed at capacity while the traced request competes for checkout.

### CHECKOUT_WAIT_OBSERVED

The traced request must show materially increased checkout wait and request latency.

### DATABASE_CAPACITY_DISTINGUISHED

Post-checkout SQL must remain near baseline and a distinct direct PostgreSQL session must remain reachable.

### CAUSAL_DIAGNOSIS_CONFIRMED

The added checkout wait must explain the request-latency increase, and checkout wait plus request latency must recover after the holder releases the pool slot.

## Exact identity rules

The profile fails closed across three identity groups:

```text
system:
  static == runtime == pool evidence

revision:
  static == runtime == pool evidence

incident:
  runtime == pool evidence
```

The request trace is then joined inside the staged proof:

```text
runtime.execution.trace_id == pool.request.trace_id
runtime.execution.span_id  == pool.request.span_id
runtime.execution.code_symbol == pool.request.code_symbol
```

A nearby trace from the same service is not evidence for this request.

## Fail-closed controls

CI deliberately tampers with discriminating evidence.

- Wrong request trace ID stops at `PRECONDITIONS_PRESENT`.
- Runtime capacity that differs from the pinned configured capacity stops at `PRECONDITIONS_PRESENT`.
- Removing the independent PostgreSQL control stops at `CHECKOUT_WAIT_OBSERVED`.
- Removing the checkout-wait explanation stops at `DATABASE_CAPACITY_DISTINGUISHED`.
- A revision mismatch is rejected as an identity error instead of being downgraded to a weaker match.

The engine must not infer a missing step from the remaining evidence.

## What this proves

RFC 0054 established that D3.1 can be represented declaratively.

RFC 0055 establishes the stronger statement:

```text
Causcope can bind D3.1 to a particular application revision,
particular code path,
particular request execution,
particular configured resource pool,
and an independent PostgreSQL control window.
```

This is a Concrete System X-Ray result rather than only a generic mechanism experiment.

## What this does not prove

The current fixture still uses a pool capacity of one to make the causal window deterministic.

The bounded Python extractor is not a general Python architecture analyzer. It exists to prove the concrete-fact contract on a second language/runtime shape without weakening evidence semantics.

The probe does not claim that increasing pool size is the correct remediation. Production sizing still depends on database capacity, workload concurrency and service-level objectives.

The trace payload is generated from server-observed timing and identity in the live fixture, then normalized through the existing OpenTelemetry concrete-runtime adapter. A later production adapter should consume native application telemetry rather than fixture response metadata.

## Acceptance criteria

The proof is accepted when CI demonstrates all of the following:

1. Static source/config extraction yields schema-valid revision-bound concrete facts.
2. The configured pool capacity is represented as typed concrete configuration.
3. A live traced request is normalized into exact `concrete_runtime_facts` for the same revision.
4. Resource-pool evidence is schema-valid and bound to the same system, revision and incident.
5. The application pool is saturated while the traced request waits.
6. SQL itself remains near baseline.
7. PostgreSQL admits an independent control connection on a distinct backend.
8. Recovery follows release of the pool slot.
9. The declarative profile reaches `CAUSAL_DIAGNOSIS_CONFIRMED`.
10. Trace, capacity, database-control and revision tampering all fail closed.
11. The generic X-Ray engine remains unchanged.
12. The original D3.1 empirical lab remains green.

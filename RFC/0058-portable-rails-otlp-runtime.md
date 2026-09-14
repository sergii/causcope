# RFC 0058: Portable Rails OTLP runtime integration

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Replace the bounded Rails fixture's synthetic OTLP serialization with a portable Rails runtime integration, the official Ruby OTLP exporter, and a Causcope concrete OTLP receiver

## Summary

RFC 0057 made static Rails discovery portable with:

```text
causcope scan ./rails-app
  -> revision-bound Concrete System Facts
```

The remaining fixture-specific gap was runtime transport. RFC 0056 still created a native OpenTelemetry span but serialized an OTLP JSON envelope inside the test probe.

This RFC removes that shortcut:

```text
Rails controller action
  -> Causcope portable Rails runtime integration
  -> native OpenTelemetry SDK span
  -> official opentelemetry-exporter-otlp gem
  -> OTLP/HTTP protobuf
  -> Causcope concrete OTLP receiver
  -> revision-bound concrete_runtime_facts
  -> unchanged D3.1 profile
  -> unchanged X-Ray engine
```

## Portable Rails runtime

`integrations/rails/causcope_runtime.rb` is a small initializer-style integration.

It requires:

- `CAUSCOPE_SYSTEM_ID`;
- `CAUSCOPE_REVISION`;
- a `concrete_system_facts` document, supplied by `CAUSCOPE_STATIC_FACTS` or the default `.causcope/concrete-system-facts.json` path.

The integration verifies that the runtime system and revision exactly match the static contract before instrumentation is enabled.

For the first portable version, exactly one ActiveRecord `resource_pool` is required. This is deliberately narrower than general Rails multi-database, role, and shard support.

## Code-symbol binding

The runtime does not invent code identities.

It loads the exact `code_symbol` entities from the static scan and instruments a Rails controller action only when its canonical identity is already present:

```text
code:OrdersController#create()
```

An action absent from the static facts is not emitted as a concrete execution.

This preserves the invariant:

```text
runtime observation cannot create static semantic identity
```

## ActiveRecord pool measurements

The integration observes the same real `ActiveRecord::ConnectionAdapters::ConnectionPool` used by the request.

It records bounded attributes on the request span, including:

- pool id and technology;
- configured capacity from static facts when known;
- pre-request pool `size`, `busy`, and `waiting`;
- measured connection checkout wait;
- pool state at checkout completion;
- post-request pool state;
- request duration.

A narrow `ConnectionPool#checkout` prepend measures wait around the real checkout call. It does not replace pool behavior or fabricate a separate resource model.

These attributes are transport evidence. The D3.1 causal profile still depends on canonical `resource_pool_runtime_evidence` and does not gain new mechanism-specific logic here.

## OTLP transport

The Rails fixture now uses the official `opentelemetry-exporter-otlp` gem.

CI uses `SimpleSpanProcessor` only to make transport deterministic for the proof. The portable integration uses the normal SDK exporter path unless `CAUSCOPE_OTEL_SYNC=1` is explicitly enabled.

The exporter sends standard OTLP/HTTP protobuf to `/v1/traces`.

No test probe constructs the OTLP envelope anymore.

## Concrete OTLP receiver

`scripts/otlp_concrete_receiver.py` accepts:

- `application/x-protobuf` / `application/protobuf` OTLP trace requests;
- OTLP JSON for compatibility;
- identity-bound static facts;
- an incident id.

For every explicitly bound span it reuses the existing `otel_concrete_runtime_facts` semantics:

```text
causcope.code_symbol
causcope.system_id
causcope.revision
```

The receiver rejects unknown symbols and system/revision mismatches rather than guessing.

It accumulates deterministic execution facts across exporter batches, recomputes cross-batch temporal overlap, validates the canonical concrete-runtime schema, and atomically updates an optional snapshot.

Unbound spans are ignored rather than converted into negative evidence.

## D3.1 proof

The existing Rails connection-pool lab now separates three evidence paths:

```text
static provider
  -> concrete_system_facts

portable Rails runtime + official OTLP exporter
  -> concrete OTLP receiver
  -> concrete_runtime_facts

bounded application/PostgreSQL probe
  -> resource_pool_runtime_evidence
```

The generic D3.1 profile joins them by exact:

- system;
- revision;
- incident;
- code symbol;
- trace id;
- span id;
- resource-pool identity and technology.

Neither `scripts/xray_engine.py` nor `xray/profiles/d3-1-concrete-connection-pool.yaml` is changed by this RFC.

## Epistemic boundaries

The proof preserves these distinctions:

```text
OTLP delivery != causal confirmation
request span != pool saturation
pool saturation != database-wide connection exhaustion
unbound span != absent execution
wrong revision != approximate match
```

The independent PostgreSQL control remains a separate read-only measurement. The Rails runtime integration does not open extra database connections merely to manufacture confirmation.

## Security and deployment boundary

The concrete receiver defaults to loopback only. Authentication, TLS termination, multi-tenant routing, persistent ingestion, and production retention are outside this proof.

A production deployment should normally place the receiver behind an authenticated local agent, collector, or trusted network boundary rather than exposing it directly to the public internet.

## What this proves

Causcope now has a production-shaped Rails integration path:

```text
arbitrary scanned Rails revision
       +
portable runtime initializer
       +
standard OpenTelemetry exporter
       +
Causcope OTLP receiver
       =
exact concrete execution evidence
```

The causal engine remains provider-independent.

## What remains

The next useful work is packaging and ergonomics rather than another mechanism-specific proof:

1. generate/install the Rails initializer from the CLI;
2. support already-configured OpenTelemetry applications without taking ownership of SDK configuration;
3. support multiple ActiveRecord pools, roles, and shards;
4. turn pool-span attributes into a reusable runtime provider instead of relying on the bounded D3.1 probe for baseline/recovery and PostgreSQL control;
5. add authenticated agent/collector ingestion and durable evidence storage.

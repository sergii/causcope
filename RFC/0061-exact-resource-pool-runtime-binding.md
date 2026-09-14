# RFC 0061: Exact resource-pool runtime binding

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Bind an observed request execution to the exact concrete resource pool it actually checked out at runtime, including Rails multi-database pool identity

## Summary

RFC 0060 made static Rails database discovery realistic enough to represent multiple database configurations without guessing which pool a generic `connection_pool` call uses.

That exposed the next missing causal edge.

Before this RFC, D3.1 could join:

```text
static code -> pool relationship
+
observed code execution
+
separate runtime evidence for the same pool id
```

but the trace itself did not prove that the observed execution actually checked out a connection from that concrete pool.

RFC 0061 adds that proof:

```text
concrete code execution
  -> observed resource-pool checkout
  -> exact concrete resource_pool
```

The relationship is runtime evidence, not a static inference.

## Generic runtime contract

`concrete_runtime_facts` gains an optional `pool_interactions` collection.

Each interaction carries:

- deterministic interaction id;
- parent concrete execution id;
- code symbol;
- concrete pool id;
- pool technology;
- provider-local configuration name;
- trace id and span id;
- event index and observed timestamp;
- measured checkout wait;
- optional observed pool size, busy count, and waiting count;
- optional provider dimensions such as role and shard;
- OpenTelemetry provenance.

An interaction therefore means:

```text
this exact bound execution
observably interacted with
this exact static resource pool
at this point in time
```

It does not by itself mean the pool was saturated or that the pool caused user-visible latency.

## Transport: OpenTelemetry span events

Pool interactions are transported as repeated events on the existing concrete request span:

```text
span: code:OrdersController#create()
  event: causcope.pool.checkout
    causcope.pool_id = pool:active_record.primary
    causcope.pool.technology = active_record
    causcope.pool.config_name = primary
    causcope.pool.role = writing
    causcope.pool.shard = default
    causcope.pool.checkout_wait_ms = ...

  event: causcope.pool.checkout
    causcope.pool_id = pool:active_record.replica
    causcope.pool.technology = active_record
    causcope.pool.config_name = replica
    causcope.pool.role = reading
    causcope.pool.shard = default
    causcope.pool.checkout_wait_ms = ...
```

A repeated event is deliberate. One request may use zero, one, or several pools. A scalar span attribute such as `causcope.pool_id` cannot represent that without losing information or making the last checkout silently overwrite earlier ones.

The old scalar pool attributes remain available only for a single-pool static contract so existing bounded consumers do not break. Multi-pool truth lives in events.

## Exact ActiveRecord identity

The Rails runtime binds the actual `ActiveRecord::ConnectionAdapters::ConnectionPool` object used by `checkout`.

The binding uses public runtime metadata from that pool:

```text
ConnectionPool
  -> db_config.name
  -> db_config.env_name
  -> db_config.adapter
  -> role
  -> shard
```

`db_config.name` is matched to the `config_name` emitted by the portable static Rails scanner.

The static pool's environment and adapter are also checked when available.

Only an exact match creates a concrete checkout event.

There is no timing-based pool assignment, no `primary` default, and no fuzzy matching.

## Fail-open monitoring, fail-closed knowledge

Instrumentation must not break the application merely because Causcope cannot identify a pool.

Therefore:

```text
ActiveRecord checkout succeeds
+
runtime pool identity cannot be matched exactly
=
application keeps running
and Causcope emits no concrete pool interaction
```

The missing interaction remains unknown.

This is different from accepting an approximate pool identity. Downstream causal progression fails closed because the exact runtime interaction is absent.

The request span may record an unresolved-checkout count for observability, but that count is not converted into a concrete pool relationship.

## Rails multi-database support

RFC 0060 allowed static contracts such as:

```text
pool:active_record.primary
pool:active_record.replica
pool:active_record.cache
pool:active_record.queue
```

RFC 0061 removes the product runtime's previous `exactly one ActiveRecord pool` installation gate.

At runtime, the exact pool instance determines which static pool event is emitted. A request using both primary and replica can therefore carry both interactions without ambiguity.

Role and shard are recorded as runtime dimensions. They do not replace `db_config.name`; they preserve additional Rails routing context.

## Provider-independent semantics

`config_name` is provider-local concrete configuration identity, not a Rails-only ontology term.

For the bounded Python/psycopg_pool D3.1 proof, the single declared pool receives the stable configuration identity:

```text
config_name = application_database
```

The Python fixture records the wall-clock timestamp immediately after successful checkout and projects that measurement into the same `causcope.pool.checkout` event shape.

This keeps the generic D3.1 profile provider-independent.

## Receiver validation

The OTLP projection rejects a pool event when:

- `pool_id` is absent or not a known concrete `resource_pool`;
- pool technology differs from the static pool;
- provider-local `config_name` differs from the static pool;
- checkout wait or optional counters are invalid;
- the parent execution cannot be established through the bound code span.

Every emitted interaction is linked to the same execution, code symbol, trace id, and span id.

The receiver accumulates and replay-deduplicates interactions by deterministic id just as it does executions.

## Stronger D3.1 progression

The generic D3.1 runtime stage now requires:

```text
static code -> pool precondition
+
concrete execution(code, trace, span)
+
concrete pool interaction(execution, same code, same trace/span, same pool, same technology)
+
resource_pool_runtime_evidence(same pool, same request trace/span)
```

Only then can the progression advance beyond `PRECONDITIONS_PRESENT`.

Removing the exact runtime pool interaction must reduce the diagnosis back to `PRECONDITIONS_PRESENT`, even if separate saturation evidence still exists.

This closes the previous epistemic gap:

```text
request happened near pool evidence
!=
request actually used that pool
```

## Epistemic boundaries

RFC 0061 preserves these distinctions:

```text
static code -> pool relation != observed checkout
observed checkout != pool saturation
pool saturation != causal latency explanation
role/shard metadata != proof of database server identity
unresolved runtime pool != primary pool
missing checkout event != no database access
```

The existing baseline, intervention, independent database control, and recovery evidence remain necessary for `CAUSAL_DIAGNOSIS_CONFIRMED` in D3.1.

## Migration

Static Rails facts generated before RFC 0060 may not contain `attributes.config_name` on ActiveRecord pools.

The exact runtime provider intentionally does not invent that missing identity. Re-scan the application with the current product provider:

```bash
causcope scan ./rails-app
```

Then install or refresh the runtime integration:

```bash
causcope rails install ./rails-app --force
```

Revision identity rules remain unchanged: runtime revision must exactly match the scanned contract.

## What this proves

For a real Rails request, Causcope can now distinguish:

```text
OrdersController#create executed
```

from:

```text
OrdersController#create executed
and actually checked out from ActiveRecord primary/writing/default
```

and from:

```text
that exact pool was saturated,
the request waited for checkout,
the database still admitted an independent connection,
and latency recovered when the pool slot returned
```

Those are separate evidence layers and remain separate in the model.

## What remains

The next useful slices are:

1. exercise a true multi-database Rails fixture where one request touches two configured pools and prove two distinct checkout interactions;
2. make the runtime coexist with applications that already own OpenTelemetry SDK configuration instead of always configuring the SDK itself;
3. project exact resource interactions for jobs and service objects, not only controller spans;
4. turn checkout events into a reusable live resource-pool evidence provider for ordinary production incidents;
5. carry exact database backend/session identity when available so pool identity can be joined to database wait and lock evidence.

# RFC 0068: Runtime target-aware investigation

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Resolve exact runtime-used resources into operational targets and fan out the current diagnostic probe across those targets without heuristic resource guessing

## Summary

Causcope already had the following pieces:

```text
runtime-resolved relationships
  -> exact resources used by a concrete execution

resource topology
  -> stable operational resources and provider instances

probe ranking
  -> which semantic observation best discriminates current hypotheses

instrument router
  -> which configured instrument can safely obtain that observation

provider information-gain routing
  -> which already-safe provider is most diagnostically useful
```

The missing link was automatic target identity.

A live diagnosis knew that it needed, for example:

```text
probe.database.measure_query_latency
```

but the routing layer still needed an explicit caller-supplied target such as:

```text
db.orders.prod
```

RFC 0068 closes that gap without inferring resource identity from names, roles, dependency types, or proximity.

The new flow is:

```text
active diagnosis evidence
  -> exact OpenTelemetry trace identity
  -> RFC 0063 used_resource relationships
  -> explicit runtime-resource -> topology-target bindings
  -> exact target set
  -> safe target-aware routing
  -> RFC 0066 provider information-gain selection per target
```

## Target set, not forced singleton

One execution may use multiple resources.

For example:

```text
trace T
  -> used_resource pool:active_record.primary
  -> used_resource pool:active_record.replica
```

If topology explicitly binds those runtime resources to:

```text
pool:active_record.primary
  -> db.orders.prod

pool:active_record.replica
  -> db.payments.prod
```

then the correct target resolution is:

```text
{db.orders.prod, db.payments.prod}
```

Causcope must not choose one merely because it is called `primary`, appears first, or has a preferred provider.

The current top-ranked probe is therefore fanned out across both exact operational targets.

## Explicit runtime bindings

RFC 0040 topology gains an optional `runtime_bindings` registry.

Example:

```yaml
runtime_bindings:
  - runtime_resource: pool:active_record.primary
    target_resource: db.orders.prod
  - runtime_resource: pool:active_record.replica
    target_resource: db.payments.prod
```

These bindings are identity statements supplied by deterministic discovery/configuration. They are not causal evidence.

The following are intentionally forbidden:

```text
primary -> orders by naming convention
replica -> payments by naming convention
postgresql dependency -> nearest database target
same network -> same resource
same database role -> same operational target
```

Missing binding means unresolved target identity.

## Exact runtime context

Target resolution starts from active evidence for the diagnosis target.

For trace-backed evidence the resolver reads the exact:

```text
source.attributes["otel.trace_id"]
```

It then considers only `used_resource` relationships from the same incident and exact trace identity.

Relationships from another trace are ignored even when they mention the same code symbol, database technology, or resource name.

The resolver does not use timestamp-nearest matching.

## Runtime target resolution projection

RFC 0068 adds:

```text
runtime_target_resolution
```

Each entry is keyed by the current diagnosis partition, diagnosis target, and top-ranked probe.

A resolved entry records:

```text
supporting active evidence instances
exact trace IDs
operational target resources
runtime resources behind each target
relationship IDs
execution IDs
```

An unresolved entry records one bounded reason:

```text
no_active_target_evidence
no_exact_trace_context
no_runtime_resource_relationships
runtime_resource_unbound
```

Unknown remains unknown.

## Routing fan-out

`build_instrument_routing_projection()` now accepts an optional runtime target resolution.

Legacy callers remain unchanged:

```text
probe -> safe route
```

Target-aware callers use:

```text
probe
  + exact target resolution
  -> one routing decision per target resource
```

When RFC 0066 is supplied, each target route becomes:

```text
safe eligible providers for target
  -> deterministic causal-contrast information-gain proxy
  -> selected provider for that target
```

This means two targets from one diagnosis may legitimately select different provider instances.

## Example

Suppose query latency is the top diagnostic probe and one trace used both orders and payments databases.

The target-aware routing projection may become:

```text
db.orders.prod
  -> provider.prometheus.orders-prod

db.payments.prod
  -> provider.prometheus.payments-prod
```

The provider choice is target-local. Evidence produced for payments cannot be relabeled as orders evidence.

## Fail-closed semantics

Automatic routing stops when exact target identity is not established.

In particular:

```text
runtime relationship exists
+
runtime resource has no topology binding
=
no automatic target route
```

Causcope does not partially route the known subset while silently discarding an unbound runtime resource in the same exact trace context.

This conservative rule prevents a partial topology from being mistaken for complete execution coverage.

## Agent-plan boundary

The existing compatibility `agent_plan` overlay is scalar: one diagnosis step maps to one route.

RFC 0068 does not silently collapse a multi-target fan-out back into one route.

If a target-aware routing projection contains multiple exact routes for one diagnosis/probe, the compatibility overlay fails closed and callers must consume the routing projection directly until the agent-plan contract gains first-class fan-out steps.

## Epistemic invariants

```text
runtime resource identity != topology target identity without explicit binding
same trace != causal responsibility
used resource != failed resource
multiple exact targets != ambiguity to be guessed away
unbound runtime resource != safe partial coverage
provider preference != target resolution
provider information gain != resource identity
route selected != evidence observed
```

## Non-goals

RFC 0068 does not add:

- heuristic database-name matching;
- automatic inference from Rails role names;
- a universal resource identity ontology;
- automatic writes or remediation;
- probabilistic resource selection;
- target selection based on provider availability;
- collapsing multiple runtime-used resources into one preferred target;
- rewriting runtime-resolved relationships as static dependencies.

## Proof

The bounded proof uses one active trace-backed database-latency observation.

The trace has exact runtime relationships to:

```text
pool:active_record.primary
pool:active_record.replica
```

The shop topology explicitly binds them to:

```text
db.orders.prod
db.payments.prod
```

The proof verifies:

```text
other-trace relationship
  -> ignored

same-trace primary + replica
  -> exact two-target set

probe.database.measure_query_latency
  -> fan out to both targets

RFC 0066
  -> provider.prometheus.orders-prod for orders
  -> provider.prometheus.payments-prod for payments

orders execution
  -> observed latency evidence

payments execution
  -> absent latency evidence

unbound runtime resource
  -> target resolution unresolved
  -> routing stops before provider selection
```

No OpenAI API is used.

## Next slice

The next useful slice is first-class multi-target execution lifecycle in the agent plan / MCP layer.

Today RFC 0068 can derive and project every exact route. The next contract should let one semantic probe step own a bounded fan-out execution set and collect all resulting evidence before causal reranking.

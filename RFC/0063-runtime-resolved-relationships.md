# RFC 0063: Runtime-resolved relationships

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Introduce a generic derived relationship layer for exact runtime resource use without rewriting static system facts

## Summary

RFC 0062 proved an important boundary on a real Rails multi-database application:

```text
static revision
  -> PoolController#multi_pool()
  -> primary pool exists
  -> replica pool exists
  -> exact code-to-pool assignment is unknown

runtime execution
  -> exact trace/span
  -> checkout primary / writing / default
  -> checkout replica / reading / default
```

The runtime observation is stronger for that concrete execution, but it does not make either resource an unconditional static dependency of the code symbol.

This RFC introduces a derived contract:

```text
concrete_system_facts
        +
concrete_runtime_facts
        |
        v
runtime_resolved_relationships
```

The first relationship is intentionally generic:

```text
execution X
  --used_resource-->
resource Y
```

For RFC 0063 the concrete source is an observed resource-pool checkout. Future projections may use other exact runtime interactions without changing the semantic rule.

## Why a new layer

There are now four distinct epistemic layers:

```text
1. Generic diagnostic knowledge
2. Concrete static system facts
3. Concrete runtime observations
4. Derived runtime-resolved relationships
```

The fourth layer is needed because raw transport observations such as an OpenTelemetry checkout event are too provider-specific for every causal profile to understand directly, while promoting them into static facts would be false.

The intended pipeline becomes:

```text
source/configuration
  -> concrete_system_facts

telemetry
  -> concrete_runtime_facts

static identity + exact runtime interaction
  -> runtime_resolved_relationships

runtime-resolved relationships + mechanism evidence
  -> X-Ray causal reasoning
```

## Core semantic rule

A runtime-resolved relationship is scoped to:

```text
system
revision
incident
execution
trace/span
observation time
```

It is not a timeless property of the code symbol.

Therefore:

```text
execution X used pool primary
!=
PoolController#multi_pool() always depends on primary
```

and:

```text
execution X used primary and replica
!=
static analysis proved two unconditional code-to-pool edges
```

## Contract

RFC 0063 adds `runtime_resolved_relationships`.

Example:

```json
{
  "kind": "runtime_resolved_relationships",
  "system_id": "rails-multi-database-app",
  "incident_id": "INC-RAILS-MULTI-DB",
  "relationships": [
    {
      "subject_execution": "execution.opentelemetry.0123456789abcdef",
      "code_symbol": "code:PoolController#multi_pool()",
      "relation": "used_resource",
      "object_resource": "pool:active_record.primary",
      "object_kind": "resource_pool",
      "interaction_kind": "resource_pool_checkout",
      "evidence_ref": "pool_interaction.opentelemetry.0123456789abcdef"
    }
  ]
}
```

The execution is the relationship subject. `code_symbol` is retained as execution context and for deterministic joins, not as the semantic subject of an unconditional relationship.

## Deterministic projection

For each concrete pool interaction Causcope requires all of the following before emitting a relationship:

1. static and runtime documents have the same system identity;
2. static and runtime documents have the same pinned revision identity;
3. the interaction references an existing runtime execution;
4. interaction and execution have identical code symbol, trace ID, and span ID;
5. the resource exists in the pinned static document;
6. the resource is a `resource_pool`;
7. runtime technology matches the static resource when statically known;
8. runtime provider-local `config_name` matches the static resource when statically known.

Any mismatch fails closed. There is no nearest-span matching, timing heuristic, `primary` fallback, fuzzy resource matching, or name-only recovery.

## Multiple resources per execution

Multiple relationships from one execution are expected and valid.

For the RFC 0062 Rails proof:

```text
execution E
  -> used_resource pool:active_record.primary
  -> used_resource pool:active_record.replica
```

This is precisely why a scalar `pool_id` on an execution is insufficient.

## Relationship provenance

Every relationship retains:

```text
exact execution ID
exact code symbol
exact resource ID
exact interaction evidence ID
trace ID
span ID
observation time
original trace source
```

The relationship is deterministic derived evidence. It does not erase the underlying runtime interaction.

## Relationship to RFC 0040

RFC 0040 introduces stable resource topology and provider-instance target binding.

RFC 0063 complements that model at runtime:

```text
RFC 0040
  -> what concrete resources exist and how instruments are bound to them

RFC 0063
  -> which concrete resource a specific execution actually used
```

Neither relationship is causal proof by itself.

## X-Ray integration boundary

Mechanism profiles should eventually depend on semantic runtime relationships instead of provider-specific transport structures when possible.

Conceptually:

```text
static candidate resources
  +
runtime relationship: execution used resource X
  +
mechanism-specific observation for resource X
  -> causal progression
```

RFC 0063 does not automatically rewrite every existing profile. It establishes and verifies the generic contract first so profile migration can happen independently and fail closed.

## Epistemic invariants

The following are explicit invariants:

```text
runtime observed use != static unconditional dependency
resource use != resource failure
resource use != causal responsibility
same resource type != same resource identity
same config name != same resource without pinned static identity
nearby timestamp != exact relationship
missing runtime relationship != proof the resource was not used
```

Unknown remains unknown.

## Proof

The real Rails multi-database CI from RFC 0062 is extended to project the observed primary and replica checkouts into exactly two runtime-resolved relationships for the same execution.

The proof also verifies fail-closed behavior by tampering with exact runtime identity and resource identity.

No OpenAI API is used.

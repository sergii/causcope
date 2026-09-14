# RFC 0040: Routing-aware agent plan and MCP surface

Status: Accepted
Date: 2026-09-14

## Context

Causcope already separates two decisions:

1. semantic probe ranking — which canonical probe is most discriminating for the current diagnosis;
2. instrument routing — which configured instrument can safely execute that probe for the selected scope.

Before this RFC, an MCP client could read the semantic `causcope://diagnosis/agent-plan`, but external diagnostic-provider routing was visible only through lower-level capability and router code. An agent therefore had to reconstruct the relationship between the top probe and the currently usable instrument itself.

## Decision

Add two read-only MCP resources through a routing-aware diagnosis adapter:

```text
causcope://diagnosis/instrument-routing
causcope://diagnosis/routed-agent-plan
```

The first projects routing for the current top-ranked canonical probe in every diagnosis partition. The second combines the existing validated compatibility agent plan and the routing projection in one envelope tied to the same incident and evidence revision.

The existing `causcope://diagnosis/agent-plan` remains unchanged for compatibility.

## Projection

For each diagnosis with a top-ranked probe, the routing projection records:

```text
scope
target
probe_id
selected instrument, if any
routing stop reason, if any
selection reason
agent action class
whether that action is currently executable over MCP
```

Agent action classes are:

- `begin_host_probe_session`
- `use_external_instrument`
- `stop`

A host executor selected by the router maps to the already-existing MCP begin/finish probe-session lifecycle. An external provider route is exposed as semantically ready but `mcp_execution_available: false` in this slice. Causcope must not pretend an MCP mutation exists when the server only exposes a read-only provider route.

## Invariants

```text
probe ranking != instrument routing
instrument availability != causal probability
route selection != causal authority
read-only discovery != execution permission
provider evidence != root cause
```

Routing never changes hypothesis ranking or canonical probe rank.

The routing projection is recomputed from the same diagnosis snapshot revision that the agent plan references. Consumers must not combine a route from one evidence revision with a plan from another.

## Scope safety

The router retains RFC 0039 behavior:

- external providers with `fixed_exact` scope must exactly match diagnosis scope;
- unavailable and unknown instruments are not automatically selected;
- host-global `/proc` observations are not relabeled into service, tenant, or dependency scope without an explicit binding contract;
- only canonical `risk: read_only` probes are routable.

## MCP adapter

`scripts/routing_mcp_server.py` subclasses the existing diagnosis MCP server and therefore preserves the normal diagnosis, status, agent-plan, and host capability resources. It adds the two routing-aware resources without changing the base server contract.

The CLI accepts an optional configured pgbot adapter/report pair. This represents an already-produced provider result and does not invoke pgbot during resource discovery.

Example:

```bash
python scripts/routing_mcp_server.py \
  --snapshot diagnosis.json \
  --pgbot-adapter examples/adapters/pgbot/postgresql.yaml \
  --pgbot-report pgbot-report.json
```

## Why a composite resource instead of changing agent-plan v0.1

The existing agent-plan schema is already consumed by MCP clients and encodes host probe-session lifecycle behavior. Replacing its execution semantics with external-provider semantics would make compatibility ambiguous.

The routed envelope makes the composition explicit:

```text
validated compatibility agent plan
        +
validated instrument routing projection
        ↓
routed agent plan
```

A later version may promote routing fields into a new agent-plan schema once direct external-provider MCP execution and host/entity binding are defined.

## Non-goals

This RFC does not:

- expose direct external-provider execution as an MCP mutation;
- change the semantic ranking algorithm;
- assign evidence-quality scores to providers;
- choose instruments by monetary cost or latency;
- add host-to-service scope binding;
- permit write or remediation actions.

## Next slice

The next useful slice is a controlled MCP mutation for a selected `execution_mode=direct` external provider. It should require the exact current diagnosis revision, exact routed probe, exact scope, and exact selected instrument, then append canonical runtime evidence and recompute diagnosis atomically.

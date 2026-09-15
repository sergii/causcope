# RFC 0069: Multi-target execution-set lifecycle

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Execute one semantic read-only probe across an exact runtime-resolved target set, compose all returned evidence, and rerank once

## Summary

RFC 0068 runtime target-aware investigation can derive multiple exact routes for one semantic probe:

```text
probe.database.measure_query_latency
  -> db.orders.prod / provider.prometheus.orders-prod
  -> db.payments.prod / provider.prometheus.payments-prod
```

The old routed MCP tool commits and reranks after one route. Running it twice would make the second execution depend on the first rerank and would no longer represent one bounded diagnostic question.

RFC 0069 adds a first-class execution set:

```text
one semantic probe
  -> bounded exact target members
  -> execute every read-only member
  -> compose all member evidence
  -> one incident-state commit
  -> one causal rerank
```

## Execution set

`routed_agent_plan` now exposes `execution_sets` derived from target-aware routing.

Each set is bound to:

```text
incident_id
evidence_revision
scope
diagnosis_target
probe_id
exact target_resource members
exact selected instrument IDs
supporting runtime relationship IDs
```

The stable `execution-set.<hash>` identity changes when any of those route identities changes.

A ready set advertises exactly one operation:

```text
causcope.instrument.execute_set
```

with only:

```text
incidentId
evidenceRevision
executionSetId
```

The server re-derives the current set before execution. Callers do not get to submit their own target or instrument list.

## Atomic Causcope state transition

The members are diagnostic reads, not state-changing remediation.

Causcope executes the members in deterministic target order and keeps their results outside incident state until every member succeeds.

Only then does it:

```text
existing runtime evidence
  + member evidence A
  + member evidence B
  + ...
  -> canonical composition
  -> evidence revision N + 1
  -> diagnosis snapshot N + 1
  -> one crash-recoverable incident commit
```

Therefore:

```text
member reads may have happened
!=
partial diagnostic state was committed
```

If any member fails, no new runtime-evidence document and no new diagnosis snapshot are committed.

## Rerank boundary

The contract is explicit:

```text
rerank_policy: after_all_members
atomic_evidence_commit: true
failure_policy: no_state_commit_on_member_failure
```

This avoids order-dependent diagnosis such as:

```text
orders probe
  -> rerank
  -> payments probe is no longer selected
```

when the original diagnostic question was intentionally:

```text
measure this observation across every exact resource used by the execution
```

## Staleness and route drift

Before execution, the controller revalidates:

```text
incident ID
evidence revision
execution-set identity
current top-ranked probe
current target set
current provider selection for every target
```

If any item changed, the set is stale and execution fails closed.

This includes provider drift. An execution set that named `provider.prometheus.orders-prod` cannot silently execute a newly preferred pgbot route.

## Target provenance

Every member result must preserve:

```text
routing.target_resource
```

and it must exactly match the member target.

Cross-target evidence cannot be committed through the set controller.

## Relationship to the compatibility agent plan

The original `agent_plan` remains unchanged and continues to model host probe sessions and scalar compatibility behavior.

`routed_agent_plan` adds `execution_sets` as the first-class representation for target-aware direct-provider fan-out.

This avoids forcing multi-target provider execution into the older one-step/one-session shape.

## MCP surface

`RoutingDiagnosisMcpServer` can receive a target-aware routing projection provider.

When present:

```text
causcope://diagnosis/instrument-routing
  -> exact multi-target routes

causcope://diagnosis/routed-agent-plan
  -> compatibility plan
  + routing
  + bounded execution_sets
```

A `RoutedExecutionSetToolController` implements:

```text
causcope.instrument.execute_set
```

using the same incident mutation claim and crash-recoverable commit machinery as existing routed execution.

## Failure semantics

A set is blocked when any member is not:

```text
exact-target resolved
safe
available
direct-execution capable
MCP-executable
```

A ready set becomes non-executable if the current revision or route changes.

During execution, any of the following aborts the whole state transition:

```text
member route changed
member instrument changed
member provider read failed
member returned no canonical evidence
member evidence target provenance mismatched
a member would contribute no new canonical instance
```

No partial Causcope evidence commit occurs.

## Proof

The bounded proof uses one trace that resolved to:

```text
db.orders.prod
db.payments.prod
```

for one query-latency probe.

It verifies:

```text
routed_agent_plan
  -> one ready execution set
  -> two exact members

one MCP tools/call
  -> both providers execute
  -> orders evidence + payments evidence
  -> evidence revision 7 -> 8 exactly once
  -> rerank_count = 1

second member failure
  -> tool error
  -> evidence file unchanged
  -> diagnosis file unchanged

reusing the old set after revision advance
  -> stale revision failure
```

No OpenAI API is used.

## Non-goals

RFC 0069 does not add:

- parallel threads or distributed job scheduling;
- retries across failed members;
- writes or remediation;
- partial-success commits;
- heuristic target selection;
- provider selection changes inside a set;
- a replacement for the existing host probe-session lifecycle.

## Next slice

The next useful extension is durable execution-set journaling if provider fan-out needs to survive process crashes between member reads. The current proof guarantees one durable Causcope state transition, but the in-memory member-read phase itself is intentionally synchronous and bounded.

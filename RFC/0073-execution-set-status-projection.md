# RFC 0073: Execution-set status projection

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Project operator-facing lifecycle state from current routed execution sets and durable execution-set journals

## Summary

RFC 0069 introduced bounded multi-target execution sets and RFC 0071 made member reads durable across process restarts.

The remaining operator problem was visibility.

Before this RFC, understanding whether a set was untouched, partially journaled, ready for its final commit, already committed, or abandoned by route/revision drift required reading raw JSONL journal files and reconstructing state manually.

RFC 0073 adds a deterministic read-only projection:

```text
current routed execution sets
+
verified durable execution-set journals
  ->
routed_execution_set_status
```

The lifecycle states are:

```text
pending
in_progress
ready_to_commit
committed
stranded
```

The projection is exposed through both a CLI and MCP.

## Why this is a projection

The journal remains the durable staging record.

The status document does not become another source of truth and is never persisted by the execution controller.

It is rebuilt from:

1. the current `routed_execution_sets` projection for the active incident revision;
2. verified RFC 0071 journal files in the configured execution-set state directory.

Therefore:

```text
journal / routed plan = source facts
status projection = operator view
```

## State semantics

### pending

The execution set is present in the current routed plan but has no journal yet.

A ready routed set is executable.

A blocked routed set may also be reported as `pending`, but its `executable` flag is false and the route-blocking reason is preserved.

### in_progress

The current execution set has a verified `set_started` journal and fewer than all members have a durable `member_succeeded` event.

Example:

```text
members: 2
journaled: 1
remaining: 1
state: in_progress
```

A current, route-valid in-progress set remains executable because the controller can resume it.

### ready_to_commit

Every member of the current execution set has a verified durable `member_succeeded` event, but no `set_committed` event exists yet.

This state means provider reads do not need to be repeated.

The remaining work is:

```text
compose journaled canonical evidence
-> crash-recoverable incident-state commit
-> one causal rerank
-> append set_committed
```

### committed

A verified `set_committed` journal event exists.

Committed sets remain visible even after the incident advances to a newer evidence revision and the old revision-bound execution set disappears from the current routed plan.

This is why the projection scans historical journals rather than looking only at current routes.

### stranded

A durable execution-set journal exists but cannot safely continue as a current set.

The first bounded cases are:

```text
unfinished journal
+ set no longer present in current routed plan
= stranded
```

or:

```text
current set
+ journal integrity / exact contract validation failure
= stranded
```

A stranded set is never advertised as executable.

## Current vs historical

Each projected set carries:

```text
current: true | false
current_route_state: ready | blocked | null
evidence_revision
```

A current item is derived from the active `routed_execution_sets` document.

A historical item is reconstructed from a verified journal that belongs to the same incident but whose execution-set ID is no longer in the active plan.

This enables the normal successful transition:

```text
revision 7
execution-set.X -> committed

revision 8
execution-set.X no longer current
but status still reports:
  current: false
  state: committed
```

## Progress

The status projection does not expose raw canonical evidence stored in `member_succeeded`.

Instead it exposes bounded operational metadata:

```text
total_members
completed_members
remaining_members

member:
  ordinal
  target_resource
  instrument_id
  state: pending | succeeded
  produced_instance_ids
```

This is enough for an operator or agent to answer:

```text
what is done?
what remains?
which exact target/provider completed?
can the set resume?
```

without dumping telemetry payloads.

## Integrity

Journal metadata is projected as:

```text
present
integrity: absent | verified | invalid
event_count
head_hash
```

For a current set, a journal verification or exact current-set contract failure is surfaced as:

```text
state: stranded
integrity: invalid
executable: false
```

The projection does not bypass RFC 0071 fail-closed behavior.

An invalid non-current journal is not attributed to the current incident because its contents cannot be trusted enough to establish ownership.

## MCP surface

`RoutingDiagnosisMcpServer` exposes:

```text
causcope://diagnosis/execution-set-status
```

The resource is private, read-only, and recomputed from the same current routing projection used by the routed agent plan plus the execution-set journal directory.

It does not add a mutation tool.

## CLI surface

The projection can be inspected without MCP:

```bash
python scripts/routed_execution_set_status.py \
  --execution-sets routed-agent-plan.json \
  --state-dir .causcope/execution-sets \
  --pretty
```

`--execution-sets` accepts either:

```text
routed_execution_sets
routed_agent_plan
```

JSON.

## Contract

`schema/routed-execution-set-status.schema.json` is strict.

Each item exposes:

```text
execution_set_id
incident_id
evidence_revision
current
current_route_state
state
executable
reason
diagnosis_target
probe_id
progress
members
journal
started_at
updated_at
committed_at
```

The root exposes counts for every lifecycle state plus current/historical totals.

The implementation additionally validates count invariants so summary and member progress cannot silently disagree.

## Failure and security semantics

The status projection does not:

- execute providers;
- append journal events;
- mutate runtime evidence;
- mutate diagnosis snapshots;
- rerank hypotheses;
- repair invalid journals;
- make a stranded set executable;
- infer journal ownership from an invalid historical file;
- expose the `runtime_evidence` payload stored in member journal events.

All routing and execution authority remains in the existing RFC 0069/RFC 0071 controller.

## Proof

The bounded proof covers:

```text
current + no journal
  -> pending

set_started
  -> in_progress 0/N

one member_succeeded
  -> in_progress 1/N

all member_succeeded
  -> ready_to_commit

set_committed + incident revision advances
  -> historical committed remains visible

unfinished journal + current plan moves on
  -> stranded

tampered current journal
  -> stranded + integrity invalid + executable false

CLI
  -> emits status projection without raw runtime evidence

MCP
  -> advertises and returns execution-set-status resource
```

No OpenAI API is used.

## Next slice

The next useful layer is recovery policy on top of `stranded`.

The projection should stay descriptive.

A separate policy can later decide whether a stranded set is:

```text
safe_to_resume
safe_to_replay
requires_operator_review
superseded
garbage_collectable
```

without collapsing lifecycle truth and recovery authority into one field.

# RFC 0071: Durable execution-set journal

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Preserve successful read-only multi-target member results across process crashes without introducing partial causal-state commits

## Summary

RFC 0069 made one semantic probe over multiple exact targets atomic at the Causcope state boundary:

```text
member A read
member B read
compose
one evidence revision
one rerank
```

The remaining gap was the synchronous in-memory phase. A process crash after member A succeeded but before member B completed forced the whole provider fan-out to run again.

RFC 0071 adds a durable, revision-bound execution-set journal:

```text
set_started
member_succeeded(target A, canonical evidence)
member_succeeded(target B, canonical evidence)
set_committed
```

A restarted controller re-derives the same current execution set, verifies the journal hash chain and exact set contract, reuses already journaled canonical member evidence, executes only unfinished members, and still performs exactly one final incident-state commit and one causal rerank.

## Journal location

Each execution set receives one JSONL journal under the incident-state directory:

```text
<diagnosis-dir>/execution-sets/<executionSetId>.journal.jsonl
```

The path is derived internally from the current `executionSetId`. MCP callers cannot submit an arbitrary path.

## Event contract

Every event contains:

```text
schema_version
kind
sequence
event_type
recorded_at
incident_id
execution_set_id
evidence_revision
data
previous_hash
event_hash
```

The journal uses the same append-only hash-chain idea as RFC 0029:

```text
E1(hash=h1, previous=null)
E2(hash=h2, previous=h1)
E3(hash=h3, previous=h2)
```

Verification fails closed on invalid JSON, schema violations, sequence gaps, previous-hash mismatch, content-hash mismatch, identity drift, or duplicate transition keys.

## Revision-bound set identity

`set_started` persists the exact routed contract:

```text
semantic scope
diagnosis target
probe ID
member ordinal
exact target resource
exact instrument ID
supporting runtime relationship IDs
```

Resume is allowed only when this persisted contract exactly matches the currently re-derived execution set at the same evidence revision.

The journal therefore does not loosen RFC 0069 staleness rules. It makes one already-authorized set restartable.

## Durable member result

After a provider read succeeds, Causcope validates and normalizes it exactly as RFC 0069 requires:

```text
correct incident
non-empty canonical evidence
routing.target_resource matches member target
scope.attributes.target_resource matches member target
```

Only then is `member_succeeded` appended and fsynced.

Its data includes:

```text
ordinal
target_resource
instrument_id
produced_instance_ids
runtime_evidence
```

`runtime_evidence` is the already-normalized canonical evidence document. The journal does not persist provider credentials, query tokens, or arbitrary transport state.

## Resume behavior

On retry after a process crash:

```text
re-derive current set
verify current evidence revision
verify exact route contract
verify journal hash chain
for each member in deterministic order:
  if matching member_succeeded exists:
    validate stored canonical evidence
    reuse it
  else:
    execute provider read
    validate result
    append + fsync member_succeeded
compose every member result
one incident-state commit
append set_committed
```

A completed provider read is therefore not repeated merely because the controller process died later in the same bounded fan-out.

## Causal-state boundary remains unchanged

The journal is staging state, not diagnosis evidence.

Before every member succeeds:

```text
runtime-evidence.json unchanged
diagnosis snapshot unchanged
evidence_revision unchanged
```

A failed second member may leave the first member's successful result in the execution-set journal, but it still creates no partial Causcope evidence revision.

Only the final RFC 0069 commit changes causal state.

## Concurrency

The routed execution controller already holds the incident mutation filesystem claim for the complete call. Journal verification, append, resume, composition, and final commit all occur inside that claim.

This prevents cooperating Causcope processes from concurrently advancing the same incident execution set or assigning competing journal transitions.

No additional execution authority is introduced by the journal module itself.

## Retry identity

There may be only one:

```text
set_started
set_committed
```

per execution-set journal, and at most one `member_succeeded` per exact `target_resource`.

A repeated append with identical semantic data is idempotent. A repeated transition key with different data fails closed.

## Failure semantics

### Crash after `set_started`

Retry resumes with zero completed members.

### Crash after one or more `member_succeeded`

Retry reuses those canonical results and executes only unfinished members.

### Member provider failure

No causal-state commit occurs. Successfully journaled earlier members remain resumable for the same still-current revision-bound set.

### Journal corruption

Execution fails closed before stored member evidence is trusted.

### Crash during final incident commit

Existing `incident_state_commit` recovery remains authoritative for the evidence/snapshot transaction.

### Commit succeeds but `set_committed` append fails

The MCP call reports that incident state committed but journal finalization failed. On the next ordinary call the old `evidenceRevision` is stale, so the old set cannot execute again. Automatic cleanup/backfill of that stranded journal is deferred.

## Security boundary

RFC 0071 does not:

- select a new probe;
- select a new target;
- change provider choice during resume;
- execute writes or remediation;
- store database credentials;
- accept a caller-controlled journal path;
- turn journaled evidence into causal state before all members succeed;
- bypass evidence-revision or route-staleness checks.

## Proof

The bounded test simulates:

```text
orders provider executes
orders canonical evidence fsynced to journal
process crash
```

and verifies:

```text
runtime evidence unchanged
diagnosis snapshot unchanged
orders provider call count = 1
```

A new controller then runs with the same persisted files:

```text
orders -> reused from journal, not executed again
payments -> provider executes once
both results -> compose
revision 7 -> 8 once
rerank_count = 1
set_committed appended
```

A second proof tampers with a journaled target while leaving the original event hash unchanged and verifies that journal verification fails closed.

No OpenAI API is used.

## Non-goals

This slice does not add:

- parallel/distributed member scheduling;
- remote journal replication;
- automatic garbage collection of old execution-set journals;
- automatic backfill when final state commits but journal finalization does not;
- provider-specific retry policy;
- time-based retry scheduling;
- partial-success causal-state commits.

## Next slice

The next useful layer is an execution-set status/read projection so operators and agents can inspect `pending`, `journaled`, `committed`, or stranded sets without reading filesystem JSONL directly.

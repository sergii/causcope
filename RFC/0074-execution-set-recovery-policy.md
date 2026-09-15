# RFC 0074: Execution-set recovery policy

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Deterministically classify journaled routed execution sets without granting new execution or cleanup authority

## Summary

RFC 0073 made durable execution-set lifecycle visible. It deliberately stopped at descriptive truth:

```text
pending
in_progress
ready_to_commit
committed
stranded
```

This RFC adds a separate advisory recovery-policy projection for journaled sets:

```text
safe_to_resume
safe_to_replay
requires_operator_review
superseded
garbage_collectable
```

Lifecycle state and recovery policy remain separate concepts.

```text
status = what happened / where the set is
recovery = what is safe to do next
```

The recovery projection never executes a provider, mutates incident state, repairs a journal, or deletes a journal.

## Classification semantics

### safe_to_resume

The journal belongs to the exact current revision-bound execution set, verifies successfully, and the current route remains ready and executable.

This applies to current `in_progress` and `ready_to_commit` sets.

The existing RFC 0071 controller remains the only execution authority. It may reuse already journaled canonical member evidence and execute only unfinished members.

### safe_to_replay

A historical unfinished journal cannot be resumed because its evidence revision is stale. However, the current routed plan contains an exact equivalent execution-set contract:

```text
same semantic scope
same diagnosis target
same probe
same exact target resources
same exact instrument IDs
same supporting runtime relationships
```

and that current set is route-ready.

The safe action is to execute the current set from scratch. Old journaled member evidence is not copied into the new revision.

This distinction is intentional:

```text
resume = reuse durable results inside the same revision-bound set
replay = run a newly authorized current set without reusing stale results
```

### requires_operator_review

Automatic recovery is not justified. Bounded examples include:

- journal integrity failure;
- exact current-set contract validation failure;
- a journaled current set whose route is no longer executable;
- an equivalent current contract exists but is blocked;
- an unexpected journaled current lifecycle state.

No stored evidence from an invalid journal is trusted.

### superseded

A verified historical unfinished journal no longer has an exact equivalent contract in the current routed plan.

Its member results are stale staging data and must not be reused. The classification is descriptive; it does not delete the journal.

### garbage_collectable

A historical verified journal already records `set_committed`.

It no longer participates in recovery and may become eligible for a future retention/garbage-collection policy.

`garbage_collectable` is not deletion authority. The projection always emits:

```text
automatic_cleanup_allowed: false
```

so audit retention and physical cleanup remain separate decisions.

## Contract equivalence

Replay equivalence uses the RFC 0071 persisted execution-set contract rather than comparing only probe IDs or target names.

The contract includes:

```text
scope
diagnosis_target
probe_id
members:
  ordinal
  target_resource
  instrument_id
  supporting_relationship_ids
```

The current execution-set ID is intentionally not part of the comparison because the ID includes `evidence_revision` and therefore changes across revisions.

## Projection inputs

```text
current routed_execution_sets
+
RFC 0073 execution-set status
+
verified RFC 0071 set_started contracts
  ->
routed_execution_set_recovery
```

Only journaled sets are candidates. A current `pending` set with no journal is not a recovery problem.

## Security and authority boundary

Every candidate carries:

```text
advisory_only: true
automatic_cleanup_allowed: false
```

The projection does not create a new MCP mutation tool and does not make stale execution-set IDs executable.

For `safe_to_resume`, the exact current set must still be independently executable through the existing routed execution controller.

For `safe_to_replay`, the projection points only to the equivalent current execution-set ID; callers must still use the current routed plan and its revision-bound execution contract.

## CLI

```bash
python scripts/routed_execution_set_recovery.py \
  --execution-sets routed-agent-plan.json \
  --state-dir .causcope/execution-sets \
  --pretty
```

The CLI exposes policy metadata only and never emits journaled `runtime_evidence`.

## MCP

`RoutingDiagnosisMcpServer` exposes the same read-only projection at:

```text
causcope://diagnosis/execution-set-recovery
```

This is a resource, not a tool.

## Proof

The bounded tests cover:

```text
current verified partial journal
  -> safe_to_resume

historical unfinished journal
+ exact equivalent current ready contract
  -> safe_to_replay

historical unfinished journal
+ no exact equivalent current contract
  -> superseded

invalid current journal
  -> requires_operator_review

historical committed journal
  -> garbage_collectable
  -> automatic_cleanup_allowed=false

CLI/MCP
  -> read-only projection
  -> no raw runtime_evidence exposure
```

No OpenAI API is used.

## Non-goals

This RFC does not add:

- automatic deletion;
- retention windows;
- provider-specific retry timing;
- copying evidence across revisions;
- repair of corrupted journals;
- automatic execution from the recovery projection;
- distributed recovery scheduling.

## Next slice

The recovery policy closes the durable multi-target lifecycle loop enough for an end-to-end vertical proof:

```text
incident
-> causal hypothesis
-> semantic probe
-> target-aware provider routing
-> multi-target execution set
-> durable member journal
-> atomic evidence commit
-> rerank
-> lifecycle status
-> deterministic recovery guidance
```

The next work should prove that complete path as one operator-visible scenario rather than add another lifecycle abstraction.

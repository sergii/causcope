# RFC 0071: Event-sourced recommendation session journal

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Persist recommendation reasoning as an append-only revisioned lifecycle without creating a second mutable source of truth

## Summary

Causcope now has a durable recommendation session for one exact architecture candidate:

```text
system + revision + incident + recommendation + subject resource + query object
        ↓
recommendation-session.<hash>.journal.jsonl
        ↓ verify hash chain + replay
recommendation_session projection
```

The journal records:

```text
session_started
action_result_recorded
```

`action_result_recorded` is typed by the current RFC 0067 `next_action`:

```text
read_only_probe
operator_question
safe_experiment
human_decision
stop_candidate
```

The journal does not execute any of these actions. It records their bounded result together with the deterministic recommendation and information-gap projections that follow.

## Why event-sourced

A recommendation lifecycle should survive process restarts and parallel agents, but a mutable `session.json` plus a separate audit log would create two competing truths.

RFC 0071 therefore derives current session state only by replaying the verified append-only journal.

There is no independently mutable recommendation-session state file.

## Identity

A session is bound to:

```text
system_id
revision
incident_id
recommendation_id
subject_resource
query_object
```

The stable session ID is the first 16 hex characters of SHA-256 over canonical JSON for that identity:

```text
recommendation-session.<16 hex>
```

The provider instance is deliberately not part of session identity. A recommendation candidate is about an exact system revision, incident, resource and query object; evidence may later be reacquired through a different compatible provider without creating a different architecture candidate.

Provider identity is still checked where it matters. The RFC 0070 read-only acquisition result must match the provider pinned by the current recommendation projection.

## Event integrity

RFC 0071 reuses the RFC 0029 journal invariants:

```text
sequence = 1, 2, 3, ...
previous_hash = prior event_hash
event_hash = SHA-256(canonical event without event_hash)
```

Verification fails closed on:

- invalid JSON or event schema;
- sequence gaps or reordering;
- previous-hash mismatch;
- event-hash mismatch;
- session identity drift;
- a non-deterministic information-gap projection;
- an action result that does not match the prior `next_action`;
- an event after terminal session closure.

The hash chain is tamper-evident, not a cryptographic signature of actor identity.

## Concurrency and revision checks

Every successful action result is conditional on:

```text
expected_session_revision == current_session_revision
```

Appending is serialized with the existing process-safe filesystem claim primitive. RFC 0071 intentionally does not introduce a second lock implementation.

Two cooperative agents cannot both advance revision 3 to different revision 4 events.

A retry of the exact immediately preceding action result is idempotent and returns the existing journal event. A conflicting retry at the stale revision fails closed.

## Snapshot semantics

Every event carries a snapshot containing:

```text
architectural_recommendation_projection
recommendation_information_gap_projection
```

The information-gap projection is recomputed from the recommendation projection during verification. A caller cannot journal an arbitrary `next_action` or maturity state that RFC 0067 would not produce.

The session projection exposes:

```text
session_revision
status
recommendation_state
information_gap_status
next_action
started_at
updated_at
head_hash
```

## Read-only probe results

RFC 0070 is the first executable action-result integration.

For `read_only_probe`, replay requires the embedded `recommendation_evidence_acquisition_result` to match:

- system/revision/incident/recommendation/resource identity;
- the prior recommendation state;
- the exact current probe ID and requested observation;
- the exact target resource;
- the provider instance pinned by the prior recommendation projection;
- the resulting recommendation state;
- the resulting information-gap status and next action;
- the `progressed` flag implied by the before/after snapshots.

Thus a fresh exact RFC 0070 acquisition can durably record:

```text
NO_PROBLEM_EVIDENCE
  → read_only_probe
  → INSUFFICIENT_CONTEXT
  → operator_question
```

A stale acquisition may also be journaled, but it cannot fake progression because the deterministic next snapshot remains unchanged.

## Operator answers

`operator_question` records:

```text
gap_id
source = human
answer
```

The answer is provenance, not automatically trusted semantic truth.

The journal does not parse free text into business facts. Recommendation maturity changes only if the separately structured recommendation context, when projected deterministically, actually changes the recommendation and information-gap projections.

This preserves the epistemic boundary:

```text
human statement != verified system fact
```

## Safe experiment results

`safe_experiment` records a result reference and a reported outcome:

```text
demonstrated
not_demonstrated
inconclusive
```

The journal does not run the experiment.

Replay requires the deterministic resulting recommendation state to agree with the reported outcome:

```text
demonstrated      → READY_FOR_HUMAN_REVIEW
not_demonstrated  → BENEFIT_NOT_DEMONSTRATED
inconclusive      → remains experiment-required / estimated-benefit
```

When the next recommendation projection carries `benefit.evidence_ref`, it must equal the recorded experiment result reference.

## Human decision and stop semantics

`human_decision` is allowed only when RFC 0067 exposes the human-decision boundary. It may close the session as:

```text
approved
rejected
```

The decision cannot rewrite recommendation evidence or maturity. Approval means only that a human approved the candidate for a separately controlled implementation workflow.

`stop_candidate` similarly closes a rejected candidate as `stopped` without changing evidence.

No additional events are permitted after terminal closure.

## Session status

The replayed status is distinct from recommendation maturity:

```text
active
awaiting_human_decision
candidate_rejected
approved
rejected
stopped
```

This prevents the architecture recommendation state from being overloaded with workflow lifecycle semantics.

## Filesystem layout

A caller supplies a recommendation session directory. Each exact candidate has one journal:

```text
<session-dir>/recommendation-session.<id>.journal.jsonl
```

Inspection is read-only:

```bash
python scripts/recommendation_session_journal.py \
  --session-dir /tmp/causcope-recommendations \
  --session-id recommendation-session.<id> \
  --pretty
```

## Security boundary

RFC 0071 does not:

- execute shell commands;
- execute probes by itself;
- run experiments;
- mutate a database or schema;
- apply normalization or denormalization;
- treat an operator answer as automatically true;
- grant provider findings causal authority;
- bypass human approval;
- turn a recommendation into an implementation plan automatically.

It persists and verifies recommendation reasoning transitions that were produced through existing bounded surfaces.

## Failure semantics

The journal is the recommendation-session source of truth, so one append is the state transition.

An action result is visible only after its event has been appended and fsynced. Replay always verifies the complete chain before returning current session state.

Unlike the RFC 0029 probe audit trail, there is no separate mutable recommendation-session state commit that can succeed while its corresponding journal append fails.

## Proof

The RFC 0071 proof covers:

1. session creation from a deterministic recommendation/gap snapshot;
2. RFC 0070 fresh read-only evidence progression;
3. idempotent retry of the exact prior action result;
4. stale conflicting revision rejection;
5. human operator answer followed by deterministic next-gap progression;
6. safe experiment progression to `READY_FOR_HUMAN_REVIEW`;
7. explicit human approval without evidence rewrite;
8. explicit stopping of a candidate whose benefit was not demonstrated;
9. wrong action-kind rejection;
10. hash-chain tampering detection.

## Next step

The next coherent layer is to expose this session through the existing investigator CLI/MCP front door so an agent can resume the exact recommendation revision after restart and can submit only the action kind currently authorized by the session.

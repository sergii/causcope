# RFC 0072: Event-sourced recommendation session journal

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

The journal records `session_started` and `action_result_recorded`. Action results are typed by the current RFC 0067 `next_action`:

```text
read_only_probe
operator_question
safe_experiment
human_decision
stop_candidate
```

The journal does not execute these actions. It persists their bounded result together with the deterministic recommendation and information-gap projections that follow.

RFC 0071 separately added durable journaling for multi-target execution sets. RFC 0072 uses the same event-integrity model but keeps recommendation semantics separate because execution-set recovery and architecture-decision lifecycle have different identities and transition rules.

## Why event-sourced

A mutable `session.json` plus a separate audit log would create two competing truths. RFC 0072 therefore derives current recommendation-session state only by replaying the verified append-only journal.

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

The provider instance is deliberately not part of the candidate identity. Provider identity is checked at evidence-acquisition time against the provider pinned by the current recommendation projection.

## Event integrity

RFC 0072 follows the existing journal protocol used by RFC 0029 and RFC 0071:

```text
sequence = 1, 2, 3, ...
previous_hash = prior event_hash
event_hash = SHA-256(canonical event without event_hash)
```

Verification fails closed on invalid JSON/schema, sequence gaps, hash mismatch, identity drift, a non-deterministic information-gap projection, an action result that does not match the prior `next_action`, or any event after terminal closure.

The hash chain is tamper-evident. It is not an actor signature.

## Concurrency and revisions

Every action result is conditional on:

```text
expected_session_revision == current_session_revision
```

Appending is serialized with the existing process-safe filesystem claim primitive. RFC 0072 does not introduce another lock implementation.

A retry of the exact immediately preceding action result is idempotent. A conflicting retry at a stale revision fails closed.

## Snapshot semantics

Every event carries:

```text
architectural_recommendation_projection
recommendation_information_gap_projection
```

During replay, Causcope recomputes the information-gap projection from the recommendation projection. A caller cannot journal an arbitrary maturity state or next action that RFC 0067 would not produce.

The replayed session exposes:

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

## RFC 0070 read-only evidence integration

For `read_only_probe`, the embedded RFC 0070 acquisition result must match:

- system/revision/incident/recommendation/resource identity;
- the prior recommendation state;
- the exact probe and requested observation;
- the exact target resource;
- the provider instance pinned by the prior recommendation projection;
- the resulting recommendation state and information-gap status;
- the resulting next action;
- the before/after-derived `progressed` flag.

This makes the following transition durable:

```text
NO_PROBLEM_EVIDENCE
  → read_only_probe
  → INSUFFICIENT_CONTEXT
  → operator_question
```

Stale evidence can be recorded, but cannot fake maturity progression.

## Operator answers

`operator_question` records an exact `gap_id`, `source = human`, and the human answer.

The answer is provenance, not automatically trusted system truth. The journal does not parse free text into facts. Recommendation maturity changes only if separately structured recommendation context produces a different deterministic projection.

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

The journal does not execute the experiment. Replay requires the resulting deterministic state to agree with the reported outcome:

```text
demonstrated      → READY_FOR_HUMAN_REVIEW
not_demonstrated  → BENEFIT_NOT_DEMONSTRATED
inconclusive      → remains experiment-required / estimated-benefit
```

When the resulting recommendation carries `benefit.evidence_ref`, it must equal the recorded experiment result reference.

## Human decision and stop semantics

`human_decision` may close a session as `approved` or `rejected` only when RFC 0067 exposes the human-decision boundary. It cannot rewrite recommendation evidence or maturity.

Approval means only that a human approved the candidate for a separately controlled implementation workflow.

`stop_candidate` closes a candidate whose benefit was not demonstrated as `stopped`, again without rewriting evidence.

No further events are allowed after terminal closure.

## Session status

Workflow status stays distinct from recommendation maturity:

```text
active
awaiting_human_decision
candidate_rejected
approved
rejected
stopped
```

## Filesystem layout

Each exact candidate has one journal:

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

RFC 0072 does not execute shell commands, probes, or experiments; mutate databases or schemas; apply normalization/denormalization; treat operator answers as automatically true; grant provider findings causal authority; bypass human approval; or turn a recommendation into an implementation automatically.

## Proof

The bounded proof covers:

1. deterministic session creation;
2. RFC 0070 fresh read-only evidence progression;
3. idempotent retry of the exact prior result;
4. stale conflicting revision rejection;
5. operator answer followed by deterministic next-gap progression;
6. safe experiment progression to human review;
7. explicit human approval without evidence rewrite;
8. explicit stopping of a failed candidate;
9. wrong action-kind rejection;
10. hash-chain tampering detection.

## Next step

Expose recommendation sessions through the existing investigator CLI/MCP front door so an agent can resume the exact recommendation revision after restart and may submit only the action kind currently authorized by the session.

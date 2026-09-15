# RFC 0066: Recommendation information-gap ranking

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Turn recommendation uncertainty into a deterministic next question, read-only probe, experiment plan, or terminal human action

## Summary

RFC 0065 deliberately returns `INSUFFICIENT_CONTEXT` when PostgreSQL evidence is not enough to justify a data-model recommendation.

That state is epistemically correct, but it is not yet operationally useful enough.

A user should not have to inspect a JSON document and reverse-engineer what Causcope needs next.

RFC 0066 adds a derived projection:

```text
architectural_recommendation_projection
                |
                v
recommendation_information_gap_projection
```

The projection answers:

```text
What information is missing?
Which missing item has the highest decision leverage?
What is the safest next action for obtaining it?
```

The first proof is bounded to:

```text
recommendation.database.denormalize_read_model
```

No architecture change is executed.

## Diagnostic probes and recommendation gaps are different rankings

Causcope already has deterministic `probe_ranking` for causal diagnosis.

That ranking asks:

```text
Which probe best discriminates the current causal hypotheses?
```

Recommendation information-gap ranking asks a different question:

```text
Which missing fact most efficiently determines whether this architecture candidate
should advance, change shape, be measured, or stop?
```

These projections MUST remain separate.

```text
probe_ranking
  -> causal discrimination

recommendation_information_gap_projection
  -> architecture-decision information acquisition
```

An architecture gap must never enter root-cause ranking merely because it is currently the most important unanswered question.

## Acquisition kinds

RFC 0066 distinguishes three information-acquisition kinds:

```text
operator_question
read_only_probe
safe_experiment
```

They have different authority boundaries.

### Operator question

Used when the missing information is business, ownership, consistency, or design intent that telemetry cannot safely invent.

Example:

```text
What is the source of truth?
What invariant must remain true?
How stale may the derived value be?
Is the duplicated value mutable state, a historical snapshot, or an intentional projection?
```

The answer is external input. Causcope must not fabricate it.

### Read-only probe

Used only when an existing catalog probe can produce the requested observation.

The first proof reuses:

```text
probe.database.measure_query_latency
  -> observation.database.query_latency
```

The information-gap projector validates that the referenced probe exists, is `read_only`, and produces the requested observation.

It does not execute the probe. Existing provider discovery, target-aware routing, and probe-execution layers remain the execution authority.

### Safe experiment

Used when semantics are known but benefit still needs to be demonstrated.

The projection may carry the already-defined bounded verification experiment into the next-action prompt, but it is an experiment plan only.

RFC 0066 does not authorize state-changing execution.

## Deterministic ordinal ranking

No probability score is introduced.

The bounded priority is:

```text
1. refresh active problem evidence
2. establish workload materiality
3. establish business semantics
4. define a bounded candidate change
5. establish maintenance semantics
6. quantify write/operational cost
7. define verification and rollback
8. demonstrate benefit
9. stable gap ID as deterministic tie-breaker
```

The ordering reflects decision leverage rather than generic importance.

For example, Causcope should determine whether a workload is material and whether the data semantics permit duplication before asking the user to invest in a benchmark.

## State mapping

RFC 0066 projects RFC 0065 recommendation states into next-action states.

```text
NO_PROBLEM_EVIDENCE
  -> EVIDENCE_REFRESH_REQUIRED
  -> read-only query-latency probe

INSUFFICIENT_CONTEXT
  -> INFORMATION_GAP
  -> ranked missing context

EXPERIMENT_REQUIRED
  -> EXPERIMENT_REQUIRED
  -> bounded experiment plan

ESTIMATED_BENEFIT
  -> EXPERIMENT_REQUIRED
  -> measured before/after evidence still needed

BENEFIT_NOT_DEMONSTRATED
  -> CANDIDATE_REJECTED
  -> stop candidate

READY_FOR_HUMAN_REVIEW
  -> HUMAN_REVIEW_READY
  -> human decision
```

This prevents a recommendation from surviving by inertia after its own verification experiment fails.

## First insufficient-context proof

The RFC 0065 fixture already has:

```text
fresh pgbot query slowdown
known dominant workload
bounded materialized-projection candidate
```

but is missing:

```text
business semantics
maintenance strategy
cost model
verification plan
```

RFC 0066 deterministically ranks:

```text
1. business semantics / consistency contract
2. maintenance semantics
3. maintenance cost
4. verification plan
```

The next action is therefore an `operator_question`, not another PostgreSQL probe:

```text
What is the source of truth,
what consistency invariant must remain true,
how stale may the derived value be,
and is the duplicated data mutable shared state,
a historical snapshot,
or an intentional projection?
```

This is the exact class of question that pgbot cannot answer from PostgreSQL performance evidence alone.

## Stale-evidence proof

If the RFC 0065 query-latency observation expires, recommendation maturity falls to:

```text
NO_PROBLEM_EVIDENCE
```

RFC 0066 then ranks fresh problem evidence ahead of all architecture questions and points to the existing cataloged read-only probe:

```text
probe.database.measure_query_latency
```

The projector checks the probe contract but does not run it.

## Benefit proof

When all semantics, maintenance, cost, and verification context exist but benefit is only expected:

```text
EXPERIMENT_REQUIRED
```

RFC 0066 emits a `safe_experiment` action.

When the benefit is planner- or benchmark-derived:

```text
ESTIMATED_BENEFIT
```

RFC 0066 still asks for measured before/after evidence.

Only after RFC 0065 reaches:

```text
READY_FOR_HUMAN_REVIEW
```

are information gaps empty. The next action becomes:

```text
human_decision
```

not automatic remediation.

## Fail-closed semantics

RFC 0066 fails closed when RFC 0065 emits a missing-assumption identifier for which no information-gap semantics exist.

It does not create a generic question such as:

```text
Tell me more about future.unknown_context
```

Instead the implementation must first define:

```text
what the gap means
why it matters
how it should be acquired
where it ranks
what authority boundary applies
```

Unknown remains unknown.

## Contract

The output records:

```text
system/revision/incident identity
recommendation and subject resource
source recommendation state
information-gap status
ranked gaps
one next action
ranking method
limitations
```

Each gap records:

```text
stable gap ID
category
rank
decision leverage
acquisition kind
question
why the gap matters now
whether it blocks progression
optional missing-assumption ID
optional catalog probe and requested observation
```

The next action records its execution boundary explicitly.

## Epistemic invariants

```text
missing business semantics != inferred business semantics
operator answer != runtime observation
question asked != question answered
probe recommended != probe executed
experiment planned != experiment run
planner estimate != measured production benefit
information-gap rank != causal rank
recommendation maturity != authorization to change production
```

## Non-goals

RFC 0066 does not add:

- a global uncertainty probability model;
- LLM-generated architecture questions;
- automatic execution of experiments;
- automatic schema changes;
- architecture questions as causal hypotheses;
- implicit conversion of operator answers into trusted facts;
- fuzzy mapping from unknown gap names to generic prompts.

## Proof

The CI proof verifies:

```text
incomplete business context
  -> INFORMATION_GAP
  -> business semantics ranked first

stale pgbot evidence
  -> EVIDENCE_REFRESH_REQUIRED
  -> existing read-only query-latency probe

expected benefit
  -> safe experiment plan

benchmark benefit
  -> measured result still required

measured full context
  -> HUMAN_REVIEW_READY
  -> human decision

failed benefit experiment
  -> CANDIDATE_REJECTED
  -> stop candidate

unknown missing-assumption semantics
  -> fail closed
```

No OpenAI API is used.

## Next slice

The next useful slice is transport exposure, not more recommendation heuristics.

The investigator CLI / MCP layer should be able to show, for one recommendation candidate:

```text
why the candidate is blocked
what exact information is missing
what Causcope recommends doing next
whether that next action is a question, an executable read-only probe, or an experiment plan
```

Read-only probe actions can then reuse the existing target-aware instrument-routing path instead of inventing a second execution mechanism.

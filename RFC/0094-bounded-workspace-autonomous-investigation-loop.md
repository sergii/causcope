# RFC 0094 - Bounded workspace autonomous investigation loop

Status: Implemented proof
Date: 2026-09-16
Depends on: RFC 0035, RFC 0069, RFC 0071, RFC 0087, RFC 0093

## Problem

`causcope why` can already choose and execute one uniquely preferred safe read-only execution set. After that atomic evidence commit it reranks, but the operator must invoke `why` again before Causcope can ask the next bounded diagnostic question.

That exposes an implementation boundary rather than a useful product boundary.

A single product invocation should be able to continue through several safe read-only discriminators while preserving the rule that every evidence revision is independently committed and reranked before the next question is selected.

## Decision

Normal canonical `causcope why` runs a bounded workspace investigation loop.

```text
current canonical diagnosis revision N
  -> causal verification already established? stop verified
  -> project exact safe read-only execution sets
  -> choose unique best semantic diagnostic question
  -> ambiguous best priority? stop ambiguous
  -> no executable read-only set? stop blocked
  -> revalidate exact revision + target + provider + route
  -> execute one existing RFC 0069 execution set
  -> journal provider results through RFC 0071
  -> atomically commit evidence revision N + 1
  -> rerank
  -> only now choose the next question
  -> repeat within the bounded mutation budget
```

The default proof budget is four evidence-acquisition commits per product invocation. The implementation supports a hard range of 1 through 16 internally; the product does not yet expose this as a required operator control.

## Stop contract

Every bounded loop terminates with one of four product-level reasons:

- `verified` - canonical intervention-based causal verification is already established after the current rerank;
- `blocked` - no current exact safe read-only execution set can be executed;
- `ambiguous` - multiple current diagnostic questions share the best semantic priority, so autonomous choice is not justified;
- `budget_exhausted` - another uniquely preferred safe question exists, but the invocation has consumed its mutation budget.

A more specific `stop_detail` preserves the underlying reason such as `semantic_priority_tie`, `no_read_only_ready_execution_set`, or `max_steps_reached`.

## Safety invariants

This loop is orchestration, not a new mutation authority.

It MUST NOT:

- execute non-read-only probes;
- choose by lexical probe, target, scope, provider, or execution-set identity;
- reuse a route from the previous evidence revision;
- bypass exact target resolution;
- bypass provider information-gain selection;
- bypass the RFC 0069 execution-set controller;
- bypass RFC 0071 journaling or atomic incident-state commit;
- perform two acquisitions against the same diagnosis revision;
- treat a provider read as successful unless the canonical evidence revision advances exactly once.

Every successful step must satisfy:

```text
previous evidence revision = N
committed evidence revision = N + 1
rerank happens at N + 1
next semantic selection is derived from N + 1
```

If an acquisition claims success without exactly one revision advance, the loop fails closed.

## Product projection

Normal JSON `causcope why` exposes the bounded run as:

```text
autonomous_investigation.kind = workspace_autonomous_investigation
autonomous_investigation.initial_evidence_revision
autonomous_investigation.final_evidence_revision
autonomous_investigation.stop_reason
autonomous_investigation.stop_detail
autonomous_investigation.steps[*]
```

Each step preserves the exact routed execution-set result that caused that revision transition. Human output renders each acquisition followed by one concise autonomous-investigation stop summary.

The historical single `acquisition` JSON field remains available when exactly one acquisition occurred so existing consumers do not need to migrate immediately. Multi-step consumers should use `autonomous_investigation.steps` / `acquisitions`.

## Relationship to RFC 0035

RFC 0035 established the earlier deterministic autonomous read-only loop over a statically supported probe executor. That remains useful for acceptance benchmarks and proves the semantic idea.

RFC 0094 moves the product continuation onto the canonical persisted workspace and current routing stack:

```text
RFC 0035
  in-memory evidence + static supported-probe executor

RFC 0094
  persisted canonical workspace
  + exact runtime target resolution
  + provider instance routing
  + information-gain provider choice
  + RFC 0069 execution sets
  + RFC 0071 durable journals
  + atomic evidence revisions
```

There is still one diagnosis engine and one canonical evidence state.

## Non-goals

This RFC does not add:

- automatic state-changing interventions;
- remediation;
- arbitrary provider retries;
- parallel execution of independent diagnostic questions;
- probabilistic stopping thresholds;
- a second diagnosis or ranking engine;
- an LLM requirement.

The loop remains deliberately bounded, sequential, deterministic, and read-only.

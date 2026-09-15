# RFC 0093 - Bounded multi-set acquisition selection

Status: Implemented proof
Date: 2026-09-16

## Problem

RFC 0092 made semantic-probe acquisition implicit in normal `causcope why`, but only when exactly one target-aware read-only execution set was ready.

A real investigation can contain more than one diagnosis partition or target. Each diagnosis can have its own top semantic probe and therefore its own ready execution set. Refusing all such states makes the product stop too early, while choosing by target name, probe ID, scope serialization, or execution-set ID would turn stable identity ordering into fake diagnostic evidence.

## Decision

Causcope may autonomously execute one of several ready execution sets only when the existing semantic probe-ranking dimensions identify a unique strictly better candidate.

The selection flow is:

```text
current canonical diagnosis revision N
  -> target-aware information-gain provider routing
  -> ready read-only execution sets
  -> recover each set's current top semantic probe candidate
  -> compare semantic discrimination priority
  -> unique best set?
       yes -> execute exactly that set
       no  -> do not mutate evidence
  -> existing revision-bound execution-set controller
  -> atomic evidence revision N+1
  -> rerank before any further acquisition
```

This is intentionally one bounded step. Causcope does not pre-plan a sequence of several execution sets against revision N because the first committed result can change the diagnosis, probe ranking, target resolution, provider route, or usefulness of every remaining set.

## Semantic priority

Cross-set selection reuses the existing deterministic probe-ranking dimensions, in the same order:

1. more top-candidate two-sided alternatives
2. more top-candidate contrast components
3. more top-candidate discriminated alternatives
4. more two-sided candidate pairs
5. more contrast components
6. more discriminated candidate pairs
7. lower probe risk
8. more hypotheses explicitly tested

The final in-diagnosis `probe_id` lexical tie-break is deliberately excluded from cross-set autonomous selection.

Probe IDs, diagnosis targets, scopes, target resources, provider IDs, and execution-set IDs are identities. They are not evidence that one diagnostic question is more informative than another.

Therefore two candidates with equal semantic priority remain ambiguous even if their IDs sort deterministically.

## Safety boundary

Only execution sets whose current semantic probe is `read_only` participate in implicit selection.

A selection result is not execution authority. The selected set still passes through the existing `RoutedExecutionSetToolController`, which re-derives and validates the current revision-bound set before execution. Existing exact-target checks, provider routing, information-gain provider choice, durable journal, atomic evidence commit, and rerank semantics remain authoritative.

If the selected set drifts before mutation, execution fails closed.

## Relationship to provider information-gain routing

This RFC answers a different question from RFC 0066.

RFC 0066 chooses the most informative safe provider for an already-selected semantic probe and exact target.

RFC 0093 chooses which one of several already-routable diagnostic questions may be asked next.

```text
semantic probe ranking
  -> RFC 0093: choose one diagnostic question across ready sets
  -> exact target
  -> RFC 0066: choose provider for that question and target
  -> execute
```

Neither layer claims probabilistic Shannon information gain. Both are deterministic evidence-backed contrast projections.

## Ambiguity

When several ready read-only sets share the same best semantic priority:

```text
selection.state = ambiguous
selection.reason = semantic_priority_tie
```

Normal implicit `causcope why` performs no acquisition in that state. It renders the current diagnosis without inventing a preference.

The hidden compatibility `--acquire` path also fails closed rather than using lexical order as an operator-independent tie-break.

## Non-goals

This proof does not add:

- a global investigation planner
- parallel execution of independent sets
- speculative multi-step plans against one evidence revision
- cost/latency/freshness weighting across diagnostic questions
- severity or business-impact prioritization
- LLM-based choice
- arbitrary lexical tie-breaking

Those dimensions can be added later only when represented as explicit evidence or policy.

## Acceptance contract

Tests lock the following behavior:

- two ready sets with different semantic priorities select the unique better set regardless of set/target/probe lexical order
- a semantic tie remains ambiguous and selects nothing
- blocked sets do not participate
- existing single-ready-set implicit acquisition still commits exactly one evidence revision through the canonical controller
- no external AI is required

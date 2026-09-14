# RFC 0044: Verification agent plan and instrument routing

- Status: Accepted
- Date: 2026-09-14

## Summary

Causcope verification is no longer only a passive evaluator. After a fix is recorded, the agent can map unresolved verification criteria to canonical read-only probes, route those probes to safe exact-scope instruments, execute direct providers, ingest the resulting post-fix evidence, and re-evaluate the original failing cohort.

```text
verification_contract
  -> evaluate current post-fix evidence
  -> unresolved criterion
  -> canonical probes that produce that observation
  -> Instrument Router, exact original scope, direct execution only
  -> execute selected read-only provider
  -> canonical runtime_evidence
  -> re-evaluate verification
  -> resolved | regressed | inconclusive
```

## Separation of concerns

The verification contract answers **what must be true before the incident may close**.

The canonical probe catalog answers **what measurement can establish that observation**.

The Instrument Router answers **which configured instrument can safely obtain it now**.

The verification agent does not change causal ranking and does not infer a different verification target because a convenient instrument exists.

## Agent plan

`verification_agent_plan` is deterministic and bound to:

- incident id;
- baseline evidence revision;
- original diagnosis target;
- exact original scope;
- fix timestamp;
- current verification outcome.

Each criterion records:

- canonical observation;
- current status;
- canonical read-only probes capable of producing it;
- selected probe, if any;
- exact routing decision, if any;
- next action.

Actions are:

```text
already_satisfied
regression_detected
execute_direct_probe
no_canonical_probe
no_safe_instrument
```

A criterion is executable only when a direct route is selected **and the selected instrument explicitly advertises the criterion observation**.

## Scope invariant

Verification preserves RFC 0043's original-scope invariant.

The router is always called with the frozen `original_scope`. Evidence returned by a verification instrument is accepted only when it belongs to the same incident and the requested criterion observation is emitted in that exact normalized scope.

There is no hierarchical or heuristic scope relabeling.

## Autonomous verification loop

The first bounded loop is intentionally small:

1. evaluate existing post-fix evidence;
2. stop immediately on `resolved` or `regressed`;
3. build the verification agent plan;
4. choose the first deterministic unresolved executable criterion;
5. execute its selected direct read-only probe through `InstrumentRouter`;
6. compose canonical evidence;
7. re-evaluate the verification contract;
8. continue until terminal outcome, no executable route, or `max_steps`.

Provider `insufficient_evidence` is recorded as such and never converted to `absent`.

## Closure semantics

The agent does not weaken RFC 0043:

- explicit post-fix `absent` evidence is required for success;
- positive/observed evidence means regression;
- silence means inconclusive;
- unavailable instruments mean inconclusive;
- lack of a canonical probe means inconclusive.

Therefore automation can accelerate verification without making incident closure less conservative.

## Current boundary

The autonomous loop is a deterministic library surface in this slice. It does not yet expose a dedicated MCP verification resource/tool or persist verification runs as incident state.

The next slice may expose the plan and bounded run through MCP while preserving exact contract identity and optimistic revision checks.

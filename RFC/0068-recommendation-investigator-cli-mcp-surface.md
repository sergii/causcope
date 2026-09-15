# RFC 0068: Recommendation investigator CLI and MCP surface

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Expose evidence-gated architectural recommendation maturity, information gaps, and the next bounded action through the Causcope investigator front door

## Summary

RFC 0065 introduced an evidence-gated architectural recommendation projection.

RFC 0067 added deterministic recommendation information-gap ranking.

Those layers are useful only if an investigator can see them without manually opening internal JSON artifacts.

RFC 0068 adds two transport projections over the existing semantics:

```text
CLI
  causcope recommendation --projection <architectural-recommendation.json>

MCP
  causcope://recommendation/current
  causcope://recommendation/information-gaps
```

No new recommendation heuristic, causal score, provider, or execution mechanism is introduced.

## CLI contract

The top-level launcher gains:

```bash
causcope recommendation --projection recommendation.json
```

The human-readable view shows:

```text
recommendation identity
subject resource
recommendation maturity state
decision status
problem query / affected path
ranked blockers
next bounded action
execution boundary
optional probe handoff
human-approval boundary
```

`--json` emits the existing strict:

```text
recommendation_information_gap_projection
```

instead of inventing a second CLI-only schema.

Example:

```text
Recommendation: recommendation.database.denormalize_read_model
Subject: db.orders.prod
State: INSUFFICIENT_CONTEXT
Decision status: INFORMATION_GAP

Blocked by:
  1. information_gap.business_semantics.consistency_contract - ...

Next best action:
  Kind: operator_question
  What is the source of truth, what consistency invariant must remain true, and how stale may the derived value be?
  Execution boundary: question_only
```

## MCP contract

The existing investigation MCP server accepts an optional:

```text
--recommendation-projection <path>
```

When configured, it exposes:

```text
causcope://recommendation/current
causcope://recommendation/information-gaps
```

When no recommendation projection is configured, those resources are not advertised.

This avoids ghost resources and keeps recommendation support optional for diagnosis-only deployments.

### Current recommendation resource

`causcope://recommendation/current` returns the validated RFC 0065 architectural recommendation projection.

It does not synthesize a recommendation from diagnosis state.

### Information-gap resource

`causcope://recommendation/information-gaps` derives RFC 0067 information-gap ranking from the current recommendation projection on read.

The derived resource therefore cannot silently drift from its source recommendation artifact.

## Read-only probe handoff

RFC 0067 may produce:

```text
next_action.kind = read_only_probe
probe_id = probe.database.measure_query_latency
subject_resource = db.orders.prod
execution_boundary = existing_read_only_probe
```

RFC 0068 exposes those exact values in CLI/MCP.

It does **not** execute the probe.

The CLI explicitly renders:

```text
Handoff: use the existing safe target-aware instrument routing path;
this command does not execute the probe.
```

## Why RFC 0068 does not call the routed diagnostic execution tool

Causcope already has:

```text
causcope.instrument.execute_routed
```

That tool has strong safety semantics. It executes only the exact:

```text
current incident
+ current evidence revision
+ selected scope
+ current top-ranked diagnostic probe
+ current selected instrument
```

and then atomically updates canonical runtime evidence and the diagnosis snapshot.

A recommendation information gap is not a diagnostic `probe_ranking` entry.

Therefore this transformation is invalid:

```text
recommendation asks for query latency
  -> pretend it is current top diagnostic probe
  -> call causcope.instrument.execute_routed
```

Doing so would weaken the stale-ranking and evidence-revision protections of the diagnostic execution path.

RFC 0068 keeps the boundary explicit instead.

## RFC 0066 provider information-gain routing boundary

RFC 0066 ranks already-eligible providers using diagnostic `probe_ranking.outcome_analysis`.

That is a deterministic proxy for how well a provider can resolve a real causal contrast.

Recommendation information-gap ranking asks a different question:

```text
What information does this architecture decision need next?
```

A recommendation gap does not automatically contain a diagnostic causal contrast.

Therefore RFC 0068 must not fabricate an `outcome_analysis` merely to invoke RFC 0066.

The valid composition is:

```text
recommendation information gap
  -> exact read-only probe + exact subject resource
  -> existing safe target-aware routing eligibility

if a genuine diagnostic probe ranking for the same probe/target also exists:
  -> RFC 0066 may refine provider choice using that real contrast
```

The two information-gain layers remain semantically separate.

## Authority boundaries

RFC 0068 surfaces four next-action classes from RFC 0067:

```text
operator_question
read_only_probe
safe_experiment
human_decision / stop_candidate
```

Their boundaries remain unchanged:

```text
operator_question
  -> asks; does not infer the answer

read_only_probe
  -> typed handoff; does not execute

safe_experiment
  -> experiment plan only; does not run it

human_decision
  -> requires explicit human approval

stop_candidate
  -> does not silently reopen without new evidence/design
```

## Epistemic invariants

```text
surface != new evidence
resource read != probe execution
probe handoff != provider selection
provider eligibility != recommendation validity
recommendation gap != diagnostic causal hypothesis
operator question != operator answer
experiment plan != measured benefit
READY_FOR_HUMAN_REVIEW != authorization to change production
```

## Fail-closed behavior

The MCP server validates the current recommendation artifact against the strict RFC 0065 schema before exposing it.

The information-gap resource is derived through the RFC 0067 projector, which already fails on unsupported missing-assumption semantics.

The CLI uses the same projector.

There is no separate permissive transport parser.

## Proof

CI verifies:

```text
causcope recommendation
  -> human-readable recommendation maturity and blockers

causcope recommendation --json
  -> strict RFC 0067 projection

NO_PROBLEM_EVIDENCE
  -> read-only probe handoff with exact target
  -> no execution

investigation MCP without recommendation input
  -> no recommendation resources advertised

investigation MCP with recommendation input
  -> current recommendation resource
  -> derived information-gap resource
  -> exact operator-question next action
```

No OpenAI API is used.

## Next slice

The next missing capability is not more presentation.

It is a **recommendation evidence-acquisition bridge** that can take:

```text
read_only_probe handoff
+ subject resource
+ safe provider routing
```

execute the approved read-only acquisition through an existing provider, then update the recommendation evidence source and re-project RFC 0065 / RFC 0067.

That bridge must preserve:

```text
provider target identity
freshness
provenance
incident/recommendation identity
no diagnostic-ranking impersonation
no autonomous architecture change
```

Until that contract exists, RFC 0068 deliberately stops at a typed handoff.

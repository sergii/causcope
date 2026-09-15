# RFC 0070: Recommendation Evidence Acquisition Bridge

Status: Implemented proof

## Problem

RFC 0065 gates one concrete database read-model recommendation on PostgreSQL evidence plus workload, business semantics, consistency cost, benefit, and verification. RFC 0067 turns missing recommendation knowledge into an explicit next action. RFC 0068 exposes that state through the investigator CLI and MCP.

The remaining gap is a safe loop for the `read_only_probe` case.

A recommendation may correctly say:

```text
NO_PROBLEM_EVIDENCE
  -> refresh observation.database.query_latency
  -> probe.database.measure_query_latency
```

but that request must not be executed through the diagnostic incident-mutation tool merely because both layers refer to the same canonical probe. `causcope.instrument.execute_routed` is intentionally bound to the current top-ranked diagnostic probe and to the incident evidence revision. Recommendation evidence acquisition has different state and different progression semantics.

## Decision

Add a separate recommendation evidence acquisition bridge that reuses the existing safe provider routing and canonical runtime-evidence contracts without pretending to be a diagnostic investigation.

```text
RFC 0067 read_only_probe
  -> exact probe_id
  -> requested observation
  -> exact semantic scope
  -> exact subject_resource
  -> existing InstrumentRouter
  -> canonical runtime_evidence
  -> RFC 0065 projector
  -> RFC 0067 projector
  -> next recommendation action
```

The bridge may advance recommendation maturity. It never authorizes a schema, application, or data mutation.

## Canonical evidence seam

Provider-specific transport must end before recommendation reasoning begins.

`database_read_model_recommendation.py` therefore gains `project_from_runtime_evidence(...)`. The existing pgbot-oriented CLI remains backward compatible, but both paths converge on the same canonical projector.

```text
pgbot / Prometheus / future provider
          |
          v
InstrumentRouter.execute
          |
          v
runtime_evidence
          |
          v
recommendation projector
```

The first bounded RFC 0070 execution proof still uses pgbot because the current recommendation is about one exact query object and the pgbot adapter preserves `pgbot.object`. The current Prometheus query-latency provider proves an exact database resource but not the exact SQL/query-object identity required by this recommendation. This is a limitation of the proof, not a reason to make the bridge pgbot-specific.

## Exact acquisition identity

A recommendation refresh is executable only when all of these are explicit:

```text
probe_id
requested_observation
semantic scope
subject_resource
provider_instance
query_object
incident_id
```

The read-model recommendation context may therefore carry `evidence_scope`. RFC 0067 propagates that scope into its `read_only_probe` handoff.

The bridge refuses acquisition if the scope is missing. It does not widen, narrow, or guess provider scope.

For the first proof the acquired evidence counts as a match only when it has:

```text
observation == observation.database.query_latency
state == observed
pgbot.object == exact workload query_object
routing.target_resource == exact subject_resource
routing.instrument_id == pinned provider_instance
labels.instrument == pinned provider_instance
```

A same-type observation for another query, database, or provider cannot satisfy the recommendation gap.

## Routing authority

RFC 0070 reuses `InstrumentRouter` rather than introducing another provider selector.

The bridge asks for direct, target-aware routing:

```text
router.route(
  probe_id,
  exact_scope,
  execution_requirement="direct",
  target_resource=subject_resource
)
```

The selected instrument must also equal the `provider_instance` already pinned by the recommendation context. This keeps the first proof reproducible and prevents evidence-source drift while a recommendation is being evaluated.

RFC 0066 provider information-gain routing remains separate. It requires a real diagnostic contrast. RFC 0070 must not fabricate `probe_ranking.outcome_analysis` merely to choose a recommendation provider.

A future recommendation contract may explicitly permit a provider set or provider-selection policy. That is not part of this proof.

## Freshness semantics

The acquisition timestamp is the recommendation evaluation time after the probe runs.

The bridge must not set evaluation time to the provider's observation timestamp. Doing so could make an old report appear fresh simply because its own timestamp is old in the same way.

Canonical query evidence is active only when:

```text
observed_at <= acquisition_time < expires_at
```

Therefore transporting a stale report is not recommendation progress. The result remains `NO_PROBLEM_EVIDENCE`, and the next action remains a read-only refresh.

## No finding remains insufficient evidence

The provider semantics remain unchanged:

```text
no mapped positive finding
!=
query latency is healthy
```

If a provider cannot produce canonical positive evidence for the requested probe, acquisition fails with insufficient evidence. The bridge does not manufacture an `absent` observation.

## Result contract

`recommendation_evidence_acquisition_result` records only the bounded acquisition transition:

- recommendation/system/revision/incident identity;
- acquisition time;
- previous recommendation state;
- probe and requested observation;
- selected exact provider/resource route;
- emitted evidence IDs and exact matching evidence IDs;
- new recommendation state and information-gap status;
- whether the recommendation actually progressed;
- next-action type and execution boundary.

The full runtime evidence, updated recommendation context, recommendation projection, and information-gap projection remain separately validated artifacts.

## First proof

The proof starts with `stale-evidence-context.json` evaluated at `00:10` and the old pgbot report collected at `00:00`. With the five-minute adapter TTL, RFC 0065 yields:

```text
NO_PROBLEM_EVIDENCE
  -> EVIDENCE_REFRESH_REQUIRED
  -> probe.database.measure_query_latency
```

A fresh pgbot report collected at `00:09` is routed through `provider.pgbot.orders-prod` to `db.orders.prod` and evaluated at `00:10`.

Expected progression:

```text
NO_PROBLEM_EVIDENCE
  -> exact routed query-latency evidence
  -> INSUFFICIENT_CONTEXT
  -> INFORMATION_GAP
  -> operator_question: business consistency semantics
```

The probe answers only the stale performance-evidence question. It does not answer business semantics, maintenance strategy, cost, or correctness.

## Fail-closed matrix

The proof requires:

- missing exact evidence scope -> refuse execution;
- current next action is not `read_only_probe` -> refuse execution;
- selected provider differs from pinned provider instance -> refuse execution;
- wrong target resource -> refuse through target-aware routing;
- wrong query object -> evidence cannot satisfy the recommendation refresh;
- stale acquired evidence -> no maturity progression;
- wrong incident -> reject canonical evidence;
- non-read-only probe -> existing `InstrumentRouter` refuses it.

## Non-goals

RFC 0070 does not:

- mutate the diagnostic incident evidence journal;
- bypass the current top-ranked diagnostic-probe invariant;
- rank architecture candidates probabilistically;
- execute a `safe_experiment` recommendation action;
- answer operator questions automatically;
- apply normalization, denormalization, migrations, schema changes, or application changes;
- treat provider findings as causal or architectural authority.

## Consequence

Causcope can now close one recommendation evidence gap with an existing safe read-only provider and immediately recompute what it knows next.

The resulting loop is:

```text
observe
  -> reason
  -> expose uncertainty
  -> acquire bounded evidence
  -> reason again
  -> ask / experiment / human review
```

This is deliberately a decision-under-uncertainty loop, not an autonomous architecture-change loop.

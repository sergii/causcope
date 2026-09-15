# RFC 0086: Canonical intervention-based causal verification

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Verify the Rails D3.1 connection-pool causal claim from canonical Investigation evidence instead of treating the specialized X-Ray `CAUSAL_DIAGNOSIS_CONFIRMED` state as an independent epistemic authority.

## Decision

Causcope distinguishes diagnosis ranking from causal verification.

A hypothesis may stop being the current leading explanation after the system recovers. That does not erase the fact that it was the leading pre-intervention hypothesis and that a bounded intervention produced its predicted recovery.

The canonical progression is now:

```text
pre-intervention diagnosis revision N
  -> leading hypothesis
  -> exact runtime-bound mechanism evidence
  -> discriminating control evidence
  -> bounded intervention
  -> predicted post-intervention recovery evidence
  -> atomic evidence revision N+1
  -> causal verification projection
```

For the Rails D3.1 proof:

```text
hypothesis.database.connection_pool_exhaustion
  -> exact observed pool wait
  -> exact observed pool saturation
  -> query latency not elevated
  -> independent PostgreSQL admission remains reachable
  -> release occupied application-pool capacity
  -> checkout wait returns to baseline
  -> request latency returns to baseline
  -> verified causal claim
```

## Canonical evidence, not a second diagnosis engine

RFC 0086 does not add another ranking system.

`scripts/rails_pool_evidence_import.py` now projects four ordinary runtime observations from the bounded experiment:

- `observation.database.connection_pool_utilization = observed` before intervention;
- `observation.database.query_latency = absent` as a discriminating control;
- `observation.database.connection_pool_wait_time = absent` after intervention;
- `observation.http.request_latency = absent` after intervention.

The last two are not new semantic concepts. They reuse the existing observations and use the existing `absent` state to say that the previously elevated condition returned to baseline.

The importer binds every projected observation to the same exact canonical seed, exact scope, exact target resource, trace/span, code symbol, runtime pool, system, and revision.

## Intervention provenance

The Rails D3.1 probe is a bounded experiment. Its recovery sample is taken only after the capacity-holding request completes and releases the occupied application-pool slot.

The canonical projected evidence records:

- a stable verification ID;
- baseline evidence revision;
- the baseline leading hypothesis;
- exact target resource;
- intervention kind `resource_capacity_release`;
- intervention resource (the exact runtime pool);
- phase: `pre_intervention`, `control`, or `post_intervention`;
- canonical seed evidence ID.

This metadata is provenance. The causal state still comes from canonical observations and their exact identities.

## Verification rule

`scripts/causal_verification.py` derives a read-only `causal_verification_projection` from the persisted `diagnosis.json` and `runtime-evidence.json`.

The first implemented rule verifies `hypothesis.database.connection_pool_exhaustion` only when all of the following are established in one exact verification identity and scope:

1. the hypothesis was rank 1 at the pre-intervention evidence revision;
2. the canonical seed is an observed connection-pool wait;
3. the application pool is observed at capacity before intervention;
4. the bounded experiment says checkout wait explains the request-latency delta;
5. elevated query latency is absent during the saturated request;
6. independent database admission remains reachable;
7. the intervention is `resource_capacity_release` on the exact pool;
8. post-intervention connection-pool wait is explicitly absent;
9. post-intervention request latency is explicitly absent.

Missing evidence is never converted into success. Identity mismatch, missing seed evidence, missing recovery, missing control, or a non-leading baseline hypothesis produces `incomplete`, not `verified`.

## Important ranking distinction

Post-intervention recovery evidence may reduce the current diagnostic score of connection-pool exhaustion. That is expected.

The two questions are different:

```text
current diagnosis:
  what explains the system state now?

causal verification:
  did the previously leading mechanism produce its predicted change
  under a bounded intervention?
```

Therefore RFC 0086 deliberately does not require the verified hypothesis to remain rank 1 after recovery.

## Compatibility boundary

The specialized Rails X-Ray state:

```text
CAUSAL_DIAGNOSIS_CONFIRMED
```

is now conceptually a compatibility projection for this golden slice.

The canonical authority is:

```text
runtime-evidence.json
  + diagnosis.json
  -> causal_verification_projection
```

The old X-Ray path remains available while product surfaces migrate. It must not override a canonical verification that is incomplete or identity-mismatched.

## Fail-closed properties

Canonical verification fails closed when:

- trace/span or runtime pool cannot bind to exactly one canonical seed;
- system/revision/incident identity differs;
- exact target resource is missing;
- verification members disagree on exact scope or identity;
- the seed evidence is missing or not an observed pool wait;
- the mechanism did not explain the request-latency delta;
- the independent database control is not established;
- either predicted recovery observation is missing;
- the hypothesis was not rank 1 before intervention.

No missing observation is inferred from silence.

## Proof

`python scripts/test_rails_pool_evidence_import.py` proves:

1. revision 1 ranks connection-pool exhaustion first;
2. one exact Rails D3.1 experiment binds to the canonical seed;
3. mechanism, control, and recovery observations are committed atomically at revision 2;
4. all projected evidence retains exact target and verification identity;
5. the canonical projection reaches `verified`;
6. removing request-latency recovery makes `--require-verified` fail;
7. duplicate import does not advance state;
8. identity mismatch fails before state mutation.

## Non-goals

This slice does not:

- claim that every recovery proves causality;
- generalize arbitrary interventions from labels alone;
- automate production mutations;
- replace RFC 0043 original-scope fix verification;
- infer recovery from missing telemetry;
- make `CAUSAL_DIAGNOSIS_CONFIRMED` a generic diagnosis ranking state.

RFC 0043 asks whether the original failing cohort recovered after a fix. RFC 0086 asks whether a bounded intervention produced the predicted effect of a previously leading causal mechanism. They remain distinct protocols.

## Next step

Expose the canonical causal-verification projection directly through the normal `causcope why` JSON/text and MCP diagnosis surfaces, then make `--require-confirmed` consume canonical verification when a workspace is supplied. Once those surfaces are proven, the Rails-specific X-Ray confirmation can be retained only as a compatibility/test projection.

# RFC 0087: Canonical intervention-based causal verification

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

RFC 0087 does not add another ranking system.

`scripts/rails_pool_evidence_import.py` projects four ordinary runtime observations from the bounded experiment:

- `observation.database.connection_pool_utilization = observed` before intervention;
- `observation.database.query_latency = absent` as a discriminating control;
- `observation.database.connection_pool_wait_time = absent` after intervention;
- `observation.http.request_latency = absent` after intervention.

The last two reuse existing observations. Post-intervention outcomes retain the original base scope and add `scope.attributes.evidence_phase=post_intervention`, so recovery evidence cannot contradict the active pre-intervention diagnosis partition while verification can still compare the shared base scope.

## Exact binding and provenance

The importer binds the experiment to exactly one canonical observed pool-wait seed by incident, system, revision, trace/span, code symbol, runtime pool, exact target resource, and base scope.

The Rails D3.1 probe takes its recovery sample only after the capacity-holding request completes and releases the occupied application-pool slot. Projected evidence records:

- a stable verification ID;
- baseline evidence revision;
- baseline leading hypothesis;
- exact target resource;
- intervention kind `resource_capacity_release`;
- exact intervention resource;
- phase: `pre_intervention`, `control`, or `post_intervention`;
- canonical seed evidence ID.

## Verification rule

`scripts/causal_verification.py` derives a read-only `causal_verification_projection` from persisted `diagnosis.json` and `runtime-evidence.json`.

The first rule verifies `hypothesis.database.connection_pool_exhaustion` only when one exact verification identity establishes all of:

1. the hypothesis was rank 1 at the pre-intervention evidence revision;
2. the canonical seed is an observed connection-pool wait;
3. the application pool is observed at capacity before intervention;
4. checkout wait explains the request-latency delta;
5. elevated query latency is absent during saturation;
6. independent database admission remains reachable;
7. the intervention is `resource_capacity_release` on the exact pool;
8. post-intervention connection-pool wait is explicitly absent;
9. post-intervention request latency is explicitly absent.

Missing evidence is never converted into success. Identity mismatch, missing seed evidence, missing recovery, missing control, or a non-leading baseline hypothesis produces `incomplete`, not `verified`.

## Diagnosis ranking remains separate

Post-intervention recovery evidence may reduce the current diagnostic score of connection-pool exhaustion. That is expected.

```text
current diagnosis:
  what explains the system state now?

causal verification:
  did the previously leading mechanism produce its predicted change
  under a bounded intervention?
```

RFC 0087 therefore does not require the verified hypothesis to remain rank 1 after recovery.

## Compatibility boundary

The specialized Rails X-Ray state `CAUSAL_DIAGNOSIS_CONFIRMED` is now conceptually a compatibility projection for this golden slice.

Canonical authority is:

```text
runtime-evidence.json
  + diagnosis.json
  -> causal_verification_projection
```

The old X-Ray path remains available while product surfaces migrate. It must not override a canonical verification that is incomplete or identity-mismatched.

## Fail-closed properties

Canonical verification fails closed when exact seed identity is ambiguous, target resource is missing, verification members disagree on identity/base scope, mechanism evidence is incomplete, independent database control is not established, either predicted recovery observation is missing, or the hypothesis was not rank 1 before intervention. Duplicate import is rejected before reranking and does not advance state.

No missing observation is inferred from silence.

## Proof

`python scripts/test_rails_pool_evidence_import.py` proves revision-1 ranking, exact seed binding, atomic revision-2 mechanism/control/recovery import, target and verification identity preservation, canonical `verified` projection, incomplete recovery failure, duplicate-import idempotence, and identity-mismatch fail-closed behavior.

Both normal investigator CLI CI and the full semantic validation suite run on the exact PR head without external AI calls.

## Non-goals

This slice does not claim that every recovery proves causality, generalize arbitrary interventions from labels alone, automate production mutations, replace RFC 0043 original-scope fix verification, infer recovery from missing telemetry, or make `CAUSAL_DIAGNOSIS_CONFIRMED` a generic diagnosis ranking state.

RFC 0043 asks whether the original failing cohort recovered after a fix. RFC 0087 asks whether a bounded intervention produced the predicted effect of a previously leading causal mechanism. They remain distinct protocols.

## Next step

Expose the canonical causal-verification projection directly through normal `causcope why` JSON/text and MCP diagnosis surfaces, then make workspace `--require-confirmed` consume canonical verification. Once those surfaces are proven, the Rails-specific X-Ray confirmation can remain only as a compatibility/test projection.

# RFC 0075: Golden vertical slice - Rails connection-pool exhaustion

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Prove one product-shaped Causcope investigation from a user-visible Rails latency symptom to a verified causal diagnosis.

## Decision

The first golden product proof is:

```text
Rails developer
  -> "checkout is slow"
  -> concrete Rails revision
  -> exact request execution
  -> exact ActiveRecord pool interaction
  -> runtime pool evidence
  -> independent PostgreSQL control
  -> causal X-Ray progression
  -> verified root cause
  -> causcope why
```

The mechanism is D3.1 application-side database connection-pool exhaustion.

This milestone deliberately connects existing machinery instead of adding another generic lifecycle, MCP surface, provider abstraction, or reasoning engine.

## Repository reconciliation

The repository was reviewed after parallel agent work before closing this slice.

The newer architecture and product material is compatible with this milestone:

- the agent-first roadmap says to finish the Rails D3.1 golden slice before broadening the surface;
- the architecture debt review warns against invented numeric confidence and unsupported blast-radius claims;
- the integration model keeps external tools as evidence providers rather than causal authorities;
- RFC 0076 now defines investigation-case identity and incident compatibility;
- RFC 0077 plus `vocabulary/rfc-id-exceptions.yaml` and `scripts/validate_rfc_ids.py` now make legacy RFC-number collisions explicit and prevent new unregistered collisions.

None of those parallel changes require a repository split, cloud service, or new reasoning layer for this local proof.

## Why this slice

A slow request can coexist with:

```text
SQL execution near baseline
PostgreSQL still accepting an independent connection
ActiveRecord pool saturated
request blocked on pool checkout
```

No single narrow instrument owns the complete explanation. Rails runtime evidence identifies the concrete pool interaction. PostgreSQL evidence distinguishes database-wide capacity failure. OpenTelemetry binds the affected request. Causcope joins those facts and decides whether the causal diagnosis is justified.

The product distinction is:

```text
PostgreSQL instrument -> knows PostgreSQL
OpenTelemetry          -> knows traces
Rails runtime          -> knows the ActiveRecord pool
Causcope               -> knows how these facts answer the debugging question
```

## Existing machinery reused

The proof reuses:

- portable Rails repository scanning;
- revision-bound Concrete System Facts;
- portable Rails OpenTelemetry integration and concrete OTLP receiver;
- exact ActiveRecord pool runtime binding;
- the generic declarative X-Ray engine;
- `xray.d3_1.concrete_connection_pool_exhaustion`;
- independent PostgreSQL capacity control;
- existing fail-closed identity semantics.

No new causal-ranking algorithm is introduced.

## Product projection

`scripts/rails_pool_vertical_slice.py` is the bounded human-facing projection over the existing D3.1 proof.

It consumes the same canonical artifacts produced by the live Rails proof:

```text
concrete_system_facts
concrete_runtime_facts
resource_pool_runtime_evidence
```

and runs the unchanged declarative X-Ray profile before rendering:

```text
Problem
Status
Root cause
Concrete scope
Evidence
Rejected nearby explanations
Blast radius
Verification
```

The projection does not infer facts the bounded proof does not establish. In particular:

```text
Blast radius
  not established by this bounded slice
```

is preserved rather than inventing affected-user or affected-request counts.

## Product front door

The repository launcher exposes:

```bash
causcope why "checkout is slow"
```

through `scripts/causcope_why.py`.

The command remains a projection over canonical state rather than a second diagnosis engine.

Without attached diagnostic artifacts it starts or resumes the existing `.causcope/` investigation workspace and returns the next scoping question. With the three canonical D3.1 artifacts supplied together, it renders the existing golden causal diagnosis:

```bash
./bin/causcope why "checkout is slow" \
  --static /tmp/rails-d3-static.json \
  --runtime /tmp/rails-d3-runtime.json \
  --pool /tmp/rails-d3-pool.json \
  --require-confirmed
```

`--json` exposes the selected canonical projection for agents and tests. `--require-confirmed` is deliberately restricted to the attached diagnostic path and fails closed unless the X-Ray reaches `CAUSAL_DIAGNOSIS_CONFIRMED`.

This is the bounded first implementation of the RFC 0059 problem-oriented front door. Future `why` coverage should dispatch to canonical investigation, evidence, ranking, routing, and verification projections rather than accumulating mechanism-specific reasoning inside the CLI.

## Required causal proof

A confirmed result requires the existing D3.1 progression to reach:

```text
PRECONDITIONS_PRESENT
RUNTIME_EXECUTION_OBSERVED
POOL_SATURATED
CHECKOUT_WAIT_OBSERVED
DATABASE_CAPACITY_DISTINGUISHED
CAUSAL_DIAGNOSIS_CONFIRMED
```

The human-facing root cause is emitted only at `CAUSAL_DIAGNOSIS_CONFIRMED`.

Anything weaker remains explicitly unconfirmed.

## Nearby explanations

The slice rejects a nearby explanation only when the corresponding existing evidence supports that rejection.

`slow SQL execution as the primary explanation` is rejected only when query latency stayed near baseline.

`PostgreSQL-wide connection admission exhaustion` is rejected only when the independent PostgreSQL control remained reachable.

If the database-capacity control is unavailable or negative, Causcope stops at the weaker epistemic state. Unavailable evidence never becomes absence.

## Verification

The causal claim is stronger than correlation because the D3.1 proof includes recovery:

```text
pool slot released
  -> checkout wait returns to baseline
  -> request latency returns to baseline
```

The product output exposes this verification instead of merely saying that pool saturation and latency occurred together.

## Live implementation proof

The live Rails workflow proved the causal core against a real Rails/PostgreSQL environment and now continues through the product front door:

```text
real Rails application
  -> revision-bound Rails scan
  -> real PostgreSQL service
  -> ActiveRecord pool capacity = 1
  -> concrete pool contention
  -> official OTLP export
  -> exact request / trace / span / pool identity
  -> independent PostgreSQL reachability control
  -> generic D3.1 X-Ray
  -> CAUSAL_DIAGNOSIS_CONFIRMED
  -> causcope why
  -> human-readable confirmed diagnosis
```

`.github/workflows/xray-d3-1-rails.yml` feeds the exact live artifacts into `causcope why` and asserts that the resulting diagnosis:

- reports `application-side database connection pool exhaustion` as the root cause;
- names `code:PoolController#work()`;
- names `pool:active_record.primary`;
- rejects slow SQL only with supporting evidence;
- rejects PostgreSQL-wide admission exhaustion only with supporting evidence;
- keeps blast radius explicitly unknown in this bounded proof;
- reaches the same confirmed state in human and JSON projections.

No hand-written diagnosis fixture substitutes for the live artifacts in this acceptance path.

The lightweight front-door tests additionally prove scoping startup/resume and fail-closed behavior when database-capacity evidence is insufficient.

## Freeze rule

The slice is implemented as a proof. The temporary freeze can be relaxed, but the product rule remains:

> Prefer completing and simplifying real end-to-end investigations over adding generic infrastructure layers.

New platform abstractions should show which concrete investigation they unblock.

## Definition of done

The milestone is complete when the exact implementation head is green and demonstrates:

```text
user-visible slow request
  -> exact Rails execution
  -> exact ActiveRecord pool
  -> pool saturation
  -> checkout wait
  -> PostgreSQL-wide exhaustion distinguished
  -> recovery
  -> CAUSAL_DIAGNOSIS_CONFIRMED
  -> causcope why
  -> product-shaped human diagnosis
```

The output must preserve explicit unknowns. Blast radius remains unknown until a separate evidence source establishes it.

## Next slice

Do not immediately add another lifecycle abstraction.

The next product work should generalize the front door from this bounded D3.1 proof toward the existing canonical investigation loop:

```text
problem
  -> persisted investigation
  -> competing hypotheses
  -> semantic next probe
  -> exact runtime target resolution
  -> safe provider routing
  -> evidence acquisition
  -> rerank
  -> verification
  -> causcope why
```

That generalization should reuse the already implemented runtime target resolution, information-gain provider routing, multi-target execution sets, durable journals, and recovery policy rather than creating parallel state.

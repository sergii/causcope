# RFC 0080: Observed Rails incident bootstrap

- Status: Implemented initial slice
- Date: 2026-09-15

## Decision

Add a bounded incident-bootstrap command for the existing Rails/PostgreSQL local-agent path:

```text
causcope runtime seed <rails-root>
```

The command converts already-observed, revision-bound Rails runtime facts into the first canonical Investigation evidence revision without inventing a mechanism from repository shape or natural-language problem text.

The implemented slice is deliberately narrow:

```text
current Investigation
  + concrete Rails runtime facts
  + explicit request-latency objective
  + explicit ActiveRecord checkout-wait objective
  + exact runtime pool relationship
  + exact topology target binding
  -> canonical runtime evidence revision 1
  -> request-latency causal candidates
  -> deterministic next discriminator
  -> diagnosis snapshot revision 1
  -> existing exact-target routing
```

It composes existing contracts. It does not introduce a second diagnosis engine, evidence format, target resolver, provider model, or probe-ranking model.

## System bootstrap is not incident bootstrap

RFC 0079 establishes system bootstrap:

```text
what exists?
what resource maps where?
which safe provider can inspect it?
```

This RFC implements the first incident-bootstrap slice:

```text
what was actually observed in this Investigation?
which exact request and runtime resource carried the observation?
which operational target is proven by that runtime identity?
which empirically grounded mechanisms remain plausible?
which existing probe best discriminates them?
```

The distinction remains strict.

## Product flow

The local path is now:

```bash
causcope bootstrap . \
  --database app_production \
  --database-url-env CAUSCOPE_PRODUCTION_DATABASE_URL

causcope why "checkout is slow"

causcope runtime start .
# reproduce the problem while the receiver observes the current Investigation

causcope runtime seed . \
  --request-latency-threshold-ms 200 \
  --pool-wait-threshold-ms 50

causcope why
```

`runtime start` resolves the current Investigation identity from `.causcope/incident-context.yaml` when `--incident-id` is not supplied. An explicit ID remains available as an override.

The default concrete runtime snapshot remains:

```text
.causcope/runtime/<investigation-id>.json
```

## Why explicit objectives are required

The runtime contains measured values, but a measurement alone does not establish that it is abnormal.

Therefore the first slice requires two explicit objectives:

```text
request duration > request latency objective
pool checkout wait > pool wait objective
```

For example:

```text
request duration = 500 ms
request objective = 200 ms

pool checkout wait = 260 ms
pool wait objective = 50 ms
```

Causcope may then state that both observations are above the caller-supplied objectives.

It must not silently invent a baseline from a generic default, the Rails checkout timeout, or one observed request.

## Selection policy

The implemented deterministic selection policy is:

```text
slowest_request_with_elevated_pool_wait_and_exact_single_target_binding
```

A candidate execution must satisfy all of the following:

1. it belongs to the current Investigation;
2. request duration exceeds the explicit request objective;
3. the same execution contains an exact ActiveRecord pool checkout interaction;
4. checkout wait exceeds the explicit pool-wait objective;
5. runtime relationships bind the execution to a concrete runtime resource;
6. topology resolves those relationships to exactly one operational target.

Optional selectors may narrow the candidate set:

```text
--code-symbol
--trace-id
```

If no execution satisfies the contract, Causcope stops without creating revision 1.

If an execution touches several operational targets, Causcope stops instead of guessing which target caused the symptom.

## Initial evidence

The first slice emits two canonical observations from the same trace and scope.

### User-visible request latency

```text
observation.http.request_latency
```

This records:

- exact request duration;
- caller-supplied latency objective;
- delta;
- trace/span identity;
- execution identity;
- code symbol;
- system/revision identity;
- exact topology target proven by the runtime binding.

This is the primary diagnosis target for revision 1 because it represents the user-visible symptom that still has competing causal explanations.

### ActiveRecord checkout wait

```text
observation.database.connection_pool_wait_time
```

This records:

- exact ActiveRecord pool ID;
- exact checkout interaction ID;
- measured checkout wait;
- caller-supplied pool-wait objective;
- the same trace/span/execution identity;
- the same exact operational target.

This is discriminating evidence that favors an application-side pool mechanism, but it does not establish that SQL execution, PostgreSQL connection admission, or database lock health are normal.

## Empirically grounded alternatives

The repository already contains empirical evidence for two distinct ways database work can contribute to end-to-end request latency.

### Application connection-pool contention

Existing evidence:

```text
hypothesis.database.connection_pool_exhaustion
claim.database.connection_pool_exhaustion.checkout_wait_drives_latency
experiment.database.connection_pool_exhaustion.python_postgres
```

The experiment demonstrates a bounded application pool where a competing request waits for checkout while the subsequent query stays fast and an independent PostgreSQL connection remains available.

The implemented graph therefore grounds:

```text
hypothesis.database.connection_pool_exhaustion
  -> causes -> observation.database.connection_pool_wait_time

hypothesis.database.connection_pool_exhaustion
  -> contributes_to -> observation.http.request_latency
```

under explicit critical-path conditions.

### Database query delay

Existing evidence:

```text
hypothesis.latency.database
claim.latency.database.query_delay_propagates_upstream
experiment.latency.database.query_delay_python_postgres
```

The experiment demonstrates controlled synchronous PostgreSQL query delay propagating into end-to-end request latency.

The implemented graph therefore grounds:

```text
hypothesis.latency.database
  -> contributes_to -> observation.http.request_latency
```

when the database operation is on the request critical path.

These edges are backed by existing claims and experiments rather than being product-specific shortcuts.

## Revision 1 candidate ranking

For a request that is both slow and observed waiting materially for ActiveRecord checkout, the first bounded proof produces competing candidates for:

```text
observation.http.request_latency
```

with the expected top ordering:

```text
1. hypothesis.database.connection_pool_exhaustion
2. hypothesis.latency.database
```

The pool-exhaustion candidate ranks first because the same scoped evidence includes the strong pool-wait observation predicted by D3.1.

The database-latency candidate remains plausible because slow synchronous query execution could also contribute materially to the same end-to-end request latency and has not yet been measured.

Revision 1 therefore means:

```text
observed symptom
  + observed discriminating runtime fact
  -> ranked alternatives
  -> next discriminator
```

It does not mean:

```text
root cause confirmed
```

## Next discriminator

The existing probe-ranking engine is intentionally preserved unchanged.

Because revision 1 contains at least two empirically grounded alternatives, normal candidate discrimination applies. In the implemented proof the deterministic next probe is:

```text
probe.database.measure_query_latency
```

Its purpose is to distinguish, among other possibilities:

```text
pool checkout wait high + subsequent query near baseline
  -> supports application pool contention relative to slow-query latency

query latency materially high
  -> supports database-latency alternative
```

The result still requires normal evidence ingestion and reranking. The seed does not pre-answer the probe.

## Exact-target requirement

Before writing revision 1, the seed command preflights the existing runtime target resolver against the request-latency diagnosis.

The proof chain is:

```text
canonical request-latency observation
  -> exact trace ID
  -> runtime used_resource relationship
  -> exact ActiveRecord pool
  -> explicit RFC 0040 runtime binding
  -> exact operational PostgreSQL target
  -> ranked next probe
```

The seed is accepted only when the request-latency diagnosis resolves to exactly the target selected from the observed execution.

This prevents later provider routing from inheriting an ambiguous bootstrap assumption.

In the product proof:

```text
pool:active_record.primary
  -> db.causcope.prod

next probe
  -> probe.database.measure_query_latency
```

The same target and probe can then enter the existing InstrumentRouter/provider-binding path.

## Workspace artifacts

A successful seed writes:

```text
.causcope/runtime-evidence.json
.causcope/runtime-relationships.json
.causcope/diagnosis.json
```

Existing artifacts are not overwritten unless `--force` is explicit.

The concrete runtime snapshot remains transport evidence under:

```text
.causcope/runtime/<investigation-id>.json
```

and is not rewritten into static system knowledge.

## Failure behavior

The implemented slice fails closed when:

- no current Investigation exists;
- static facts or topology are missing;
- runtime facts belong to another Investigation;
- no request exceeds the request objective;
- no same-request pool wait exceeds the pool-wait objective;
- the runtime pool has no topology binding;
- the request touches several target resources;
- the request-latency diagnosis has no empirically grounded candidate;
- the candidates have no deterministic discriminating next probe;
- the diagnosis cannot resolve back to exactly one expected target;
- revision-1 artifacts already exist and `--force` was not supplied.

No partial evidence/diagnosis state is written before all preflight checks pass.

## Proven product path

The CI proof now covers:

```text
Rails repository
  -> causcope bootstrap
  -> causcope why creates Investigation
  -> causcope runtime start resolves that same Investigation
  -> concrete slow request + exact pool checkout observation
  -> causcope runtime seed
  -> runtime evidence revision 1
  -> D3.1 vs database-latency alternatives
  -> next probe: measure query latency
  -> exact PostgreSQL target
  -> causcope why reads the persisted diagnosis and route
```

Negative tests cover:

- low pool wait below the explicit objective;
- runtime facts belonging to a different Investigation;
- overwrite without `--force`.

## Non-goals

This slice does not:

- infer latency objectives automatically;
- treat every slow Rails request as a database problem;
- seed requests that do not show elevated ActiveRecord checkout wait;
- confirm connection-pool exhaustion from checkout wait alone;
- claim query execution is fast before measuring it;
- inspect PostgreSQL admission or locks during seed;
- handle arbitrary non-Rails runtimes;
- replace the existing `why --acquire` loop;
- create Cloud- or Relay-specific reasoning.

## Follow-up direction

The same incident-bootstrap pattern can now generalize:

```text
observed signal
  -> canonical user-visible observation
  + scoped discriminating observation(s)
  -> empirically grounded alternatives
  -> exact runtime identity
  -> exact target
  -> next discriminator
  -> existing acquisition/reranking loop
```

Future seed adapters may start from HTTP metrics, Sentry events, Prometheus, OpenTelemetry dependency spans, structured logs, PagerDuty incidents, or other sources, but they should enter the same canonical evidence and diagnosis contracts rather than adding source-specific reasoning engines.

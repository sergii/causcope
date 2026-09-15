# RFC 0080: Observed Rails incident bootstrap

- Status: Proposed implementation slice
- Date: 2026-09-15

## Decision

Add a bounded incident-bootstrap command for the existing Rails/PostgreSQL local-agent path:

```text
causcope runtime seed <rails-root>
```

The command converts already-observed, revision-bound Rails runtime facts into the first canonical Investigation evidence revision without inventing a mechanism from repository shape or natural-language problem text.

The first slice is deliberately narrow:

```text
current Investigation
  + concrete Rails runtime facts
  + explicit request-latency objective
  + explicit ActiveRecord checkout-wait objective
  + exact runtime pool relationship
  + exact topology target binding
  -> runtime evidence revision 1
  -> diagnosis snapshot revision 1
  -> existing exact-target routing
```

It composes existing contracts. It does not introduce a second diagnosis engine, evidence format, target resolver, or provider model.

## System bootstrap vs incident bootstrap

RFC 0079 establishes system bootstrap:

```text
what exists?
what resource maps where?
which safe provider can inspect it?
```

This RFC adds the first incident-bootstrap slice:

```text
what was actually observed in this Investigation?
which exact request and runtime resource carried the observation?
which operational target is proven by that runtime identity?
what candidate mechanism should be investigated next?
```

The distinction remains strict.

## Product flow

The intended local path becomes:

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

Causcope may then state that both observations are above the caller-supplied objective.

It must not silently invent a baseline from a generic default, the Rails checkout timeout, or one observed request.

## Selection policy

The initial deterministic selection policy is:

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

### Request latency

```text
observation.http.request_latency
```

This records the user-visible symptom evidence:

- exact request duration;
- caller-supplied latency objective;
- delta;
- trace/span identity;
- execution identity;
- code symbol;
- system/revision identity;
- exact topology target proven by the runtime binding.

This observation alone does not identify a mechanism.

### Connection-pool checkout wait

```text
observation.database.connection_pool_wait_time
```

This records the discriminating application-runtime observation:

- exact ActiveRecord pool ID;
- exact checkout interaction ID;
- measured checkout wait;
- caller-supplied pool-wait objective;
- same trace/span/execution identity;
- exact operational target.

The observation establishes application-side pre-query waiting on that request. It does not establish that SQL execution, PostgreSQL connection admission, or database lock health are normal.

## Causal graph grounding

The repository already contains:

```text
hypothesis.database.connection_pool_exhaustion
claim.database.connection_pool_exhaustion.checkout_wait_drives_latency
experiment.database.connection_pool_exhaustion.python_postgres
```

The experiment demonstrates a bounded application pool where a competing request waits for checkout while the subsequent query stays fast and an independent PostgreSQL connection remains available.

This RFC therefore promotes the empirically grounded causal relation:

```text
hypothesis.database.connection_pool_exhaustion
  -> observation.database.connection_pool_wait_time
```

with claim and experiment provenance.

The edge makes D3.1 a candidate when elevated checkout wait is observed. It does **not** make D3.1 a confirmed diagnosis.

Confirmation still requires the stronger evidence contract used by the D3.1 X-Ray proof, including nearby-alternative discrimination and recovery evidence.

## Revision 1 semantics

`diagnosis.json` at evidence revision 1 means:

```text
observed symptom
  + observed discriminating runtime fact
  -> ranked candidate(s)
  -> next probe
```

It does not mean:

```text
root cause confirmed
```

The product must preserve this difference in CLI, MCP, Dashboard, and future Cloud projections.

For the first slice, `hypothesis.database.connection_pool_exhaustion` may become the leading candidate because the pool-wait observation now has an explicit causal edge and the same request also exhibits elevated HTTP latency.

The next probe remains responsible for collecting additional evidence or falsifying the candidate.

## Exact-target requirement

Before writing revision 1, the seed command preflights the existing runtime target resolver.

The proof chain is:

```text
canonical pool-wait observation
  -> exact trace ID
  -> runtime used_resource relationship
  -> exact ActiveRecord pool
  -> explicit RFC 0040 runtime binding
  -> exact operational target
```

The seed is accepted only when the pool-wait diagnosis resolves to exactly the target selected from the observed execution.

This prevents later provider routing from inheriting an ambiguous bootstrap assumption.

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

The first slice fails closed when:

- no current Investigation exists;
- static facts or topology are missing;
- runtime facts belong to another Investigation;
- no request exceeds the request objective;
- no same-request pool wait exceeds the pool-wait objective;
- the runtime pool has no topology binding;
- the request touches several target resources;
- the canonical diagnosis cannot resolve back to exactly one expected target;
- revision-1 artifacts already exist and `--force` was not supplied.

No partial evidence/diagnosis state should be written before all preflight checks pass.

## Non-goals

This slice does not:

- infer latency objectives automatically;
- treat every slow Rails request as a database problem;
- diagnose requests that do not show elevated ActiveRecord checkout wait;
- confirm connection-pool exhaustion from checkout wait alone;
- inspect SQL execution or PostgreSQL admission during seed;
- handle arbitrary non-Rails runtimes;
- replace the existing `why --acquire` loop;
- create Cloud- or Relay-specific reasoning.

## Follow-up direction

Once this bounded slice is proven, the same incident-bootstrap pattern can generalize:

```text
observed signal
  -> canonical observation
  -> exact runtime identity
  -> exact target
  -> candidate ranking
  -> next discriminator
```

Future seed adapters may start from HTTP metrics, Sentry events, Prometheus, OpenTelemetry dependency spans, structured logs, PagerDuty incidents, or other sources, but they should enter the same canonical evidence and diagnosis contracts rather than adding source-specific reasoning engines.

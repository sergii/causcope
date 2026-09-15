# RFC 0083: Canonical deterministic acceptance benchmark

- Status: Implemented initial slice
- Date: 2026-09-15

## Decision

Add one canonical blind acceptance benchmark that runs a real Docker Compose fault through the complete bounded deterministic Causcope investigation loop and only then compares the result with hidden oracle ground truth.

The first benchmark is:

```text
scenario.shop.sqlite_write_lock
```

The public scenario report is available to Causcope. `oracle.json` is not.

## Why this exists

Causcope already has several complementary proofs:

```text
mechanism labs
  -> prove individual mechanisms empirically

investigation labs
  -> prove investigation ordering/invariants

Rails/PostgreSQL golden slice
  -> prove a product-shaped concrete causal path

Shop testbed
  -> prove a bounded autonomous read-only loop against a running application
```

What was missing was one stable acceptance contract that can answer:

> Given the same hidden fault and the same public incident context, does this Causcope surface arrive at the expected canonical investigation result without access to the oracle?

This benchmark becomes the cross-surface reference point for future CLI, MCP/agent, Dashboard, Cloud, and Relay projections.

## Canonical flow

```text
fresh Docker Compose reference system
  -> public scenario report
  -> durable Investigation
  -> inject known hidden fault
  -> verify public symptom
  -> passive runtime evidence
  -> deterministic causal ranking
  -> deterministic next-probe ranking
  -> bounded allowlisted read-only probe execution
  -> canonical new evidence
  -> evidence revision increment
  -> deterministic rerank
  -> bounded stop
  -> project completed Investigation through causcope why
  -> load hidden oracle
  -> score final Causcope state and product projection
```

Oracle data MUST NOT be used to construct observations, hypotheses, probe choices, target scope, diagnosis, or the `causcope why` projection.

## First scenario

The first canonical benchmark uses the Shop SQLite write-lock scenario because it has:

- a real application process;
- a real database;
- a real competing writer process;
- observable healthy controls;
- a repeatable request failure;
- a discriminating read-only probe;
- hidden ground truth distinct from the evidence Causcope consumes.

The public report says only that order writes fail intermittently while product reads remain healthy.

The hidden oracle records that a competing process holds a SQLite write transaction long enough for application writes to exceed the configured busy timeout.

## Hidden scoring contract

`testbed_scenario_oracle` may contain an optional `expected_causcope` object. This object is oracle-only and is forbidden from the public scenario contract.

For the first benchmark it declares:

```text
target
  observation.http.request_failure

scope contains
  method = POST
  path = /orders
  client_platform = web

expected leading hypothesis
  hypothesis.database.lock_contention

required completed probe
  probe.database.inspect_lock_error_events

minimum evidence revision
  2
```

The benchmark scorer compares the finished Investigation to these expectations only after Causcope has stopped.

## LLM policy

The canonical deterministic benchmark MUST NOT depend on an LLM.

The runner removes common AI-provider credential environment variables from all child processes, including:

```text
OPENAI_API_KEY
ANTHROPIC_API_KEY
GOOGLE_API_KEY
GEMINI_API_KEY
```

The result records:

```text
llm.enabled = false
oracle_policy.loaded_after_investigation = true
oracle_policy.used_to_construct_diagnosis = false
```

This benchmark proves the Causcope reasoning loop, not a model's ability to improvise.

A future agent benchmark may run the same public scenario through an LLM-backed MCP client, but it must be scored against the same hidden oracle contract.

## Result contract

The runner emits `acceptance_benchmark_result` JSON containing:

```text
benchmark identity
surface identity
scenario identity
Investigation identity
LLM policy
oracle policy
hidden expectations
observed final state
individual checks
passed boolean
```

The schema is:

```text
schema/acceptance-benchmark-result.schema.json
```

The output is intended to be stable enough for CI and future cross-surface comparison.

## Canonical command

From the repository root:

```bash
python scripts/run_acceptance_benchmark.py \
  --scenario sqlite-write-lock \
  --workspace /tmp/causcope-acceptance \
  --result /tmp/causcope-acceptance.json
```

The runner owns the reference-system lifecycle for the benchmark:

```text
down -> up -> investigate -> fault -> verify -> Causcope -> why projection -> score -> stop -> down
```

## What is scored

The first slice scores semantic product outcomes rather than exact prose or incidental ordering:

1. exactly one diagnosis matches the expected target and scope subset;
2. the expected canonical hypothesis ranks first;
3. the required discriminating probe completed;
4. the evidence revision advanced far enough to prove feedback-loop execution;
5. `causcope why --json` exposes the same expected diagnosis scope;
6. the product projection exposes the same leading hypothesis as the canonical autonomous result;
7. the product projection reads the same final evidence revision rather than a stale snapshot.

CI also keeps stronger evidence-provenance assertions for the canonical lock observation:

```text
source.type == probe
source.name == probe.database.inspect_lock_error_events
labels.scope_correlation == request_metadata
```

This prevents a benchmark pass from being achieved by merely hard-coding the final hypothesis.

## Product front-door projection

The acceptance runner now invokes the real product front door after the deterministic autonomous loop has finished and before the hidden oracle is loaded:

```bash
causcope why --workspace <benchmark-workspace> --json
```

The benchmark does not ask `why` to recompute a second diagnosis. It verifies that the product projection consumes the same persisted canonical Investigation and exposes the same target, scope, leading hypothesis, and evidence revision.

This closes the first cross-surface consistency check:

```text
deterministic autonomous loop
  -> canonical persisted Investigation
  -> causcope why product projection
  -> same semantic answer
```

A stale projection, a different leading hypothesis, or a scope mismatch fails the benchmark even when the underlying autonomous loop itself passed.

## Determinism boundary

Deterministic means:

- the same semantic rules and ranking contracts are used;
- probe selection is not delegated to an LLM;
- the oracle is not visible to the investigator or product projection;
- the fault is controlled and repeatable;
- scoring is machine-readable and stable;
- unknown/insufficient evidence remains explicit.

It does not mean wall-clock timing, container IDs, timestamps, request IDs, or every log line must be byte-identical across runs.

## Relationship to labs

This benchmark does not replace `lab/`.

```text
lab/
  tests mechanism claims

lab/investigation/
  tests investigation behavior

canonical acceptance benchmark
  tests the bounded product loop against a hidden real fault
```

Mechanism labs should remain small and focused rather than being rewritten as product acceptance tests.

## Future surfaces

The same scenario/oracle pair should later be reusable for:

```text
deterministic local loop      # implemented
CLI product projection        # implemented as read-only cross-surface check
MCP agent
LLM-backed agent
Dashboard
Cloud/Relay
```

A new surface should not get a different answer key.

Differences in presentation are allowed. Differences in canonical evidence, scope, probe provenance, or diagnosis require explanation.

## Initial Definition of Done

The slice is complete when CI proves:

1. the public scenario does not contain oracle-only benchmark fields;
2. the deterministic scorer has positive and negative unit cases;
3. AI provider credentials are stripped from child execution;
4. the Docker Compose SQLite fault is injected and publicly verified;
5. Causcope runs the bounded autonomous read-only loop without oracle access;
6. `causcope why` projects the completed Investigation before oracle access;
7. the hidden oracle is loaded only after the run and product projection;
8. the final hypothesis and evidence revision satisfy the hidden scoring contract;
9. the `why` projection matches the canonical target/scope, hypothesis, and evidence revision;
10. the correlated lock observation has canonical probe provenance;
11. the benchmark result validates against its JSON Schema.

All eleven checks are exercised by the Shop CI workflow when this revision is active.

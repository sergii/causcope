# RFC 0033: Testbed Runtime Evidence Bridge

Status: Accepted

## Summary

The integration testbed proves that Causcope can run beside a small realistic application, but RFC 0032 intentionally stopped before automatic evidence collection. An investigator still had to inspect Docker logs manually and then translate findings into Causcope runtime evidence.

This RFC adds the first read-only bridge from a running application into the existing evidence and diagnosis pipeline:

```text
running system
  -> read-only structured-log query
  -> runtime_evidence
  -> causal ranking
  -> recommended discriminating probe
```

The bridge does not introduce testbed-specific causal reasoning. It converts ordinary runtime observations into canonical observation concepts and lets the existing diagnosis engine reason over them.

## Source boundary

The first source is structured application logging from the Shop testbed. Causcope reads it through:

```text
docker compose logs app
```

This operation does not mutate the application, database, traffic generator, or scenario helper. Causcope-local files may be written under `.causcope/`.

The generic adapter is `scripts/structured_log_evidence.py`. Docker Compose is only the source transport used by `testbed/shop/causcope_bridge.py`.

That separation matters because the same adapter contract can later accept logs from Loki, Datadog, Elasticsearch, CloudWatch, journald, Kubernetes, or an MCP connector without changing the causal model.

## New diagnostic capability

The vocabulary adds:

```text
capability.logs.query
```

A probe can require this capability when it needs to aggregate already-recorded log events rather than execute a state-changing request against the system.

The first probe using it is:

```text
probe.http.compare_client_cohorts
```

which produces:

```text
observation.http.client_cohort_failure_skew
```

## Request-failure evidence

Structured `http_request` log events are grouped by:

```text
method
path
client_platform
app_version
```

For every observed cohort, the adapter emits:

```text
observation.http.request_failure
```

with an `observed` or `absent` state and a measured failure percentage.

A request failure is deliberately nonspecific. It is an outcome that may have multiple causal antecedents.

For the first integrated graph, both of these can contribute to the same HTTP failure observation:

```text
hypothesis.database.lock_contention
hypothesis.client.payload_contract_mismatch
```

This gives the diagnosis engine alternatives to rank rather than letting the adapter jump directly from an HTTP status to a root cause.

## Failing versus working cohorts

When comparable route cohorts have materially different failure rates, the adapter emits:

```text
observation.http.client_cohort_failure_skew
```

The observation records the failing and working cohort labels and the percentage-point difference.

The invariant remains:

```text
cohort difference != root cause
```

The causal graph may rank a client-contract hypothesis strongly from this evidence, but the evidence itself is only a discriminator.

## Database lock evidence

The Shop application already emits a structured `sqlite_operational_error` event when SQLite reports a lock failure. Reading that existing event is a read-only log query.

The adapter maps an explicit SQLite `database is locked` event to:

```text
observation.database.lock_wait_event
```

with source provenance identifying the structured log. It does not inspect the scenario oracle and it does not use the presence of the lock-holder container as evidence.

The causal graph connects:

```text
hypothesis.database.lock_contention
  -> observation.database.lock_wait_event
```

so the existing ranking engine can reach the hypothesis through normal causal edges.

## Files produced

A bridge run writes:

```text
.causcope/
  source-shop-app.log
  runtime-evidence.json
  diagnosis.json
  diagnosis-summary.json
```

If an Investigator CLI workspace already exists, its `incident_id` is reused. Otherwise the caller must provide an explicit incident id.

The bridge does not rewrite incident context from telemetry. Context and evidence remain separate records.

## Dogfood workflow

```text
./testbed/shop/testbed up
./testbed/shop/testbed scenario start sqlite-write-lock --duration 180

./bin/causcope investigate \
  "Some order writes fail intermittently while product reads remain healthy."

./testbed/shop/testbed causcope --workspace .causcope
```

The resulting diagnosis can then be compared with the scenario oracle only after the investigation:

```text
./testbed/shop/testbed scenario reveal sqlite-write-lock
```

## Safety

The bridge is read-only with respect to the observed system:

- it reads Docker Compose logs;
- it parses already-recorded JSON events;
- it does not invoke scenario activation or verification;
- it does not issue HTTP writes;
- it does not modify SQLite;
- it never reads `oracle.json`.

Scenario activation remains a separate testbed action controlled by the operator or CI.

## Why this is not a testbed-only architecture

The reusable boundary is:

```text
telemetry source
  -> adapter
  -> canonical runtime_evidence
  -> Causcope diagnosis core
```

Only the source transport is testbed-specific today. The observation concepts, evidence schema, scope semantics, causal ranking, probe ranking, and diagnosis snapshot are the same contracts used elsewhere in Causcope.

This is the first concrete path from the repository's ontology into a future SRE MCP or SaaS product: adapters can collect evidence from connected systems while the reasoning model stays stable.

## Next step

The next slice should make selected `risk: read_only` probe recommendations executable through source adapters rather than merely reporting them as unavailable. For example:

```text
probe.http.compare_client_cohorts
  -> structured-log executor

probe.database.inspect_lock_waits
  -> database/log executor appropriate to the engine
```

That would close the loop from diagnosis to evidence-producing probe execution without allowing the agent to mutate the production system.

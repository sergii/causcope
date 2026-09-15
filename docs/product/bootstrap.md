# Bootstrap product state

Status: Implemented initial system + incident bootstrap slices

This document is the product projection of:

```text
RFC/0079-agent-first-rails-postgresql-bootstrap.md
RFC/0080-observed-rails-incident-bootstrap.md
```

## Product boundary

Causcope distinguishes two different bootstrap problems:

```text
system bootstrap
  -> what exists?
  -> what exact resources are known?
  -> which safe evidence providers can inspect them?

incident bootstrap
  -> what was actually observed for this Investigation?
  -> which runtime identity connects the symptom to an exact resource?
  -> which empirically grounded mechanisms remain plausible?
  -> what should be checked next?
```

Both now have an implemented bounded Rails/PostgreSQL local-agent slice.

Neither requires Causcope Cloud.

## System bootstrap

```bash
causcope bootstrap ./my-rails-app \
  --database app_production \
  --database-url-env CAUSCOPE_PRODUCTION_DATABASE_URL
```

The command reuses the revision-bound Rails scanner and writes:

```text
.causcope/
  concrete-system-facts.json
  resource-topology.yaml
  pgbot-postgresql.yaml
  provider-bindings.yaml
```

The deterministic setup path is:

```text
Rails repository
  -> revision-bound concrete system facts
  -> selected ActiveRecord PostgreSQL pool
  -> explicit pool -> PostgreSQL target runtime binding
  -> local runner
  -> exact pgbot provider instance
  -> pgbot_cli binding
  -> named environment-variable secret boundary
```

System bootstrap does not query PostgreSQL and does not manufacture runtime evidence or diagnosis.

It explicitly reports:

```text
runtime_evidence_created: false
diagnosis_created: false
```

That remains a product invariant.

### Multi-database safety

If one PostgreSQL ActiveRecord pool exists, bootstrap may select it.

If several exist, the user must specify:

```text
--pool-config <config_name>
```

The expected database identity is explicit:

```text
--database <database_name>
```

Later live pgbot evidence is checked against that identity before it can enter the Investigation.

Raw DSNs are not stored in the workspace. `provider-bindings.yaml` stores only the name of the environment variable that resolves the DSN.

## Investigation creation

The human-facing front door remains:

```bash
causcope why "checkout is slow"
```

With no diagnostic evidence yet, `why` creates or resumes the local Investigation/scoping state and asks the next unresolved scoping question.

It does not infer a root cause from the problem statement.

The current compatibility storage still uses:

```text
.causcope/incident-context.yaml
```

while RFC 0076 defines `Investigation` as the intended Causcope-owned parent concept.

## Runtime observation

The portable Rails runtime and OTLP receiver can now reuse the active Investigation identity automatically:

```bash
causcope runtime start ./my-rails-app
```

Unless explicitly overridden, the command reads the current identity from the workspace and writes concrete runtime facts under:

```text
.causcope/runtime/<investigation-id>.json
```

The user then reproduces the observed behavior while Rails instrumentation emits exact request and ActiveRecord pool identity.

## Incident bootstrap

The first implemented incident seed is intentionally narrow:

```bash
causcope runtime seed ./my-rails-app \
  --request-latency-threshold-ms 200 \
  --pool-wait-threshold-ms 50
```

The two objectives are explicit because a measured value alone does not prove abnormality.

The seed selects only an execution that satisfies all of these conditions:

```text
same current Investigation
request duration > explicit request objective
same execution has exact ActiveRecord checkout event
checkout wait > explicit pool-wait objective
runtime relationship exists
runtime resource has explicit topology binding
all relevant relationships resolve to exactly one target
```

Optional selectors can narrow the observation:

```text
--code-symbol
--trace-id
```

If the contract cannot be proven, Causcope fails closed and does not create diagnosis revision 1.

## Canonical revision-1 evidence

A successful seed writes:

```text
.causcope/runtime-evidence.json
.causcope/runtime-relationships.json
.causcope/diagnosis.json
```

The initial evidence contains two observations from the same trace and scope:

```text
observation.http.request_latency
observation.database.connection_pool_wait_time
```

The request-latency observation is the user-visible symptom.

The pool-wait observation is a discriminating runtime fact. It favors an application-side pool mechanism but does not claim that SQL execution or PostgreSQL itself is healthy.

## Candidate model

The repository now has empirical causal grounding for two distinct explanations of the same slow request.

### Application-side pool contention

```text
hypothesis.database.connection_pool_exhaustion
  -> connection pool checkout wait
  -> request latency when checkout is on the critical path
```

Grounded by:

```text
claim.database.connection_pool_exhaustion.checkout_wait_drives_latency
experiment.database.connection_pool_exhaustion.python_postgres
```

### Database query delay

```text
hypothesis.latency.database
  -> request latency when synchronous database work is on the critical path
```

Grounded by:

```text
claim.latency.database.query_delay_propagates_upstream
experiment.latency.database.query_delay_python_postgres
```

For the implemented proof, revision 1 therefore ranks:

```text
1. hypothesis.database.connection_pool_exhaustion
2. hypothesis.latency.database
```

The first candidate receives stronger support because elevated checkout wait was directly observed on the same request.

This is still candidate ranking, not root-cause confirmation.

## Next discriminator

The existing deterministic probe-ranking engine remains unchanged.

With those two alternatives it selects:

```text
probe.database.measure_query_latency
```

The useful contrast is:

```text
pool wait high + query latency near baseline
  -> supports application pool contention relative to slow-query latency

query latency materially high
  -> supports database-latency alternative
```

The seed does not pre-answer that question.

It hands the Investigation into the already-existing evidence acquisition loop.

## Exact-target requirement

The initial diagnosis must resolve through the same runtime identity chain used later for provider routing:

```text
request-latency observation
  -> exact trace
  -> runtime used_resource relationship
  -> ActiveRecord pool
  -> explicit topology runtime binding
  -> exact PostgreSQL target
  -> ranked next probe
```

For the product proof this becomes:

```text
pool:active_record.primary
  -> db.causcope.prod

next probe
  -> probe.database.measure_query_latency
```

Causcope does not route a database provider merely because the application has only one database or because the problem text sounds database-related.

## Continuing the investigation

After revision 1 exists:

```bash
causcope why
```

projects the persisted diagnosis, candidate ranking, next discriminator, exact target, and available provider route.

When a bounded read-only provider is available, acquisition remains explicit:

```bash
causcope why --acquire
```

That reuses the existing target-aware execution-set machinery:

```text
revision N
  -> exact target
  -> selected safe provider
  -> explicit read-only acquisition
  -> canonical evidence
  -> atomic evidence + diagnosis commit
  -> revision N + 1
  -> rerank
```

## What has been proven

The CI-backed local path now covers:

```text
Rails repo
  -> system bootstrap
  -> Investigation creation
  -> runtime receiver bound to same Investigation
  -> concrete slow request + exact pool checkout observation
  -> incident seed revision 1
  -> D3.1 vs database-latency alternatives
  -> query-latency discriminator
  -> exact PostgreSQL target
  -> persisted `causcope why` projection
```

Negative paths include:

```text
low checkout wait below objective -> no seed
runtime facts from another Investigation -> no seed
ambiguous/unbound target -> no seed
overwrite without --force -> rejected
```

## What remains

Bootstrap is no longer the main missing reasoning link for this bounded Rails/PostgreSQL slice.

The remaining product work is primarily ergonomics and breadth:

```text
orchestrate receiver + instrumented Rails process more cleanly
store/service objectives instead of always passing thresholds on CLI
reduce manual reproduce/start/seed steps
support more observed symptom shapes
support additional runtime/provider targets when a concrete use case requires them
connect the same contracts to Dashboard/Cloud/Relay later
```

The important invariant remains:

> Automation may reduce setup steps, but it must not weaken provenance, explicit objectives, exact runtime identity, or target resolution.

## Relationship to future Cloud and Relay

No bootstrap-specific reasoning should be added to Cloud or Relay.

Future deployment surfaces should produce or transport the same contracts:

```text
Concrete System Facts
Resource Topology
Provider Bindings / Capability declarations
Runtime Evidence
Runtime Relationships
Diagnosis Snapshot
```

A Helm chart, Relay daemon, Dashboard, or managed Cloud setup wizard may automate discovery, configuration, and lifecycle management, but the Investigation engine should see the same semantic objects.

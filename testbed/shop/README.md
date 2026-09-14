# Causcope Shop Testbed

This is a deliberately small but real application used to dogfood Causcope end to end.

It is not a mechanism micro-lab and it is not only an investigation fixture. The shop is a persistent reference system with real HTTP requests, a real SQLite database, Docker process boundaries, application logs, working controls, and failure scenarios that can be activated and investigated without changing the Causcope reasoning core.

## Why this exists

Causcope now has three complementary executable layers:

```text
lab/
  Proves individual failure mechanisms empirically.

lab/investigation/
  Tests whether an investigator follows the right reasoning process.

testbed/
  Runs the complete product against a small realistic application.
```

The testbed is where ontology, incident scoping, evidence collection, probes, agent tooling, MCP, and future SaaS adapters can meet one running system.

## System

```text
                  HTTP :18080
                      |
              +-------v--------+
              | FastAPI shop   |
              | Python 3.13    |
              +-------+--------+
                      |
                 SQLite/WAL
                      |
                /data/shop.db

Scenario helpers share the same Docker Compose topology:

  lock-holder   -> competing SQLite writer
  mobile-client -> web + iOS cohort traffic
```

The application exposes:

```text
GET  /health
GET  /products
POST /orders
GET  /orders/{id}
POST /orders/{id}/pay
```

The request log includes request ID, route, status, client platform, app version, duration, and observation time. SQLite operational errors inherit the same request metadata so diagnostic evidence can be correlated to an exact request scope instead of guessed from timing alone.

## Start and verify the happy path

From the repository root:

```bash
./testbed/shop/testbed up
./testbed/shop/testbed smoke
```

The service listens on `127.0.0.1:18080` by default. Override it with `SHOP_PORT`.

List scenarios:

```bash
./testbed/shop/testbed scenario list
```

Stop everything and delete the test database:

```bash
./testbed/shop/testbed down
```

## Autonomous read-only mode

The most complete dogfood path is now:

```text
passive runtime evidence
  -> causal ranking
  -> ranked discriminating probe
  -> statically allowlisted read-only executor
  -> new runtime evidence
  -> re-rank
  -> next read-only probe or bounded stop
```

Run it with:

```bash
./testbed/shop/testbed causcope \
  --autonomous \
  --workspace .causcope
```

Autonomous mode is deliberately bounded. It executes only canonical probes that are both `risk: read_only` and statically registered by the Shop adapter. It does not run arbitrary shell commands, mutate the observed system, activate scenarios, apply remediation, or read scenario oracles.

The Shop adapter currently supports:

```text
probe.http.compare_client_cohorts
probe.database.inspect_lock_error_events
```

If a probe cannot make a justified `observed` or `absent` claim, the run records `insufficient_evidence` and tries the next ranked eligible probe. It does not invent an `absent` result.

Autonomous mode writes an explicit audit trail:

```text
.causcope/
  incident-context.yaml             # when started through investigator CLI
  investigation-session.yaml        # when started through investigator CLI
  scoping-projection.json           # when started through investigator CLI
  source-shop-app.log
  initial-runtime-evidence.json
  initial-diagnosis.json
  autonomous-run.json
  runtime-evidence.json
  diagnosis.json
  diagnosis-summary.json
```

Inspect the reasoning transition with:

```bash
cat .causcope/autonomous-run.json
cat .causcope/diagnosis-summary.json
```

## Scenario 1: SQLite write lock

Start the fault for three minutes:

```bash
./testbed/shop/testbed scenario start sqlite-write-lock --duration 180
./testbed/shop/testbed scenario report sqlite-write-lock
./testbed/shop/testbed scenario verify sqlite-write-lock
```

The public report intentionally does not reveal the root cause.

Start a Causcope investigation if you want the normal incident workspace:

```bash
./bin/causcope investigate \
  "Some order writes fail intermittently while product reads remain healthy."
```

Then run the bounded autonomous loop:

```bash
./testbed/shop/testbed causcope \
  --autonomous \
  --workspace .causcope
```

The initial autonomous evidence contains direct request outcomes only. Causcope must choose a discriminating probe before the stronger diagnostic finding appears.

With only one comparable order client cohort, `probe.http.compare_client_cohorts` may legitimately report insufficient evidence. The loop can then execute:

```text
probe.database.inspect_lock_error_events
```

against the same request scope. A correlated SQLite `database is locked` event becomes:

```text
observation.database.lock_error_event
```

with probe provenance. The existing causal engine then re-ranks `hypothesis.database.lock_contention`; the adapter itself does not assign the cause.

Useful raw surfaces remain available for manual comparison:

```bash
docker compose -f testbed/shop/compose.yaml logs app
curl -i http://127.0.0.1:18080/products
curl -i \
  -H 'Content-Type: application/json' \
  -d '{"items":[{"product_id":1,"quantity":1}]}' \
  http://127.0.0.1:18080/orders
```

After the investigation, reveal benchmark ground truth only for scoring or manual comparison:

```bash
./testbed/shop/testbed scenario reveal sqlite-write-lock
./testbed/shop/testbed scenario stop sqlite-write-lock
```

## Scenario 2: mobile payload regression

Start repeat traffic from a healthy web cohort and a failing iOS cohort:

```bash
./testbed/shop/testbed scenario start mobile-bad-payload
./testbed/shop/testbed scenario report mobile-bad-payload
./testbed/shop/testbed scenario verify mobile-bad-payload
sleep 5
```

Run the autonomous investigation:

```bash
./testbed/shop/testbed causcope \
  --autonomous \
  --incident-id incident.local.mobile-payload \
  --workspace /tmp/causcope-mobile
```

The initial evidence shows the iOS order requests failing and the web order requests succeeding, but autonomous mode does not precompute the higher-order cohort finding.

Causcope can choose:

```text
probe.http.compare_client_cohorts
```

which compares the same method/path across platform/version cohorts and emits:

```text
observation.http.client_cohort_failure_skew
```

into the selected failing iOS diagnosis scope. The interpretation remains:

```text
client cohort difference != root cause
```

The lock-error probe can also produce an explicit `absent` result for that same iOS request scope when matching requests are present but no correlated lock error exists. Together those observations change the normal causal ranking toward `hypothesis.client.payload_contract_mismatch` without granting either probe direct authority over the diagnosis.

Inspect raw traffic when useful:

```bash
docker compose -f testbed/shop/compose.yaml logs -f app mobile-client
```

Reveal the oracle only after the investigation:

```bash
./testbed/shop/testbed scenario reveal mobile-bad-payload
```

## Scenario contracts and oracles

Each scenario has two machine-readable files:

```text
scenarios/<slug>/scenario.json
scenarios/<slug>/oracle.json
```

`scenario.json` is safe to expose to an investigator. It contains the initial incident report, activation metadata, known working controls, and black-box verification checks.

`oracle.json` is ground truth for benchmark scoring and regression tests. The validator rejects root-cause/evidence oracle keys if they leak into the public scenario contract.

The schemas are:

```text
schema/testbed-scenario.schema.json
schema/testbed-scenario-oracle.schema.json
```

## Runtime evidence bridge

The non-autonomous bridge remains available for direct telemetry ingestion:

```bash
./testbed/shop/testbed causcope --workspace .causcope
```

Its path is:

```text
Docker Compose structured logs
  -> scripts/structured_log_evidence.py
  -> runtime_evidence
  -> existing live diagnosis engine
  -> causal ranking
  -> recommended discriminating probe
```

For backward compatibility this mode can derive supported higher-order log findings during ingestion.

Autonomous mode instead uses the same adapter in passive-only form first, then lets the normal probe ranking decide whether a higher-order observation should be collected:

```text
structured logs
  -> passive request evidence
  -> diagnosis
  -> probe ranking
  -> read-only Shop probe adapter
  -> additional canonical evidence
  -> updated diagnosis
```

The reusable boundary remains canonical `runtime_evidence`. Docker Compose is only the first source transport; future providers can query Loki, Datadog, Elasticsearch, CloudWatch, journald, Kubernetes, or deterministic MCP-connected diagnostic tools without creating a second reasoning engine.

## Safety boundary

The autonomous Shop loop enforces all of these constraints before evidence can affect a re-ranking:

```text
recommended by deterministic probe ranking
AND statically supported by the adapter
AND canonical risk == read_only
AND emitted observation is declared by probe.produces
AND source.type == probe
AND source.name == probe id
AND evidence scope == selected diagnosis scope
AND bounded max_steps
```

A source that cannot justify the requested scope must fail closed as insufficient evidence.

The loop performs no remediation. Verification after a future fix remains a separate phase tied back to the original incident scope.

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

The request log includes request ID, route, status, client platform, app version, duration, and observation time. That is ordinary runtime evidence, not a hidden root-cause endpoint.

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

## Scenario 1: SQLite write lock

Start the fault for three minutes:

```bash
./testbed/shop/testbed scenario start sqlite-write-lock --duration 180
./testbed/shop/testbed scenario report sqlite-write-lock
```

The public report intentionally does not reveal the root cause.

Start a Causcope investigation:

```bash
./bin/causcope investigate \
  "Some order writes fail intermittently while product reads remain healthy."
```

Causcope can now read the normal application log surface without mutating the shop and feed it through the canonical runtime-evidence and diagnosis pipeline:

```bash
./testbed/shop/testbed causcope --workspace .causcope
```

That writes:

```text
.causcope/
  incident-context.yaml
  investigation-session.yaml
  scoping-projection.json
  source-shop-app.log
  runtime-evidence.json
  diagnosis.json
  diagnosis-summary.json
```

For this scenario, explicit SQLite lock errors can become `observation.database.lock_wait_event`, and HTTP request outcomes become scoped `observation.http.request_failure` evidence. Causal ranking still happens in the normal Causcope engine; the adapter does not read the oracle or assign the root cause itself.

Useful raw surfaces remain available for manual comparison:

```bash
docker compose -f testbed/shop/compose.yaml logs app
curl -i http://127.0.0.1:18080/products
curl -i \
  -H 'Content-Type: application/json' \
  -d '{"items":[{"product_id":1,"quantity":1}]}' \
  http://127.0.0.1:18080/orders
```

The scenario contract can check only the externally observable surface:

```bash
./testbed/shop/testbed scenario verify sqlite-write-lock
```

After the investigation, reveal the ground truth:

```bash
./testbed/shop/testbed scenario reveal sqlite-write-lock
```

Then stop the helper:

```bash
./testbed/shop/testbed scenario stop sqlite-write-lock
```

## Scenario 2: mobile payload regression

Start repeat traffic from a healthy web cohort and a failing iOS cohort:

```bash
./testbed/shop/testbed scenario start mobile-bad-payload
./testbed/shop/testbed scenario report mobile-bad-payload
```

Let the cohorts produce several comparable requests, then run the evidence bridge:

```bash
sleep 5
./testbed/shop/testbed causcope \
  --incident-id incident.local.mobile-payload \
  --workspace /tmp/causcope-mobile
```

The structured-log adapter groups HTTP outcomes by method, path, client platform, and app version. A material failing-versus-working difference becomes:

```text
observation.http.client_cohort_failure_skew
```

The intended interpretation remains:

```text
client cohort difference != root cause
```

The causal graph can rank `hypothesis.client.payload_contract_mismatch` from this evidence, but source provenance and the distinction between discriminator and cause are preserved.

Inspect the app and client logs directly when useful:

```bash
docker compose -f testbed/shop/compose.yaml logs -f app mobile-client
```

Verify the observable behavior:

```bash
./testbed/shop/testbed scenario verify mobile-bad-payload
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

The current integrated path is:

```text
Docker Compose structured logs
  -> scripts/structured_log_evidence.py
  -> runtime_evidence
  -> existing live diagnosis engine
  -> causal ranking
  -> recommended discriminating probe
```

The reusable boundary is the adapter into canonical `runtime_evidence`. Docker Compose is only the first source transport; future adapters can query Loki, Datadog, Elasticsearch, CloudWatch, journald, Kubernetes, or MCP-connected telemetry without creating a second reasoning engine.

The bridge is read-only with respect to the observed system. It reads logs and writes Causcope-local evidence/diagnosis files; it never activates scenarios, issues HTTP writes, modifies SQLite, or reads `oracle.json`.

## Current boundary

Recommended probes are now produced from real testbed evidence, but most source-specific probes are not yet executable through the generic built-in probe executor registry. The next integration is to bind selected `risk: read_only` probes to source adapters so an agent can close the loop:

```text
running system
  -> evidence
  -> causal ranking
  -> recommended probe
  -> safe read-only executor
  -> new evidence
  -> updated ranking
  -> verification against the original incident scope
```

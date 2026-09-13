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

The request log includes request ID, route, status, client platform, app version, and duration. That is ordinary runtime evidence, not a hidden root-cause endpoint.

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

Now start a real Causcope investigation:

```bash
./bin/causcope investigate \
  "Some order writes fail intermittently while product reads remain healthy."
```

Useful raw surfaces during the investigation include:

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

Inspect the app and client logs:

```bash
docker compose -f testbed/shop/compose.yaml logs -f app mobile-client
```

The intended investigation should discover a failing-versus-working cohort before making a causal claim. Client version is a discriminator first, not automatically the cause.

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

## Current boundary

This first slice deliberately does not auto-connect testbed logs to Causcope runtime evidence. Today a human or agent can inspect the running system and record investigation context manually.

The next integration is to let Causcope consume this same testbed through read-only probes and telemetry adapters so that:

```text
running system
  -> scoped observation
  -> runtime evidence
  -> causal ranking
  -> next discriminating probe
  -> verification against the original incident scope
```

That step should extend the existing evidence/probe contracts rather than add testbed-specific reasoning.

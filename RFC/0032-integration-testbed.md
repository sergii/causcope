# RFC 0032: Integration Testbed

Status: Accepted

## Summary

Causcope already has two executable validation layers:

1. mechanism labs that test whether a diagnostic mechanism is empirically reproducible;
2. investigation labs that test whether an investigator follows the intended reasoning process.

Neither layer proves that the complete Causcope workflow remains useful against a small but realistic running application with persistent state, process boundaries, client cohorts, request logs, and failures that emerge from ordinary system behavior.

This RFC introduces `testbed/` as a third executable layer.

## Layering

```text
lab/
  question: is this mechanism real and observable?

lab/investigation/
  question: can an investigator discover the cause from incomplete information?

testbed/
  question: can the complete Causcope product investigate a running reference system?
```

The layers are complementary. A testbed scenario may reuse a mechanism that is already covered by a lab, but it should exercise that mechanism through a realistic application boundary instead of replacing the empirical lab.

## First reference system

The first testbed is `testbed/shop/`:

```text
FastAPI
  -> SQLite in WAL mode
  -> Docker Compose
```

The application implements a minimal shop flow with products, orders, order items, and payments.

It intentionally remains small. The purpose is not to benchmark framework complexity or reproduce a production commerce platform. The purpose is to provide enough real state and runtime behavior for Causcope integrations to have something honest to investigate.

## Scenario model

A scenario has a public contract and a separate oracle:

```text
scenarios/<slug>/scenario.json
scenarios/<slug>/oracle.json
```

The public scenario may contain:

- an initial incident report;
- activation metadata;
- known working controls;
- black-box verification checks.

It must not contain root cause, expected evidence, or hidden causal truth.

The oracle may contain:

- root-cause mechanism;
- expected discriminators;
- expected evidence;
- causal notes.

This separation lets the same scenario support human dogfooding, agent evaluation, and deterministic regression testing without giving the investigator the answer in the normal input contract.

## Activation semantics

Scenario activation is allowed to use helper processes when those processes reproduce a real system condition rather than bypassing the application with a synthetic error endpoint.

Examples in the first slice:

- a second SQLite writer holds a real `BEGIN IMMEDIATE` transaction, producing genuine single-writer contention;
- a mobile-client process sends a real contract-incompatible payload while an equivalent web cohort continues to succeed.

The application does not expose an endpoint such as `/fail?type=db_lock` to manufacture the expected status code.

## Observable surface

Scenario verification is black-box. It checks HTTP behavior visible to an external client.

The scenario oracle is not consulted to generate application responses.

This preserves an important benchmark property:

```text
failure mechanism
  -> runtime behavior
  -> observations
  -> investigation
```

instead of:

```text
scenario id
  -> hard-coded expected error
```

## Relationship to Causcope state

The testbed must not introduce testbed-specific causal ranking or incident semantics.

A real investigation should still flow through the same product contracts:

```text
incident_context
  -> scoping_projection
  -> investigation_session
  -> runtime_evidence
  -> causal ranking
  -> probe recommendation
  -> verification
```

Today the testbed provides the running system and raw observable surfaces. A human or agent can use the existing investigator CLI to record context manually.

Future integrations should translate testbed telemetry and read-only probes into the existing runtime-evidence and probe contracts.

## First scenarios

### SQLite write lock

A helper process shares the application SQLite volume and holds a real write transaction. Reads remain healthy while writes exceed the application's short busy timeout.

This scenario exercises:

- flow scope;
- reproducibility;
- failing-versus-working operation comparison;
- database contention evidence;
- the distinction between symptom and mechanism.

### Mobile payload regression

A traffic generator emits a healthy web request and a failing iOS 7.42.0 request. The iOS client serializes an integer field as a string while the server contract requires a strict integer.

This scenario exercises:

- client cohort discovery;
- failing-versus-working comparison;
- contract/data-shape evidence;
- the invariant that a client version is a discriminator before it becomes a causal conclusion.

## Non-goals

The first testbed does not:

- emulate Kubernetes or a multi-region production platform;
- introduce Prometheus or an OpenTelemetry Collector merely for realism;
- auto-generate Causcope evidence from every application log;
- require an LLM;
- replace existing mechanism labs;
- expose scenario oracle data through the application.

Those additions should happen only when they test a concrete Causcope integration boundary.

## Product direction

The testbed creates a stable place to dogfood future product surfaces:

```text
Causcope CLI
Causcope MCP
agent harness
HTTP API
SaaS control plane
telemetry adapters
read-only probe executors
```

All of them should be able to investigate the same reference incidents and be compared against the same machine-readable oracle.

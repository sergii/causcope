# RFC 0054: Third X-Ray mechanism proof - D3.1 connection-pool exhaustion

- Status: Implemented proof
- Date: 2026-09-14
- Scope: Validate the RFC 0053 declarative X-Ray engine on a third independent failure mechanism without adding mechanism-specific projection code

## Summary

RFC 0051 proved a database deadlock path. RFC 0052 proved duplicate external side effects after an ambiguous retry. RFC 0053 extracted their repeated epistemic progression into a bounded deterministic X-Ray engine.

This RFC tests whether that abstraction survives a third mechanism that has different causal structure:

```text
application connection pool reaches capacity
  -> concurrent request waits for checkout
  -> request latency increases
  -> SQL itself remains fast
  -> PostgreSQL still accepts an independent connection
  -> holder releases the slot
  -> checkout wait and request latency recover
  -> application pool exhaustion is causally supported
```

The mechanism is already represented independently in Causcope as:

- catalog code `D3.1`;
- `hypothesis.database.connection_pool_exhaustion`;
- `claim.database.connection_pool_exhaustion.checkout_wait_drives_latency`;
- `experiment.database.connection_pool_exhaustion.python_postgres`;
- the Docker Compose lab under `lab/database-connection-pool/`.

The proof therefore adds no new domain analyzer and no `d3_1_projection.py`.

## Why this is a useful third family

D3.1 differs materially from the first two X-Ray proofs.

D2.2 depends on a cyclic wait-for graph and exact database-session correlation. Duplicate side effect depends on retry identity, provider effects and an idempotency counterfactual. D3.1 instead depends on queueing at an application-owned resource boundary plus discriminating controls that reject nearby explanations.

The reusable abstraction must therefore handle all three shapes:

```text
cyclic relational mechanism
retry / duplicate-effect mechanism
resource saturation / latency attribution mechanism
```

without embedding any of those meanings in `scripts/xray_engine.py`.

## Existing deterministic analyzer

`lab/database-connection-pool/probe.py` already performs the controlled experiment and emits schema-validated `empirical_evidence`.

The intervention deliberately uses an application pool with capacity one. A holder request occupies that slot while sleeping in application code. A measured concurrent request then waits for checkout before running the same `SELECT 1` used at baseline.

The analyzer separately measures:

- connection checkout wait;
- end-to-end request latency;
- SQL query latency after checkout;
- application-pool utilization;
- an independent direct PostgreSQL connection;
- recovery after the holder releases the slot.

It emits deterministic assertions using explicit thresholds. The X-Ray engine does not reproduce those measurements or thresholds.

This preserves the boundary:

```text
instrument / domain analyzer
  -> deterministic sourced assertions
  -> declarative X-Ray profile
  -> generic epistemic progression
```

## Declarative profile

`xray/profiles/d3-1-connection-pool.yaml` defines five ordered stages.

### PRECONDITIONS_PRESENT

The input evidence must identify the canonical D3.1 experiment and claim.

### POOL_SATURATED

The intervention must explicitly occupy all application pool slots and the deterministic analyzer must report the application pool at capacity.

### CHECKOUT_WAIT_OBSERVED

Both pool checkout wait and request latency must increase during the intervention.

### DATABASE_CAPACITY_DISTINGUISHED

The SQL query must remain near baseline and an independent direct PostgreSQL connection must remain available. These controls distinguish application pool exhaustion from two nearby alternatives:

```text
slow SQL execution
PostgreSQL-wide connection admission exhaustion
```

### CAUSAL_DIAGNOSIS_CONFIRMED

The added checkout wait must explain the request-latency increase, and both checkout wait and request latency must recover after the holder releases the slot.

The final result must remain `supports`.

## Fail-closed tests

The CI proof intentionally tampers with three independent discriminators.

If `checkout_wait_explains_request_delta` becomes false, progression stops at `DATABASE_CAPACITY_DISTINGUISHED`.

If `database_still_accepts_direct_connections` becomes false, progression stops at `CHECKOUT_WAIT_OBSERVED`.

If `application_pool_was_at_capacity` becomes false, progression stops at `PRECONDITIONS_PRESENT`.

The engine must never infer the missing causal step from the remaining evidence.

## What this proves

After this RFC, the same generic engine has expressed three different mechanism families without mechanism-specific projection Python:

```text
D2.2 deadlock
Q2.1 duplicate side effect
D3.1 application connection-pool exhaustion
```

This is stronger evidence that the RFC 0053 abstraction is a reusable deterministic proof engine rather than a common wrapper around two special cases.

## What this does not prove

This slice reuses a controlled empirical lab. It does not yet bind D3.1 to a revision-pinned production application, request trace, or concrete source-code path.

That distinction is deliberate. The purpose of RFC 0054 is to validate the projection abstraction against an independently modeled third mechanism.

A later Concrete System X-Ray slice can bind the same D3.1 semantics to application configuration, runtime pool telemetry, traces and database evidence without changing the generic engine.

## Acceptance criteria

The proof is accepted when CI demonstrates all of the following:

1. The existing D3.1 Docker Compose experiment returns schema-valid evidence with result `supports`.
2. The declarative profile reaches `CAUSAL_DIAGNOSIS_CONFIRMED`.
3. No D3.1-specific projection script is introduced.
4. Removing the checkout-latency explanation prevents causal confirmation.
5. Removing the independent database control prevents the database-capacity distinction.
6. Removing pool saturation prevents progression beyond preconditions.
7. Existing semantic and generic-X-Ray validation remain green.

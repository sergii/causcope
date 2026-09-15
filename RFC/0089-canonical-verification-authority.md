# RFC 0089: Canonical verification is the product authority

- Status: Implemented
- Date: 2026-09-15
- Depends on: RFC 0087, RFC 0088

## Decision

`causal_verification` is the only normal product authority for claims that an Investigation has been causally verified.

The historical Rails X-Ray state:

```text
CAUSAL_DIAGNOSIS_CONFIRMED
```

remains a deterministic compatibility proof, but it is no longer auto-selected from files that merely happen to exist in a workspace.

## Product rule

Normal product state is:

```text
diagnosis.json
runtime-evidence.json
  -> causal_verification_projection
  -> claims[*].status = verified | incomplete
```

A product consumer asking whether causality is established must inspect canonical `causal_verification`, not a Rails-specific epistemic-state string.

## Compatibility rule

The old concrete D3.1 renderer remains callable only by explicit compatibility inputs:

```bash
causcope why \
  --static concrete-system-facts.json \
  --runtime concrete-runtime-facts.json \
  --pool resource-pool-runtime-evidence.json \
  --require-confirmed
```

This explicit path may still emit:

```text
CAUSAL_DIAGNOSIS_CONFIRMED
```

for historical tests, empirical proof reproduction, and migration checks.

The presence of those three files under `.causcope/` no longer activates the compatibility renderer.

## Why

Silent auto-detection created two possible authorities in one workspace:

```text
canonical Investigation state
vs.
legacy Rails X-Ray proof artifacts
```

That is unsafe for agents and confusing for users because file retention could change which diagnosis surface answered `causcope why`.

After RFC 0089, retained compatibility artifacts are inert unless the caller explicitly selects them.

## Entrypoint precedence

The product entrypoint now follows:

```text
--observe
  -> bounded observation orchestration

explicit --static/--runtime/--pool
  -> compatibility X-Ray renderer

canonical diagnosis.json + runtime-evidence.json
  -> canonical diagnosis + causal_verification

otherwise
  -> ordinary Investigation/scoping path
```

There is no workspace filename auto-discovery step for the legacy proof.

## `--require-confirmed`

On a canonical workspace:

```text
--require-confirmed
  -> require at least one causal_verification claim with status=verified
```

On the explicit compatibility path:

```text
--require-confirmed
  -> preserve the historical Rails X-Ray confirmation assertion
```

Without either canonical verification state or explicit compatibility inputs, the command fails closed.

## Demo classification

`scripts/demo_rails_pool.sh` is now explicitly labeled and invoked as a compatibility X-Ray proof. It passes all three old proof files on the command line instead of relying on workspace auto-detection.

This prevents the empirical lab from being mistaken for the normal product state model.

A future user-facing golden demo should seed/import the same canonical Investigation artifacts used by the normal product flow and end in `causal_verification.claims[*].status=verified`.

## Tests

The former workspace-golden test is retained as a migration boundary test. It proves:

1. legacy proof files sitting in a workspace do not silently produce `CAUSAL_DIAGNOSIS_CONFIRMED`;
2. `--require-confirmed` fails closed without canonical verification or explicit compatibility paths;
3. the same old proof still succeeds when all compatibility inputs are explicitly selected.

RFC 0088 tests continue to prove canonical CLI and MCP verification.

## Historical RFCs

Older RFCs describing `CAUSAL_DIAGNOSIS_CONFIRMED` are historical records of the mechanism proofs that introduced the state. They are not rewritten to pretend the state never existed.

Current product documentation and new integrations must refer to canonical causal verification instead.

## Next step

Build the reproducible three-minute golden demo entirely on the canonical Investigation path:

```text
problem
  -> observe/seed
  -> diagnosis revision 1
  -> discriminating evidence
  -> intervention/control/recovery evidence
  -> canonical commit
  -> causal_verification verified
  -> operator-visible explanation
```

At that point the explicit Rails X-Ray renderer can be considered for relocation under a dedicated compatibility/lab command rather than `causcope why`.

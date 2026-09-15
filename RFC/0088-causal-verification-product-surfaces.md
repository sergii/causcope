# RFC 0088: Canonical causal verification product surfaces

- Status: Implemented proof
- Date: 2026-09-15
- Depends on: RFC 0087

## Decision

Canonical causal verification is now a normal product surface, not a Rails D3.1-only presentation state.

When an Investigation workspace contains both `diagnosis.json` and `runtime-evidence.json`, normal:

```bash
./bin/causcope why --workspace .causcope
```

renders the ordinary diagnosis/routing projection and a read-only causal-verification section derived from the same persisted canonical state.

JSON adds:

```text
causal_verification.kind = causal_verification_projection
causal_verification.claims[*].status = verified | incomplete
```

No second diagnosis or ranking path is introduced.

## `--require-confirmed`

For canonical workspaces, `--require-confirmed` now means:

> fail closed unless at least one canonical intervention-based causal claim is `verified`.

It no longer rejects a workspace diagnosis merely because the old Rails compatibility proof was not supplied as three explicit files.

Explicit `--static/--runtime/--pool` remains supported as the Rails D3.1 compatibility surface. The compatibility state `CAUSAL_DIAGNOSIS_CONFIRMED` is not emitted by the canonical workspace path.

## Workspace precedence

A workspace may retain the old concrete Rails artifacts after canonical seeding/import. The product entrypoint must not let those compatibility files shadow canonical state.

Precedence is therefore:

1. explicit `--static/--runtime/--pool` means compatibility proof;
2. otherwise, if `diagnosis.json` plus `runtime-evidence.json` exist, use canonical workspace diagnosis and verification;
3. otherwise, the legacy auto-detected complete Rails D3.1 workspace proof remains available;
4. otherwise continue normal scoping/diagnosis behavior.

This makes migration monotonic: once canonical state exists, ordinary `causcope why` reads it.

## Human-readable surface

The canonical text projection reports:

```text
Causal verification
  VERIFIED: hypothesis.database.connection_pool_exhaustion
    target: db.causcope.prod
    intervention: resource_capacity_release on pool:active_record.primary
    canonical evidence: 5 instances
    predicted recovery: observed
```

Incomplete claims include explicit reasons. No missing evidence is presented as confirmation.

## MCP

The routing-aware diagnosis MCP server adds:

```text
causcope://diagnosis/causal-verification
```

The resource is read-only, private, zero-TTL, and derived from the same current diagnosis snapshot plus canonical runtime evidence. It does not execute providers, mutate evidence, rerank, or consult the Rails compatibility X-Ray state.

By default the evidence source is sibling `<snapshot-dir>/runtime-evidence.json`. `--runtime-evidence` may provide the explicit canonical source and remains required for routed provider mutation tools.

## Failure semantics

Canonical confirmation fails closed when:

- runtime evidence is unavailable;
- runtime evidence belongs to another incident;
- RFC 0087 returns no verified claim;
- recovery/control/identity evidence is incomplete.

A diagnosis may remain available while causal verification is absent or incomplete. Diagnosis ranking and causal verification remain distinct questions.

## Compatibility

RFC 0088 does not delete the Rails D3.1 compatibility renderer or `CAUSAL_DIAGNOSIS_CONFIRMED`. Explicit concrete proof flags continue to exercise that path.

The compatibility path is now secondary. Product consumers should migrate to `causal_verification` and the MCP causal-verification resource.

## Proof

The deterministic proof covers:

- canonical `causcope why` text output;
- canonical `causcope why --json` output;
- workspace `--require-confirmed` success only for `verified` claims;
- fail-closed incomplete recovery;
- absence of `CAUSAL_DIAGNOSIS_CONFIRMED` from canonical workspace output;
- MCP resource discovery/read at the same evidence revision;
- existing explicit Rails D3.1 compatibility tests unchanged.

No external AI call is required.

## Next step

Move any remaining product/test consumers of Rails-specific `CAUSAL_DIAGNOSIS_CONFIRMED` to canonical `causal_verification`, then reduce the specialized X-Ray state to compatibility-only coverage rather than a product authority.

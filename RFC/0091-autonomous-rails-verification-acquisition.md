# RFC 0091 - Autonomous Rails verification acquisition

Status: Implemented proof

Date: 2026-09-16

## Decision

The canonical Rails D3.1 golden path must not require an operator to choose or manually import the next diagnostic evidence after diagnosis revision 1.

The operator authorizes one bounded read-only acquisition with the existing product surface:

```bash
causcope why "checkout is slow" --acquire --require-confirmed
```

Causcope owns the rest of the decision:

```text
canonical diagnosis revision 1
  -> ranked semantic probe
  -> exact runtime target resolution
  -> safe provider route
  -> provider/instrument execution
  -> canonical evidence revision 2
  -> rerank
  -> causal verification projection
```

The golden demo therefore no longer calls `causcope runtime import-pool`.

## Tests first

Before the provider implementation, the branch added `scripts/test_canonical_rails_autonomous_acquisition.py` and wired it into `Validate investigator CLI`.

That contract fixes the externally relevant shape:

- bootstrap advertises a local Rails runtime-evidence provider;
- the provider is bound to the same exact PostgreSQL target as the ActiveRecord runtime resource;
- its runner requires only local file read capability;
- the workspace binding names the bounded pool, runtime-evidence, and diagnosis artifacts;
- the canonical demo contains no manual `runtime import-pool` step;
- the product confirmation path uses `--acquire` and `--require-confirmed` together.

The implementation does not rewrite that test to fit itself.

A second regression test, `scripts/test_runtime_seed_target_scope.py`, was added after the first live CI run exposed an existing partitioning defect. It fixes the invariant that revision-1 evidence already carries the exact resolved target in semantic scope.

## Provider boundary

`provider.rails.active_record_pool` is a local deterministic provider over an already-captured, identity-bound Rails runtime experiment artifact.

It is not causal authority. It exposes only canonical read-only semantic probes supported by that artifact:

- `probe.database.measure_query_latency`
- `probe.database.inspect_connection_pool`

The first is the current revision-1 discriminator for the Rails D3.1 slice. The second remains available when the causal ranking asks directly for pool state.

The selected semantic probe authorizes inspection of the bounded experiment bundle. Linked mechanism, independent database-control, and recovery observations retain experiment provenance and are not represented as causal conclusions emitted by the provider.

## Exact target partitioning

The first live autonomous CI attempt correctly selected the next semantic probe and committed revision 2, but canonical verification remained unverified.

The cause was evidence partition drift:

```text
revision 1 scope
  service + code_symbol + runtime_resource

routed revision 2 scope
  service + code_symbol + runtime_resource + target_resource
```

The routed execution-set controller intentionally binds exact target identity into evidence scope. Therefore the correct fix is not to weaken routed evidence partitioning. Revision-1 seed evidence now also includes:

```text
scope.attributes.target_resource = <exact resolved target>
```

This preserves the RFC 0069 invariant that exact target identity participates in evidence partitioning and allows revision 1 and routed revision 2 to compose into the same causal question.

## Safety

This proof does not authorize Causcope to create production load or perform a remediation.

The Rails lab command still creates the deterministic test scenario and captures its bounded experiment artifact. Causcope's autonomous step only selects and reads already-captured evidence through a read-only provider route.

Unavailable artifacts, incident mismatch, scope mismatch, target drift, stale revision, unsafe probes, and provider-routing drift continue to fail closed.

## Compatibility

`causcope runtime import-pool` remains available as a lower-level compatibility/debugging surface. It is no longer part of the canonical golden product flow.

## Acceptance

The live Rails/PostgreSQL CI must prove all of the following in one workspace:

1. revision 1 is seeded from one real request and exact ActiveRecord pool interaction;
2. revision-1 evidence scope contains the exact target resource;
3. the ranked next discriminator is selected by Causcope, not the operator;
4. `why --acquire` routes a safe provider for that discriminator;
5. no manual `runtime import-pool` command runs;
6. exactly one canonical evidence revision is committed;
7. final evidence revision is 2;
8. `causcope why --require-confirmed` succeeds;
9. canonical causal verification is `verified` for `hypothesis.database.connection_pool_exhaustion`;
10. the verified intervention observation remains the lab's `resource_capacity_release` for `pool:active_record.primary`.

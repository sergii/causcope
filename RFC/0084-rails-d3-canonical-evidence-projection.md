# RFC 0084: Rails D3.1 canonical evidence projection

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Project the existing bounded Rails D3.1 resource-pool proof into the persisted canonical Investigation instead of keeping the proof only on a mechanism-specific diagnosis path.

## Decision

The existing Rails D3.1 proof remains a valuable concrete instrument, but its observations must feed the same runtime-evidence and diagnosis lifecycle used by every other Causcope investigation.

The canonical continuation is now:

```text
problem
  -> bounded Rails OTLP observation
  -> canonical evidence revision 1
  -> ranked competing hypotheses
  -> exact runtime target
  -> bounded Rails resource-pool proof
  -> canonical evidence projection
  -> one atomic evidence revision 2 commit
  -> canonical rerank
  -> causcope why
```

The resource-pool artifact is not itself a diagnosis authority. It is an evidence source.

## Exact binding rule

`causcope runtime import-pool` does not guess a target from `dependency=postgresql`, a database name, or a pool name.

Before importing anything it requires the resource-pool proof to bind to exactly one existing canonical pool-wait evidence instance by all of:

```text
incident_id
system_id
revision
trace_id
span_id
code_symbol
runtime pool id
```

The exact semantic target is inherited from that already resolved canonical seed evidence. If the proof cannot bind exactly once, import fails closed and no incident state changes.

This deliberately reuses runtime target resolution performed during incident seeding instead of creating a second target resolver.

## Projected observations

The first projection maps only facts that already have canonical semantic observations.

When the bounded proof establishes application pool capacity, it emits:

```text
observation.database.connection_pool_utilization
state = observed
```

When the bounded proof establishes that query latency stayed near baseline, it emits:

```text
observation.database.query_latency
state = absent
```

Here `absent` means the elevated-query-latency observation was absent. It does not mean no SQL query ran or the database was absent.

Both observations reuse the exact canonical incident scope and preserve the exact target resource in source provenance and labels.

## Facts intentionally not promoted yet

The D3.1 proof also contains:

- independent PostgreSQL admission remained reachable;
- checkout wait explains the request-latency delta;
- checkout wait returned to baseline after capacity release;
- request latency returned to baseline after capacity release.

Those are important verification facts, but the current semantic graph does not yet define canonical observations for all of them. RFC 0084 does not invent generic observations merely to make the old X-Ray status fit the new path.

For now they remain in the bounded proof and provenance. A later change may model them explicitly and let canonical verification consume them.

## Atomic state transition

Import reuses the existing incident mutation claim and crash-recoverable incident-state commit machinery.

One successful import performs:

```text
evidence revision N
  -> compose old + projected evidence
  -> build diagnosis revision N+1
  -> atomic incident-state commit
```

Duplicate evidence, identity mismatch, corrupt input, or an unbound proof does not advance the evidence revision.

## Product surface

The explicit command is:

```bash
./bin/causcope runtime import-pool \
  --workspace .causcope \
  --pool-evidence /path/to/resource-pool-runtime-evidence.json
```

After it succeeds, normal:

```bash
./bin/causcope why --workspace .causcope
```

reads the persisted canonical diagnosis. It does not need the three specialized D3.1 artifact flags to see the reranked Investigation.

The older `--static/--runtime/--pool --require-confirmed` projection remains temporarily as a compatibility and verification surface. It is no longer the only way the D3.1 evidence can affect product state.

## Definition of done

The proof is complete when deterministic CI demonstrates:

1. revision 1 is seeded from an exact Rails request and ActiveRecord pool wait;
2. the bounded pool proof binds to that exact canonical evidence;
3. pool utilization and non-elevated query latency are projected as canonical evidence;
4. exactly one new evidence revision is committed;
5. `hypothesis.database.connection_pool_exhaustion` remains the leading canonical explanation after rerank;
6. `causcope why` reads revision 2 from persisted canonical state;
7. duplicate or identity-mismatched imports fail without mutating evidence or diagnosis.

## Next step

The remaining D3.1 gap is verification semantics, not another diagnosis engine.

Model the currently proof-local verification facts as explicit semantic observations only where they generalize beyond this fixture, then let the canonical investigation lifecycle express:

```text
hypothesis
  -> discriminating evidence
  -> intervention/recovery evidence
  -> verified causal claim
```

At that point the specialized `CAUSAL_DIAGNOSIS_CONFIRMED` projection can become a compatibility view over canonical Investigation state rather than a parallel epistemic authority.

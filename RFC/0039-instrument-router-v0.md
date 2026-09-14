# RFC 0039: Instrument router v0

- Status: Accepted
- Date: 2026-09-14

## Summary

Causcope now has two intentionally separate execution capability surfaces:

1. host-local built-in executors (`probe_execution_capabilities`);
2. external diagnostic providers (`diagnostic_provider_capabilities`).

This RFC adds the first deterministic routing layer that composes those surfaces **after** semantic probe ranking:

```text
causal diagnosis
      -> semantic probe ranking
      -> canonical read-only probe
             +
         host executor capabilities
             +
         external provider capabilities
             |
             v
       instrument router
             |
             v
       one safe route or an explicit stop
```

The router does not modify causal ranking, probe ranking, evidence weights, or provider semantics.

## Decision

Add `scripts/instrument_router.py` and the strict `instrument_routing_decision` contract.

For one canonical probe and one normalized diagnosis scope, the router enumerates every configured instrument that advertises the probe and records:

- instrument identity;
- instrument kind (`host_executor` or `diagnostic_provider`);
- execution mode (`session` or `direct`);
- current availability;
- scope compatibility;
- required capabilities;
- observations the instrument can produce;
- eligibility and explicit rejection reasons.

A route is selected only when the candidate is:

```text
canonical probe risk == read_only
AND availability == available
AND scope_match == exact
AND execution mode satisfies the caller requirement
```

If more than one candidate remains, v0 uses stable instrument identity as the deterministic tie-break. This is deliberately not presented as evidence-quality scoring.

## Why routing is downstream from probe ranking

These are different questions:

```text
Which observation would best discriminate current hypotheses?
    -> semantic probe ranking

Which configured instrument can safely obtain that observation here?
    -> instrument routing
```

Availability must not make a weaker diagnostic question appear causally better. A semantically best probe can remain best even when no instrument is currently available to execute it.

## Execution modes

### External providers: `direct`

The current pgbot provider exposes a bounded one-shot `execute()` surface to the autonomous loop. It can therefore satisfy `execution_requirement=direct` when:

- the provider is available;
- its fixed scope exactly matches the diagnosis scope;
- the probe is in its reviewed allowlist.

### Host executors: `session`

The existing built-in `/proc` executors intentionally use the established begin/finish session lifecycle. They capture a baseline and later evaluate a delta.

The router therefore advertises them as `execution_mode=session` and does not collapse them into a fake one-shot measurement.

An autonomous caller requiring `direct` execution will see the host candidate but it will be ineligible with an explicit reason.

## Scope safety

### External providers

Provider capability discovery already declares `scope_mode=fixed_exact`. The router requires normalized exact equality between that provider scope and the selected diagnosis scope.

### Host executors

The existing host capability contract describes the current machine and source path, but it does not declare a semantic binding from that host to arbitrary application/service scopes.

Therefore v0 is intentionally conservative:

```text
host executor + unscoped diagnosis
    -> scope-compatible

host executor + arbitrary scoped diagnosis
    -> scope mismatch
```

The router refuses to relabel host-global `/proc` evidence as if it were automatically evidence for `service=checkout-api`, a tenant, region, dependency, or another narrower scope.

A later RFC may introduce an explicit host/entity binding contract. Until that exists, no heuristic scope inheritance is allowed.

## Routing contract

Example external-provider route:

```json
{
  "schema_version": "0.1",
  "kind": "instrument_routing_decision",
  "probe": {
    "id": "probe.database.inspect_lock_waits",
    "title": "Inspect database lock waits",
    "risk": "read_only"
  },
  "scope": {
    "boundaries": ["boundary.application.external_dependency"],
    "attributes": {
      "dependency": "postgresql",
      "service": "checkout-api"
    }
  },
  "execution_requirement": "direct",
  "selection_policy": "safe_exact_scope_then_stable_identity",
  "candidates": [
    {
      "instrument": {
        "id": "provider.pgbot.postgresql",
        "kind": "diagnostic_provider",
        "execution_mode": "direct"
      },
      "availability": {
        "state": "available",
        "reason": null
      },
      "scope_match": "exact",
      "capabilities": ["capability.database.inspect"],
      "observations": ["observation.database.lock_wait_time"],
      "eligible": true,
      "reasons": []
    }
  ],
  "selection": {
    "instrument": {
      "id": "provider.pgbot.postgresql",
      "kind": "diagnostic_provider",
      "execution_mode": "direct"
    },
    "reason": "instrument is available, exact-scope compatible, execution-mode compatible, and wins the stable instrument-identity tie-break"
  },
  "stop_reason": null
}
```

No route is also a first-class result. The stop reason distinguishes:

- `no_instrument_for_probe`;
- `no_safe_available_instrument`.

## Autonomous execution

`InstrumentRouter.execute()` uses the same deterministic decision with `execution_requirement=direct`.

If the selected instrument is an external provider, the router delegates to that provider and then adds routing provenance to the resulting canonical evidence:

```text
source.attributes.routing.router
source.attributes.routing.instrument_id
source.attributes.routing.instrument_kind
source.attributes.routing.execution_mode
labels.instrument
```

The original provider provenance remains intact.

A session-mode host executor is never silently converted into direct execution. Such a route remains visible to an interactive/agent workflow, which can use the existing begin/finish lifecycle.

## Live proof

The pinned PostgreSQL + pgbot integration now uses the router rather than passing `provider.execute` directly to the autonomous loop:

```text
synthetic request-failure symptom
  -> Causcope ranks inspect_lock_waits
  -> router sees configured instruments
  -> exact-scope available pgbot provider selected
  -> real pgbot wait_lock_contention finding
  -> canonical lock-wait runtime evidence
  -> router provenance preserved
  -> Causcope re-ranks
  -> hypothesis.database.lock_contention ranks first
```

This proves that provider selection is now an explicit architectural step rather than test harness wiring.

## Non-goals

v0 does not add:

- evidence-quality scoring;
- cost or latency optimization;
- provider preference learned from incidents;
- remote host/entity discovery;
- heuristic scope inheritance;
- automatic begin/finish lifecycle for session probes;
- write or remediation tools;
- dynamic plugin installation;
- changes to causal or semantic probe ranking.

## Future work

The next useful slices are:

1. expose the routing decision through MCP/agent plan projection;
2. add explicit host/entity binding so host-local executors can safely participate in scoped investigations;
3. add more external providers (Prometheus/OTel/Kubernetes) to exercise multi-instrument choice;
4. add optional evidence-quality/cost metadata only when we can justify and test the policy.

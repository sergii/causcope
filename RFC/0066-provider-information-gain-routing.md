# RFC 0066: Provider information-gain routing

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Choose among multiple safe provider instances for one already-selected resource target using the causal contrast already computed by probe ranking

## Summary

RFC 0039 separated semantic probe selection from instrument routing. RFC 0040 added concrete resource targets and provider instances. The Prometheus target-aware provider then proved that one target can have more than one eligible diagnostic instrument.

For example:

```text
db.orders.prod
  -> provider.pgbot.orders-prod
  -> provider.prometheus.orders-prod
```

Both providers may serve the same canonical probe:

```text
probe.database.measure_query_latency
```

A stable provider-ID tie-break is deterministic, but it ignores a useful fact already present in Causcope: different providers can resolve different diagnostic outcomes for the same observation.

RFC 0066 adds a provider-selection layer after safety routing:

```text
causal ranking
  -> semantic probe ranking
  -> exact resource target
  -> base instrument router safety filtering
  -> provider information-gain proxy
  -> selected provider instance
  -> evidence
  -> causal reranking
```

## Boundary

This RFC does not change hypothesis ranking or probe ranking.

It also does not make an unsafe provider eligible.

The base `InstrumentRouter` remains authoritative for:

- read-only policy;
- exact scope compatibility;
- exact target binding;
- provider availability;
- runner availability;
- provider endpoint reachability;
- runner transport capabilities;
- execution-mode compatibility.

The information-aware layer considers only provider instances that the base router already marked `eligible: true`.

## Why this is an information-gain proxy, not Shannon information gain

Causcope does not currently have calibrated probabilities for future probe outcomes. Therefore RFC 0066 must not claim a probabilistic entropy reduction.

The selector uses a deterministic ordinal proxy derived from the existing `probe_ranking.outcome_analysis` contract.

For every discriminating observation, probe ranking already records:

```text
observed_distinguishes_pairs
absent_distinguishes_pairs
```

A provider can cover some or all of those outcomes.

The proxy ranks providers by:

1. more top-candidate alternatives distinguishable in both observed and absent outcomes;
2. more top-candidate alternatives distinguishable in at least one supported outcome;
3. more two-sided candidate pairs;
4. more discriminated candidate pairs;
5. more discriminating observations covered;
6. two-sided outcome support over positive-findings-only support;
7. stable provider-instance identity.

This is deterministic and explainable. It is not learned and not probabilistic.

## Provider evidence semantics matter

The current pgbot provider intentionally has:

```text
positive_findings_only = true
missing_positive_finding = insufficient_evidence
```

Therefore a missing pgbot finding cannot be converted into `observation=absent`.

The target-aware Prometheus provider can evaluate a threshold in both directions and emit either:

```text
observed
absent
```

For the same canonical query-latency probe, if both `observed` and `absent` outcomes discriminate the current hypotheses, Prometheus can be more informative than pgbot even though both are safe and both target the same PostgreSQL resource.

Example:

```text
current hypotheses
  A: database latency
  B: connection-pool exhaustion

query-latency observation
  observed -> distinguishes A vs B
  absent   -> distinguishes A vs B

pgbot
  observed -> usable
  absent   -> insufficient evidence

Prometheus
  observed -> usable
  absent   -> usable
```

The information-aware selector therefore prefers the Prometheus provider for this specific investigation step.

This does not mean Prometheus is globally better. A different probe, such as PostgreSQL lock-wait inspection, may only be available through pgbot.

## Contract

RFC 0066 adds `information_gain_routing_decision`.

Each provider candidate retains:

```text
instrument identity
base eligibility
base rejection reasons
information_gain_proxy
rank
```

The proxy contains:

```text
outcome_support
discriminating_observations
observed_distinguishes_pairs
absent_distinguishes_pairs
discriminated_candidate_pairs
two_sided_candidate_pairs
top_candidate_discriminated_alternatives
top_candidate_two_sided_alternatives
```

The output explicitly states:

```text
probabilistic_information_gain: false
```

## Execution

`InformationGainInstrumentRouter.execute()` repeats the same decision with direct execution required, invokes the selected bound provider instance, and adds routing provenance:

```text
routing.router = information_gain_router.v0
routing.base_router = instrument_router.v0
routing.instrument_id
routing.target_resource
routing.endpoint_resource
routing.selection_policy
```

Provider evidence remains evidence, not causal authority.

## Failure behavior

The layer fails closed when:

- the probe candidate does not contain the causal contrast required for provider ranking;
- the target resource cannot be safely routed by the base router;
- no eligible bound provider exists;
- the selected provider has no execution binding.

It never treats provider unavailability or missing evidence as negative evidence.

## Proof

The proof uses the existing shop topology and the same `db.orders.prod` target with two provider instances:

```text
provider.pgbot.orders-prod
provider.prometheus.orders-prod
```

Both support `probe.database.measure_query_latency`.

The ordinary base router still selects pgbot by stable identity, proving backward compatibility.

The information-aware router sees that pgbot is positive-findings-only while Prometheus supports both observed and absent query-latency outcomes. For a causal contrast where both outcomes distinguish the current hypotheses, it selects Prometheus.

Execution then returns the target-bound Prometheus evidence and records the selected provider, observed resource, and Prometheus endpoint in provenance.

No OpenAI API is used.

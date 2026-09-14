# RFC 0037: pgbot autonomous probe provider

- Status: Accepted
- Date: 2026-09-14

## Summary

RFC 0034 established the semantic adapter from pgbot findings to Causcope `runtime_evidence`. RFC 0036 proved the adapter against a pinned real pgbot v0.8.1 run on PostgreSQL 17. RFC 0035 established the bounded autonomous read-only investigation loop.

This RFC connects those pieces:

```text
runtime symptom
  -> Causcope causal ranking
  -> Causcope probe ranking
  -> selected canonical PostgreSQL probe
  -> pgbot deterministic read-only instrument
  -> canonical runtime_evidence
  -> Causcope re-ranking
  -> next probe or bounded stop
```

pgbot remains a specialized PostgreSQL instrument. Causcope owns incident scope, competing hypotheses, probe selection, evidence composition, causal re-ranking, and stop policy.

## Decision

Add `scripts/pgbot_autonomous_provider.py` as a provider for a deliberately small static allowlist:

```text
probe.database.inspect_lock_waits
probe.database.measure_query_latency
```

A probe is exposed only when all of these are true:

```text
probe id is explicitly allowlisted
AND canonical concept kind == probe
AND canonical risk == read_only
AND probe.produces intersects an explicit pgbot adapter mapping
```

Adding a new pgbot mapping therefore does not silently grant a new autonomous capability.

The provider accepts a `context_supplier`. That transport can be a controlled CLI invocation, MCP operation, CI-produced pgbot report, or another deterministic integration. The provider owns semantic eligibility and normalization rather than transport discovery.

## Exact scope binding

The current PostgreSQL adapter is scoped to:

```yaml
boundaries:
  - boundary.application.external_dependency
attributes:
  service: checkout-api
  dependency: postgresql
```

The selected diagnosis scope must equal that normalized scope exactly. A mismatch becomes `ProbeInsufficientEvidence`.

The provider does not widen, narrow, rename, or infer equivalence between scopes. PostgreSQL evidence from one service or dependency cannot silently influence another diagnosis partition.

## Positive-finding semantics

The current pgbot adapter represents positive findings. Therefore:

```text
no pgbot finding != absent evidence
suppressed pgbot finding != absent evidence
```

If a selected probe has no active mapped positive finding, the provider returns `ProbeInsufficientEvidence`. The autonomous loop may then try another ranked eligible probe.

The provider MUST NOT turn missing positive evidence into a falsifier. A future provider may emit trustworthy `absent` evidence only when the source contract proves that the relevant subsystem was successfully inspected and the predicted condition was absent.

## Upstream contract

The provider reuses the adapter's explicit `accepted_schema_versions` contract. The current live integration pins pgbot v0.8.1 and accepts JSON schema `1.2.0`. Unsupported upstream schema versions fail closed before normalization.

The autonomous layer does not invent compatibility rules around the external contract.

## Provenance

Passive imported pgbot findings use source type `other`. When Causcope explicitly selects pgbot to satisfy a canonical probe, the resulting evidence uses probe provenance:

```text
source.type = probe
source.name = <canonical probe id>
labels.probe = <canonical probe id>
labels.provider = provider.pgbot.postgresql
```

Original pgbot provenance remains in source attributes, including finding identity, source name, schema contract, source severity/confidence metadata, provider identity, and the selected Causcope target.

The audit trail can therefore answer both:

```text
What diagnostic action did Causcope choose?
Which external instrument produced the result?
```

## Autonomous convergence

The investigation begins with only a scoped symptom:

```text
observation.http.request_failure = observed
```

Causcope has competing causes for that outcome. The generic probe ranking can choose:

```text
probe.database.inspect_lock_waits
```

The pgbot provider supplies the deterministic source finding:

```text
wait_lock_contention
  -> observation.database.lock_wait_time = observed
```

The new observation enters standard `runtime_evidence`, evidence revision advances, diagnosis is rebuilt, and the original request-failure target re-ranks to:

```text
hypothesis.database.lock_contention
```

The provider never injects that hypothesis or a root-cause label.

## Real PostgreSQL proof

RFC 0036 now creates a real PostgreSQL row-lock incident with one blocking transaction and multiple application waiters while preserving enough diagnostic headroom for pgbot collectors.

The pinned pgbot run must emit:

```text
wait_lock_contention
```

This RFC feeds that real `pgbot-report.json` into the autonomous provider and runs the complete bounded loop:

```text
synthetic incident symptom only
  -> competing Causcope hypotheses
  -> Causcope selects inspect_lock_waits
  -> real pgbot wait_lock_contention finding
  -> observation.database.lock_wait_time
  -> Causcope re-ranks original symptom
  -> hypothesis.database.lock_contention ranks first
```

Only the initial symptom is synthetic in this CI assertion. The discriminating PostgreSQL evidence comes from the real database and real pgbot execution; the scenario oracle is not consulted.

## Safety properties

The provider:

- exposes only statically reviewed canonical read-only probes;
- never treats an adapter mapping as execution permission;
- never executes remediation text;
- never grants pgbot severity causal authority;
- refuses scope relabeling;
- fails closed on unsupported pgbot contracts;
- preserves external provenance;
- converts missing or suppressed positive findings to insufficient evidence rather than false absence;
- returns only observations declared by the selected probe's canonical `produces` set.

The generic autonomous loop independently revalidates probe risk, incident identity, produced observations, provenance, and exact scope before new evidence may affect ranking.

## Validation

`scripts/test_pgbot_autonomous_provider.py` covers provider policy and deterministic convergence using the stable fixture.

`scripts/verify_pgbot_autonomous_live.py` consumes the report generated by the existing PostgreSQL 17 live workflow and proves the full external-provider feedback loop with real pgbot evidence.

The live workflow saves the autonomous result beside the raw pgbot and trace artifacts for audit.

## Consequences

Causcope now has two autonomous provider shapes behind the same reasoning loop:

```text
Shop structured-log provider
  -> first-party read-only instrument

pgbot PostgreSQL provider
  -> external specialized deterministic instrument
```

Provider specialization no longer implies a separate reasoning engine.

## Next work

1. Add provider capability metadata so Causcope can know before execution whether a provider can answer a selected probe in the current environment.
2. Model external evidence-quality states such as unavailable, cold-window, reset, and explicitly-negative inspection without collapsing them into observed/absent.
3. Expose autonomous provider eligibility through MCP/HTTP while keeping write-capable operations outside autonomous policy.
4. Add a second external provider from another domain, such as Kubernetes or network telemetry, to prove cross-provider selection.
5. After a fix, run verification against the original incident scope without letting the autonomous diagnostic loop perform remediation itself.

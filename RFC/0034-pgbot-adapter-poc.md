# RFC 0034: pgbot PostgreSQL diagnostic adapter proof of concept

- Status: Implemented proof of concept
- Date: 2026-09-14

## Summary

This slice implements the first external deterministic diagnostic adapter proposed in RFC 0033.

The proof of concept translates selected pgbot PostgreSQL findings into canonical Causcope runtime observations and composes them with OpenTelemetry evidence in the same incident and semantic scope.

```text
pgbot --json findings --------------------\
                                           -> runtime_evidence composition
OpenTelemetry PostgreSQL client span -----/             |
                                                         v
                                                live diagnosis
```

The adapter does not make pgbot the diagnosis engine. pgbot remains a PostgreSQL-specific evidence instrument. Causcope owns semantic scope, evidence composition, causal reasoning, competing hypotheses, next probes, and verification.

## First mapping

The first slice maps five real pgbot finding IDs:

| pgbot finding | Causcope observation |
| --- | --- |
| `query_slowdown` | `observation.database.query_latency` |
| `connection_saturation` | `observation.database.connection_utilization` |
| `seq_scan_heavy` | `observation.database.sequential_scan_pressure` |
| `wait_lock_contention` | `observation.database.lock_wait_time` |
| `txid_wraparound` | `observation.database.transaction_id_age` |

The source finding IDs are external adapter vocabulary. They do not become canonical Causcope semantic IDs.

The pgbot finding catalogue is documented at <https://github.com/pgrundev/pgbot/tree/main/docs/findings>.

## Adapter boundary

The executable path is:

```text
pgbot JSON Context
  -> scripts/pgbot_adapter.py
  -> explicit mapping YAML
  -> Causcope runtime_evidence
```

The mapping is stored in:

```text
examples/adapters/pgbot/postgresql.yaml
```

The adapter preserves:

- pgbot schema version;
- target fingerprint when available;
- finding ID;
- severity;
- source numeric confidence;
- source object identity when present;
- finding detail and caveats;
- the configured Causcope semantic scope.

It does not import pgbot remediation text as causal evidence.

## Scope

For the proof of concept, the adapter is explicitly configured to describe the PostgreSQL dependency used by `checkout-api`:

```yaml
boundaries:
  - boundary.application.external_dependency
attributes:
  service: checkout-api
  dependency: postgresql
```

The OpenTelemetry PostgreSQL client-span fixture emits the same scope.

This is deliberate. Evidence composition should happen because two sources describe the same system boundary, not because they happen to mention PostgreSQL.

## OpenTelemetry composition

The OpenTelemetry fixture records a slow PostgreSQL client span and maps it independently to:

```text
observation.database.query_latency
```

The pgbot `query_slowdown` finding maps to the same canonical observation.

After composition, Causcope therefore has two provenance-distinct evidence instances for one observation:

```text
pgbot deterministic finding -> observation.database.query_latency
OTel measured span           -> observation.database.query_latency
```

The instances are not collapsed. The runtime resolver sees one canonical observed state while provenance remains auditable.

The same composed partition also contains the other PostgreSQL observations from pgbot.

## Suppression and uncertainty

A source-suppressed pgbot finding is not translated into `absent` evidence.

In this proof of concept it is omitted from active runtime evidence and the generated document states that a suppressed mapped finding was skipped.

This is intentionally conservative:

```text
suppressed != absent
unknown != absent
unavailable != absent
```

The current `runtime_evidence` schema only represents `observed` and `absent` active states. A richer evidence-quality model is required before source states such as unavailable, cold-window, reset, or insufficient-evidence can be represented directly without semantic loss.

Until then, the adapter must prefer omission over invented certainty.

## Unmapped findings

An unknown pgbot finding ID is ignored by the semantic adapter.

The adapter does not infer a canonical observation from title text, detail text, severity, or an LLM.

Adding a new finding requires an explicit mapping to an existing canonical observation or an explicit addition to the Causcope ontology.

## Fixtures and tests

The proof of concept includes:

```text
examples/telemetry/pgbot/postgresql-findings.json
examples/telemetry/opentelemetry/postgresql-query-trace.json
scripts/test_pgbot_adapter.py
scripts/test_pgbot_otel_composition.py
scripts/demo_pgbot_postgresql.py
```

The fixture carries five mapped pgbot findings plus one source-suppressed unmapped finding.

The tests verify:

1. five real pgbot finding IDs map to the intended canonical observations;
2. deterministic repeated translation;
3. source suppression never becomes `absent`;
4. unknown source finding IDs do not invent ontology;
5. pgbot and OpenTelemetry evidence compose into one semantic partition;
6. the same query-latency observation can retain independent pgbot and trace provenance.

## Non-goals

This proof of concept does not yet:

- execute the pgbot binary;
- connect to PostgreSQL;
- call pgbot MCP tools;
- validate the complete upstream pgbot JSON Schema;
- model every pgbot finding;
- import remediation as an action;
- turn source severity into Causcope causal weight;
- model unavailable/reset/cold-window states directly;
- dynamically discover adapters;
- load third-party executable code.

## Next slice

The next implementation should replace the fixture boundary with one read-only pgbot invocation or MCP call, pin the accepted pgbot JSON schema version, and introduce an explicit evidence-quality state so unavailable, reset, cold-window, suppressed, and insufficient-evidence source states can survive normalization without becoming either `observed` or `absent`.

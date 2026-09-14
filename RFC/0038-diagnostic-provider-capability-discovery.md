# RFC 0038: Diagnostic provider capability discovery

- Status: Accepted
- Date: 2026-09-14

## Summary

Causcope can now discover the capabilities of configured external diagnostic providers without executing a diagnostic probe.

The first provider is the pgbot PostgreSQL provider introduced by RFC 0037.

The projection answers five questions explicitly:

```text
What instrument is configured?
What canonical probes can it serve?
What observations can it actually produce?
For which semantic scope?
Can the configured transport be used now?
```

It also exposes the provider's evidence semantics so an investigator can distinguish a positive-only source from a source that can justify absence.

## Why this is separate from probe ranking

Semantic probe ranking and execution availability remain separate concerns.

```text
best diagnostic question
        !=
available instrument on this process
```

The causal/probe ranking engine continues to rank canonical probes from knowledge and current evidence only. Provider availability does not become a hidden causal weight.

Capability discovery is a later execution-planning projection:

```text
causal candidates
      -> semantic probe ranking
      -> provider capability discovery
      -> executable instrument choice
      -> probe execution
      -> evidence
      -> re-ranking
```

## Contract

The machine-readable projection is:

```text
schema/diagnostic-provider-capabilities.schema.json
```

with kind:

```text
diagnostic_provider_capabilities
```

Each provider publishes:

- stable provider ID;
- instrument name;
- transport class;
- scope binding mode and normalized semantic scope;
- current availability state;
- accepted upstream contract versions;
- evidence semantics;
- canonical read-only probes it can serve;
- required canonical capabilities for those probes;
- the mapped observations this provider can actually emit.

The initial pgbot shape is conceptually:

```yaml
id: provider.pgbot.postgresql
instrument: pgbot
transport: context_supplier
scope_mode: fixed_exact
scope:
  boundaries:
    - boundary.application.external_dependency
  attributes:
    service: checkout-api
    dependency: postgresql
availability:
  state: available
  reason: null
contract:
  name: pgbot_json
  accepted_schema_versions:
    - "1.2.0"
evidence_semantics:
  positive_findings_only: true
  missing_positive_finding: insufficient_evidence
  suppressed_positive_finding: insufficient_evidence
  provenance_preserved: true
  causal_authority: false
probes:
  - probe:
      id: probe.database.inspect_lock_waits
      risk: read_only
    requires:
      - capability.database.inspect_locks
    mapped_observations:
      - observation.database.lock_wait_time
```

## Mapped observations, not declared probe outputs

The provider projection intentionally reports `mapped_observations` rather than blindly copying every output declared by the canonical probe.

For example, the canonical lock-wait probe can produce both lock-wait time and a lock-wait event. The current pgbot adapter maps only:

```text
observation.database.lock_wait_time
```

The capability projection therefore advertises only that observation.

This prevents a future router from assuming an instrument can provide evidence merely because the semantic probe knows that such evidence could exist.

## Availability states

Availability is tri-state:

```text
available
unavailable
unknown
```

`available` means the provider exposes a non-invasive discovery check and the configured transport currently passes it.

`unavailable` means discovery completed and found a concrete blocker such as a missing report, unreadable source, invalid report, or incompatible upstream contract.

`unknown` means the provider transport does not expose a safe non-invasive availability check. Discovery must not invoke an opaque supplier merely to find out whether it works.

This avoids turning capability discovery into accidental diagnostic execution.

## pgbot report transport

RFC 0037 intentionally separates provider semantics from transport. The first capability-aware transport is the existing report-file supplier.

`file_context_supplier()` now returns an availability-aware object. Discovery checks only:

1. the report path exists;
2. it is a readable file;
3. the JSON context can be parsed;
4. its pgbot schema version is accepted by the configured adapter.

It does not run pgbot, query PostgreSQL, capture a new sample, or infer any diagnosis.

An opaque callable supplier remains supported for execution, but its discovery state is `unknown` unless it explicitly exposes a safe availability check.

## Incident independence

Provider discovery does not require an incident ID.

This is deliberate: the configured diagnostic substrate exists before an incident starts.

Execution still requires an incident ID because produced runtime evidence must belong to a concrete incident. A discovery-only pgbot provider therefore rejects `execute()` until it has been bound to an incident.

## Relationship to existing host executor capabilities

RFC 0019 already exposes host-local built-in executor capabilities through:

```text
probe_execution_capabilities
```

RFC 0038 does not replace or duplicate that registry.

There are now two explicit capability surfaces:

```text
host-local built-in executors
  -> probe_execution_capabilities

external specialized providers
  -> diagnostic_provider_capabilities
```

A later routing projection may compose these two surfaces when deciding which concrete instrument should satisfy a ranked semantic probe.

The routing layer must consume these existing projections rather than reimplementing availability logic.

## Evidence semantics are part of capability discovery

Provider availability alone is not enough.

A future planner also needs to know what a negative result means. The initial pgbot provider is positive-finding oriented:

```text
mapped positive finding -> observed evidence
missing finding         -> insufficient evidence
suppressed finding      -> insufficient evidence
```

Therefore:

```text
no pgbot finding != absent observation
```

The projection makes that contract machine-readable before execution.

The provider also declares:

```text
provenance_preserved: true
causal_authority: false
```

which records that the provider supplies evidence but does not own the root-cause conclusion.

## CLI

The generic projection builder is:

```bash
python scripts/diagnostic_provider_capabilities.py \
  --pgbot-adapter examples/adapters/pgbot/postgresql.yaml \
  --pgbot-report examples/telemetry/pgbot/postgresql-findings.json \
  --pretty
```

The builder accepts a list of provider objects internally, rejects duplicate provider IDs, sorts deterministically, and validates the final document against the JSON Schema.

The CLI wires only pgbot today because it is the first external provider. Adding another provider should add another capability projection rather than adding special-case inference to the generic builder.

## Safety boundary

Capability discovery never grants execution permission.

For pgbot, the autonomous allowlist remains the authority for which canonical probes the provider can serve. The projection is derived from that reviewed allowlist plus explicit adapter mappings.

Discovery does not:

- add a probe to the allowlist;
- run pgbot;
- query PostgreSQL;
- execute remediation;
- convert missing evidence to absence;
- change causal or probe ranking;
- dynamically load third-party code.

## Testing

CI verifies:

1. the pgbot provider advertises only the two reviewed read-only probes;
2. each advertised probe exposes only explicitly mapped observations;
3. fixed exact semantic scope is preserved;
4. a valid compatible report is `available`;
5. a missing report is `unavailable`;
6. an incompatible pgbot contract is `unavailable`;
7. an opaque supplier is `unknown` and is not invoked by discovery;
8. provider discovery works without an incident ID while execution still requires one;
9. duplicate provider IDs fail closed;
10. the complete projection validates against the strict schema.

The live PostgreSQL/pgbot workflow also emits this capability projection from the real `pgbot-report.json`, proving that the same report used by autonomous diagnosis is discoverable through the provider capability boundary.

## Next slice

The next useful slice is capability-aware instrument routing:

```text
ranked canonical probe
       +
probe_execution_capabilities
       +
diagnostic_provider_capabilities
       |
       v
candidate instruments
       |
       v
safe deterministic instrument selection
```

The first version should remain deterministic and auditable. It should prefer an available provider that can produce the ranked probe's discriminating observation in the exact diagnosis scope, while preserving probe ranking as a separate semantic decision.

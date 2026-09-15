# RFC 0076: Investigation case identity and incident compatibility

- Status: Proposed
- Date: 2026-09-15

## Summary

Causcope needs one canonical runtime object for the thing being investigated, independent of whether a formal operational incident exists in PagerDuty, ServiceNow, Jira Service Management, Datadog Incident Management, or any other incident system.

The repository currently uses `incident_context` and `incident_id` as the pre-evidence scoping contract and join key. That terminology predates the broader product model and now creates an ambiguity:

```text
local debugging session
Sentry-only issue
proactive anomaly
learning lab
pre-incident investigation
formal P1 incident
```

are all valid Causcope investigations, but only the last item necessarily represents a formal operational incident.

This RFC introduces **Investigation** as the canonical Causcope case identity while preserving the existing `incident_context` contract as a compatibility surface during migration.

## Decision

The canonical product model becomes:

```text
Investigation
  Causcope-owned runtime case
  identity: investigation_id

Incident
  optional external operational lifecycle object
  authority: PagerDuty / ServiceNow / JSM / Datadog / customer system

InvestigationSession
  journal / interaction session that advances an Investigation

InvestigationContext
  scoping state used before and during evidence gathering

RuntimeEvidence
  measured observations used by deterministic diagnosis
```

An Investigation MAY have zero, one, or multiple related external incidents.

An external incident MUST NOT become the identity of the Causcope investigation.

## Compatibility with the existing `incident_context`

The accepted v0.1 contract remains valid during the compatibility period:

```text
schema/incident-context.schema.json
kind: incident_context
incident_id: ...
.causcope/incident-context.yaml
```

For compatibility, the existing `incident_id` MUST be interpreted as a **legacy Causcope case correlation key**, not as proof that a formal external incident exists.

Existing data, labs, scripts, and RFCs therefore remain readable without immediate migration.

New product architecture and integrations MUST avoid assuming:

```text
incident_id == PagerDuty incident
incident_id == formal operational incident
incident_context exists => external incident exists
```

## Target model

A future versioned runtime case contract should resemble:

```yaml
schema_version: "0.1"
kind: investigation
investigation_id: investigation.checkout.20260915.001
summary: Checkout intermittently fails
status: active

trigger:
  kind: human_report
  source: cli

external_incidents:
  - provider: pagerduty
    external_id: P123ABC
    relationship: operational_incident

context:
  ref: .causcope/incident-context.yaml

sessions:
  - investigation-session.001
```

The exact schema is intentionally deferred until the compatibility mapping is proven against the current CLI, runtime evidence, and existing examples.

## Authority model

Authority is per concern:

```text
formal incident lifecycle        external incident system
raw telemetry                    originating evidence provider
normalized investigation state   Causcope
hypotheses and causal ranking     Causcope
probe history                     Causcope
external incident identifiers     originating incident system
```

This keeps Causcope from pretending to own paging, acknowledgement, escalation, or compliance workflow when the customer already has a system for those concerns.

## Context is not evidence

This RFC preserves the existing invariant from the incident-scoping work:

```text
context != evidence
correlation != causality
change near onset != root cause
```

Renaming or wrapping `incident_context` must not weaken the boundary between scoping context and runtime evidence.

An Investigation may contain contextual statements such as:

```text
errors began after deploy abc123
only EU users have reported the problem
```

without allowing those statements to affect deterministic causal ranking until they are represented as validated runtime evidence.

## Migration strategy

Migration should be incremental and non-breaking.

### Phase 1 - semantic clarification

Immediately:

- use `Investigation` in new product and integration documentation;
- treat current `incident_id` as a legacy case correlation key;
- keep existing schemas and files unchanged;
- preserve all current stored sessions and examples.

### Phase 2 - parent Investigation contract

Introduce a versioned `Investigation` case schema with:

```text
investigation_id
summary
lifecycle state
trigger/provenance
external incident references
context reference
session references
```

The parent object may initially wrap the existing `incident_context` rather than replacing it.

### Phase 3 - join-key migration

Gradually allow runtime contracts to join through `investigation_id`.

During a compatibility window, adapters may accept both:

```text
investigation_id
legacy incident_id
```

but all newly created canonical cases should prefer `investigation_id` once the new schema is accepted.

### Phase 4 - context naming cleanup

Only after compatibility is proven, decide whether:

```text
incident_context
```

remains as a legacy serialized form or is superseded by:

```text
investigation_context
```

Do not rename files or fields silently.

## Integration behavior

Examples:

### PagerDuty-triggered investigation

```text
PagerDuty incident P123ABC
        -> Causcope Investigation CS-4821
```

The Investigation references the PagerDuty incident, but its identity remains Causcope-owned.

### Sentry-only investigation

```text
Sentry issue
    -> Causcope Investigation
    -> no formal incident
```

### Local debugging

```text
causcope investigate "checkout is slow"
    -> local Causcope Investigation
    -> no cloud account
    -> no external incident
```

### Proactive investigation

```text
Causcope detector / scheduled analysis
    -> Investigation
    -> policy decides whether an external incident should be created
```

## Incident creation policy

Causcope MUST NOT equate every anomaly or signal with an incident.

A future policy layer may create or request creation of an external incident when conditions such as the following are satisfied:

```text
confirmed customer impact
severity threshold
blast-radius threshold
persistent failure
explicit human request
customer-defined automation policy
```

Incident creation is an operational action and should remain separate from diagnostic truth.

## CLI implications

The current local workspace remains valid:

```text
.causcope/
  incident-context.yaml
  investigation-session.yaml
  scoping-projection.json
```

A future compatible workspace may become:

```text
.causcope/
  investigation.yaml
  investigation-context.yaml
  investigation-session.yaml
  scoping-projection.json
```

but this RFC does not authorize that breaking migration yet.

## Invariants

- Every Causcope diagnosis belongs to an Investigation.
- An Investigation does not require a formal Incident.
- An external Incident does not replace Causcope Investigation identity.
- External systems remain authoritative for their own incident lifecycle and raw observations.
- Causcope remains authoritative for normalized investigation state and reasoning provenance.
- Existing `incident_context` data remains readable during migration.
- Context must not silently become runtime evidence.
- Migration must be versioned and reversible.

## Consequences

This model allows the same core to support:

```text
learning
local debugging
coding agents
SMB deployments
SaaS integrations
PagerDuty-driven operations
enterprise Relay deployments
proactive investigations
future remediation workflows
```

without forcing all of them into an incident-management abstraction.

## Follow-up work

1. define the smallest `investigation-case.schema.json` proposal;
2. map existing `incident_id` references across schemas and scripts;
3. add compatibility fixtures proving old workspaces still load;
4. decide how runtime evidence migrates from `incident_id` to `investigation_id`;
5. update CLI display terminology before changing serialized storage;
6. keep external incident references provider-qualified and provenance-preserving.

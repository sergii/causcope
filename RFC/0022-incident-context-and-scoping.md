# RFC 0022: Incident context and scoping

- Status: Accepted
- Date: 2026-09-13

## Summary

Atlerror's executable diagnostic loop already models runtime evidence, causal ranking, discriminating probes, execution availability, and agent planning. It starts too late for many real incidents, however. Before reliable observations exist, an engineer or agent first has to answer a different question:

```text
What exactly is broken, for whom, where, since when, under which conditions, and with what impact?
```

This RFC adds a machine-readable `incident_context` record and an explicit scoping phase before runtime evidence.

The full workflow becomes:

```text
something is wrong
  -> incident context / scoping
  -> blast radius and impact
  -> failing-vs-working comparison
  -> runtime evidence
  -> candidate hypotheses
  -> predictions
  -> probes / experiments
  -> findings
  -> hypothesis updates
  -> cause / contributing factors
  -> mitigation / fix
  -> verification / prevention
```

The new layer deliberately does not turn contextual correlation into causal evidence.

## Why this layer is separate

Runtime evidence answers questions such as:

```text
Was observation X present or absent?
When was it observed?
From which source?
With what confidence?
In which semantic scope?
```

Incident context answers earlier triage questions such as:

```text
Who appears affected?
Where does the problem appear?
When did it start?
Which flow is failing?
Which clients or data shapes correlate with failure?
What changed near onset?
Can the issue be reproduced?
What is the current blast radius and impact?
```

Those are not interchangeable contracts. A report that failures started after a deploy does not prove that the deploy caused the failure. A report that only EU users complained does not prove that the failure is region-specific.

Keeping context separate prevents early guesses from silently affecting deterministic causal ranking.

## Contract

The canonical schema is:

```text
schema/incident-context.schema.json
```

The top-level record is:

```yaml
schema_version: "0.1"
kind: incident_context
incident_id: incident.example
summary: A concise description of the reported problem.
scope: {}
time:
  pattern: unknown
impact:
  severity: unknown
reproduction:
  status: unknown
unknowns:
  - who
  - where
  - when
  - what
  - client
  - change
  - data
  - reproduction
  - impact
```

An incident context is a runtime record, not a canonical semantic concept. It therefore does not add `incident_context` to the catalog of concept kinds such as `symptom`, `observation`, `hypothesis`, or `probe`.

## Scoping dimensions

### Who

`scope.subjects` captures affected populations or cohorts before precise impact counts are known.

Examples:

```text
paid customers
new tenants
warehouse operators
background jobs
```

Precise counts belong in `impact.populations`.

### Where

The scope may include:

- environments;
- regions;
- availability zones;
- services;
- semantic entities;
- semantic boundaries.

Existing semantic entity and boundary IDs should be reused when known. Free-form service and deployment labels remain allowed because triage often begins before topology has been normalized.

### When

The time block can record:

- onset;
- last known good time;
- first reported time;
- continuous, intermittent, periodic, single-event, or unknown behavior;
- known duration.

Unknown timestamps are omitted rather than invented.

### What

`features` and `operations` describe the affected product or technical flow, for example:

```text
checkout
password reset
POST /checkout
invoice import
```

These fields are contextual selectors, not canonical causal nodes.

### Client

Client context can distinguish browser, mobile, desktop, API, worker, device, or other consumers with optional name, version, OS, application version, and attributes.

### Change

Nearby changes are recorded explicitly as candidates:

```text
deploy
feature flag
configuration
migration
dependency
infrastructure
data
```

Each change includes a qualitative temporal relationship to incident onset:

```text
before_onset
near_onset
after_onset
unknown
```

The contract intentionally calls these `changes`, not causes.

### Data

Data scope can capture tenant, record type, role, permission, new/existing data age, and exact contextual attributes.

### Reproduction

Reproduction state is one of:

```text
always
sometimes
rare
not_reproduced
unknown
```

Conditions and steps can be recorded without claiming that any condition is causal.

### Impact and blast radius

Impact carries qualitative severity plus optional affected populations.

When known, record both affected and total counts, and optionally the percentage:

```yaml
populations:
  - unit: requests
    affected: 184
    total: 2510
    percentage: 7.33
```

The schema does not calculate or verify percentage arithmetic. Producers should keep those values internally consistent.

## Failing-vs-working comparisons

The context may contain explicit comparisons between a failing case and a working case.

Example:

```yaml
comparisons:
  - failing:
      attributes:
        region: eu-central
        app_version: 7.42.0
    working:
      attributes:
        region: us-east
        app_version: 7.42.0
    differences:
      - region
```

A comparison records observed contrast. It does not assert that a listed difference is the cause.

This distinction is important because controlled contrast is useful for hypothesis generation while still remaining weaker than diagnostic evidence that directly supports or contradicts a hypothesis.

## Explicit unknowns

The `unknowns` array makes missing triage dimensions first-class:

```yaml
unknowns:
  - who
  - change
```

Allowed dimensions are:

```text
who
where
when
what
client
change
data
reproduction
impact
```

A dimension may be partially populated and still appear under `unknowns` when the important boundary is unresolved. Consumers should interpret it as "materially incomplete", not necessarily "completely absent".

## Relationship to runtime evidence

`incident_id` is the join key between incident context and runtime evidence bundles.

Context can guide collection and filtering, but MUST NOT enter causal ranking automatically.

A context statement becomes runtime evidence only when a producer can express it through the runtime evidence contract as an observation with appropriate:

- state;
- observation time;
- source and provenance;
- confidence;
- semantic or attribute scope.

For example:

```text
Context:
  failures appear limited to eu-central

Later measured evidence:
  observation.http.error_rate = observed in eu-central
  observation.http.error_rate = absent in us-east
```

The first statement narrows investigation. The second pair can affect diagnosis.

## Relationship to causal ranking

Incident context does not add a new ranking score and does not directly reorder hypotheses.

The existing ordering remains:

```text
runtime evidence
  -> causal ranking
  -> probe ranking
  -> probe execution annotation
  -> agent plan
```

Future projections may use incident context to recommend which evidence to collect, but any such behavior must preserve the context/evidence distinction.

## Relationship to verification

Verification should reuse the original incident scope rather than checking a convenient global metric only.

A fix should be tested against questions such as:

```text
Did the affected population recover?
Did the failing comparison become equivalent to the working comparison?
Did the symptom disappear in the original region, client, and data scope?
Did another scope regress?
```

This makes the incident context useful at both the beginning and the end of the workflow.

## Example

A complete example is provided at:

```text
examples/incidents/checkout-latency.yaml
```

It captures a production checkout incident with region, client version, blast radius, a nearby deploy, a failing-vs-working comparison, reproduction conditions, and an explicit unresolved `who` dimension.

## Invariants

- Unknown incident dimensions are explicit rather than guessed.
- A nearby change is contextual correlation, not causal proof.
- A failing-vs-working difference is a discriminator, not causal proof.
- Incident context does not silently mutate causal ranking.
- Runtime evidence remains the boundary for facts that affect deterministic diagnosis.
- Existing semantic entity and boundary IDs should be reused when available.
- Scope should survive from incident context through evidence, diagnosis, probes, and verification.

## Future work

Natural next slices are:

1. expose incident context through HTTP and MCP read-only projections;
2. let agents report which material scoping dimensions remain unknown;
3. recommend evidence collection from unresolved context without turning context into evidence;
4. connect verification results back to the original incident scope and blast radius;
5. add ingestion adapters for tickets, chat reports, and manual operator input;
6. model incident lifecycle state only if it can remain separate from causal truth.

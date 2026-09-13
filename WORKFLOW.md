# Diagnostic Workflow

Atlerror's diagnostic workflow starts before causal ranking. A report such as "checkout is slow" is not yet enough context to reason safely about causes.

The full workflow is:

```text
something is wrong
  -> capture incident context
  -> project known / partial / unknown scope
  -> clarify the next unresolved dimension
  -> estimate blast radius and impact
  -> compare failing and working cases
  -> collect runtime evidence
  -> candidate hypotheses
  -> predictions
  -> probes / experiments
  -> findings
  -> hypothesis updates
  -> cause / contributing factors
  -> mitigation / fix
  -> verification / prevention
```

## 1. Scope the incident

Causcope uses ten stable investigation dimensions:

| Dimension | Questions |
| --- | --- |
| Blast radius | Which users, accounts, tenants, devices, jobs, records, or requests are affected? How many out of how many? |
| Where | Which environment, region, availability zone, datacenter, service, entity, or boundary? |
| When | When did it start? What was the last known good time? Continuous, intermittent, periodic, or one-off? |
| Flow | Which feature, endpoint, operation, or user journey fails? |
| Client | Which browser, mobile app, OS, API consumer, worker, device, or version? |
| Change | What deploy, feature flag, config, migration, dependency, infrastructure, or data change happened near onset? |
| Dependency | Which upstream, downstream, external, or peer dependency is in the affected path? |
| Data | Is the problem tenant-specific, role-specific, permission-specific, record-specific, or limited to new/existing data? |
| Reproducibility | Can it be reproduced? Always, sometimes, rarely, or not yet? Under which conditions? |
| Impact | What user and business consequence exists? How severe is it? |

The stable IDs live in `vocabulary/investigation-dimensions.yaml`. The machine-readable incident contract is `schema/incident-context.schema.json`.

## 2. Project scoping state

Run:

```bash
python scripts/scoping_projection.py examples/incidents/checkout-latency.yaml
```

The projection classifies every dimension as:

```text
known
partial
unknown
```

and returns a deterministic `next_action` with the next clarification question.

The first policy follows the canonical dimension order. This is a transparent baseline, not a claim that static ordering is globally optimal. Future policies can rank questions by expected information gain, cost, safety, available telemetry, and cohort structure.

Scoping completeness is not diagnosis confidence.

## 3. Estimate blast radius

Prefer both an absolute count and a denominator when they are available:

```text
184 affected requests / 2,510 total requests = 7.33%
```

Do not replace an unknown denominator with a guess. Blast radius is breadth, while severity is consequence. Neither is proof of a cause.

## 4. Compare failing and working cases

A working comparison often removes more hypotheses than another isolated failing example.

Useful comparisons include:

```text
failing region vs working region
failing app version vs working app version
failing tenant vs working tenant
failing data age vs working data age
before deploy vs after deploy
```

Record observed differences without interpreting them as causal proof.

## 5. Convert facts into runtime evidence

Incident context narrows the search space. It MUST NOT silently enter causal ranking as evidence.

A contextual fact should become runtime evidence only when it can be represented as an observation with the existing evidence requirements, including time, source/provenance, state, confidence, and applicable scope.

For example:

```text
Context: failures appear limited to eu-central

Not enough by itself to assert:
  hypothesis.region_failure

Possible evidence after measurement:
  observation.http.error_rate is observed in eu-central
  observation.http.error_rate is absent in us-east
```

This preserves the distinction between triage information and measured diagnostic evidence.

## 6. Record investigation evolution

`schema/investigation-session.schema.json` defines a transport-independent session journal for:

```text
question
answer
comparison
evidence
hypothesis
probe
verification
note
```

This is the common state that future MCP, HTTP, SaaS, and agent-harness adapters can share instead of implementing separate investigation logic.

## 7. Rank hypotheses and choose probes

Once runtime evidence exists, use the existing deterministic layers:

```text
runtime evidence
  -> causal ranking
  -> probe ranking
  -> probe execution annotation
  -> agent plan
```

The incident-scoping layer does not introduce another probability score and does not reorder causal candidates directly.

## 8. Fix and verify

A mitigation is not the end of the workflow. Verification should check the original incident scope and blast radius, not only a single metric.

A useful close-out asks:

```text
Did the affected population recover?
Did failing cases become working cases?
Did the symptom disappear in the original region/client/data scope?
Did the fix introduce a regression elsewhere?
What evidence should prevent or detect recurrence?
```

## MCP and investigation lab

`scripts/investigation_mcp_server.py` extends the diagnosis MCP surface with:

```text
atlerror://incident/context
atlerror://incident/scoping
```

The investigation lab under `lab/investigation/` keeps initial information separate from hidden oracle truth and can be used as the foundation for future multi-model debugging benchmarks.

## Invariants

- Unknowns are explicit rather than guessed.
- A nearby deploy or configuration change is a candidate, not a cause.
- A dependency in the failing path is context, not proof that the dependency is at fault.
- Incident context narrows investigation but is not automatically diagnostic evidence.
- Working and failing comparisons should be captured early.
- A difference is a discriminator, not a cause.
- Severity is not blast radius.
- Scoping completeness is not root-cause confidence.
- Scope and provenance should survive every transition from context to evidence to diagnosis.
- The workflow remains useful to both humans and agents.

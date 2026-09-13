# Diagnostic Workflow

Atlerror's diagnostic workflow starts before causal ranking. A report such as "checkout is slow" is not yet enough context to reason safely about causes.

The full workflow is:

```text
something is wrong
  -> scope the incident
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

Capture what is known and what is still unknown across these dimensions:

| Dimension | Questions |
| --- | --- |
| Who | Which users, accounts, tenants, devices, jobs, or records are affected? How many? |
| Where | Which environment, region, availability zone, service, entity, or boundary? |
| When | When did it start? What was the last known good time? Continuous, intermittent, periodic, or one-off? |
| What | Which feature, endpoint, operation, or user journey fails? |
| Client | Which browser, mobile app, OS, API consumer, worker, or version? |
| Change | What deploy, feature flag, config, migration, dependency, infrastructure, or data change happened near onset? |
| Data | Is the problem tenant-specific, role-specific, permission-specific, record-specific, or limited to new/existing data? |
| Reproduction | Can it be reproduced? Always, sometimes, rarely, or not yet? Under which conditions? |
| Impact | What user and business effect exists? What is the affected count and percentage? |

The machine-readable contract is `schema/incident-context.schema.json`. An example is in `examples/incidents/checkout-latency.yaml`.

## 2. Estimate blast radius

Prefer both an absolute count and a denominator when they are available:

```text
184 affected requests / 2,510 total requests = 7.33%
```

Do not replace an unknown denominator with a guess. Blast radius is incident context, not proof of a cause.

## 3. Compare failing and working cases

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

## 4. Convert facts into runtime evidence

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

## 5. Rank hypotheses and choose probes

Once runtime evidence exists, use the existing deterministic layers:

```text
runtime evidence
  -> causal ranking
  -> probe ranking
  -> probe execution annotation
  -> agent plan
```

The incident-scoping layer does not introduce another probability score and does not reorder causal candidates directly.

## 6. Fix and verify

A mitigation is not the end of the workflow. Verification should check the original incident scope and blast radius, not only a single metric.

A useful close-out asks:

```text
Did the affected population recover?
Did failing cases become working cases?
Did the symptom disappear in the original region/client/data scope?
Did the fix introduce a regression elsewhere?
What evidence should prevent or detect recurrence?
```

## Invariants

- Unknowns are explicit rather than guessed.
- A nearby deploy or configuration change is a candidate, not a cause.
- Incident context narrows investigation but is not automatically diagnostic evidence.
- Working and failing comparisons should be captured early.
- Scope and provenance should survive every transition from context to evidence to diagnosis.
- The workflow remains useful to both humans and agents.
# RFC 0030: Investigation scoping protocol

Status: Accepted

Date: 2026-09-13

## Summary

RFC 0022 introduced `incident_context` as the pre-evidence incident-scoping record. This RFC makes that layer executable.

Causcope now defines ten stable investigation dimensions, a deterministic scoping projection, an appendable investigation-session contract, and read-only MCP projections suitable for agents.

The target workflow is:

```text
something is wrong
  -> incident context
  -> scoping projection
  -> highest-value unresolved dimension
  -> question / safe observation
  -> context revision
  -> failing-vs-working comparison
  -> runtime evidence
  -> causal diagnosis
  -> discriminating probe
  -> mitigation
  -> verification against original scope
```

The core remains product-neutral. CLI, MCP, HTTP, SaaS, and agent harnesses are projections or adapters over the same contracts.

## Ten investigation dimensions

The canonical registry is `vocabulary/investigation-dimensions.yaml`.

The stable dimension IDs are:

```text
investigation.blast_radius
investigation.where
investigation.when
investigation.flow
investigation.client
investigation.change
investigation.dependency
investigation.data
investigation.reproducibility
investigation.impact
```

They correspond to the practical questions:

```text
WHO / HOW MANY?
WHERE?
WHEN?
WHAT FLOW?
WHICH CLIENT?
WHAT CHANGED?
WHICH DEPENDENCY?
WHICH DATA?
CAN IT REPRODUCE?
WHAT IS THE CONSEQUENCE?
```

`blast_radius` and `impact` are intentionally separate. Breadth is not severity.

## Compatibility with incident context

`incident_context.unknowns` predates the stable dimension registry and uses compact values such as `who`, `what`, and `reproduction`.

The scoping projection normalizes those values:

```text
who          -> investigation.blast_radius
what         -> investigation.flow
reproduction -> investigation.reproducibility
```

The existing runtime record therefore remains readable without forcing a destructive migration.

RFC 0030 adds `dependency` as an allowed unresolved incident-context dimension.

## Dependency scope

Incident context now has explicit dependency selectors:

```yaml
scope:
  dependencies:
    - name: payment-provider
      relationship: external
      boundary: boundary.application.external_dependency
```

Allowed relationships are:

```text
upstream
downstream
external
peer
unknown
```

A dependency selector is context. It does not assert that the dependency caused the incident.

Datacenter selectors are also first-class under `scope.datacenters`.

## Scoping projection

`scripts/scoping_projection.py` turns incident context into a deterministic read model validated by `schema/scoping-projection.schema.json`.

The projection answers:

```text
Which dimensions are known?
Which are partially known?
Which are unknown?
How complete is the current scope?
What should be clarified next?
```

Example shape:

```json
{
  "kind": "scoping_projection",
  "incident_id": "incident.checkout.eu.latency",
  "completeness": 0.75,
  "known_count": 7,
  "partial_count": 1,
  "unknown_count": 2,
  "next_action": {
    "kind": "ask_question",
    "dimension": "investigation.client",
    "question": "Which browser, mobile app, OS, device, worker, or API version is affected?"
  }
}
```

The initial policy uses deterministic dimension order. This is intentionally a baseline, not a claim that static ordering is globally optimal.

Future policies may rank unresolved dimensions by expected information gain, cost, safety, available telemetry, or failing-vs-working cohort structure. Such ranking must remain explainable and independently testable.

## Context completeness is not diagnosis confidence

Scoping completeness means only that important investigation boundaries have been described.

It MUST NOT be interpreted as:

- probability that a hypothesis is correct;
- confidence in a root cause;
- incident severity;
- evidence quality.

A fully scoped incident can still have no known cause.

## Investigation session

`schema/investigation-session.schema.json` defines a transport-independent investigation journal.

A session belongs to one incident and tracks a `context_revision` plus typed events such as:

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

This record is the intended backbone for a future SaaS or agent platform. It captures how the investigation evolved without turning conversational history into causal truth.

Questions and answers are contextual state. Evidence events point toward runtime evidence. Hypothesis events describe belief updates. Probe events describe diagnostic actions. Verification returns to the original incident boundary.

## Separation of truth layers

The following invariants remain mandatory:

```text
context != evidence
correlation != causality
difference != cause
severity != blast radius
question priority != hypothesis probability
```

A nearby deploy can guide investigation without entering causal ranking.

A client difference can be a discriminator without proving a client bug.

A dependency in the failing path can be relevant without being at fault.

## MCP projection

The diagnosis MCP server may expose incident scoping as read-only resources when an incident-context provider is configured:

```text
atlerror://incident/context
atlerror://incident/scoping
```

The first resource returns validated incident context. The second returns the deterministic scoping projection.

This allows an agent to ask Causcope what is known and what should be clarified before jumping directly to root-cause hypotheses.

The existing `atlerror://` namespace is retained for compatibility. Product naming and URI migration are a separate versioning decision.

## Product architecture

Causcope should keep one investigation core with multiple adapters:

```text
knowledge + causal graph
          +
incident context
          +
runtime evidence
          |
          v
 investigation core
          |
  +-------+--------+---------+
  |       |        |         |
 CLI     MCP      HTTP     harness
                    |
                   SaaS
```

A future SaaS should provide persistence, organizations, integrations, permissions, dashboards, and multi-agent execution without reimplementing diagnostic semantics.

## Investigation lab

The existing lab answers questions such as:

```text
Is this diagnostic mechanism empirically reproducible?
```

The investigation lab adds a second question:

```text
Can an investigator discover the mechanism from incomplete information without violating investigation invariants?
```

The first scenario is a checkout incident containing incomplete initial context, hidden oracle facts, and a nearby deploy red herring. The deterministic baseline is expected to request client context before producing a root-cause claim.

Future agent harnesses can score behaviors such as:

- scope before hypothesizing;
- identify blast radius;
- find a useful failing/control cohort;
- choose high-information questions;
- avoid treating temporal correlation as cause;
- collect discriminating evidence;
- eliminate alternatives;
- verify recovery in the original scope.

## Non-goals

This RFC does not:

- define a universal probabilistic root-cause model;
- let incident context directly rerank causal hypotheses;
- execute arbitrary diagnostic actions;
- make an LLM the semantic source of truth;
- define SaaS tenancy or billing;
- rename existing Atlerror protocol identifiers.

## Next slices

Natural follow-up work is:

1. dynamic next-question ranking based on expected information gain;
2. explicit failing/control cohort objects beyond pairwise comparisons;
3. writable MCP tools for controlled context updates;
4. HTTP equivalents of context and scoping resources;
5. agent-harness adapters for multiple models;
6. investigation scoring over complete multi-step scenarios;
7. verification projection that reuses the original blast radius.

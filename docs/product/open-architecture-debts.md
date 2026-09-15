# Open architecture debts

Status: Active review list

This file records inconsistencies discovered while reconciling the current repository with the agent-first product architecture. These are not all implementation bugs. Some are naming or governance debts that should be resolved deliberately rather than through silent breaking changes.

## 1. `incident_context` now conflicts with the broader Investigation model

### Current state

Accepted RFC 0022 introduced:

```text
kind: incident_context
incident_id: ...
schema/incident-context.schema.json
```

The local Investigator also persists:

```text
.causcope/incident-context.yaml
```

At the time, `incident` was used broadly for "the problem being investigated."

The newer integration architecture now distinguishes:

```text
Investigation
  canonical Causcope case/state

Incident
  optional operational lifecycle object owned by PagerDuty/ServiceNow/JSM/etc.
```

An Investigation may exist without a formal Incident.

### Risk

If the current naming becomes part of cloud/webhook integrations, it can incorrectly imply:

```text
every investigation == formal incident
```

This would make proactive findings, local debugging sessions, Sentry-only issues, learning labs, and pre-incident investigations awkward to model.

### Recommended resolution

Do not rename the accepted schema/file ad hoc.

Create a compatibility RFC that evaluates one of these approaches:

```text
A. Rename canonical runtime concept to investigation_context
   and provide incident_context compatibility/migration.

B. Introduce investigation as the parent case object
   while keeping incident_context as an optional scoping subrecord.

C. Explicitly redefine incident_context as legacy terminology
   with a versioned replacement contract.
```

Preference: B or a carefully versioned A. Preserve old stored sessions during migration.

## 2. RFC numeric identifiers are not unique

The `RFC/` directory currently contains multiple files with the same numeric prefix. Confirmed examples include:

```text
0022-agent-plan-probe-session-state.md
0022-incident-context-and-scoping.md

0033-external-diagnostic-adapters.md
0033-testbed-runtime-evidence-bridge.md

0040-resource-topology-provider-instances.md
0040-routing-aware-agent-plan-and-mcp.md

0059-investigator-cli-diagnosis-front-door.md
0059-rails-product-cli.md

0068-recommendation-investigator-cli-mcp-surface.md
0068-runtime-target-aware-investigation.md
```

### Risk

References such as "RFC 0059" are ambiguous and no longer act as stable identifiers.

This matters increasingly as `docs/`, issues, code comments, agents, and future public documentation cross-reference architectural decisions.

### Recommended resolution

Do not silently renumber files that may already be referenced.

First:

1. inventory all duplicate prefixes;
2. determine which references exist in repository history/current files;
3. define immutable RFC identity rules;
4. introduce explicit aliases/supersession metadata if renumbering is required;
5. add validation preventing any new duplicate number.

A validator should fail CI/local validation when two RFC filenames claim the same numeric ID.

Future RFC creation should allocate the next unique identifier atomically rather than having parallel agents independently choose a number.

## 3. Product roadmap wording lags implemented agent machinery

The repository already contains accepted/implemented work beyond a purely hypothetical agent roadmap, including:

```text
autonomous bounded read-only investigation
probe ranking/execution machinery
MCP surfaces
provider/capability discovery
runtime evidence composition
Concrete System / X-Ray work
Rails runtime providers
```

The current golden milestone is an in-progress Rails D3.1 connection-pool vertical slice rather than the creation of the first generic investigation concepts from scratch.

### Recommended resolution

Treat the roadmap phases as product sequencing, not as a claim that earlier phases are unimplemented.

Add/maintain a separate current-state projection that maps repository capabilities to roadmap phases.

## 4. Confidence terminology must remain aligned with deterministic ranking

The current core intentionally exposes ordinal ranking and its factors instead of pretending to calculate universal probabilities.

Product surfaces must not independently introduce values such as:

```text
73% confidence
medium-high confidence
```

unless a future RFC defines their semantics and empirical calibration.

Current preferred UI projection:

```text
Leading hypothesis
supporting evidence
contradicting evidence
unknown discriminators
ranking explanation
```

## 5. Trust model is directional, not yet a canonical contract

`docs/architecture/trust-access-blast-radius.md` proposes:

```text
Trust Manifest
Trust Diff
Access Drift
blast-radius dimensions
```

These are currently product architecture ideas, not yet canonical schemas/vocabulary.

Before implementations depend on them, stabilize the smallest useful slice through RFC + schema, preferably starting with one concrete integration such as GitHub App or local PostgreSQL diagnostic access.

## 6. Cloud component model is logical, not a microservice plan

The future Cloud architecture names logical responsibilities such as:

```text
Ingress
Normalizer
Correlation
Investigation Store
Orchestrator
Capability Router
Output Adapters
```

These names must not be interpreted as a requirement to deploy separate microservices.

A modular monolith is the preferred first implementation unless scaling, security, team ownership, or independent lifecycle creates a real boundary.

## Review rule

When an architecture debt becomes contract-defining or requires a breaking semantic change, resolve it through an RFC/schema migration rather than only editing directional prose under `docs/`.

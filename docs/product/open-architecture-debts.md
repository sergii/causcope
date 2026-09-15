# Open architecture debts

Status: Active review list

This file records inconsistencies discovered while reconciling the current repository with the agent-first product architecture. These are not all implementation bugs. Some are naming or governance debts that should be resolved deliberately rather than through silent breaking changes.

## 1. `incident_context` vs broader Investigation model

Status: **Compatibility direction proposed, migration still open**

### Current state

Accepted historical contracts use:

```text
kind: incident_context
incident_id: ...
schema/incident-context.schema.json
.causcope/incident-context.yaml
```

The product architecture now distinguishes:

```text
Investigation
  canonical Causcope case/state

Incident
  optional operational lifecycle object owned by PagerDuty/ServiceNow/JSM/etc.
```

An Investigation may exist without a formal Incident.

### Resolution in progress

`RFC/0076-investigation-case-and-incident-compatibility.md` now proposes:

- `Investigation` as the Causcope-owned parent case;
- `investigation_id` as the future canonical identity;
- external incidents as optional provider-qualified references;
- existing `incident_context` and `incident_id` preserved during a compatibility period;
- no silent file/schema rename.

### Remaining work

The architecture question is no longer whether an Investigation should exist independently from an Incident. The remaining debt is migration mechanics:

```text
investigation-case schema
legacy incident_id mapping
runtime-evidence join-key compatibility
workspace compatibility fixtures
eventual investigation_context naming decision
```

Until that migration is accepted and implemented, existing serialized contracts remain authoritative.

## 2. Historical RFC numeric collisions

Status: **Recurrence prevented, historical cleanup still open**

The `RFC/` directory contains legacy duplicate numeric prefixes:

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

### Implemented governance

`RFC/0077-rfc-identity-governance.md` defines the future identity rule.

The repository now contains:

```text
vocabulary/rfc-id-exceptions.yaml
scripts/validate_rfc_ids.py
```

and the main validation workflow runs the RFC identity validator.

The validator allows only the exact registered historical collision groups. A new duplicate or an additional file under one of those legacy IDs fails validation.

### Remaining work

Historical IDs are still ambiguous. Before any renumbering:

1. inventory current references to each collision pair;
2. decide whether one file keeps the historical ID and the other receives a new one;
3. preserve explicit former-ID/alias metadata if renumbering occurs;
4. use full filenames when referencing a grandfathered ambiguous RFC in the meantime.

The urgent governance bug is fixed. Historical cleanup is lower priority than current product work.

## 3. Product roadmap vs implemented agent machinery

Status: **Resolved as documentation structure; keep current-state projection fresh**

The repository already contains substantial implemented machinery:

```text
autonomous bounded read-only investigation
probe ranking/execution
MCP surfaces
provider/capability discovery
runtime evidence composition
Concrete System / X-Ray
Rails runtime providers
```

The roadmap phases therefore describe product sequencing, not a claim that those capabilities are unimplemented.

`docs/product/current-state.md` now maps repository reality to the roadmap and should remain the descriptive source for implementation status.

The Rails D3.1 golden vertical slice in `RFC/0075-golden-vertical-slice-rails-connection-pool.md` is now an implemented proof, not an in-progress conceptual milestone.

## 4. Confidence terminology must remain aligned with deterministic ranking

Status: **Active invariant**

The core intentionally exposes ordinal ranking and its factors instead of pretending to calculate universal probabilities.

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

This remains a guardrail rather than a migration task.

## 5. Trust model is directional, not yet a canonical contract

Status: **Open**

`docs/architecture/trust-access-blast-radius.md` proposes:

```text
Trust Manifest
Trust Diff
Access Drift
blast-radius dimensions
```

These are currently product architecture ideas, not yet canonical schemas/vocabulary.

Before implementations depend on them, stabilize the smallest useful slice through RFC + schema, preferably starting with one concrete integration such as GitHub App or local PostgreSQL diagnostic access.

This should not interrupt current Agent First product consolidation unless a concrete integration requires it.

## 6. Cloud component model is logical, not a microservice plan

Status: **Active architecture guardrail**

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

## 7. Product front door is not yet the generic evidence-acquisition loop

Status: **Open, current near-term priority**

The initial `causcope why` front door now exists.

It can:

- start or resume existing investigation/scoping state;
- avoid guessing a cause before evidence exists;
- consume the canonical Rails D3.1 artifact set;
- render the already-proven product diagnosis without introducing another reasoning engine.

The remaining gap is:

```text
plain problem statement
  -> capability discovery
  -> provider/instrument selection
  -> safe evidence acquisition
  -> generic diagnosis projection
```

without requiring the user to manually supply subsystem artifact paths.

Most of the underlying capability, provider, routing, probe, and autonomous-execution machinery already exists. The debt is composition and product consolidation, not another reasoning abstraction.

## Review rule

When an architecture debt becomes contract-defining or requires a breaking semantic change, resolve it through an RFC/schema migration rather than only editing directional prose under `docs/`.

When an item is resolved, update this document and `docs/product/current-state.md` so agents and humans do not plan from stale architecture assumptions.

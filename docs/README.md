# Causcope documentation

This directory records the product and deployment architecture around the existing Causcope semantic and investigation core.

The central product principle is:

> Causcope is agent first, not agent only.

The first useful product should work locally with an engineer or autonomous agent and must not require Causcope Cloud. Cloud, dashboard, collaboration, managed integrations, and enterprise deployment surfaces are planned extensions around the same investigation contracts and reasoning engine.

## Documents

### Architecture

- [Agent-first product architecture](architecture/agent-first-product-architecture.md) - product layers, boundaries, execution model, human-learning projection, and why cloud is not the core.
- [Deployment model](architecture/deployment-model.md) - local, SMB, managed cloud, hybrid relay, Helm/Docker, and private deployment modes.
- [Cloud component model](architecture/cloud-component-model.md) - future logical cloud components such as ingress, normalization, correlation, orchestration, evidence routing, Relay control, and output adapters without making them an immediate implementation priority.
- [Trust, access, and blast radius](architecture/trust-access-blast-radius.md) - access boundaries, capability model, least privilege, Trust Manifest, Trust Diff, data minimization, and standards crosswalk.

### Integrations

- [Integration model](integrations/integration-model.md) - signals, trigger modes, investigation-vs-incident policy, incident systems, communication surfaces, evidence providers, source-of-truth boundaries, and integration priorities.

### Product

- [Current product state](product/current-state.md) - what is actually implemented today, the Rails D3.1 golden proof, the current `causcope why` front door, and the remaining product-integration gap.
- [Agent-first roadmap](product/agent-first-roadmap.md) - recommended product sequence from local investigator to dashboard and enterprise distribution.
- [Operational terminology](product/operational-terminology.md) - concise distinction between signal, symptom, context, observation, evidence, mechanism, hypothesis, investigation, incident, diagnosis, mitigation, and verification.
- [Repository strategy](product/repository-strategy.md) - why the project remains in `sergii/causcope` for now and the criteria for a future organization/repository split.
- [Open architecture debts](product/open-architecture-debts.md) - known naming/governance inconsistencies that need deliberate RFC/schema resolution rather than silent changes.

## Relationship to the existing repository

These documents do not replace the existing RFCs or semantic artifacts.

The existing repository already defines the core diagnostic loop:

```text
symptom
  -> observations
  -> candidate hypotheses
  -> predictions
  -> probes / experiments
  -> findings
  -> hypothesis updates
  -> cause / contributing factors
  -> mitigation / fix
  -> verification / prevention
```

It also already contains canonical symptoms, mechanisms, claims, experiments, runtime evidence, causal ranking, investigation state, and local transports such as CLI, HTTP, and MCP.

Important existing foundations include:

```text
README.md
INVESTIGATE.md
RFC/0001-semantic-foundation.md
RFC/0003-diagnostic-catalog-codes.md
RFC/0005-runtime-evidence-instances.md
RFC/0012-recommended-next-probe.md
RFC/0075-golden-vertical-slice-rails-connection-pool.md
```

The documents in `docs/` describe how that core becomes an end-user product without making SaaS infrastructure a prerequisite for useful diagnosis.

## Documentation authority

The layers have different purposes:

```text
vocabulary / schemas / knowledge
  canonical machine-readable semantics

RFC/
  design decisions and semantic/technical contracts

docs/
  current product, deployment, integration and roadmap architecture
```

If a directional `docs/` document conflicts with an accepted or implemented canonical contract, the conflict should be resolved explicitly rather than silently treating the prose as a second source of truth.

When a directional architecture decision becomes stable and contract-defining, promote the relevant parts into an RFC/schema/vocabulary artifact.

## Decision summary

1. **Knowledge and investigation semantics are the core product asset.**
2. **The first execution surface is a local/near-system agent.**
3. **Human learning, human troubleshooting, and machine investigation should project from the same knowledge.**
4. **The same contracts must power CLI, MCP, local daemon, future dashboard, Slack, PagerDuty, and managed cloud.**
5. **Cloud is a delivery, collaboration, orchestration, and enterprise-management layer, not a separate reasoning implementation.**
6. **A customer-side Relay is a deployment role of the same agent runtime where practical, not a second reasoning product.**
7. **Read-only investigation comes before remediation.**
8. **Enterprise readiness is designed in from the beginning through explicit trust boundaries and capability declarations, but it does not block the first local product.**
9. **Dashboard remains important and should follow the useful agent core rather than precede it.**
10. **Signals, incidents, raw telemetry, and Causcope Investigations have different authorities and must not be collapsed into one source of truth.**
11. **Repository boundaries remain flexible until components have genuinely independent lifecycles.**
12. **Known model/governance debts are tracked explicitly instead of being hidden by prose edits.**

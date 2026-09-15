# Causcope documentation

This directory records the product and deployment architecture around the existing Causcope semantic and investigation core.

The central product principle is:

> Causcope is agent first, not agent only.

The first useful product should work locally with an engineer or autonomous agent and must not require Causcope Cloud. Cloud, dashboard, collaboration, managed integrations, and enterprise deployment surfaces are planned extensions around the same investigation contracts and reasoning engine.

## Documents

### Architecture

- [Agent-first product architecture](architecture/agent-first-product-architecture.md) - product layers, boundaries, execution model, and why cloud is not the core.
- [Deployment model](architecture/deployment-model.md) - local, SMB, managed cloud, hybrid relay, Helm/Docker, and private deployment modes.
- [Trust, access, and blast radius](architecture/trust-access-blast-radius.md) - access boundaries, capability model, least privilege, Trust Manifest, and Trust Diff.

### Integrations

- [Integration model](integrations/integration-model.md) - signals, incident systems, communication surfaces, evidence providers, and the first integration priorities.

### Product

- [Agent-first roadmap](product/agent-first-roadmap.md) - recommended product sequence from local investigator to dashboard and enterprise distribution.

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

The documents in `docs/` describe how that core becomes an end-user product without making SaaS infrastructure a prerequisite for useful diagnosis.

## Decision summary

1. **Knowledge and investigation semantics are the core product asset.**
2. **The first execution surface is a local/near-system agent.**
3. **The same contracts must power CLI, MCP, local daemon, future dashboard, Slack, PagerDuty, and managed cloud.**
4. **Cloud is a delivery, collaboration, orchestration, and enterprise-management layer, not a separate reasoning implementation.**
5. **A customer-side Relay is a deployment role of the same agent runtime where practical, not a second reasoning product.**
6. **Read-only investigation comes before remediation.**
7. **Enterprise readiness is designed in from the beginning through explicit trust boundaries and capability declarations, but it does not block the first local product.**
8. **Dashboard remains important and should follow the useful agent core rather than precede it.**

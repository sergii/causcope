# Repository strategy

Status: Directional product engineering decision

## Current decision

Keep the project in the existing `sergii/causcope` repository while the semantic model, investigation engine, agent runtime contracts, cloud boundaries, and Relay role are still evolving together.

Do not split the project into multiple repositories merely to make the project look more mature.

The current repository is intentionally a product/research monorepo where architecture boundaries can still move cheaply.

## Why not split now

Premature repository boundaries would force decisions before we know which components actually have independent lifecycles.

Today the following are tightly coupled conceptually:

```text
knowledge
schemas
rules
investigation state
reasoning
agent-facing contracts
labs
collectors
```

The project benefits from changing these atomically while the model is still being discovered through vertical slices.

## When to create a GitHub organization

Create a dedicated Causcope organization when there are multiple components with genuinely independent operational or release lifecycles.

Useful signals include:

- different release cadences;
- separate CI/CD requirements;
- distinct permission boundaries;
- different maintainers;
- one component becomes open source while another is private;
- the packaged runtime/Relay has its own release stream;
- the managed control plane has its own deployment lifecycle;
- semantic knowledge can version independently from both runtime and cloud.

At that point a GitHub organization is an architectural consequence rather than branding work.

Preferred organization names, subject to availability:

```text
causcope
causcopehq
```

## Likely future repository boundaries

The most plausible long-term split currently looks like:

```text
causcope/causcope
  managed control plane
  API
  dashboard
  investigation orchestration
  managed SaaS integrations

causcope/relay
  packaged local/customer runtime
  CLI/daemon/Relay role
  collectors
  local policy and capability enforcement

causcope/knowledge
  ontology
  symptoms and mechanisms
  claims
  probes
  rules
  schemas
  empirical knowledge assets
```

These are hypotheses, not commitments.

## What should probably not become separate repositories early

Avoid a repository zoo such as:

```text
causcope-pagerduty
causcope-sentry
causcope-slack
causcope-datadog
causcope-github
```

Most managed integration adapters should remain in the control-plane codebase unless they develop a real independent lifecycle or SDK boundary.

Likewise, do not split a CLI from the local runtime merely because they are different commands. A single runtime may expose:

```text
causcope investigate
causcope diagnose
causcope serve --mcp
causcope daemon
```

and use the same binary in local and Relay roles.

## Migration rule

Repository split must not change canonical semantic identity or investigation contracts.

If code moves later:

```text
semantic IDs stay stable
schemas stay versioned
investigation state stays portable
capability names stay stable or receive explicit migrations
```

Repository layout is implementation structure, not product identity.

# Deployment model

Status: Directional architecture

## Goal

Causcope should support a progression from a single engineer on a laptop to a regulated enterprise without changing the semantic or investigation core.

The deployment model is therefore layered rather than split into unrelated products.

## Common logical components

```text
Causcope Core
  semantic knowledge
  investigation state
  causal reasoning
  probe selection
  evidence contracts

Causcope Runtime
  CLI
  MCP
  local HTTP
  collectors
  capability registry
  policy enforcement

Causcope Cloud
  optional managed control plane
  dashboard
  team state
  integrations
  webhook/event ingestion
  orchestration
  history
  enterprise controls

Causcope Relay
  optional customer-environment runtime role
  local credentials
  approved collectors
  outbound connection to Cloud
```

Not every deployment needs every component.

## Mode 1 - Local developer / freelancer

```text
Engineer or coding agent
        |
      MCP/CLI
        |
     Causcope
        |
  +-----+------+-------+
  |            |       |
 git        Docker   PostgreSQL
 logs       local app   etc.
```

Characteristics:

- no Causcope Cloud required;
- state may live under `.causcope/`;
- local credentials stay local;
- ideal for learning, debugging, agent integration, reproducible labs, and early dogfooding;
- install may be via package manager or downloadable binary.

Potential distribution:

```text
brew install causcope
cargo install ...      # only if appropriate
binary release
Docker image
```

The distribution mechanism does not define the architecture.

## Mode 2 - Small team / SMB

A small team may still run Causcope close to its systems while optionally using managed collaboration.

```text
GitHub / Sentry / Datadog
          |
          v
    Causcope Cloud
          |
    notifications/UI
          |
     Slack/Telegram

optional:

local Causcope runtime -> private evidence
```

Characteristics:

- SaaS integrations can provide a large amount of evidence without private-network access;
- local agent/daemon can add PostgreSQL, Docker, logs, or other private evidence;
- Telegram can be useful for founders and small teams even though it is not the primary enterprise communication surface.

## Mode 3 - Managed cloud without private Relay

```text
PagerDuty ------+
Datadog --------+
Sentry ---------+
GitHub App -----+----> Causcope Cloud
OTel/Prometheus +          |
                           +-> Dashboard
                           +-> Slack/Teams
                           +-> investigation history
```

This mode is useful when the available SaaS APIs and webhooks provide enough evidence.

It should be possible to deliver meaningful value without:

- SSH;
- database credentials;
- kubectl from Causcope Cloud;
- inbound access to a customer VPC;
- arbitrary code execution in the customer environment.

This is an important adoption path because it reduces vendor-risk and security review scope.

## Mode 4 - Hybrid enterprise with Causcope Relay

```text
                       Causcope Cloud
                   control / collaboration
                             |
                    outbound session
                             |
                             v
+--------------------------------------------------+
| customer VPC / cluster                           |
|                                                  |
| Causcope Relay                                   |
|   capability registry                            |
|   local policy                                   |
|   approved collectors                            |
|        |                                         |
|        +-> PostgreSQL                            |
|        +-> Kubernetes                            |
|        +-> Prometheus                            |
|        +-> internal logs                         |
|        +-> internal APIs                         |
|        +-> pgbot / local diagnostic tools        |
+--------------------------------------------------+
```

Characteristics:

- outbound-only connectivity should be the default where possible;
- cloud does not need customer database passwords;
- local secrets should live in customer-controlled secret stores;
- raw sensitive data can remain local by default;
- Relay returns structured evidence rather than unrestricted dumps where possible;
- collectors are versioned and allowlisted;
- local policy may deny a cloud-requested probe even when the binary technically supports it.

## Mode 5 - Kubernetes enterprise distribution

A common enterprise installation form is expected to be Helm plus container images.

Potential packaging:

```text
Helm chart
  Deployment/StatefulSet as justified
  ServiceAccount
  RBAC
  NetworkPolicy
  ConfigMap
  Secret references
  optional sidecars/exporters only when necessary
```

Important rule:

> The Helm chart declares permissions explicitly; it must not silently require cluster-admin.

Possible deployment scope:

- namespace only;
- selected namespaces;
- cluster-wide read-only where the customer explicitly chooses it.

The chart should make the blast-radius difference visible before installation.

## Mode 6 - Docker / VM / bare Linux

Not every customer uses Kubernetes.

The same runtime should support:

```text
Docker container
systemd service
VM appliance if justified later
```

For a daemon installation:

```text
causcope daemon
```

should remain conceptually equivalent to the Relay role when connected to managed Cloud.

## Mode 7 - Private / self-hosted Causcope

Some regulated customers may require that investigation state and evidence never leave their environment.

Possible future topology:

```text
Customer environment

Causcope Control Plane
Causcope Dashboard
Causcope Investigation Engine
Causcope Relay(s)
customer identity provider
customer data stores
```

This should be considered a later enterprise distribution mode, not an early prerequisite.

Self-hosted deployment introduces substantial operational commitments:

- upgrades and rollback;
- migrations;
- support matrix;
- air-gapped or restricted egress environments;
- customer-managed identity;
- backup/restore;
- observability of Causcope itself;
- support tooling.

Do not implement it before the core product demonstrates value.

## GitHub App

GitHub is a particularly useful cloud-side integration because code and deploy changes are high-value causal context.

The app should prefer read-only permissions and support installation on selected repositories or an organization-defined repository set.

Useful evidence includes:

- commits;
- pull requests;
- changed files;
- deployment metadata;
- checks/workflows where justified;
- ownership and repository topology.

Source-code access itself is sensitive and should be treated as a meaningful confidentiality blast radius even when access is read-only.

## Dashboard role

The dashboard is not the investigation engine. It is a shared projection over canonical state.

It should eventually answer:

- What investigations are active?
- What is affected?
- What evidence has been collected?
- Which hypotheses remain?
- What was ruled out and why?
- What changed near onset?
- What probe is recommended next?
- Which capabilities are available or denied?
- What actions require approval?
- What is the trust/access footprint of this installation?
- What happened in previous similar investigations?

This is important for enterprises even if engineers increasingly interact with agents through text.

## Distribution principle

Causcope should not fork into separate reasoning products for CLI, cloud, and enterprise.

The target is:

```text
same knowledge
same schemas
same investigation state
same evidence model
same capability model
same reasoning

multiple deployments and surfaces
```

That keeps local experimentation directly relevant to the future managed product.

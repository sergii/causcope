# Trust, access, and blast radius

Status: Directional architecture

## Goal

Every Causcope integration and deployment should make its trust requirements explicit and machine-readable.

The product must be able to answer:

```text
Who is the principal?
Which credential does it use?
What resources can it reach?
Which actions can it perform?
Which data can it read?
Which data leaves the customer boundary?
Which data is retained?
What is the maximum compromise blast radius?
What requires human approval?
What changed compared with the previous version?
```

This model should serve product design, customer security review, CI policy, audit, and future compliance automation.

## Principle

Causcope should minimize required trust rather than ask customers to trust a broad privileged agent.

Prefer:

```text
postgres.inspect_locks
```

over:

```text
postgres.*
```

Prefer:

```text
kubernetes.events.read
```

over:

```text
cluster-admin
```

Prefer:

```text
approved collector
```

over:

```text
remote arbitrary shell
```

## Access levels

The following levels are a product-oriented shorthand, not a universal industry standard.

### L0 - incident and operational metadata

Examples:

- PagerDuty incident ID/status;
- service name;
- severity;
- timestamps;
- external links.

Typical risk: low to moderate operational information exposure.

### L1 - change and source context

Examples:

- GitHub commits;
- PR metadata;
- deployment records;
- source code where permitted;
- configuration diffs that do not contain secrets.

Typical risk: potentially high confidentiality impact even when read-only.

### L2 - telemetry

Examples:

- metrics;
- traces;
- error events;
- sampled structured diagnostic events.

Typical risk: moderate to high depending on payload content and tenant data.

### L3 - raw logs and dumps

Examples:

- application logs;
- stack traces containing request data;
- process dumps;
- profiles containing sensitive identifiers.

Typical risk: high confidentiality and privacy exposure.

### L4 - private infrastructure and databases

Examples:

- PostgreSQL diagnostic access;
- Kubernetes API access;
- internal service APIs;
- private Prometheus;
- customer VPC resources.

Typical risk: high. Scope and credentials must be strongly constrained.

### L5 - state-changing actions

Examples:

- rollback;
- restart;
- scale;
- feature-flag mutation;
- database write;
- queue replay;
- infrastructure change.

Typical risk: highest availability/integrity blast radius and normally requires explicit approval policy.

## Blast radius is multidimensional

Avoid reducing access risk to one unexplained number.

Represent dimensions explicitly:

```yaml
blast_radius:
  tenants: 1
  environments: [production]
  regions: [eu-central-1]
  repositories: 182
  services: [checkout-api]
  resource_scope: organization

  confidentiality: high
  integrity: none
  availability: none

  privilege: read
  reversibility: not_applicable
  network_reach: external_api
  human_approval: not_required
```

A UI may derive a summary such as `HIGH`, but the underlying dimensions should remain visible and auditable.

## Canonical trust graph

A useful conceptual model is:

```text
Principal
  -> Credential
      -> Capability
          -> Action
              -> Resource
                  -> Scope
                      -> Data
                          -> Boundary
                              -> Consequence
                                  -> Control
```

Examples:

```text
Causcope GitHub App
  -> installation token
  -> repository.contents.read
  -> read
  -> repository contents
  -> selected repositories
  -> source code
  -> GitHub -> Causcope Cloud
  -> possible source-code disclosure
  -> least privilege / customer installation policy
```

and:

```text
Causcope Relay
  -> customer DB role
  -> postgres.inspect_locks
  -> read diagnostic views
  -> checkout production database
  -> selected database
  -> lock/session metadata
  -> DB -> Relay -> optional structured evidence -> Cloud
  -> diagnostic metadata disclosure
  -> local policy + read-only DB role
```

## Existing standards and concepts to reuse

Causcope should not claim that the entire trust model is a new security standard. It is a normalized operational profile over established concepts.

Relevant foundations include:

```text
Access-control matrix
  subject x object -> allowed rights

NIST SP 800-53 AC-6
  least privilege

OAuth 2.0 RFC 6749
  scopes and delegated authorization

RFC 9396 - Rich Authorization Requests
  structured fine-grained authorization details

NIST SP 800-207
  zero-trust resource-oriented access decisions

OSCAL
  machine-readable security controls and assessment information

CycloneDX SaaSBOM
  services, dependencies, endpoints and data-flow concepts

SLSA provenance
  machine-readable software/build provenance
```

Causcope's added value is the cross-provider operational model:

```text
what can this integration touch?
what can it observe?
what can it change?
what data crosses which boundary?
what is the worst plausible impact if it is compromised?
what changed since the previous version?
```

## Causcope Trust Manifest

Causcope should eventually define a versioned machine-readable manifest that normalizes this information across providers.

Illustrative example:

```yaml
apiVersion: causcope.dev/v1
kind: IntegrationCapability

metadata:
  name: github

principal:
  type: github_app

access:
  provider: github
  scope:
    organization: acme
    repositories: selected

permissions:
  - capability: repository.contents.read
    resource: repository.contents
    actions: [read]
  - capability: pull_requests.read
    resource: pull_requests
    actions: [read]

credentials:
  type: installation_token
  lifetime: short_lived

network:
  flows:
    - from: github
      to: causcope_cloud

data:
  reads:
    - source_code
    - commit_metadata
    - deployment_metadata
  stores:
    - commit_metadata
  excluded:
    - repository_secrets

actions:
  write: false
  delete: false
  execute: false

blast_radius:
  resource_scope: selected_repositories
  confidentiality: high
  integrity: none
  availability: none
```

The initial format should map cleanly to existing standards where possible rather than creating incompatible vocabulary for concepts that already exist.

## Declared access vs observed access

The system should distinguish:

```text
Declared requirements
        vs
Observed effective permissions
```

Example:

```text
Declared:
  postgres.inspect_activity
  postgres.inspect_locks

Observed role:
  SELECT ON ALL TABLES
```

Finding:

```text
ACCESS-DRIFT
Granted privileges exceed declared investigation requirements.
```

This creates a path toward automated least-privilege validation.

## Trust Diff

Permission and data-flow changes should be treated as meaningful product changes, similar to an API or schema diff.

Example:

```text
repository.contents:
  read -> write
```

Causcope should be able to derive:

```text
ACCESS-EXPANDED

New capability:
  modify repository contents

Affected scope:
  182 repositories

Blast-radius delta:
  confidentiality: unchanged
  integrity: none -> critical

Security review:
  required
```

Candidate change classes:

```text
ACCESS-EXPANDED
ACCESS-REDUCED
DATA-COLLECTION-ADDED
DATA-EXPORT-ADDED
DATA-RETENTION-INCREASED
NETWORK-BOUNDARY-CROSSED
WRITE-CAPABILITY-ADDED
EXECUTION-CAPABILITY-ADDED
TENANT-SCOPE-EXPANDED
CREDENTIAL-LIFETIME-INCREASED
HUMAN-APPROVAL-REMOVED
```

These should become canonical machine-addressable concepts if the model proves useful.

## Trust Diff as a CI artifact

The long-term workflow should be changelog-like and automatable.

Conceptually:

```text
GitHub App manifest / IAM / RBAC / Terraform / Helm / GRANTs
                         |
                         v
                 normalized trust state
                         |
                   compare base/head
                         |
                         v
                     Trust Diff
```

Example CLI shape:

```text
causcope trust inspect
causcope trust diff --base main --head HEAD
```

A pull request could then expose:

```text
New access: repository.contents write
Scope delta: 12 -> 182 repositories
New data export: raw logs -> external SaaS
Approval removed: production restart
```

Policy can later require security review for selected change classes.

## Inputs that can be analyzed automatically

Potential sources for generating the Trust Manifest or effective-access view include:

```text
GitHub App permissions
OAuth scopes
AWS IAM policies
GCP/Azure IAM
Kubernetes RBAC
Kubernetes NetworkPolicy
Terraform
Helm manifests
PostgreSQL GRANTs
Vault policies
Slack OAuth scopes
Datadog integration scopes
Sentry integration permissions
Causcope local policy
```

The long-term goal is to reduce manually maintained security documentation by deriving as much as possible from actual configuration.

## Data minimization defaults

Private evidence collection should default to the minimum information needed to support or falsify a hypothesis.

Prefer:

```text
structured finding
measurement
resource identity
scope
provenance
relevant timestamps
```

over unrestricted export of:

```text
raw database rows
full database dumps
entire log archives
secrets
unrelated tenant data
```

Database credentials should normally remain inside the customer environment when a Relay is used. Raw SQL text, raw rows, and full logs should not leave the boundary by default merely because the collector can see them.

Any exception should be explicit in the Trust Manifest and customer policy.

## Integration review template

Every integration should document at least:

```text
Access requested
Credentials used
Resources in scope
Data read
Data stored
Data transmitted
Retention
Network direction
Actions allowed
Approval requirements
Worst-case confidentiality impact
Worst-case integrity impact
Worst-case availability impact
Revocation path
Auditability
```

## Relay security rules

The customer-side Relay should follow these defaults:

- outbound connectivity where possible;
- mutually authenticated transport where practical, with rotating/short-lived credentials preferred;
- no arbitrary remote shell;
- no implicit root or cluster-admin requirement;
- local secrets remain local;
- explicit capability advertisement;
- local policy can deny cloud requests;
- read-only collectors first;
- structured evidence preferred over raw bulk data;
- every probe records provenance;
- all state-changing actions are a separate policy class.

Example capability declaration:

```text
allowed
  kubernetes.pods.read
  kubernetes.events.read
  kubernetes.deployments.read
  postgres.activity.read
  postgres.locks.read

forbidden
  kubernetes.exec
  kubernetes.secrets.read
  postgres.write
  shell.exec
```

## Compliance and enterprise adoption

Compliance reports such as SOC 2 are important trust signals and are often required by larger customers, but architecture should not treat them as a binary prerequisite for all useful deployments.

The product should allow a progression:

```text
small team
  -> SaaS API integrations / local agent

larger SaaS customer
  -> security review / DPA / policies / audit logs

enterprise
  -> stronger identity / retention / review / Relay / managed deployment

regulated customer
  -> tightly scoped Relay or private Causcope deployment
```

The design objective is to reduce the amount of trust each customer must grant.

## Product principle

> The less trust Causcope requires, the easier Causcope is to deploy.

This principle applies equally to the local agent, managed cloud, dashboard integrations, and future remediation capabilities.

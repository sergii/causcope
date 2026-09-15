# Current product state

Status: Living projection

This document maps the repository as it exists today to the agent-first product roadmap. It is intentionally descriptive rather than aspirational.

It should answer:

> What can Causcope actually do now, and what is still only architecture or planned work?

## Summary

Causcope is no longer only a troubleshooting ontology or a collection of empirical labs.

The repository already contains a deterministic investigation substrate with:

```text
semantic knowledge
runtime evidence
causal ranking
next-probe ranking
safe read-only execution
provider capability discovery
instrument routing
MCP and HTTP projections
persistent investigation/scoping state
bounded autonomous investigation
Concrete System / X-Ray projections
Rails and PostgreSQL evidence providers
```

The strongest current product proof is the Rails D3.1 golden vertical slice.

## Proven product slice

`RFC/0075-golden-vertical-slice-rails-connection-pool.md` is an implemented proof.

The live CI path demonstrates:

```text
user-visible slow request
  -> revision-bound Rails scan
  -> exact Rails code symbol
  -> exact ActiveRecord pool
  -> real pool saturation
  -> measured checkout wait
  -> OpenTelemetry request identity
  -> independent PostgreSQL capacity control
  -> generic D3.1 X-Ray progression
  -> recovery evidence
  -> CAUSAL_DIAGNOSIS_CONFIRMED
  -> product-shaped human diagnosis
```

The bounded proof explicitly keeps blast radius unknown because it has no evidence source establishing affected-user/request counts.

That behavior is intentional and product-defining: unknown evidence remains unknown rather than being guessed.

## Product front door

The repository now exposes:

```text
causcope why "checkout is slow"
```

as an initial thin product front door.

Current behavior:

### No diagnostic evidence yet

`causcope why` creates or resumes the same local investigation/scoping state used by the existing Investigator and presents the next unresolved scoping question.

It does not invent a root cause from the problem statement.

### Canonical Rails D3.1 artifacts available

The same command can consume:

```text
Concrete System Facts
Concrete Runtime Facts
Resource-pool Runtime Evidence
```

and delegate to the already-proven Rails D3.1 product projection.

The command does not implement another causal-ranking algorithm.

Current technical bridge:

```text
causcope why
  -> causcope_cli investigation/scoping contracts
  OR
  -> rails_pool_vertical_slice
       -> generic X-Ray engine
```

This is an intentionally narrow first product bridge. Automatic evidence acquisition from a plain problem statement remains future work.

## Roadmap mapping

### Semantic core

State: **implemented and actively expanding**

Includes:

- symptom/mechanism catalog;
- canonical semantic IDs;
- predictions and falsifiers;
- claims and empirical experiments;
- causal graph;
- diagnostic catalog codes;
- runtime evidence contracts;
- deterministic causal ranking.

This area is mature enough to support product proofs but not complete across all failure domains.

### Local Investigator

State: **implemented for scoping, partially productized for diagnosis**

Implemented:

```text
causcope investigate
causcope next
causcope answer
causcope status
causcope report
causcope why
```

Scoping is durable under `.causcope/`.

The diagnosis front door currently has a proven D3.1 path but is not yet a generic automatic bridge from every symptom to evidence acquisition.

### Agent integration

State: **substantial machinery implemented**

Existing repository work includes:

- MCP resources and tools;
- agent-plan projections;
- next-probe selection;
- safe read-only probe execution;
- bounded autonomous investigation;
- workflow recovery/journaling;
- provider capability discovery;
- instrument routing.

The remaining work is product consolidation and ergonomic use of this machinery, not inventing agent support from scratch.

### Real local evidence providers

State: **implemented for several bounded paths**

Existing providers/adapters include:

- Prometheus;
- OpenTelemetry;
- pgbot/PostgreSQL;
- Rails repository/runtime evidence;
- structured logs;
- selected local probe executors.

Provider breadth is not the immediate goal. Complete product-shaped investigations are preferred over adding more adapters without a demonstrated use case.

### Dashboard

State: **not implemented as the shared product surface described in `docs/`**

The dashboard remains the next major human/team surface after the agent/local investigation loop is sufficiently coherent.

It must project canonical investigation state rather than introduce another diagnosis model.

### Managed Cloud

State: **architecture documented, implementation intentionally deferred**

Logical responsibilities are described in:

```text
docs/architecture/cloud-component-model.md
docs/architecture/deployment-model.md
```

There is no requirement for the current local product to depend on Causcope Cloud.

### Managed SaaS integrations

State: **planned product architecture**

Priority set currently includes:

```text
GitHub App
PagerDuty
Sentry
Slack
Generic Webhook API

then:
Datadog
Teams
Telegram
```

These are delivery, signal, evidence, and communication adapters around the same investigation core.

### Relay / enterprise deployment

State: **architecture documented, not yet productized**

Target forms include:

```text
same Causcope runtime in daemon/Relay role
Docker image
systemd
Helm chart
private/on-prem deployment later
```

The intended security model is capability-based, read-only first, customer-controlled credentials, outbound connectivity where possible, and no arbitrary remote shell.

### Trust Manifest / Trust Diff

State: **directional architecture, not yet canonical schema**

The model is documented under:

```text
docs/architecture/trust-access-blast-radius.md
```

It should become machine-readable only through a focused RFC/schema slice, not by treating the current prose example as a stable standard.

### Investigation vs Incident identity

State: **compatibility design proposed**

`RFC/0076-investigation-case-and-incident-compatibility.md` proposes `Investigation` as the Causcope-owned case object while preserving existing `incident_context`/`incident_id` data during migration.

No breaking storage rename has been authorized yet.

### RFC identity governance

State: **validator implemented, historical cleanup deferred**

`RFC/0077-rfc-identity-governance.md` defines the direction.

The repository now contains:

```text
vocabulary/rfc-id-exceptions.yaml
scripts/validate_rfc_ids.py
```

and CI prevents new unregistered numeric collisions while grandfathering the known historical pairs.

## Immediate product gap

The largest remaining gap is no longer the causal proof itself.

It is the bridge:

```text
plain user problem
  -> investigation state
  -> capability discovery
  -> evidence acquisition
  -> generic diagnosis projection
```

without requiring the user to manually identify or pass subsystem-specific artifact files.

The existing repository contains most of the pieces for that path. The next work should compose those pieces rather than add another generic reasoning layer.

## Current priority

Near-term work should therefore favor:

```text
1. consolidate `causcope why` around canonical investigation state;
2. bridge `why` to existing provider/capability routing;
3. make the D3.1 live proof reachable through that same front door;
4. generalize only after the product path is clean;
5. keep Dashboard/Cloud architecture compatible but secondary.
```

## Guardrail

A new abstraction should be treated skeptically unless it is required to move this path forward:

```text
problem
  -> scope
  -> evidence
  -> discriminate
  -> diagnose
  -> verify
```

Causcope currently needs integration and product consolidation more than additional conceptual layers.

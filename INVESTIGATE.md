# Causcope Investigator

Causcope Investigator is the first end-user interface over the incident-context, scoping, and investigation-session contracts.

It is intentionally deterministic and LLM-independent. The CLI does not guess root causes from a problem statement. It records what is known, identifies unresolved investigation dimensions, and recommends the next scoping question from the canonical Causcope model.

## Start an investigation

```bash
./bin/causcope investigate "Checkout sometimes fails"
```

Causcope creates local state under `.causcope/`:

```text
.causcope/
  incident-context.yaml
  investigation-session.yaml
  scoping-projection.json
```

The first question comes from the canonical investigation-dimension registry. A new incident begins with all ten dimensions unresolved, so the default first question is blast radius:

```text
Who is affected and how broadly?
```

Interactive answers use dimension-specific `key=value` fields. For example:

```text
unit=users affected=8 total=120
```

The CLI records the answer in the canonical incident context, appends question and answer events to the investigation session, recomputes scoping state, and moves to the next unresolved dimension.

Use `/status` to show current progress or `/quit` to leave the session without losing state.

## Non-interactive workflow

The same state machine can be driven by scripts, agents, MCP tools, or a future SaaS UI.

Create the incident without prompting:

```bash
./bin/causcope investigate \
  "Checkout sometimes fails" \
  --non-interactive
```

Inspect the next question:

```bash
./bin/causcope next
```

Record structured answers:

```bash
./bin/causcope answer blast_radius \
  unit=users affected=8 total=120

./bin/causcope answer where \
  environment=production region=eu-central

./bin/causcope answer when \
  onset_at=2026-09-14T00:15:00Z pattern=intermittent

./bin/causcope answer flow \
  feature=checkout "operation=POST /checkout"

./bin/causcope answer client \
  type=mobile os=iOS app_version=7.42.0

./bin/causcope answer change \
  type=deploy timing=near_onset \
  "description=checkout release 2026.09.14.1"

./bin/causcope answer dependency \
  name=stripe relationship=external

./bin/causcope answer data \
  tenant=acme record_type=payment role=customer

./bin/causcope answer reproducibility \
  status=sometimes "conditions=production,EU,iOS 7.42"

./bin/causcope answer impact \
  severity=high "user_effect=checkout cannot complete"
```

For dimensions where the absence of a value is itself known, use explicit none where supported:

```bash
./bin/causcope answer change none=true
./bin/causcope answer dependency none=true
./bin/causcope answer data none=true
```

## See investigation state

```bash
./bin/causcope status
```

Machine-readable projection:

```bash
./bin/causcope status --json
```

The output keeps these concepts separate:

```text
blast radius != severity
context != evidence
correlation != causality
difference != cause
scoping completeness != diagnosis confidence
```

A recent deploy can be recorded as context without being promoted to a cause. Client or region differences can be recorded as discriminators without being promoted to causal evidence.

## Produce a report

```bash
./bin/causcope report
```

Or save Markdown:

```bash
./bin/causcope report --output incident-report.md
```

The report summarizes current scope, impact, known and unknown investigation dimensions, recent changes, recorded answers, and the next recommended scoping action.

## Why this exists

This CLI is not intended to become a separate reasoning implementation. It is a thin end-user adapter over the same contracts that can later power:

```text
CLI
MCP
HTTP API
SaaS
agent harness
```

The local `.causcope/` directory is deliberately portable. Future adapters should read and update the same incident context and investigation session rather than inventing another incident state model.

## Current boundary

This first slice covers incident scoping. Once scoping is sufficiently useful, the next integration point is the existing Causcope runtime-evidence and causal-diagnosis pipeline:

```text
problem statement
  -> incident context
  -> scoping projection
  -> failing vs working comparison
  -> runtime evidence
  -> causal ranking
  -> recommended probe
  -> verification
```

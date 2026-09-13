# RFC 0031: Investigator CLI

Status: Accepted

## Summary

Causcope now has a machine-readable incident-context contract, ten canonical investigation dimensions, a deterministic scoping projection, an investigation-session contract, runtime evidence, causal ranking, probe ranking, and MCP/HTTP projections.

The missing piece for immediate human use is a thin end-user interface that can start with a vague problem statement and drive the existing scoping model without requiring a custom application or an LLM.

This RFC introduces the first stateful Causcope CLI:

```text
causcope investigate
causcope next
causcope answer
causcope status
causcope report
```

## Goals

The CLI must:

1. make the existing investigation model useful from a terminal today;
2. preserve one canonical incident state instead of inventing CLI-only semantics;
3. remain deterministic and LLM-independent;
4. expose the same state that future MCP, HTTP, SaaS, and agent-harness adapters can consume;
5. keep context, evidence, and causal conclusions separate.

## Local investigation workspace

The default workspace is `.causcope/`:

```text
.causcope/
  incident-context.yaml
  investigation-session.yaml
  scoping-projection.json
```

`incident-context.yaml` is the canonical current scoping state.

`investigation-session.yaml` is the chronological audit trail of questions and answers.

`scoping-projection.json` is derived state and can always be rebuilt from the incident context.

The workspace is ignored by Git by default because it may contain incident-specific operational information.

## Start semantics

A new investigation begins from the weakest valid incident context:

```yaml
scope: {}
time:
  pattern: unknown
impact:
  severity: unknown
reproduction:
  status: unknown
unknowns:
  - who
  - where
  - when
  - what
  - client
  - change
  - dependency
  - data
  - reproduction
  - impact
```

The initial problem statement is not evidence and does not generate hypotheses.

The existing scoping projection decides the next unresolved dimension. No independent CLI prioritization algorithm is introduced.

## Answers

Answers are intentionally structured as dimension-specific `key=value` fields.

Examples:

```text
blast_radius: unit=users affected=8 total=120
where: environment=production region=eu-central
client: type=mobile os=iOS app_version=7.42.0
```

This is less conversational than free text, but it has two important properties:

- answers can update the canonical incident-context schema without an LLM parser;
- the exact same operation can later be exposed through MCP or HTTP tools.

A human-facing SaaS or agent may provide a natural-language layer later, but that layer should compile user input into this structured state rather than replacing it.

## Session semantics

Every recorded answer produces two session events:

```text
question(status=answered)
answer(source=human)
```

The session `context_revision` increments after every successful context update.

The CLI validates the resulting incident context by rebuilding the existing scoping projection before persisting a mutation. Invalid state is rejected rather than written partially.

## Explicit absence

Some investigation dimensions need to distinguish unknown from explicitly absent.

The first CLI slice supports:

```text
change none=true
dependency none=true
data none=true
```

These map to the existing schema representation where an explicit empty collection means the absence was investigated rather than omitted.

## Report

`causcope report` is a human projection over current state. It may summarize:

- impact;
- scope;
- dimension completeness;
- recent changes;
- recorded answers;
- the next recommended scoping action.

It must preserve the invariant that recent changes are correlation candidates, not causal proof.

## Non-goals

This slice does not:

- interpret arbitrary natural language into structured incident context;
- collect telemetry automatically;
- generate causal hypotheses directly from the initial summary;
- execute probes;
- persist investigation state remotely;
- provide authentication, organizations, or SaaS collaboration.

Those capabilities belong above or after the investigation core.

## Product architecture

The CLI establishes a useful adapter boundary:

```text
                    Causcope Core
                         |
        incident context + investigation session
                         |
                  scoping projection
                         |
        +----------------+----------------+
        |                |                |
       CLI              MCP             HTTP
                                           |
                                          SaaS
```

The product value comes from keeping these adapters projections over the same investigation state, not from implementing separate debugging logic in every surface.

## Next integration

After an incident is scoped, Causcope should bridge the investigation workspace into the existing runtime-evidence and diagnosis path:

```text
incident context
  -> scoped evidence collection
  -> causal ranking
  -> discriminating probe
  -> evidence update
  -> verification against original scope
```

That bridge is intentionally outside this RFC so the first end-user slice can remain small, deterministic, and immediately dogfoodable.

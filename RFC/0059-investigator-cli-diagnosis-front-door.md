# RFC 0059: Investigator CLI diagnosis front door

- Status: Proposed
- Date: 2026-09-15

## Summary

Causcope already has most of the semantic and execution machinery needed for a useful end-user investigation workflow:

```text
incident context
  -> scoping projection
  -> runtime evidence
  -> causal ranking
  -> next-probe ranking
  -> instrument routing
  -> safe read-only execution
  -> new evidence
  -> re-ranking
  -> verification
```

What is still missing is a compact product-facing projection over those layers.

The current Investigator CLI is strongest at incident scoping. It exposes `investigate`, `next`, `answer`, `status`, and `report`, but it does not yet provide a simple front door for the later diagnostic loop.

This RFC proposes an Investigator CLI v2 that keeps the existing deterministic semantic contracts intact while exposing a small problem-oriented command surface:

```text
causcope why
causcope evidence
causcope hypotheses
causcope next
```

The CLI must remain a projection over existing Causcope state and reasoning. It MUST NOT become a second diagnosis engine.

## Product boundary

The user should not need to know which low-level diagnostic tool or subsystem command to invoke.

A user typically begins with a problem such as:

```text
checkout is slow
requests fail only for some iOS clients
after the deploy the API became slower
```

They do not begin with:

```text
inspect PostgreSQL lock waits
query pg_stat_statements
check TCP retransmissions
run a specific profiler
```

Causcope should therefore expose the investigation question at the same abstraction level as the user-visible problem.

The intended split is:

```text
specialized tools and adapters
  -> answer narrow deterministic questions inside one subsystem

Causcope
  -> decides which question matters next across subsystem boundaries
```

A specialized analyzer such as pgbot remains a PostgreSQL instrument. Causcope remains responsible for incident scope, evidence composition, competing hypotheses, causal reasoning, next-probe selection, instrument routing, stop conditions, and verification.

## Goals

The CLI v2 should:

1. provide one obvious entry point from a user-visible symptom;
2. hide subsystem-specific command selection behind semantic probe ranking and instrument routing;
3. expose current evidence, hypotheses, contradictions, unknowns, and next diagnostic action in human-readable form;
4. preserve the existing machine-readable contracts for agents, MCP, HTTP, and tests;
5. keep uncertainty explicit and avoid fabricated numeric confidence;
6. make investigation state persistent and resumable through the existing `.causcope/` workspace;
7. keep differences, changes, and correlations separate from causal proof;
8. allow external analyzers such as pgbot to remain deep domain instruments instead of being reimplemented inside Causcope.

## Non-goals

This RFC does not:

- introduce another causal-ranking algorithm;
- add a global probability model;
- replace the existing incident-context or investigation-session contracts;
- reimplement pgbot or other specialized diagnostic tools;
- make arbitrary shell commands executable;
- authorize state-changing remediation;
- collapse RunDiff-style semantic comparison into the Causcope causal engine;
- let an LLM invent measurements, observations, or causal facts.

## Command surface

The preferred human-facing surface is deliberately small.

### `causcope why`

`why` is the primary diagnosis front door.

Examples:

```bash
causcope why
causcope why "checkout is slow"
```

When a problem statement is supplied and no investigation exists, the CLI may initialize the same incident context and investigation session currently created by `causcope investigate`.

When an investigation already exists, `why` consumes the current scoped incident state and available runtime evidence.

The command should project:

```text
problem / target
current leading hypotheses
supporting evidence
contradicting evidence
important unknowns
causal path where one is supported
recommended next probe
selected instrument when executable
explicit stop reason when no safe next action exists
```

Example shape:

```text
$ causcope why

Target
  checkout request latency

Leading explanation
  hypothesis.database.query_regression

Causal path
  query-shape change
    -> sequential-scan pressure
    -> database query latency
    -> checkout latency

Supported by
  + sequential-scan pressure observed
  + database query latency observed
  + dependency latency observed in the same checkout/PostgreSQL scope

Contradicted by
  - no active contradiction currently known

Unknown
  ? previous query plan is unavailable

Next diagnostic probe
  inspect the current query plan

Instrument
  provider.pgbot.postgresql
```

The exact wording is a projection concern. The semantic facts must come from canonical runtime evidence, causal ranking, probe ranking, and instrument routing.

### `causcope evidence`

This command presents the currently active evidence for the investigation scope.

It should separate at least:

```text
observed
absent
insufficient / unavailable / stale when supported by the evidence-quality model
context-only facts
```

Evidence should retain source and scope provenance.

Example:

```text
$ causcope evidence

OBSERVED
  database.query_latency
    source: pgbot
    scope: checkout-api -> postgresql

  dependency.latency
    source: opentelemetry
    scope: checkout-api -> postgresql

ABSENT
  host.cpu_saturation
    source: host probe

CONTEXT ONLY
  deploy 8f12c9 occurred near onset
```

A nearby deploy MUST NOT move from context to causal evidence merely because the CLI displays it next to runtime observations.

### `causcope hypotheses`

This command exposes the complete current candidate ordering and the visible reasons for that ordering.

Causcope currently uses deterministic ordinal ranking rather than pretending to know a universal numeric probability.

The CLI should therefore prefer output such as:

```text
$ causcope hypotheses

1. hypothesis.database.query_regression
   supported by:
     + query latency
     + sequential-scan pressure
   contradicted by:
     none
   unresolved:
     query-plan change

2. hypothesis.database.lock_contention
   supported by:
     none
   contradicted by:
     - lock-wait evidence absent

3. hypothesis.external_dependency_latency
   supported by:
     + downstream span latency
   unresolved:
     provider-side evidence unavailable
```

The CLI MUST NOT turn ordinal rank into values such as `0.87`, `87%`, or other pseudo-probabilities unless a future separately justified statistical model defines their semantics.

### `causcope next`

The current Investigator already uses `next` for the next unresolved scoping question.

CLI v2 should preserve that behavior before diagnosis has enough context, then naturally progress to the next diagnostic probe once the investigation crosses the scoping boundary.

Conceptually:

```text
if a material investigation dimension remains unresolved:
    next -> next scoping question
else if competing hypotheses remain and a discriminating probe exists:
    next -> recommended probe + executable route
else:
    next -> explicit stop reason / verification step
```

The user should not need to know whether the internal source of the recommendation was `scoping_projection`, `probe_ranking`, `agent_plan`, or `instrument_router`.

Machine-readable output may expose that provenance.

## Existing commands remain valid

The current commands remain useful:

```text
causcope investigate
causcope answer
causcope status
causcope report
```

They are not replaced by this RFC.

Instead, the CLI becomes two compatible views over one investigation state:

```text
structured / explicit workflow
  investigate -> answer -> status -> report

problem-oriented workflow
  why -> evidence -> hypotheses -> next
```

Both MUST use the same `.causcope/` state and canonical projections.

## Investigation state

The existing workspace remains the local durable boundary:

```text
.causcope/
  incident-context.yaml
  investigation-session.yaml
  scoping-projection.json
  ...derived diagnosis projections as needed
```

The CLI MUST NOT create an independent hidden state model for `why`, `evidence`, or `hypotheses`.

A future SaaS UI, MCP consumer, IDE, or agent harness should be able to inspect or reproduce the same investigation from the same underlying contracts.

## Relationship to specialized diagnostic tools

Causcope should integrate with deep domain tools rather than compete with them feature-by-feature.

The architecture is:

```text
pgbot ------------------\
OpenTelemetry -----------\
Prometheus ---------------> normalized runtime evidence
host probes -------------/             |
other future providers --/             v
                                 causal reasoning
                                        |
                                 next semantic probe
                                        |
                                 instrument router
```

The user-facing command remains:

```bash
causcope why
```

The user should not need to decide whether the next useful fact comes from pgbot, OpenTelemetry, Prometheus, a host executor, Kubernetes, a language runtime, or another provider.

This is convenience through abstraction, not merely a prettier terminal UI.

## Relationship to RunDiff-style comparison

Causcope already treats failing-vs-working comparison as an important investigation primitive.

The boundary remains:

```text
semantic comparison / RunDiff-style analysis
  -> what differs between A and B?

Causcope causal reasoning
  -> which difference is relevant to the observed outcome, and what evidence would test that claim?
```

Therefore:

```text
difference != cause
```

A comparison engine may contribute structured differences such as:

```text
deploy changed
feature flag changed
query fingerprint appeared
latency changed
resource pressure changed
```

Causcope may use those differences as context or, when they become properly sourced and scoped observations, as runtime evidence.

Causcope SHOULD NOT assign causal authority to a difference merely because it is unique to the failing case.

A future integration can make RunDiff-style semantic deltas a first-class input without merging the two product responsibilities.

## `what changed?` as an investigation question

The question "what changed near onset?" already exists in the incident-scoping model.

The CLI may eventually expose an ergonomic projection such as:

```bash
causcope changes
```

or consume a RunDiff-style provider automatically.

However, this RFC does not require a new first-class `what-changed` engine inside Causcope.

The distinction is:

```text
change discovery
  -> context / candidate differences

causal diagnosis
  -> evidence-backed explanation
```

## Hypothesis falsification

Falsification is already a first-class semantic requirement in Causcope and should become visible in the CLI.

The first implementation does not need a literal `causcope falsify H1` command, but `hypotheses` and `next` should make the same reasoning visible:

```text
Hypothesis
  database lock contention

Would be weakened by
  lock-wait inspection successfully observing no relevant waits

Best next discriminator
  probe.database.inspect_lock_waits
```

A later UX extension may add:

```bash
causcope test <hypothesis-id>
causcope falsify <hypothesis-id>
```

if those commands can be implemented as thin projections over existing hypothesis, probe-ranking, and routing contracts.

They MUST NOT introduce a separate reasoning path.

## Evidence and confidence presentation

Causcope should expose uncertainty, but it should not manufacture precision.

Preferred representation:

```text
SUPPORTED BY
CONTRADICTED BY
UNKNOWN
INSUFFICIENT EVIDENCE
NEXT DISCRIMINATING PROBE
```

Not:

```text
confidence: 0.87
```

unless a future confidence model explicitly defines what that number means and how it is calibrated.

Source confidence, measurement quality, sampling state, freshness, and caveats may still be displayed as source metadata where their contracts define them.

They MUST NOT be silently converted into root-cause probability.

## Human and machine output

Each new command should support a human-readable default projection and a stable machine-readable representation.

Preferred pattern:

```bash
causcope why
causcope why --json

causcope evidence
causcope evidence --json

causcope hypotheses
causcope hypotheses --json

causcope next
causcope next --json
```

The JSON form should reuse existing projection contracts where practical rather than introducing one large CLI-specific schema.

A CLI envelope may identify the selected projection, but causal ranking, evidence, probe ranking, and routing semantics should remain owned by their existing schemas.

## Determinism and LLM boundary

The core front-door workflow must remain usable without an LLM.

Deterministic responsibilities include:

```text
state loading
scope resolution
evidence resolution
causal ranking
probe ranking
instrument capability filtering
routing
stop policy
```

An LLM may later improve natural-language explanation, summarize a large evidence set, translate a free-form user report into proposed incident context, or suggest unknown hypotheses.

Any model-generated material must remain distinguishable from measured evidence and deterministic ranking.

The CLI MUST NOT require an LLM to answer a case already covered by canonical Causcope knowledge and deterministic instruments.

## Safety

The front door does not weaken existing execution policy.

`why` and `next` may route and execute only capabilities already authorized by the existing safe execution layers.

The initial product path should remain read-only by default.

State-changing mitigations remain outside the autonomous investigation loop unless separately modeled with explicit risk, approval, and reversibility contracts.

## Example end-to-end flow

```text
$ causcope why "checkout sometimes fails"

Investigation created.
Need more scope before diagnosis.
Next question: Who is affected and how broadly?

$ causcope answer blast_radius unit=requests affected=184 total=2510
$ causcope answer where environment=production region=eu-central
$ causcope answer flow feature=checkout "operation=POST /checkout"
$ causcope answer dependency name=postgresql relationship=downstream

$ causcope next

Recommended diagnostic probe:
  Inspect database lock waits

Selected instrument:
  provider.pgbot.postgresql

Risk:
  read_only

$ causcope why

Leading explanation:
  hypothesis.database.lock_contention

Supported by:
  + database lock-wait time observed
  + checkout request failure observed in the same scope

Alternative:
  hypothesis.client.payload_contract_mismatch

Next discriminator:
  inspect matching request payload / lock-error correlation
```

The important property is that the user remains at the investigation level while Causcope chooses and composes lower-level instruments.

## Implementation strategy

Implement this RFC incrementally.

### Slice 1: Read-only projections

Add human and JSON commands that only consume existing state:

```text
causcope evidence
causcope hypotheses
```

No new reasoning semantics.

### Slice 2: `causcope why`

Compose existing incident, diagnosis, causal-ranking, and next-probe projections into one human-facing answer.

The implementation should expose an explicit stop when diagnosis is not yet possible because scoping or evidence is insufficient.

### Slice 3: Unified `causcope next`

Bridge the current scoping `next` behavior to the existing next-probe / agent-plan path without changing either underlying ranking system.

### Slice 4: Instrument-aware execution

When existing policy allows it, show the routed instrument and optionally execute the same safe read-only action already available through the autonomous investigation loop.

### Slice 5: Comparison-provider integration

Accept structured RunDiff-style or other semantic comparison output as context/evidence input without treating differences as causes.

## Acceptance criteria

This RFC is implemented when a user can start from a symptom and complete a deterministic read-only investigation without needing to know subsystem-specific commands.

At minimum, an end-to-end test should demonstrate:

```text
problem statement
  -> persisted incident context
  -> scoped runtime evidence
  -> at least two competing hypotheses
  -> visible evidence and contradiction explanation
  -> recommended discriminating probe
  -> routed external or built-in instrument
  -> new evidence
  -> changed causal ranking
  -> human-readable `causcope why` output
```

The test should prove that:

- pgbot or another external provider remains an evidence instrument rather than the diagnosis authority;
- the CLI reuses existing semantic projections;
- no numeric root-cause probability is invented;
- unavailable evidence stays unavailable rather than becoming absent;
- a nearby change or failing-vs-working difference is not automatically promoted to cause;
- the investigation can be resumed from the persisted workspace.

## Consequences

Causcope's core architecture is already broader than a subsystem-specific diagnostic CLI. This RFC makes that architecture legible to an end user.

The intended product model becomes:

```text
specialized instruments
  -> deep subsystem facts

RunDiff-style comparison
  -> meaningful differences

Causcope
  -> investigation
  -> cross-domain causal reasoning
  -> next discriminating question
  -> verification
```

The resulting CLI is not `pgbot++`.

It is a debugging front door over a set of specialized instruments and a shared causal reasoning model.

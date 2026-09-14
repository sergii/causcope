# RFC 0035: Autonomous read-only investigation loop

- Status: Accepted
- Date: 2026-09-14

## Summary

Causcope can already rank causal hypotheses, recommend a discriminating next probe, expose whether a built-in probe can run, and let an MCP client begin and finish a safe probe session explicitly.

This RFC adds a bounded orchestration layer that can execute eligible read-only recommendations automatically, append the resulting standard `runtime_evidence`, recompute diagnosis, and continue until it cannot make further justified progress.

The loop is:

```text
passive evidence
  -> causal ranking
  -> ranked discriminating probes
  -> highest-ranked eligible read-only probe
  -> probe evidence
  -> compose runtime evidence
  -> recompute causal ranking
  -> next eligible probe
  -> stop
```

The orchestration layer does not add a second diagnosis engine. It repeatedly invokes the existing evidence, causal-ranking, probe-ranking, and diagnosis contracts.

## Motivation

The Shop integration testbed established this working path:

```text
running application
  -> read-only telemetry
  -> canonical runtime evidence
  -> Causcope diagnosis
  -> recommended next probe
```

The missing transition was from recommendation back into evidence without requiring a human or agent to manually coordinate every safe read-only step.

That transition matters because a useful diagnostic system should be able to reduce uncertainty itself when all of the following are true:

- the next action is already selected deterministically by Causcope;
- the action is explicitly classified `risk: read_only`;
- a narrowly trusted executor or adapter is registered for it;
- the result can be represented as ordinary scoped runtime evidence;
- execution is bounded and auditable.

## Decision

Add `scripts/autonomous_investigation.py` as a generic bounded orchestrator.

The orchestrator accepts:

- the current runtime evidence bundle;
- the current diagnosis snapshot;
- canonical concepts and causal edges;
- a static set of supported probe IDs;
- a probe execution callback;
- a maximum step count.

It then:

1. reads the current deterministic probe ranking;
2. chooses the highest-ranked probe that is both statically supported and canonically `risk: read_only`;
3. executes that probe against the exact diagnosis target and scope;
4. validates that returned evidence matches the canonical probe contract;
5. composes the new evidence with the existing incident evidence;
6. increments the evidence revision;
7. rebuilds diagnosis using the existing live diagnosis engine;
8. repeats while progress remains possible and the step bound has not been reached.

## Safety boundary

Autonomous execution is deliberately narrower than generic tool execution.

A probe is eligible only when all of these are true:

```text
probe is present in deterministic probe ranking
AND probe id is in a static adapter/executor allowlist
AND canonical probe risk == read_only
AND executor returns canonical runtime_evidence
AND every emitted observation is declared in probe.produces
AND evidence provenance identifies the probe
AND evidence scope exactly matches the selected diagnosis scope
```

The first implementation does not provide:

- arbitrary subprocess execution;
- dynamic Python plugin loading;
- shell commands selected by a model;
- write-capable probes;
- remediation;
- configuration changes;
- deployment rollback;
- database mutation;
- unbounded loops.

`max_steps` is required to be between 1 and 16. The Shop CLI defaults to four steps.

## Ranked probe fallback

A ranked probe may be safe to execute but still lack enough source data to produce an honest `observed` or `absent` result.

For example, `probe.http.compare_client_cohorts` cannot compare cohorts when the captured window contains only one cohort.

This condition is represented as `ProbeInsufficientEvidence`. The orchestrator records the attempted step as:

```text
status = insufficient_evidence
```

and tries the next ranked eligible read-only probe.

It MUST NOT convert insufficient evidence into an `absent` observation.

```text
not measured != absent
not enough comparison data != normal
probe unavailable != hypothesis falsified
```

## Exact scope binding

Autonomous probe evidence MUST be bound to the same normalized semantic scope as the diagnosis that requested the probe.

This preserves the existing Causcope partition invariant. Evidence about one client cohort, host, region, tenant, or request path must not silently influence a different partition.

A provider that cannot justify the selected scope should return insufficient evidence rather than widen or narrow scope heuristically.

For example, the Shop lock-error probe does not treat an uncorrelated `database is locked` message as evidence for an arbitrary failing request. The testbed carries request metadata into the SQLite operational-error log so the probe can correlate:

```text
request_id
method
path
client_platform
app_version
```

before emitting evidence into that request scope.

## First implementation: Causcope Shop

The first autonomous provider is a static Shop structured-log adapter. It supports:

```text
probe.http.compare_client_cohorts
probe.database.inspect_lock_error_events
```

The adapter operates only on application log events already captured read-only by the Shop bridge.

### Client cohort probe

The probe compares failure rates for the same HTTP method and path across client platform/version cohorts and emits:

```text
observation.http.client_cohort_failure_skew
```

into the selected failing request scope while preserving the working and failing cohort identities in labels. The observation remains a discriminator, not causal proof.

### Database lock-error probe

The probe searches the captured diagnostic stream for explicit lock errors correlated to the selected request metadata and emits:

```text
observation.database.lock_error_event
```

This observation is a strong prediction of `hypothesis.database.lock_contention` when the application surfaces lock acquisition failure or timeout.

An absent result means only that matching requests existed in the captured application-log window but no correlated lock error was present. It decreases the hypothesis; it does not prove all lock contention impossible.

## Passive evidence before active probes

The structured-log adapter historically produced both direct request outcomes and higher-order derived findings in one pass. That behavior remains the default for backward compatibility.

Autonomous mode instead starts with passive direct evidence only:

```text
HTTP request outcome
  -> observation.http.request_failure observed/absent
```

It intentionally withholds higher-order cohort and lock findings until Causcope chooses the corresponding probe.

This makes the feedback loop real rather than simulated:

```text
symptom evidence
  -> competing hypotheses
  -> discriminating probe
  -> new evidence
  -> changed ranking
```

## Audit trail

Shop autonomous mode preserves both the initial and final states:

```text
initial-runtime-evidence.json
initial-diagnosis.json
autonomous-run.json
runtime-evidence.json
diagnosis.json
diagnosis-summary.json
source-shop-app.log
```

`autonomous-run.json` is validated by `schema/autonomous-investigation-run.schema.json` and records for every attempted step:

- step index;
- status (`completed` or `insufficient_evidence`);
- target observation;
- exact scope;
- probe ID and ranking position;
- top hypothesis before and after;
- next probe after recomputation;
- evidence instance IDs;
- evidence revision;
- insufficient-evidence reason when applicable.

This lets a human or agent answer both "what does Causcope think?" and "what did it inspect to change its mind?"

## Relationship to MCP probe sessions

This RFC does not replace the existing MCP begin/finish workflow.

```text
MCP session probe
  baseline -> external controlled workload -> comparison -> evidence

autonomous one-shot probe
  read-only query/inspection -> evidence -> immediate re-rank
```

Long-running, baseline/comparison, or externally coordinated probes should continue to use the session lifecycle, filesystem claims, reconciliation, and retry semantics already defined by RFCs 0016-0029.

The autonomous loop is appropriate only when the registered provider can produce a complete read-only result in one bounded invocation.

## Relationship to external diagnostic adapters

RFC 0033 defines specialized deterministic analyzers as instruments that feed Causcope evidence, and RFC 0034 adds the first pgbot adapter PoC.

Those adapters can become autonomous probe providers when they expose a narrow read-only operation with trustworthy scope and deterministic output:

```text
Causcope next PostgreSQL probe
  -> pgbot deterministic read-only operation
  -> mapped runtime evidence
  -> Causcope re-rank
  -> cross-domain next probe
```

The same safety rules apply. External source identity never grants privileged causal weight.

## Stop conditions

The loop stops when one of these occurs:

- no ranked eligible provider remains;
- all currently eligible recommendations were already attempted;
- a completed probe adds no new evidence;
- the configured maximum step count is reached.

An individual insufficient-evidence result is recorded but does not by itself terminate the loop if another ranked eligible probe remains.

## Validation

`scripts/test_autonomous_investigation.py` proves two deterministic convergence cases:

```text
mobile request failures
  -> compare client cohorts
  -> cohort skew observed
  -> lock error absent
  -> client payload contract mismatch ranks first
```

and:

```text
single-cohort 503
  -> cohort comparison insufficient
  -> correlated lock error observed
  -> database lock contention ranks first
```

The Shop GitHub Actions workflow runs the same autonomous path against the real FastAPI + SQLite reference application for both fault scenarios. The CI assertion reads final Causcope evidence and diagnosis and never reads `oracle.json` to construct the diagnosis.

## Consequences

Causcope now has a complete bounded diagnostic feedback loop:

```text
runtime symptom
  -> evidence
  -> competing causes
  -> discriminating probe
  -> safe read-only execution
  -> new evidence
  -> re-ranking
  -> next probe or stop
```

The remaining gap to a broader autonomous SRE agent is no longer the reasoning loop itself. It is expansion of trustworthy domain-specific read-only probe providers, plus policy for which environments are allowed to auto-execute them.

## Next work

1. Promote suitable pgbot PoC operations into scoped autonomous read-only probe providers.
2. Expose eligible autonomous steps through MCP/HTTP without weakening the existing explicit probe-session safety path.
3. Add provider capability metadata so a provider can declare deterministic source requirements before execution.
4. Add execution policy by environment so production can require stricter opt-in than testbed/local runs.
5. Add verification-loop semantics after a fix so Causcope can compare the post-fix system against the original incident scope without performing remediation itself.

# RFC 0033: External deterministic diagnostic adapters

- Status: Proposed
- Date: 2026-09-14

## Summary

Causcope should be able to consume specialized diagnostic engines as external evidence providers without delegating cross-domain diagnosis to them.

The core boundary is:

```text
raw domain signals
  -> deterministic domain analysis
  -> typed findings + provenance + caveats
  -> Causcope runtime evidence
  -> cross-domain causal reasoning
  -> next probe
  -> cause / contributing factors
  -> verification
```

A specialized analyzer may understand one subsystem deeply. Causcope remains responsible for composing evidence across subsystems, maintaining the causal graph, comparing competing hypotheses, deciding what evidence is still missing, and selecting the next discriminating probe.

This is a different extension point from the built-in probe executor registry in RFC 0018. Probe executors perform one canonical Causcope probe. External diagnostic adapters ingest the output of an existing diagnostic system that may already compute many observations and findings of its own.

## Motivation

Causcope should not reimplement every mature domain-specific diagnostic engine.

A PostgreSQL analyzer may already understand locks, transactions, WAL, vacuum, indexes, query statistics, replication, counter resets, and database-specific caveats better than a generic debugging engine should. The same pattern can later apply to Linux, Kubernetes, queues, cloud providers, language runtimes, tracing systems, and other domains.

The reusable product value is not owning every collector. It is owning the diagnostic semantics that connect domains:

```text
user-visible symptom
  <- application mechanism
  <- dependency mechanism
  <- database / network / runtime antecedent
```

Therefore Causcope should prefer integration over duplication when an external tool can provide trustworthy, machine-readable, read-only diagnostic evidence.

## Design principles

### 1. Deterministic findings before model reasoning

Facts and first-order diagnostic findings SHOULD be produced by deterministic code whenever the source permits it.

An LLM may explain, prioritize, connect, or propose the next probe, but it MUST NOT silently manufacture measurements or deterministic findings that the adapter could have computed directly.

Preferred architecture:

```text
signals
  -> deterministic observations / findings
  -> typed evidence
  -> causal and hypothesis reasoning
  -> human or agent explanation
```

Not:

```text
signals
  -> opaque model prompt
  -> unsupported diagnosis
```

This preserves replayability, auditability, testing, and the ability to distinguish measured state from inferred explanation.

### 2. Findings are richer than alerts

An imported finding SHOULD carry enough structure to be useful both to a human and to an agent.

Where available, an adapter should preserve or map:

- stable finding identity;
- observation or condition detected;
- severity or impact classification;
- why the condition matters;
- measured values and comparison baseline;
- affected scope or object;
- provenance and timestamp;
- verification method;
- suggested mitigation or fix;
- when the finding may be safely ignored or suppressed;
- limitations and blind spots;
- source-specific caveats.

Causcope MUST distinguish these fields from causal proof. A tool recommendation or severity level does not by itself establish root cause.

### 3. Uncertainty is first-class evidence

An adapter MUST be able to represent that a source cannot currently support a conclusion.

Examples include:

- sampled rather than exact data;
- cumulative counters without a trustworthy baseline;
- reset or restarted counters;
- insufficient observation window;
- cold-start or cold-window statistics;
- unavailable subsystem statistics;
- partial permissions;
- unsupported platform behavior;
- suppressed or intentionally ignored findings;
- stale evidence;
- insufficient evidence.

`insufficient_evidence` is a valid diagnostic result and is preferable to a confident guess.

Adapters MUST NOT convert unavailable or unreliable measurements into `absent` observations unless the source semantics justify that conclusion.

### 4. Preserve provenance and source semantics

External findings do not become anonymous Causcope facts.

Every imported evidence instance should preserve enough source metadata to answer:

```text
where did this fact come from?
what was actually measured?
when was it measured?
what scope did it cover?
what assumptions or caveats applied?
```

Source identity MUST NOT grant privileged causal weight. Evidence from a specialized adapter enters the same scope, freshness, contradiction, and causal reasoning pipeline as native runtime evidence.

### 5. Separate symptom, mechanism, and antecedent

A useful diagnostic chain distinguishes the visible effect from the mechanism and the condition that produced it.

Example shape:

```text
symptom
  <- mechanism
  <- antecedent
```

For a larger system, the chain may cross domains:

```text
checkout latency
  <- application request latency
  <- database query latency
  <- sequential scan growth
  <- query shape or data distribution change
```

Adapters may contribute one segment of this chain. Causcope composes segments and evaluates alternative branches.

### 6. Domain analyzers are instruments, not the diagnosis engine

A domain adapter SHOULD answer questions such as:

- what is happening inside this subsystem?
- what changed relative to a baseline?
- which deterministic findings are active?
- which subsystem-specific checks would verify them?

Causcope answers the broader questions:

- does this explain the user-visible symptom?
- what other domains could produce the same symptom?
- which findings support or contradict each hypothesis?
- what is the smallest next probe that best separates candidates?
- what is the likely root cause or contributing-factor chain?
- how do we verify the fix across system boundaries?

### 7. Prefer read-only diagnostic surfaces

The first external adapters SHOULD consume read-only APIs, CLI JSON, MCP tools, or other deterministic machine interfaces.

An adapter MUST NOT inherit arbitrary command execution merely because the external tool has a CLI.

Read-only inspection and remediation are separate capabilities. A future remediation integration requires its own explicit risk and approval model.

## Adapter boundary

A diagnostic adapter conceptually performs four steps:

```text
external diagnostic output
  -> source-specific parser
  -> semantic mapping
  -> runtime_evidence instances
```

The adapter mapping owns:

- source finding IDs to canonical observations where a safe mapping exists;
- source objects to Causcope semantic scope;
- source exactness / availability / caveat semantics;
- source timestamps and baseline windows;
- preservation of raw measurements needed for audit;
- deterministic evidence identity.

The adapter MUST NOT:

- create causal edges merely because the source uses causal language;
- widen evidence scope beyond what the source measured;
- reinterpret `unknown` as `absent`;
- hide source caveats;
- directly mutate hypothesis rankings;
- bypass runtime evidence freshness or contradiction handling;
- execute remediation.

## Mapping source findings into Causcope

A specialized tool may expose records such as:

```text
finding
  observation
  severity
  why_it_matters
  verification
  recommendation
  caveats
  limitations
```

Causcope does not need to copy that source schema into the ontology.

Instead, the adapter should map the source record into one or more canonical observations plus provenance-rich runtime evidence. Source-specific explanatory fields can remain attached as evidence metadata or projection context.

If no safe canonical observation exists, the adapter SHOULD fail closed or preserve the item as unmapped source data for inspection rather than inventing ontology semantics.

## Relationship to built-in probes

External diagnostic adapters and built-in probe executors complement each other.

```text
external analyzer
  -> broad domain findings
  -> Causcope evidence
  -> unresolved hypotheses
  -> Causcope next probe
  -> built-in or external read-only probe
  -> new evidence
```

A specialized adapter can therefore reduce the number of low-level probes Causcope must implement itself while still participating in the same feedback loop.

The built-in executor registry remains intentionally static and narrowly trusted. This RFC does not introduce dynamic Python plugin loading, arbitrary subprocess execution, or third-party code execution inside that registry.

## First external adapter target: PostgreSQL via pgbot

The first external diagnostic adapter target should be [pgbot](https://pgbot.dev/), with its source available at [pgrundev/pgbot](https://github.com/pgrundev/pgbot).

It is a useful first target because it provides the properties this RFC wants from a domain analyzer:

- PostgreSQL-specific deterministic findings;
- read-only operation;
- stable machine-readable output;
- historical baseline and change-oriented diagnostics;
- explicit caveats around counter resets, cold windows, and insufficient evidence;
- subsystem-specific diagnostic views;
- an MCP surface that exposes deterministic read-only tools while leaving higher-level reasoning to the connected agent.

The integration goal is not to make pgbot the PostgreSQL diagnosis authority for Causcope. It is to use it as a high-quality PostgreSQL instrument.

Target flow:

```text
pgbot
  -> pgbot adapter
  -> PostgreSQL runtime evidence
  -> compose with application / trace / host / network evidence
  -> Causcope causal graph
  -> ranked hypotheses
  -> next discriminating probe
```

Initial adapter work should prefer its versioned JSON or deterministic MCP tool outputs over parsing human CLI text.

The first slice should remain read-only and should not expose database credentials, raw query literals, arbitrary SQL, or write-capable database operations through Causcope.

## Example cross-domain composition

Consider a user-visible symptom:

```text
checkout is slow
```

A PostgreSQL adapter may contribute:

```text
observation.database.query_latency = observed
observation.database.sequential_scan_pressure = observed
```

OpenTelemetry may contribute:

```text
observation.dependency.latency = observed
```

A host collector may contribute:

```text
observation.cpu.utilization = absent
```

Deployment evidence may contribute:

```text
observation.deployment.recent_change = observed
```

Causcope can then compare candidate chains rather than treating the database finding as the whole diagnosis:

```text
checkout latency
  <- database query latency
     <- sequential scan pressure
        <- query-shape change

versus

checkout latency
  <- external dependency latency

versus

checkout latency
  <- host saturation
```

The next probe should be selected based on which unresolved observation best discriminates these candidates.

## Security and privacy

An external adapter MUST define its trust boundary explicitly.

At minimum it should document:

- whether the provider runs locally or remotely;
- whether data leaves the machine;
- credential handling;
- query or payload redaction policy;
- exact read permissions required;
- timeout and resource limits;
- whether any provider action can mutate the target system;
- which outputs are retained in runtime evidence.

Causcope SHOULD prefer least-privilege credentials and source-side redaction when available.

## Non-goals

This RFC does not add:

- a generic plugin marketplace;
- arbitrary executable adapters;
- automatic installation of third-party binaries;
- write-capable database operations;
- remediation;
- source-specific causal truth;
- global numeric probability scoring;
- automatic ontology generation from external findings;
- privileged ranking for any vendor or adapter.

## Consequences

This architecture lets Causcope grow horizontally without becoming a collection of shallow reimplementations.

The semantic core stays stable while specialized instruments can evolve independently:

```text
PostgreSQL analyzer --\
Linux collector ------\
trace adapter ----------> normalized evidence -> causal reasoning
queue analyzer --------/
cloud adapter ---------/
```

The result is a system that knows how to debug across boundaries, not merely a system that knows how to collect every metric itself.

## Next work

1. Define a minimal `diagnostic_adapter` mapping contract without adding a new canonical concept kind unless implementation proves it necessary.
2. Implement the first pgbot adapter against deterministic JSON or MCP output.
3. Map a small initial set of PostgreSQL findings into existing or newly justified canonical observations.
4. Preserve source caveats, exactness, baseline window, and unavailable-state semantics in runtime evidence.
5. Add a fixture-driven integration test showing PostgreSQL evidence composed with at least one non-database evidence source.
6. Demonstrate that Causcope can choose a cross-domain next probe rather than simply repeating the adapter recommendation.

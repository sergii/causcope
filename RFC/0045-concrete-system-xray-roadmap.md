# RFC 0045: Concrete System X-Ray Roadmap

- Status: Draft for coordination and review
- Date: 2026-09-14
- Scope: Predictive reasoning over a concrete production system

## Summary

Causcope already has the main incident-diagnosis loop: semantic failure knowledge, causal ranking, scoped runtime evidence, safe read-only probes, provider capability discovery, deterministic instrument routing, autonomous re-ranking, crash-recoverable state updates, and original-scope autonomous verification.

The next frontier is not another reasoning engine or a larger failure catalog. It is a **Concrete System Model** that lets existing generic failure knowledge bind to facts about one real application.

```text
Generic Failure Knowledge
        x
Concrete System Model
        x
Runtime / Diagnostic Evidence
        =
Concrete Risk + Diagnosis + Blast Radius + Verification
```

The first proof should be predictive D2.2 deadlock risk in a Ruby/Rails + PostgreSQL system. The second should be a duplicate external/business side-effect risk, proving that the model is not database-specific.

## What is already solved

The roadmap MUST reuse these existing layers rather than rebuild them:

- RFC 0001 semantic foundation;
- RFC 0004 explicit causal graph;
- RFC 0005 scoped runtime evidence;
- RFC 0007 OpenTelemetry trace adapter;
- RFC 0014 multi-source evidence composition;
- incident context, blast-radius and investigation scoping;
- RFC 0033 external deterministic diagnostic adapters;
- RFC 0034/0036 pgBot adapter and live PostgreSQL integration;
- RFC 0035 bounded autonomous read-only investigation;
- RFC 0037 pgBot autonomous probe provider;
- RFC 0038 provider capability discovery;
- RFC 0039 deterministic instrument routing;
- RFC 0040 routing-aware agent plan;
- RFC 0041 revision-bound routed MCP execution;
- RFC 0042 crash-recoverable incident state commit;
- RFC 0043 original-scope verification;
- RFC 0044 routed autonomous verification.

The completed operational loop is therefore approximately:

```text
incident symptom
  -> scoped evidence
  -> causal candidates
  -> next canonical probe
  -> provider capability discovery
  -> deterministic instrument route
  -> read-only execution
  -> new canonical evidence
  -> re-rank
  -> external mitigation/fix
  -> original-scope autonomous verification
```

## Primary missing layer

Causcope currently knows generic entities such as application service, database, queue and boundary types. Runtime evidence can carry scope attributes such as service and dependency. Incident context can describe affected services, data, dependencies and changes.

That is not yet a durable representation of facts such as:

```text
CheckoutController#create
  -> CheckoutService#call
  -> transaction T1
  -> writes accounts
  -> writes ledger_entries

SettlementJob#perform
  -> transaction T2
  -> writes ledger_entries
  -> writes accounts
```

The missing layer must preserve the difference between **possible structure** and **observed execution**:

```text
static analyzer: A may call B
OTel:            A did call B in this execution
```

Likewise:

```text
static facts: opposing resource order is possible
runtime facts: paths actually overlap
DB evidence:   a concrete lock wait / wait-for cycle occurred
```

These are different epistemic states and MUST NOT be collapsed.

## Minimal Concrete System Model

Do not model all software architecture. Model only what the first vertical slice needs.

Candidate fact families:

```text
code.symbol
code.calls
code.reads
code.writes
code.transaction_boundary
data.resource
runtime.executes
runtime.concurrent_with
change.deploy
```

Names above are illustrative. Existing `SystemEntity`, `Boundary`, runtime scope and incident context MUST be audited before any new canonical schema is introduced.

A useful concrete fact needs at least:

- stable identity;
- subject and relation;
- object or value;
- provenance/source;
- confidence/exactness;
- whether it is static possibility, runtime observation, or declared configuration;
- source location or external reference where applicable;
- freshness/version where the fact can become stale.

## Provider boundary

Do not create a second adapter/router stack.

Specialized tools contribute facts or evidence. Causcope owns diagnostic and predictive semantics.

```text
Rubydex / code analyzer
  -> possible code facts

OpenTelemetry
  -> observed execution facts

pgBot / PostgreSQL probes
  -> database observations

logs / metrics / probes
  -> incident evidence

Causcope
  -> risk + diagnosis + next probe + blast radius + verification
```

Static analyzers may not fit the current executable-probe provider contract exactly because their output is often passive, repository-scoped and versioned rather than incident-scoped runtime evidence. Extend existing contracts only after the first slice proves the missing abstraction.

## First vertical slice: D2.2 predictive deadlock risk

The existing D2.2 knowledge and labs already prove the generic mechanism. The new proof asks a different question:

> Does this concrete application contain reachable, concurrency-relevant resource ordering that can produce D2.2 even before a deadlock event has been observed?

Target composition:

```text
Static facts
  Path A: Account -> Ledger
  Path B: Ledger -> Account

Runtime facts
  A executes
  B executes
  overlap/concurrency is observed or remains unknown

Database evidence
  lock waits / blockers / transaction age / deadlock counters

Causcope projection
  known mechanism: D2.2
  structural preconditions: present | partial | absent | unknown
  runtime concurrency: observed | absent | unknown
  deadlock event: observed | absent | unknown
  risk state: derived
  blast radius: grounded in concrete system scope
  next discriminating probe: canonical and routable
```

Opposing write order MUST NOT be treated as proof that a deadlock will occur. A deadlock requires a concrete wait-for cycle at runtime.

## Epistemic state

The useful states are approximately:

```text
UNKNOWN
  -> POSSIBLE
  -> PRECONDITIONS_PRESENT
  -> RISK_DETECTED
  -> OBSERVED
  -> CONFIRMED
```

These names are not yet approved as persisted ontology records. Prefer a deterministic **derived projection** over existing facts, evidence, diagnosis and verification semantics unless the vertical slice proves persistence is required.

## Second vertical slice: duplicate side effect

After D2.2, prove the architecture across a different domain:

```text
job retry
+
external side effect
+
ambiguous timeout / response loss
+
no idempotency evidence
=
concrete duplicate-effect risk path
```

Reuse existing messaging/idempotency knowledge. The new value is binding it to one concrete application's job, retry boundary, dependency call and business effect.

## Work packages

### WP-1 - capability gap analysis

Audit current semantics and implementation and produce:

```text
required concept | current representation | sufficient? | gap | recommendation
```

No schema changes by default.

### WP-2 - minimal sourced fact vocabulary

Propose the smallest vendor-neutral fact contract required for D2.2. Every proposed field must explain why current concepts/scope are insufficient.

### WP-3 - Rubydex capability spike

Determine which Ruby/Rails facts Rubydex can produce reliably today. Separate:

- directly provided facts;
- inferred facts with explicit uncertainty;
- unavailable/unreliable facts.

### WP-4 - realistic deadlock application fixture

Create a small Ruby/Rails + PostgreSQL app with two realistic code paths acquiring shared resources in opposite order. Support both safe baseline and concurrency capable of producing a deadlock.

### WP-5 - cross-source composition

Combine static code facts, OTel execution evidence and pgBot/PostgreSQL observations into one inspectable D2.2 risk/diagnosis projection.

### WP-6 - epistemic projection

Derive possible/preconditions/observed/confirmed from current evidence. Add a new state model only if derivation is insufficient.

### WP-7 - duplicate-side-effect design

Map the existing idempotency/messaging knowledge onto a concrete retry + ambiguous response + external side effect path.

## Execution order

```text
WP-1 audit
  -> WP-2 minimum fact contract
  -> WP-3 Rubydex spike
  -> WP-4 concrete app fixture
  -> WP-5 D2.2 composition
  -> WP-6 epistemic projection
  -> WP-7 second domain proof
```

Additional eBPF, Sidekiq/Redis, deploy, feature-flag or configuration providers should be added only when these slices expose a specific missing fact.

## Acceptance criteria

The X-Ray frontier is proven when:

1. Generic failure mechanisms remain application-independent.
2. Concrete code/data/runtime relationships are separately sourced.
3. Static possibility remains distinct from runtime observation.
4. Multiple providers preserve provenance and uncertainty.
5. Causcope can state which D2.2 preconditions are present, absent or unknown.
6. Next probes reuse the existing routing/execution stack.
7. Blast radius is grounded in concrete graph/scope facts, not textual guessing.
8. A second non-database risk slice reuses the same model.
9. Original-scope verification still closes the loop after an observed incident is fixed.
10. Every conclusion is inspectable back to evidence or sourced facts.

## Coordination rule

Before implementing any work package, re-read `main`. If another agent has already closed the gap, update this roadmap instead of reimplementing it.

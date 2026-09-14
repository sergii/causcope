# Concrete System Model - WP-1 capability gap analysis

Date: 2026-09-14
Status: coordination result for RFC 0045

## Question

What is actually missing before Causcope can project generic failure knowledge onto one concrete application, and which proposed pieces are already represented by current semantics?

This audit intentionally prefers reuse over adding schemas.

## Result

| Required concept | Current representation | Sufficient? | Gap | Recommendation |
| --- | --- | --- | --- | --- |
| Generic service/database/queue/process types | `system_entity` concepts | Yes for types | Not concrete instances/symbols | Reuse as semantic types |
| Generic application-to-database boundary | `boundary.application.database` | Yes | None for semantic boundary type | Reuse |
| Concrete service/dependency identity on one evidence item | runtime evidence `scope.attributes` | Yes for scoped measurements | Not a durable system graph | Reuse for incident evidence only |
| Affected service/data/client/dependency/change | `incident_context` | Yes for investigation scope | Does not express code/resource relationships | Reuse for incident context and blast radius |
| Static code symbol identity | None in canonical concept schema | No | Missing sourced concrete symbol/fact identity | Candidate concrete-fact layer |
| May-call edge | None | No | Must preserve static uncertainty | Candidate concrete fact relation |
| Did-call edge | OTel trace spans can prove execution/dependency behavior | Partial | No canonical bridge to a durable code-symbol edge | Project runtime execution separately from static graph |
| Transaction boundary in concrete code | None | No | Missing | Source from analyzer when reliable; preserve uncertainty |
| Reads/writes concrete DB resource | None | No | Missing | Minimum D2.2 fact vocabulary should add resource access facts |
| Ordered resource acquisition/write relation | None | No | Critical D2.2 gap | Model order explicitly for first slice |
| Runtime concurrency/overlap of concrete paths | Trace timing can carry raw timestamps | Partial | No explicit derived concrete-path concurrency fact | Derive from runtime evidence where supportable |
| Database lock waits/blockers | canonical observations + pgBot/PostgreSQL probes | Yes | None | Reuse |
| Generic D2.2 mechanism | existing deadlock knowledge/claims/lab/catalog | Yes | None | Reuse, do not remodel |
| Next diagnostic probe | canonical probes + ranking | Yes | None | Reuse |
| Provider availability | RFC 0038 capability discovery | Yes | None | Reuse |
| Instrument selection | RFC 0039 router | Yes | None | Reuse |
| Safe execution | RFC 0041 routed MCP + bounded autonomous loop | Yes | None | Reuse |
| Recovery-safe state mutation | RFC 0042 | Yes | None | Reuse |
| Post-fix verification | RFC 0043/0044 | Yes | None | Reuse |
| Possible/preconditions/observed/confirmed distinction | confidence + evidence state + diagnosis + verification pieces | Partial | No single predictive-risk projection | Derive first; do not introduce persisted state machine yet |
| Concrete blast radius through code/data dependencies | incident scope exists | Partial | No concrete graph to propagate through | Build only after concrete facts exist |
| Static analyzer provenance | runtime evidence source has provenance shape, but evidence requires an observation and incident | Partial | Static repository facts are not naturally incident runtime evidence | Do not force static facts into `runtime_evidence` |
| Passive/offline analyzer discovery | provider schema is probe-centric, fixed-exact scope, read-only execution-centric | Partial | Static analyzers do not naturally behave like incident probes | Prefer passive fact ingestion first; extend router only if a real execution need appears |

## Findings

### 1. `SystemEntity` is semantic type knowledge, not the Concrete System Model

`schema/concept.schema.json` supports generic entity types such as `application_service`, `database`, `queue`, `worker`, `process` and `host`. That is appropriate for reusable ontology nodes.

It does not represent arbitrary concrete symbols such as:

```text
OrdersController#create
CheckoutService#call
SettlementJob#perform
public.accounts
public.ledger_entries
```

Adding every concrete symbol as a canonical knowledge concept would mix reusable ontology with one repository's implementation details. Do not do that by default.

### 2. Runtime evidence scope is powerful but intentionally not a durable topology graph

`runtime_evidence.scope` can carry canonical entity/boundary IDs plus arbitrary string attributes. That is enough to keep measurements for `service=checkout-api` and `dependency=postgresql` in one semantic partition.

It does not express ordered relationships among concrete code paths, transactions and resources. Using scope attributes as an implicit graph would make traversal and provenance ambiguous.

Conclusion: keep runtime evidence for observed incident facts. Do not stretch it into the static system model.

### 3. Incident context already owns triage scope and changes

`incident_context` already carries affected services, entities, boundaries, dependencies, clients, data cohorts, changes and failing-vs-working comparisons.

This is enough for the early question "who/where/when/what changed?" and should remain separate from causal proof.

It is not a code graph. A deploy reference near onset remains context until another sourced fact/evidence record gives it diagnostic meaning.

### 4. Existing provider/routing architecture solves execution, not passive repository facts

The diagnostic provider capability schema is intentionally probe-centric:

```text
provider
  -> fixed exact scope
  -> availability
  -> read-only probes
  -> mapped observations
```

That is excellent for pgBot and other instruments that satisfy a canonical diagnostic probe.

A static analyzer usually answers a different question:

```text
for repository revision R, what code/topology facts can be extracted?
```

Those facts may exist before any incident and are versioned by repository commit rather than incident timestamp/TTL.

Conclusion: do not bend Rubydex into a fake runtime probe merely to reuse the router. First define passive sourced-fact ingestion. If later Causcope needs to invoke a code analyzer on demand, its execution may be exposed through provider capability discovery while its output still lands in the sourced-fact layer.

### 5. The minimum real D2.2 gap is ordered resource access

The first slice does not need a universal architecture graph. It needs enough facts to establish this shape:

```text
path A
  transaction T1
  acquires/writes X before Y

path B
  transaction T2
  acquires/writes Y before X
```

plus runtime facts about whether A and B actually execute and can overlap.

This suggests that the first fact contract should be deliberately narrow rather than starting with a generic graph database abstraction.

### 6. Predictive state should initially be derived

Current Causcope already distinguishes:

- semantic possibility through generic knowledge;
- observations present/absent;
- confidence and falsification;
- diagnosis ranking;
- verification resolved/regressed/inconclusive.

The missing predictive labels can initially be a deterministic projection over concrete facts + runtime evidence:

```text
possible
preconditions_present
runtime_supported
observed
confirmed
```

Do not persist a new state machine until the D2.2 slice demonstrates a state that cannot be reconstructed from authoritative inputs.

## Specific cleanup discovered during the audit

### PostgreSQL scope should use the canonical database boundary

The ontology already defines:

```text
boundary.application.database
```

for application-to-PostgreSQL interaction, while the pgBot adapter and its OTel PostgreSQL example still use the generic:

```text
boundary.application.external_dependency
```

This is a concrete semantic cleanup, not a new model. The pgBot/OTel PostgreSQL integration should migrate together to `boundary.application.database`, including fixtures, live trace defaults, tests, routing examples and workflow arguments.

### Do not add causal edges merely to make a diagnostic target appear

`hypothesis.database.lock_contention` already predicts `observation.database.lock_wait_time`, and `hypothesis.latency.database` predicts `observation.database.query_latency`. Empirical claims exist for both mechanisms.

RFC 0004 deliberately separates diagnostic prediction from causal graph edges. Therefore a direct `hypothesis -> observation` causal edge should only be added when the relationship is intended as a causal mechanism under explicit conditions, not simply because an adapter emits that observation or because a test wants a non-empty reverse-cause projection.

The current autonomous incident flow can start from the user-visible symptom and use the database observations to re-rank candidates correctly. Treat this as an audit item, not an automatic missing edge.

## Proposed minimal next contract

WP-2 should test a small `concrete_system_facts` document rather than changing the canonical concept schema immediately.

A candidate shape is:

```yaml
schema_version: "0.1"
kind: concrete_system_facts
system_id: checkout-app
revision: git:abc123
facts:
  - id: fact.code.checkout_service.writes_accounts
    subject: code:CheckoutService#call
    relation: writes
    object: db:public.accounts
    certainty: direct
    source:
      type: static_analysis
      name: rubydex
      location: app/services/checkout_service.rb:42
```

For D2.2 the contract probably also needs transaction membership and an order/sequence relation. Exact field names remain WP-2 work.

Important invariants:

```text
static fact != runtime evidence
may-call != did-call
unknown != absent
inferred != directly observed
repository revision is part of provenance
```

## Decision

WP-1 concludes that the **Concrete System Model is a real gap**, but it should be introduced as a small sourced concrete-fact layer rather than by expanding generic ontology concepts or repurposing incident runtime evidence.

The next two work packages can proceed in parallel:

1. WP-2: define the smallest `concrete_system_facts` contract needed for D2.2.
2. WP-3: spike Rubydex and measure what facts it can actually emit reliably.

Do not begin the full predictive deadlock implementation until those two outputs meet at a stable fact boundary.

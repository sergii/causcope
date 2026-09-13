# Causcope Semantic Specification

This document defines the minimal semantic contract used by Causcope knowledge files and runtime diagnostic records.

## Dual-use invariant

> Every concept should be useful to a human and addressable by a machine. Every diagnostic relationship should be explainable to a human and executable or testable by an agent where possible.

## Layers

Causcope separates four semantic concerns:

1. **Vocabulary** - the language: concept kinds, relations, action classes, and semantic constraints.
2. **Knowledge** - concrete facts expressed using that language, including explicit causal edges.
3. **Rules** - deterministic inference over observations and hypotheses.
4. **Projections** - generated views for people and software: docs, website pages, CLI, MCP, HTTP APIs, agent skills, or other adapters.

Runtime records such as incident context, investigation sessions, and runtime evidence sit beside the canonical semantic source. They describe a particular incident and may reference canonical semantic IDs, but they are not themselves reusable ontology concepts.

The canonical semantic source is machine-readable YAML validated by JSON Schema. Markdown is a human projection and explanatory layer, not the source of truth for executable relations.

## Stable IDs

IDs are namespaced by semantic role rather than by product name.

Examples:

```text
symptom.cpu.high
hypothesis.traffic.increase
hypothesis.cpu.busy_loop
observation.http.request_rate
probe.http.inspect_request_rate
capability.cpu.profile
tool.ebpf
causal.network.packet_loss.tcp_retransmissions
investigation.blast_radius
investigation.client
```

Product or repository names MUST NOT be embedded into semantic IDs.

## Minimal concept kinds

The current executable slice uses:

- `symptom`
- `hypothesis`
- `observation`
- `probe`
- `system_entity`
- `boundary`

Causal edges are first-class semantic records but are not concept nodes. They connect existing concepts and carry typed causal semantics, conditions, strength, and optional evidence references.

`incident_context`, `investigation_session`, and `runtime_evidence` are runtime record kinds, not concept kinds. They describe one incident and can reference semantic entities, boundaries, observations, and investigation dimensions without becoming reusable nodes in the canonical knowledge graph.

`scoping_projection` is a deterministic projection over incident context, not a source-of-truth record.

The broader target model is documented in `RFC/0001-semantic-foundation.md`.

## Diagnostic workflow

The complete workflow starts before evidence collection:

```text
something is wrong
  -> incident context
  -> scoping projection
  -> next unresolved investigation dimension
  -> blast radius and impact
  -> failing-vs-working comparison
  -> runtime evidence
  -> candidate hypotheses
  -> predictions
  -> probes / experiments
  -> findings
  -> hypothesis updates
  -> cause / contributing factors
  -> mitigation / fix
  -> verification / prevention
```

The human-readable workflow is documented in `WORKFLOW.md`. The machine-readable incident context is defined by `schema/incident-context.schema.json` and RFC 0022. The executable scoping protocol is defined by `vocabulary/investigation-dimensions.yaml`, `schema/scoping-projection.schema.json`, `schema/investigation-session.schema.json`, and RFC 0030.

Incident context MUST NOT silently become causal evidence. It may guide what to measure next, but only facts represented through the runtime evidence contract can affect deterministic diagnosis.

## Incident context and investigation scoping

Incident context captures the earliest triage state before reliable diagnostic evidence is complete.

Causcope defines ten stable investigation dimensions:

- `investigation.blast_radius` - who is affected and how broadly;
- `investigation.where` - environment, region, availability zone, or datacenter;
- `investigation.when` - onset, last-known-good, and temporal pattern;
- `investigation.flow` - feature, endpoint, operation, or user journey;
- `investigation.client` - browser, mobile, OS, device, worker, app, or API version;
- `investigation.change` - deploy, flag, migration, config, dependency, infrastructure, or data change near onset;
- `investigation.dependency` - upstream, downstream, external, or peer dependency scope;
- `investigation.data` - tenant, record type, role, permission, or data age;
- `investigation.reproducibility` - whether and under which conditions the problem reproduces;
- `investigation.impact` - actual user or business consequence and severity.

Blast radius and impact are distinct. Breadth of affected population MUST NOT be treated as severity.

Unknown dimensions are explicit rather than guessed. A dimension can be partially known and still be marked materially incomplete.

The scoping projection classifies each dimension as `known`, `partial`, or `unknown`, computes context completeness, and recommends the next unresolved clarification using an explainable deterministic baseline. Scoping completeness MUST NOT be interpreted as root-cause confidence.

Nearby changes, dependencies in the failing path, and failing-vs-working differences are contextual discriminators, not causal proof. They should become diagnostic evidence only after they can be represented as sourced, time-bounded observations with confidence and applicable scope.

## Diagnostic semantics

### Symptom

A deviation from expected system behavior. A symptom does not assert a cause.

### Observation

A concrete measured or reported fact about a system. Observations should carry provenance when runtime instances are modeled.

### Hypothesis

A candidate explanation for one or more symptoms or observations. A hypothesis is not a fact and should define testable predictions.

### Prediction

An expected observation if a hypothesis is true. Predictions enable falsification and confidence updates.

### Probe

A diagnostic action whose primary purpose is to gather evidence. Probes should be side-effect free where possible and declare required capabilities.

## Relations

The minimal vocabulary supports these semantic relations:

- `may_indicate`: symptom -> hypothesis
- `predicts`: hypothesis -> expected observation or condition
- `tested_by`: hypothesis -> probe
- `produces`: probe -> observation
- `requires`: probe -> capability
- `supports`: observation -> hypothesis
- `contradicts`: observation -> hypothesis
- `causes`: concept -> concept, represented by a causal edge record
- `contributes_to`: concept -> concept, represented by a causal edge record
- `related_to`: concept -> concept

`may_indicate` MUST NOT be interpreted as causality.

`supports` and `contradicts` SHOULD be treated as updates to belief or confidence, not universal proof, unless a rule explicitly declares a deterministic exclusion.

`related_to` MUST remain non-causal. A causal statement MUST use an explicit causal edge rather than relying on adjacency, naming, prose, or `related_to`.

## Causal edges

Causal edges model directional mechanism and consequence structure separately from diagnostic belief updates.

A causal edge contains:

- stable `causal.*` ID
- `source` and `target` concept IDs
- relation: `causes` or `contributes_to`
- qualitative strength
- optional conditions under which the causal claim applies
- optional claim and experiment evidence references
- human-readable explanation and limitations

Example:

```yaml
id: causal.network.packet_loss.tcp_retransmissions
kind: causal_edge
source: hypothesis.network.packet_loss
target: observation.network.tcp_retransmissions
relation: causes
strength: strong
conditions:
  - Missing delivery affects data on an active TCP transfer.
evidence:
  claims:
    - claim.network.packet_loss.partial_loss_causes_tcp_retransmissions
explanation: Missing TCP segments drive reliable transport recovery and retransmission.
```

Causal direction MUST NOT be inferred from prediction, support, contradiction, or correlation alone. Evidence references justify an edge but do not change the identity of its endpoint concepts.

## Rules

Rules are separate from concepts. A rule describes how an observed condition changes diagnostic state.

Example:

```yaml
id: rule.traffic_increase.request_rate_normal
hypothesis: hypothesis.traffic.increase
when:
  observation: observation.http.request_rate
  operator: not_above_baseline
effect:
  confidence: decrease
```

The initial rule model intentionally avoids a global numeric probability system. Early rules use qualitative effects such as `increase`, `decrease`, and `reject`.

## Human-facing fields

Concepts may include explanatory fields such as:

- `title`
- `summary`
- `explanation`
- `why_it_matters`
- `common_misconceptions`
- `prerequisites`
- `examples`
- `search_terms`

These fields can power documentation, learning paths, SEO pages, and short educational content without changing the executable semantic relations.

## Machine-facing fields

Machine-facing fields include:

- stable semantic `id` values;
- runtime `incident_id` and investigation `session_id` values;
- concept `kind`, runtime record `kind`, and projection `kind`;
- explicit diagnostic and causal relations;
- the ten stable investigation dimensions;
- incident scope, impact, reproduction, comparisons, and unknowns;
- deterministic scoping state and next-question projections;
- investigation-session events;
- predictions;
- probes;
- capabilities;
- deterministic rules;
- causal conditions and evidence provenance;
- risk and approval metadata for actions as the model expands.

## Integration boundary

The semantic core is transport independent.

Expected consumers include:

- CLI
- embedded library
- local daemon
- Unix domain socket
- MCP server
- HTTP API
- gRPC API if justified
- agent-evaluation harnesses
- SaaS control planes
- Run Witness-like local runtime instrumentation
- RunDiff/Plywo-style regression analysis
- incident and observability integrations

MCP, HTTP, CLI, SaaS, and harnesses are adapters or projections, not the ontology itself.

## Versioning

The project is experimental. Changes to IDs or relation semantics should be treated as breaking semantic changes even before a formal versioning policy is introduced.

# RFC 0047: Rubydex to Concrete System Facts v0

- Status: Accepted
- Date: 2026-09-14

## Summary

Causcope now has a first executable bridge from a real semantic code analyzer into the revision-bound `concrete_system_facts` contract introduced by RFC 0046.

The first provider is Rubydex. The initial slice is deliberately narrow:

```text
Ruby workspace at pinned revision
  -> Rubydex semantic graph
  -> workspace-defined declarations + ownership
  -> concrete_system_facts
```

This RFC does not make Rubydex a runtime diagnostic provider and does not infer Rails/database semantics that Rubydex cannot prove directly.

## Why this slice exists

RFC 0045 identified the Concrete System Model as the missing layer between generic failure knowledge and runtime evidence. RFC 0046 introduced a provider-neutral sourced fact contract. The remaining requirement was to prove that a real repository semantic backend could populate that contract without leaking backend-specific node types into Causcope reasoning.

Rubydex is appropriate for the first proof because it deterministically resolves Ruby declarations and ownership while preserving source locations.

## Decision

`scripts/rubydex_concrete_system_facts.rb` indexes a target workspace with Rubydex and emits Causcope `concrete_system_facts` JSON directly.

The v0 exporter includes only workspace-defined:

- classes;
- modules;
- methods;
- declaration-level ownership as `contains` facts;
- primary deterministic source location;
- definition multiplicity;
- pinned repository/system revision;
- Rubydex provenance.

All emitted entities and facts are `certainty: direct`.

## Epistemic boundary

The important invariant is:

```text
Rubydex semantic fact
  !=
Rails framework interpretation
  !=
runtime observation
```

Therefore this exporter does not claim:

- a method executed;
- two paths overlapped;
- a block is an ActiveRecord transaction;
- a model maps to a particular table;
- a call reads or writes a database resource;
- one resource is acquired before another;
- a lock wait or deadlock occurred.

Those facts belong to later deterministic enrichment or runtime/database evidence.

## Source identity and reopened declarations

Rubydex declarations can contain multiple source definitions. The current `concrete_system_facts` entity contract has one `source_location`, so v0 chooses the first workspace definition under a stable `(path, line, column)` ordering and records `definition_count` in attributes.

This is a projection choice, not a claim that only one definition exists.

If later X-Ray slices need every reopening location, that requirement should produce an explicit multi-location/evidence-set extension rather than hiding additional definitions in prose.

## Provider neutrality

Causcope IDs are generated from semantic declaration names:

```text
code:CheckoutService
code:CheckoutService#call()
```

Rubydex class names or internal graph IDs are preserved only as attributes/provenance. Core inference therefore remains independent of Rubydex storage and object identity.

Ownership is normalized as:

```text
code:CheckoutService
  --contains-->
code:CheckoutService#call()
```

The exporter does not add new generic ontology concepts.

## Determinism

The output is intentionally stable for the same workspace/revision:

- entities are sorted by canonical Causcope id;
- ownership facts receive content-derived SHA-256 identifiers;
- facts are sorted by id;
- no wall-clock `generated_at` value is emitted;
- the integration workflow runs the exporter twice and requires byte-identical output.

## Live integration proof

`lab/rubydex-concrete-system` contains a minimal Ruby workspace with four classes and four methods.

The GitHub Actions integration installs Rubydex `~> 0.4.1`, executes the real Rubydex graph against that workspace, validates the resulting document against `schema/concrete-system-facts.schema.json`, and checks:

- expected concrete symbols exist;
- class-to-method ownership is preserved;
- all current facts remain direct static evidence;
- source locations are present;
- no D2.2 `accesses_before` precondition is invented from symbol structure alone;
- repeated runs are deterministic.

The workflow requires no LLM or OpenAI API access.

## What this proves

We now have an executable chain:

```text
real repository
  -> deterministic semantic analyzer
  -> provider-neutral sourced facts
  -> Causcope contract validation
```

This is the static side of the X-Ray architecture. It is intentionally weaker than the final D2.2 projection because honest uncertainty is more valuable than manufacturing data-access semantics from names.

## Next slice

The next high-value layer is deterministic Rails-aware enrichment on top of these direct facts.

The first target should be only the facts needed by D2.2:

```text
class -> Rails model identity
model -> table mapping
code path -> transaction boundary
code path -> reads/writes resource
resource X -> accesses_before -> resource Y
```

Every derived fact must carry `certainty: inferred`, an explicit deriving rule, source provenance, and limitations. Static ordering should still establish only a structural deadlock precondition. OpenTelemetry and PostgreSQL/pgBot evidence remain responsible for runtime execution, concurrency, wait state, and observed deadlock evidence.

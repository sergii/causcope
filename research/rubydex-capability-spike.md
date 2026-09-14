# Rubydex capability spike for Causcope WP-3

Date: 2026-09-14
Status: research result for RFC 0045
Upstream inspected: `Shopify/rubydex` plus the existing `sergii/rubydex-labs` experiments

## Goal

Determine which facts Rubydex can provide directly enough to feed a future Causcope Concrete System Model, which facts require deterministic inference on top, and which facts must come from another evidence source.

The key rule is:

```text
direct semantic fact != inferred framework meaning != runtime observation
```

## Executive result

Rubydex is a strong first **semantic repository evidence backend**, but it is not by itself a Rails transaction/data-access/lock-order analyzer.

It directly gives Causcope useful symbol and relationship facts such as declarations, definitions, ownership, locations, ancestry/descendants, constant references, method references, and resolvable method targets. It also exposes a read-only Cypher query surface and machine-renderable JSON results.

For the D2.2 predictive-deadlock slice, Rubydex can reliably establish much of the **code identity and semantic neighborhood**. It does not directly establish all of these higher-level facts:

```text
this block is one ActiveRecord transaction
this call writes table accounts
this later call locks ledger_entries
resource X is acquired before resource Y
these two paths execute concurrently in production
```

Those require a deterministic Rails-aware extractor and/or runtime evidence.

Therefore the correct role is:

```text
Rubydex
  -> direct semantic facts
  -> deterministic Rails-aware enrichment where justified
  -> concrete_system_facts

OTel / runtime
  -> did-execute / overlap facts

pgBot / PostgreSQL
  -> lock / wait / transaction observations

Causcope
  -> D2.2 risk and diagnosis projection
```

## Directly provided facts

### Workspace semantic graph

Rubydex indexes a workspace and dependencies, then resolves collected information into a semantic graph.

This gives us a repository-revision-scoped semantic source rather than a text-search approximation.

Recommended provenance for any imported fact:

```text
backend: rubydex
repository: <repo identity>
revision: <git commit>
workspace/config fingerprint: <when available>
```

### Declarations and definitions

The public Ruby API exposes declarations and documents. Declarations include:

- fully qualified name;
- unqualified name;
- definitions;
- owner.

Definitions expose source locations, names and comments.

This is strong enough for stable concrete identities such as:

```text
ruby:CheckoutService#call()
ruby:SettlementJob#perform()
ruby:Account
```

provided the Causcope adapter records the pinned repository revision and source location rather than pretending the identifier is globally timeless.

Classification: `direct`.

### Namespace membership

Namespace declarations expose members and singleton classes.

Useful for:

- class/module containment;
- locating concrete methods/ivars/constants;
- compact semantic neighborhoods.

Classification: `direct`.

### Ancestors and descendants

Rubydex exposes declaration ancestors and descendants and has an MCP `get_descendants` tool.

Useful for:

- inheritance;
- module inclusion/extension relationships represented by the resolved graph;
- concrete implementation sets;
- Rails base-class relationships where statically resolvable.

Classification: `direct`.

### Resolved constant references

Rubydex exposes constant references globally and an MCP `find_constant_references` tool specifically described as returning precise resolved references across the codebase.

Useful for statements such as:

```text
file/path.rb references Account
CheckoutService references PaymentGateway
```

Classification: `direct` when the reference is resolved by Rubydex.

Unresolved references must remain `unknown/unresolved`, never be turned into `absent`.

### Method references and targets

The Ruby API exposes graph/document/declaration method-reference iterators. `Rubydex::MethodReference#target` is nullable and, when resolved, points to a `Rubydex::Method`.

This is especially useful for Causcope because it gives a clean epistemic distinction:

```text
target present -> Rubydex resolved the semantic target
target nil     -> unresolved / insufficient evidence
```

A nullable target MUST NOT be interpreted as proof that there is no callee.

Classification:

- reference occurrence/location: `direct`;
- target relation when non-null: `direct`;
- meaning of an unresolved target: `unknown`, not `absent`.

### Documents and require paths

Rubydex exposes indexed documents, their definitions, require-path resolution and all indexed require paths.

Useful for:

- source provenance;
- file-to-symbol mapping;
- load/require structure where resolved.

Classification: `direct`.

### Read-only query surface

Rubydex exposes a read-only subset of Cypher through:

```text
rdx query
Rubydex::Query
```

and supports JSON rendering. The upstream README explicitly shows queries such as:

```text
MATCH (c:Class)-[:DEFINES]->(m:Method)
RETURN c.name, m.name
```

The query surface cannot mutate the graph.

For Causcope this is preferable to free-form model navigation because deterministic queries can own membership/count/completeness-sensitive result sets.

Classification: `direct deterministic query result`.

### Current MCP surface

The documented MCP tools currently include:

- `search_declarations`;
- `get_declaration`;
- `get_descendants`;
- `find_constant_references`;
- `get_file_declarations`;
- `codebase_stats`.

The full Ruby/query API is richer than this MCP surface. A Causcope prototype should therefore not assume MCP alone exposes every fact we need.

## Facts that can be deterministically inferred on top

These are **not Rubydex facts** even when Rubydex supplies the raw semantic inputs.

### Caller/call edge from a method reference

A resolved method reference gives us a target and location. Associating that reference with an enclosing concrete method can produce:

```text
caller -> callee
```

if the enclosing definition can be determined deterministically.

Classification: `derived_static`.

The fact should carry provenance to both the Rubydex reference and the deterministic enclosing-definition rule.

### Rails model identity

A class descending from `ApplicationRecord`/`ActiveRecord::Base` can often be identified from ancestry. Mapping that class to a database table using conventional Rails naming can be deterministic only when no override/dynamic configuration invalidates the convention.

Classification:

- model ancestry: usually `direct`;
- inferred table name: `derived_static` with explicit rule and confidence;
- custom/dynamic table mapping: `unknown` unless source/config is inspected.

### ActiveRecord transaction boundaries

Rubydex can expose references to methods named `transaction`, but the semantic statement:

```text
these operations execute in one database transaction
```

requires Rails-aware interpretation of receiver/target and block/source structure.

Classification: `derived_static` at best.

It MUST remain `unknown` when the target cannot be resolved or when transaction behavior is hidden behind framework helpers/metaprogramming that the extractor does not understand.

### Rails callbacks

Rubydex can expose macro/method references and referenced callback methods, but callback execution semantics are framework meaning rather than a generic Rubydex relationship.

A Rails-aware extractor may derive facts such as:

```text
Order after_commit -> PublishOrder
```

only when the macro arguments and callback target are statically recoverable.

Classification: `derived_static`.

### Job/service invocation

Calls such as `perform_later`, `perform_async` or a project-specific service `.call` can be recognized from resolved method/constant references plus deterministic framework/project rules.

Classification: `derived_static` unless Rubydex directly exposes a resolved target that already represents the desired relation.

### External client call sites

Rubydex can locate references/calls to known client classes and methods. Deciding that a target is an external network boundary requires architecture/framework knowledge.

Classification: `derived_static + architecture knowledge`.

## Facts Rubydex does not establish by itself

### Runtime execution

Static reference/call possibility does not prove that a path executed for an incident or in production.

Source: OTel/traces/logs/runtime probes.

### Runtime concurrency or overlap

Two callable paths may exist without overlapping in practice.

Source: trace timing, job/runtime evidence, or an explicitly modeled concurrency guarantee.

### PostgreSQL wait-for graph and lock state

Source: PostgreSQL/pgBot/direct database probes.

### Exact row/resource lock acquisition

A model/table write does not fully specify the exact PostgreSQL lock resources or lock ordering for all SQL generated at runtime.

Source: a combination of deterministic SQL/data-access analysis and runtime database evidence.

### Complete Rails data-access semantics

Rubydex's generic Ruby semantic graph does not automatically mean:

```text
update! -> writes table X
find -> reads/locks row domain Y
association callback -> later writes Z
```

That requires a Rails-aware semantic layer.

### Metaprogrammed/dynamic behavior that cannot be resolved

`method_missing`, dynamic constantization, string-based dispatch, runtime-generated methods, reflective calls and configuration-dependent wiring can break static completeness.

The adapter must surface these as uncertainty/blind spots rather than silently producing a complete graph.

## D2.2 suitability matrix

| D2.2 fact | Rubydex alone | Rails-aware enrichment | Runtime/DB evidence |
| --- | --- | --- | --- |
| concrete class/method identity | strong | no | no |
| source location | strong | no | no |
| ancestor/descendant relation | strong | no | no |
| resolved constant reference | strong | no | no |
| resolved method target | partial/strong when non-null | no | no |
| caller -> callee | partial | useful | optional confirmation |
| Rails model -> table | partial | required for robust mapping | DB can confirm |
| transaction boundary | weak/partial | required | trace/DB can confirm behavior |
| write/read resource | weak | required | SQL/DB can confirm |
| X-before-Y resource order | not first-class | required | runtime can confirm observed path |
| path concurrency | no | maybe declared possibility | required for observed support |
| wait-for cycle | no | no | required |
| actual deadlock | no | no | required |

## Adapter recommendation

### Do not model Rubydex as only an incident probe

Rubydex indexes repository state. Its useful facts are versioned primarily by code revision, not incident TTL.

The first Causcope integration should therefore be passive fact ingestion:

```text
repository revision
  -> Rubydex graph/query
  -> deterministic adapter/enrichment
  -> concrete_system_facts
```

If later Causcope wants to invoke Rubydex on demand, the execution capability can be registered with the existing provider/router stack, but the semantic output should still be concrete system facts rather than fake `runtime_evidence` observations.

### Preserve machine-owned sets

The existing Rubydex Labs work already reached the useful invariant:

> Models may interpret evidence. Models must not reconstruct authoritative complete sets when a deterministic backend can preserve them.

Causcope should adopt the same behavior for completeness-sensitive static results:

- result membership owned by Rubydex/query/filter;
- count preserved;
- repository revision pinned;
- query/filter recorded;
- truncation/completeness explicit;
- model summaries never become authoritative membership.

### Preserve uncertainty explicitly

A Causcope imported fact should be able to say at least:

```text
direct
inferred
unresolved
```

and record the deriving rule for inferred facts.

Suggested invariant:

```text
Rubydex target == nil
  -> unresolved
  != no target exists
```

## Minimal WP-4 extractor experiment

Before building the Rails deadlock fixture, create a tiny extractor against an existing Ruby fixture that emits only facts Rubydex can prove directly:

```text
symbol declaration
source location
owner
ancestor/descendant
resolved constant reference
resolved method reference target
```

Then add Rails-aware facts one at a time and label each as derived:

```text
model -> table
transaction boundary
read/write resource
resource order
```

This makes it measurable exactly where Rubydex stops and Causcope-specific semantic enrichment begins.

## Decision

Rubydex is suitable as the **first semantic code backend** for the Causcope X-Ray work.

It is sufficient to begin WP-2/WP-4 because it provides deterministic identities, locations and several important relationship sets. It is not sufficient to skip a small Rails-aware fact extraction layer, and it must never be used as evidence that a static path actually executed or contended in production.

The first D2.2 implementation should therefore be designed around a provider-neutral `concrete_system_facts` contract with provenance/certainty, not around Rubydex-native node types.

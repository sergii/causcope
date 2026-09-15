# RFC 0084: Deterministic MCP agent acceptance benchmark

- Status: Implemented initial slice
- Date: 2026-09-15

## Decision

Add a second blind acceptance surface that drives canonical Causcope investigation state through MCP resources and MCP `tools/call`, then scores the finished state against the same hidden-oracle benchmark contract used by the deterministic local acceptance harness.

The first MCP benchmark uses:

```text
scenario.shop.mobile_bad_payload
```

and runs with no LLM credentials.

## Why a second acceptance surface exists

RFC 0083 proved that the bounded deterministic Causcope investigation loop can reach a hidden expected semantic result against a real Docker Compose fault.

That proves the core feedback loop. It does not by itself prove that an agent-facing transport can safely drive the same canonical state transitions.

The MCP benchmark therefore asks:

> Can a deterministic MCP client inspect current Causcope state, execute only server-authorized safe read-only diagnostic operations, advance canonical evidence revisions, and reach the hidden expected diagnosis without access to the oracle?

This is a transport/agent-surface proof, not a second diagnosis engine.

## Canonical flow

```text
fresh Shop Docker Compose system
  -> public incident report
  -> durable Investigation
  -> activate mobile payload fault
  -> verify public failing iOS request and healthy web control
  -> passive canonical runtime evidence revision 1
  -> deterministic diagnosis
  -> MCP routing resource
  -> highest-ranked currently safe/routable read-only probe
  -> MCP tools/call
  -> atomic canonical evidence + diagnosis commit
  -> evidence revision N + 1
  -> read current MCP routing again
  -> next eligible read-only probe
  -> bounded stop
  -> load hidden oracle
  -> score final canonical state
```

The hidden oracle is unavailable to the MCP client until the investigation has stopped.

## Scenario and hidden expected result

The public scenario says that some users cannot create orders while web checkout appears healthy. Its verification contract exposes one failing public request scope:

```text
method = POST
path = /orders
client_platform = iOS
app_version = 7.42.0
```

The hidden benchmark expectation is:

```text
target
  observation.http.request_failure

scope
  POST /orders
  iOS 7.42.0

leading hypothesis
  hypothesis.client.payload_contract_mismatch

required completed probes
  probe.http.compare_client_cohorts
  probe.database.inspect_lock_error_events

minimum evidence revision
  3
```

Probe order is not an oracle requirement. Semantic ranking and current execution eligibility determine the actual order.

## Why this first MCP proof uses the mobile scenario

The existing MCP direct-execution contract intentionally fails closed around the current server-authorized probe route.

The SQLite write-lock acceptance scenario has a valid semantic top probe that the Shop structured-log provider cannot execute. The autonomous loop already knows how to continue through the ranked list when an unavailable probe should not block a lower-ranked supported read-only discriminator.

The mobile scenario exposed the same general product issue during the first MCP benchmark attempt: the semantic top probe was not routable through the available Shop provider.

The benchmark must not solve this by:

```text
client-side skipping of arbitrary probes
rewriting semantic rank
pretending unavailable evidence is absent
changing the oracle to fit the transport
```

Instead this RFC adds an explicit server-side execution-eligibility projection.

## Ranked routable fallback

Causcope now has an initial bounded primitive for selecting:

```text
highest semantic probe rank
for which a current safe exact-scope direct route exists
```

The invariant is:

```text
semantic rank 1 remains semantic rank 1

if rank 1 is currently unroutable:
  it remains rank 1 in diagnosis
  it is not rejected
  it is not converted to absent evidence
  it is not silently reordered

execution authority may expose rank 2+
only when it is the highest-ranked probe with a safe current route
```

This is an execution eligibility decision, not a causal or probe-ranking algorithm.

The initial implementation is split into:

```text
scripts/routable_probe_selection.py
scripts/ranked_routable_projection.py
scripts/ranked_routable_mcp_tool.py
```

and the routing projection may expose:

```text
probe_rank
routing_strategy = ranked_routable_fallback
```

## MCP mutation boundary

After passive evidence revision 1 is persisted, benchmark evidence mutations occur only through MCP `tools/call`.

The ranked-routable tool is still revision- and identity-bound. Before execution the server recomputes the current choice and requires exact agreement on:

```text
incidentId
evidenceRevision
target
scope
probeId
instrumentId
```

A stale or client-invented probe/instrument identity is not execution authority.

Successful execution:

```text
safe read-only provider result
  -> canonical runtime evidence
  -> require at least one new evidence instance
  -> atomic evidence + diagnosis commit
  -> evidence revision increment
  -> deterministic rerank
```

## Shop routed provider

The benchmark wraps the already-existing Shop structured-log adapter as a standard fixed-exact routed provider:

```text
provider.shop.structured_logs
```

It supports only canonical read-only probes already implemented by the Shop adapter:

```text
probe.http.compare_client_cohorts
probe.database.inspect_lock_error_events
```

The wrapper does not assign hypotheses or causal weight. It only advertises capabilities, enforces exact scope, and returns the adapter's canonical evidence.

## Proven run

The real Docker Compose CI benchmark reached:

```text
initial evidence revision = 1
final evidence revision   = 3

completed MCP probes:
  probe.database.inspect_lock_error_events
  probe.http.compare_client_cohorts

final leading hypothesis:
  hypothesis.client.payload_contract_mismatch

stop:
  no_executable_route
```

Both required evidence instances preserve canonical probe provenance. The final hidden-oracle score is `passed: true`.

The stop state is legitimate. The benchmark proves bounded justified progress, not a requirement to execute every semantic probe in the catalog.

## LLM policy

This benchmark is deterministic and LLM-independent.

Child processes run without common AI-provider credentials:

```text
OPENAI_API_KEY
ANTHROPIC_API_KEY
GOOGLE_API_KEY
GEMINI_API_KEY
```

The result records:

```text
surface = deterministic_mcp_agent
llm.enabled = false
oracle_policy.loaded_after_investigation = true
oracle_policy.used_to_construct_diagnosis = false
```

A future LLM-backed MCP benchmark must use the same public-scenario/hidden-oracle discipline rather than receiving a different answer key.

## Relationship to RFC 0083

RFC 0083 and this RFC test different surfaces over the same canonical semantic contracts:

```text
RFC 0083
  deterministic local autonomous product loop

RFC 0084
  deterministic MCP agent loop
```

The first implemented scenarios differ because their currently available provider/safety contracts differ. They share the same benchmark methodology and oracle schema.

Cross-surface parity should become stricter over time. In particular, the same scenario should be runnable through multiple surfaces once each surface has explicit audited semantics for `insufficient_evidence` and provider fallback.

## Non-goals

This RFC does not add:

- an LLM;
- OpenAI API dependency;
- model-selected causal facts;
- client-authorized arbitrary probe skipping;
- arbitrary subprocess execution;
- write-capable remediation;
- automatic production changes;
- a new causal-ranking algorithm.

## Definition of Done

The initial slice is complete when CI proves:

1. public failing scope is derived without oracle access;
2. passive evidence creates revision 1;
3. MCP exposes only server-authorized routable operations for the selected scope;
4. a higher-ranked unroutable semantic probe does not block a lower-ranked safe routable probe;
5. semantic ranking itself is not rewritten;
6. every mutation is an MCP `tools/call` after revision 1;
7. two canonical read-only probe results advance evidence to at least revision 3;
8. evidence preserves probe provenance and exact scope;
9. final leading hypothesis satisfies the hidden oracle;
10. the oracle is loaded only after investigation stops;
11. no LLM credential is required;
12. existing deterministic benchmark, autonomous Shop loop, Investigator CLI, target-aware routing, and semantic validation remain green.

## Next slice

The next acceptance surface may be an LLM-backed MCP client using a real model API.

That benchmark should test the model as a client of Causcope rather than move diagnosis authority into the model:

```text
LLM decides how to navigate exposed MCP resources/tools
Causcope remains authority for canonical evidence, rank, scope, safety, and execution eligibility
hidden oracle remains unavailable until scoring
```

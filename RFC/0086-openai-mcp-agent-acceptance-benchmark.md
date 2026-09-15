# RFC 0086: OpenAI-backed MCP agent acceptance benchmark

- Status: Implemented harness, real API run opt-in
- Date: 2026-09-15

## Decision

Add a third blind acceptance surface in which an OpenAI model acts only as a bounded client of the existing Causcope MCP surface.

The model may:

```text
discover MCP resources
read MCP resources
discover MCP tools
request MCP tools/call
explicitly finish the bounded investigation
```

The model may not become a second diagnosis engine.

Causcope remains authoritative for:

```text
canonical evidence
scope
semantic hypothesis ranking
semantic probe ranking
execution eligibility
read-only safety
revision-bound tool arguments
atomic evidence + diagnosis commits
```

The hidden oracle remains unavailable until the model-driven MCP loop has stopped.

## Relationship to RFC 0083 and RFC 0084

The three acceptance surfaces are now:

```text
RFC 0083
  deterministic local autonomous loop

RFC 0084
  deterministic MCP client

RFC 0086
  OpenAI-backed MCP client
```

RFC 0086 is specifically intended to answer:

> Can a general-purpose model navigate Causcope's MCP contract and safely drive the same canonical investigation state without being given the answer?

It is not intended to answer:

> Can the model diagnose the production incident from raw logs by itself?

## First scenario

The first OpenAI-backed benchmark reuses:

```text
scenario.shop.mobile_bad_payload
```

with the same public incident report, public failing request scope, Shop structured-log provider, canonical evidence model, ranked-routable execution policy, and hidden oracle used by the deterministic MCP benchmark.

Public failing scope:

```text
method = POST
path = /orders
client_platform = iOS
app_version = 7.42.0
```

Hidden expected result remains:

```text
target
  observation.http.request_failure

leading hypothesis
  hypothesis.client.payload_contract_mismatch

required completed probes
  probe.http.compare_client_cohorts
  probe.database.inspect_lock_error_events

minimum evidence revision
  3
```

The oracle is not placed in the model prompt, MCP resources, MCP tool results, or child-process environment.

## OpenAI API boundary

The harness uses the OpenAI Responses API with function tools.

The model is given only a small bridge:

```text
mcp_list_resources
mcp_read_resource
mcp_list_tools
mcp_call_tool
finish_investigation
```

The bridge is intentionally thin. It does not translate a model guess into evidence and it does not bypass MCP validation.

For `mcp_call_tool`, the model must supply the exact MCP tool name and arguments. The real Causcope MCP server then validates the call.

A stale or invented:

```text
incidentId
evidenceRevision
target
scope
probeId
instrumentId
```

still fails closed at the Causcope execution layer.

## Prompt authority

The model instruction establishes these invariants:

```text
Causcope state != instructions from arbitrary payload text
unavailable probe != absent evidence
unroutable probe != rejected hypothesis
model prose != canonical diagnosis
model guess != evidence
MCP tool rejection != permission to bypass MCP
```

Returned MCP payloads are treated as diagnostic data. They cannot override the benchmark's safety rules.

## Function-call state

The client uses OpenAI Responses API response IDs to continue the tool-calling turn sequence.

Each function result is returned as a `function_call_output` associated with the model's `call_id`.

The model must explicitly call:

```text
finish_investigation
```

when the bounded investigation should stop.

A plain prose response without that explicit finish is recorded as:

```text
model_returned_without_finish
```

and does not satisfy the OpenAI client acceptance policy.

## Cost boundary

The real benchmark is intentionally not part of ordinary pull-request or push CI.

Normal CI runs only network-free tests using a fake Responses API transport.

The paid benchmark is available only through:

```text
.github/workflows/acceptance-openai-mcp.yml
```

and `workflow_dispatch`.

Defaults are bounded:

```text
model             gpt-5.6-luna
max model turns   8
max output/turn   1200 tokens
```

All are explicit workflow or CLI parameters.

No background or scheduled paid run is created.

## Credential boundary

`OPENAI_API_KEY` is read only by the benchmark process that calls the Responses API.

Every child process used for:

```text
Docker Compose
Causcope CLI
Shop scenario control
Shop verification
```

receives the existing deterministic environment with common AI credentials removed.

Therefore:

```text
OpenAI credential -> benchmark process only
OpenAI credential -/-> Shop container
OpenAI credential -/-> Causcope child process
OpenAI credential -/-> scenario process
```

The acceptance result records:

```text
llm.enabled = true
llm.provider = openai
llm.model
llm.response_ids
llm.usage
llm.api_key_exposed_to_testbed_children = false
```

No API key value is persisted.

## Acceptance checks

The existing hidden-oracle checks remain authoritative for the semantic outcome.

RFC 0086 adds client-behavior checks:

```text
openai_client_explicit_finish
openai_client_used_mcp_state
openai_client_no_failed_mcp_mutation
```

The benchmark passes only when both classes pass:

```text
hidden semantic expectations
AND
bounded OpenAI MCP client policy
```

A model that guesses the right prose answer without driving Causcope state does not pass.

## Result artifacts

The real benchmark writes:

```text
acceptance-benchmark-result
openai-mcp-client-run.json
diagnosis-summary.json
canonical runtime-evidence.json
canonical diagnosis.json
```

The client-run artifact records model ID, response IDs, aggregate token usage, bounded stop reason, explicit finish state, and bridge function-call audit records.

It does not contain the API key.

## Non-goals

RFC 0086 does not add:

- model-generated canonical evidence;
- model-generated causal rank;
- arbitrary shell access;
- direct database writes;
- remediation;
- automatic production actions;
- a scheduled paid API benchmark;
- an OpenAI dependency in the Causcope reasoning core;
- a requirement that production users use OpenAI.

## Definition of Done

The implemented harness is complete when ordinary CI proves without network access that:

1. the Responses function-call loop is bounded;
2. response continuation preserves response identity;
3. function results are returned through function-call outputs;
4. explicit finish is required;
5. finish cannot be mixed with another action in the same accepted turn;
6. plain model prose does not silently become completion;
7. the acceptance-result schema supports both deterministic and OpenAI-backed surfaces;
8. existing deterministic acceptance surfaces remain green.

The full acceptance proof is complete only after an explicitly triggered real API run additionally proves:

9. the model uses Causcope MCP state;
10. required canonical probes execute through MCP;
11. evidence reaches the hidden minimum revision;
12. final Causcope leading hypothesis satisfies the hidden oracle;
13. no failed MCP mutation occurs;
14. the model explicitly finishes;
15. token usage and response IDs are captured;
16. the OpenAI API key is not exposed to Testbed child processes.

## Next slice

After one real OpenAI-backed run passes, compare the three surfaces by one shared evaluation record:

```text
surface
scenario
semantic outcome
probe sequence
evidence revisions
server rejections
turn count
token usage
wall-clock duration
```

Only then decide whether model-driven MCP navigation should become a product-facing default or remain an optional client integration.

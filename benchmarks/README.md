# Causcope acceptance benchmarks

Causcope acceptance benchmarks test a complete bounded investigation against a hidden real fault.

They are different from mechanism labs:

```text
lab/
  -> does this mechanism behave as claimed?

lab/investigation/
  -> does the investigator follow the intended reasoning protocol?

acceptance benchmark
  -> can the product or agent surface investigate a running fault and reach the hidden expected semantic result?
```

## Deterministic local benchmark

The first canonical benchmark is:

```text
scenario.shop.sqlite_write_lock
```

Run it from the repository root:

```bash
python scripts/run_acceptance_benchmark.py \
  --scenario sqlite-write-lock \
  --workspace /tmp/causcope-acceptance \
  --result /tmp/causcope-acceptance.json
```

The runner:

```text
fresh Docker Compose shop
  -> create Investigation from public incident summary
  -> activate hidden SQLite write-lock fault
  -> verify public symptom
  -> run bounded deterministic autonomous Causcope investigation
  -> stop investigation
  -> load hidden oracle
  -> score canonical diagnosis
```

The oracle is never passed to the Causcope process.

## Deterministic MCP agent benchmark

The second implemented acceptance surface drives canonical investigation state through MCP resources and MCP tools rather than through the in-process autonomous loop.

Its first scenario is:

```text
scenario.shop.mobile_bad_payload
```

Run it with:

```bash
python scripts/run_mcp_acceptance_benchmark.py \
  --workspace /tmp/causcope-mobile-mcp \
  --result /tmp/causcope-mcp-acceptance.json
```

The flow is:

```text
fresh Docker Compose shop
  -> public incident report
  -> durable Investigation
  -> activate hidden mobile payload fault
  -> verify public failing iOS request + healthy web control
  -> passive runtime evidence revision 1
  -> deterministic diagnosis
  -> MCP routing resource
  -> server-authorized highest-ranked safely routable probe
  -> MCP tools/call
  -> atomic canonical evidence + diagnosis revision
  -> re-read MCP routing
  -> next routed read-only probe
  -> bounded stop
  -> load hidden oracle
  -> score canonical diagnosis
```

After revision 1, evidence-changing diagnostic operations in this benchmark are performed through MCP tool calls.

The initial proof reaches evidence revision 3 with both:

```text
probe.http.compare_client_cohorts
probe.database.inspect_lock_error_events
```

and the hidden expected leading hypothesis:

```text
hypothesis.client.payload_contract_mismatch
```

The order of required probes is not part of the oracle contract.

### Ranked routable execution

Semantic probe ranking and execution eligibility are intentionally separate.

If semantic rank 1 has no current safe route, MCP does not pretend that evidence is absent and does not rewrite the ranking. The server may expose the highest-ranked later probe for which a safe exact-scope direct route exists.

```text
semantic ranking
  rank 1 -> still rank 1, currently unroutable
  rank 2 -> safe direct route exists

MCP execution projection
  -> may authorize rank 2

canonical diagnosis
  -> semantic rank remains unchanged
```

The MCP mutation controller recomputes the selection at call time and binds execution to exact incident, evidence revision, target, scope, probe, and instrument identity.

## OpenAI-backed MCP agent benchmark

The third acceptance surface keeps the same Causcope authority boundaries but lets a real OpenAI model decide how to navigate the MCP surface.

It reuses:

```text
scenario.shop.mobile_bad_payload
surface = openai_mcp_agent
```

The model does not receive raw oracle data and does not become diagnosis authority. Its bridge is limited to:

```text
mcp_list_resources
mcp_read_resource
mcp_list_tools
mcp_call_tool
finish_investigation
```

Causcope remains authoritative for canonical evidence, semantic ranking, exact scope, read-only safety, execution eligibility, and revision-bound state commits.

Run locally only when you explicitly want to make paid OpenAI API requests:

```bash
OPENAI_API_KEY=... \
python scripts/run_openai_mcp_acceptance_benchmark.py \
  --model gpt-5.6-luna \
  --workspace /tmp/causcope-openai-mcp \
  --result /tmp/causcope-openai-mcp.json
```

The same real benchmark is available through the manual-only workflow:

```text
.github/workflows/acceptance-openai-mcp.yml
```

It uses `workflow_dispatch` only. It does not run on normal pushes or pull requests and is not scheduled.

Default cost bounds are:

```text
model             gpt-5.6-luna
max model turns   8
max output/turn   1200 tokens
```

The model and both limits are explicit CLI/workflow parameters.

`OPENAI_API_KEY` is used only by the benchmark process. Docker, the Shop testbed, Causcope CLI children, and scenario-control subprocesses receive an environment with common AI credentials removed.

The OpenAI client must explicitly call `finish_investigation`. A prose answer without that function call is recorded as a bounded client-policy failure rather than being accepted as a diagnosis.

### Proven real API run

A real paid OpenAI run passed on 2026-09-15 using GitHub Actions run `35025847376` and `gpt-5.6-luna`.

Observed result:

```text
hidden oracle             PASS
final evidence revision   3
leading hypothesis        hypothesis.client.payload_contract_mismatch
completed probes          probe.database.inspect_lock_error_events
                          probe.http.compare_client_cohorts
failed MCP mutations      0
explicit finish           yes
model turns/responses     7
input tokens              64,549
output tokens             909
total tokens              65,458
API key in testbed child  no
```

The model first inspected MCP resources/tools, executed both server-authorized read-only probes with exact revision-bound arguments, re-read Causcope state after each mutation, and explicitly stopped when the remaining semantic probe had no safe direct route.

The schema-valid persisted result is:

```text
benchmarks/results/2026-09-15-openai-mcp-mobile-bad-payload.json
```

The hidden oracle was loaded only after the model-driven investigation stopped and was not used to construct the diagnosis.

## LLM independence of the core

The deterministic local and deterministic MCP acceptance surfaces remove common AI-provider credentials from child processes:

```text
OPENAI_API_KEY
ANTHROPIC_API_KEY
GOOGLE_API_KEY
GEMINI_API_KEY
```

They prove Causcope's canonical evidence and investigation contracts independently of model behavior.

The OpenAI-backed surface is additive. It evaluates a model as a client of Causcope, not as a replacement for Causcope reasoning.

## Result

The commands emit a machine-readable `acceptance_benchmark_result` and exit:

```text
0  benchmark passed
1  benchmark completed but failed hidden expectations
2  benchmark infrastructure/contract error
```

The result schema is:

```text
schema/acceptance-benchmark-result.schema.json
```

Current surfaces include:

```text
deterministic_shop_autonomous
deterministic_mcp_agent
openai_mcp_agent
```

The hidden expected Causcope outcome lives beside scenario ground truth in:

```text
testbed/shop/scenarios/<slug>/oracle.json
```

Public `scenario.json` files are validated so oracle-only benchmark keys cannot leak into investigator input.

## Cross-surface rule

Acceptance surfaces should reuse the same semantic scenario/oracle discipline rather than inventing surface-specific answers.

The first local proof uses the SQLite scenario while both MCP surfaces use the mobile scenario. Over time the benchmark matrix should run the same scenarios through every applicable surface once each surface has explicit audited semantics for provider fallback and insufficient evidence.

Current and planned surfaces are:

```text
deterministic local loop      implemented + proven
deterministic MCP agent       implemented + proven
OpenAI-backed MCP agent       implemented + real API proven
Dashboard                     planned
Cloud / Relay                 planned
```

Presentation and client strategy may differ. Canonical scope, evidence provenance, authorization boundaries, and semantic diagnosis should not drift silently.

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

## No LLM dependency

Both implemented acceptance surfaces remove common AI-provider credentials from benchmark child processes:

```text
OPENAI_API_KEY
ANTHROPIC_API_KEY
GOOGLE_API_KEY
GEMINI_API_KEY
```

An LLM token is not required for either deterministic benchmark.

This is deliberate. These benchmarks prove Causcope's canonical evidence and investigation contracts independently of model behavior.

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
```

The hidden expected Causcope outcome lives beside scenario ground truth in:

```text
testbed/shop/scenarios/<slug>/oracle.json
```

Public `scenario.json` files are validated so oracle-only benchmark keys cannot leak into investigator input.

## Cross-surface rule

Acceptance surfaces should reuse the same semantic scenario/oracle discipline rather than inventing surface-specific answers.

The first local and MCP proofs currently use different Shop scenarios because the available provider and safety contracts differ. Over time the benchmark matrix should run the same scenario through multiple surfaces once each surface has explicit audited semantics for provider fallback and insufficient evidence.

Current and planned surfaces are:

```text
deterministic local loop      implemented
deterministic MCP agent       implemented
LLM-backed MCP agent          next candidate
Dashboard                     planned
Cloud / Relay                 planned
```

Presentation and client strategy may differ. Canonical scope, evidence provenance, authorization boundaries, and semantic diagnosis should not drift silently.

# Causcope acceptance benchmarks

Causcope acceptance benchmarks test a complete bounded investigation against a hidden real fault.

They are different from mechanism labs:

```text
lab/
  -> does this mechanism behave as claimed?

lab/investigation/
  -> does the investigator follow the intended reasoning protocol?

acceptance benchmark
  -> can the product investigate a running fault and reach the hidden expected semantic result?
```

## Canonical benchmark

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

The deterministic benchmark also strips common AI-provider credentials from child processes. An OpenAI, Anthropic, Gemini, or other LLM token is not required to pass it.

## Result

The command emits a machine-readable `acceptance_benchmark_result` and exits:

```text
0  benchmark passed
1  benchmark completed but failed hidden expectations
2  benchmark infrastructure/contract error
```

The result schema is:

```text
schema/acceptance-benchmark-result.schema.json
```

The hidden expected Causcope outcome lives beside the scenario ground truth in:

```text
testbed/shop/scenarios/<slug>/oracle.json
```

Public `scenario.json` files are validated so oracle-only benchmark keys cannot leak into investigator input.

## Cross-surface rule

Future surfaces should reuse the same public scenario and hidden oracle rather than creating surface-specific answer keys.

Planned comparisons include:

```text
deterministic local loop
MCP agent
LLM-backed MCP agent
Dashboard
Cloud / Relay
```

Presentation may differ. Canonical scope, evidence provenance, and semantic diagnosis should not drift silently.

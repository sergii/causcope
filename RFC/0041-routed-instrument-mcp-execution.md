# RFC 0041: Revision-bound routed instrument MCP execution

- Status: Accepted
- Date: 2026-09-14

## Summary

Causcope may execute a direct external diagnostic provider over MCP only when the caller repeats the exact route advertised by the current diagnosis revision.

The mutation tool is:

```text
causcope.instrument.execute_routed
```

It accepts:

- `incidentId`
- `evidenceRevision`
- `target`
- `scope`
- `probeId`
- `instrumentId`

These are not free-form execution instructions. They form an optimistic-concurrency and route-identity assertion against the current diagnosis.

## Preconditions

Execution fails closed unless all of the following are still true while the incident mutation claim is held:

1. `incidentId` equals the current diagnosis incident.
2. `evidenceRevision` equals the current diagnosis revision.
3. `target + scope` identify exactly one current diagnosis.
4. `probeId` is still the top-ranked canonical probe for that diagnosis.
5. the instrument router still selects `instrumentId` for that probe and scope.
6. the selected route supports `execution_mode=direct`.
7. the provider still passes its own read-only, contract, scope, and availability checks.
8. the runtime evidence file belongs to the same incident.
9. execution produces at least one new canonical evidence instance.

A stale route is an error, not permission to execute the old action.

## Mutation sequence

```text
current diagnosis revision N
        ↓
acquire incident mutation claim
        ↓
re-read current diagnosis
        ↓
revalidate exact routed action
        ↓
execute selected direct provider
        ↓
canonical runtime_evidence
        ↓
compose with current evidence
        ↓
build diagnosis revision N+1
        ↓
atomically replace evidence file
        ↓
atomically replace diagnosis snapshot
        ↓
release claim
```

Runtime evidence remains authoritative. The diagnosis snapshot remains a deterministic projection that can be rebuilt from evidence.

The two files are not claimed to be a filesystem-wide ACID transaction. Each replacement is atomic and cooperative writers are serialized by the existing POSIX filesystem-claim mechanism. A future durable state-store slice may make the evidence-plus-projection commit transactional across process crashes.

## MCP exposure

The routing MCP server exposes this tool only with explicit process opt-in:

```text
--enable-routed-provider-tools
--runtime-evidence <path>
```

A configured direct provider is also required.

When the mutation is enabled, the read-only routing projection changes only the execution-availability annotation:

```yaml
agent_action:
  kind: use_external_instrument
  mcp_execution_available: true
```

This does not change hypothesis ranking, probe ranking, provider selection, or scope semantics.

## Safety properties

The tool cannot:

- choose a different probe from the current top-ranked probe;
- choose a different instrument from the router selection;
- widen or change scope;
- execute non-read-only probes;
- execute host session-style probes as a fake one-shot action;
- mutate remediation state;
- accept a stale diagnosis revision;
- convert insufficient provider evidence into negative evidence.

## Concurrency

The mutation reuses the existing filesystem claim layer with an incident-level identity:

```text
purpose = routed_instrument_mutation
identity = { incident_id }
```

This serializes cooperative routed evidence writers across processes.

## Result

A successful call returns the previous and new evidence revisions, the exact executed canonical probe and instrument, the newly added evidence instance IDs, and the timestamp of the recomputed diagnosis.

The next routed-agent-plan read is therefore based on the new evidence revision and may recommend a different probe or stop investigation.

## Deferred work

This RFC intentionally does not add:

- remediation execution;
- non-read-only provider actions;
- cross-file ACID storage;
- provider cost or evidence-quality optimization;
- automatic retries after `insufficient_evidence`;
- multi-provider fan-out.

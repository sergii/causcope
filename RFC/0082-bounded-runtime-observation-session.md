# RFC 0082: Bounded runtime observation session

- Status: Proposed implementation slice
- Date: 2026-09-15

## Decision

Add a bounded local orchestration command:

```bash
causcope runtime observe <rails-root> -- <application-command>
```

The command composes existing Causcope contracts instead of adding a new diagnosis or evidence model.

Its responsibility is lifecycle orchestration:

```text
current Investigation
  -> validate workspace objectives
  -> start exact OTLP receiver
  -> launch one revision-bound instrumented application command
  -> wait for successful bounded command completion
  -> stop receiver
  -> require captured concrete runtime facts
  -> run existing incident seed
  -> produce diagnosis revision 1
```

## Why this exists

The Rails/PostgreSQL local-agent path already proves all of the individual reasoning steps, but the user currently has to coordinate them manually:

```text
runtime start
application launch / reproduce
receiver stop
runtime seed
```

This RFC removes lifecycle ceremony without weakening evidence provenance or target identity.

## Bounded command semantics

The first slice deliberately supports only an application command that exits on its own with status `0`.

It is not yet an interactive long-running Rails server/session supervisor.

A non-zero application exit means:

```text
observation session failed
runtime seed not attempted
no diagnosis revision created by this command
```

Long-running server mode, signal forwarding, explicit stop/finalize, and multi-process orchestration are deferred until this bounded primitive is proven useful.

## Reused contracts

`runtime observe` reuses:

```text
Concrete System Facts
Investigation identity from workspace compatibility state
Workspace Objectives
portable Rails runtime binding
OTLP concrete receiver
Concrete Runtime Facts
runtime relationship projection
Resource Topology
incident seed revision 1
causal ranking
probe ranking
exact target resolution
```

It must not implement parallel versions of those contracts.

## Objective policy

The observation session requires valid workspace objectives before starting the application command.

The first slice depends on:

```text
observation.http.request_latency
observation.database.connection_pool_wait_time
```

No numeric defaults are invented by `observe`.

If objectives are absent or invalid, the application command is not started.

## Revision and identity policy

The application command is launched through the existing revision-bound Rails runtime wrapper.

The pinned static revision is passed explicitly to that wrapper, and the wrapper still enforces the Causcope system/revision environment identity used by Rails instrumentation.

The receiver is bound to the current Investigation identity and writes the standard snapshot:

```text
.causcope/runtime/<investigation-id>.json
```

## Receiver lifecycle

The command starts the existing OTLP receiver and waits until its health endpoint is available before launching the application command.

For this first slice the receiver port must be explicit and non-zero. Dynamic port discovery is deferred.

After the application command completes, the receiver is terminated and the standard snapshot is passed to the existing `runtime seed` path.

If no explicitly bound runtime facts were captured, Causcope fails closed and does not seed a diagnosis.

## Seed policy

The orchestration layer delegates revision-1 creation to the existing incident seed path.

Therefore all existing seed requirements remain authoritative:

```text
same Investigation
explicit objectives
exact request trace
exact ActiveRecord pool interaction
explicit runtime relationship
single exact topology target
empirically grounded causal alternatives
existing deterministic next-probe ranking
```

Optional `--code-symbol` and `--trace-id` selectors are forwarded to the existing seed path.

Existing seed artifacts are not overwritten unless `--force-seed` is explicit.

## Security boundary

`causcope runtime observe` executes a command explicitly supplied by the local user.

That does **not** authorize a generic Cloud or Relay remote-shell capability.

The trust boundary remains:

```text
local CLI user explicitly chooses application command
!=
Causcope Cloud may execute arbitrary customer commands
```

Future Relay/Cloud execution must continue to use capability-constrained typed operations rather than reusing this local CLI command as remote arbitrary execution.

## Output

A successful bounded session returns a product result containing:

```text
Investigation identity
system + revision
OTLP endpoint
runtime snapshot path
application exit code = 0
existing incident_seed_result
```

The canonical evidence and diagnosis remain the standard workspace artifacts, not data embedded only in the orchestration result.

## Initial Definition of Done

The slice is complete when CI proves:

1. workspace objectives are checked before the application command runs;
2. the receiver is ready before the application command starts;
3. a bounded command can emit exact OTLP request + ActiveRecord pool evidence;
4. the runtime snapshot is persisted under the current Investigation;
5. revision 1 is seeded through the existing incident-bootstrap implementation;
6. the result resolves the exact PostgreSQL target and existing next discriminator;
7. a missing objective prevents application execution;
8. a non-zero application exit does not create a diagnosis;
9. existing Investigator, semantic, Rails golden, and D3.1 proof paths remain green.

## Next step after this RFC

If the bounded primitive is stable, the next product surface may compose it from `causcope why`, for example:

```text
causcope why "checkout is slow" --observe -- <bounded-command>
```

That should remain a product wrapper over the same Investigation and runtime contracts rather than a new agent state machine.

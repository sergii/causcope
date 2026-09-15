# RFC 0082: Bounded runtime observation session

- Status: Implemented initial slice
- Date: 2026-09-15

## Decision

Provide a bounded local orchestration primitive:

```bash
causcope runtime observe <rails-root> -- <application-command>
```

and compose that primitive from the Agent First product front door:

```bash
causcope why "checkout is slow" --observe <rails-root> -- <application-command>
```

Neither command adds a new diagnosis, evidence, ranking, routing, or agent state machine.

The lower-level observation primitive owns lifecycle orchestration:

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

The `why --observe` product wrapper adds only:

```text
create/resume the same Investigation
  -> delegate to runtime observe
  -> render the resulting persisted diagnosis through normal causcope why
```

## Why this exists

The Rails/PostgreSQL local-agent path already proved all individual reasoning steps, but previously required manual coordination:

```text
runtime start
application launch / reproduce
receiver stop
runtime seed
why
```

The bounded observation primitive removes receiver/application/seed lifecycle ceremony.

The `why --observe` composition removes one more product-layer handoff without weakening evidence provenance, execution authorization, or target identity.

## Bounded command semantics

The first slice deliberately supports only an application command that exits on its own with status `0`.

It is not yet an interactive long-running Rails server/session supervisor.

A non-zero application exit means:

```text
observation session failed
runtime seed not attempted
no diagnosis revision created by this command
```

Long-running server mode, signal forwarding, explicit stop/finalize, and multi-process orchestration remain deferred.

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

`why --observe` reuses `runtime observe` and then the normal persisted `why` projection. It does not bypass or duplicate these contracts.

## Objective policy

The observation session requires valid workspace objectives before starting the application command.

The first slice depends on:

```text
observation.http.request_latency
observation.database.connection_pool_wait_time
```

No numeric defaults are invented by `observe` or `why --observe`.

If objectives are absent or invalid, the application command is not started.

## Investigation and workspace policy

`why --observe` creates or resumes the same Investigation that the observation session will use.

When `--workspace` is omitted, the product wrapper uses:

```text
<rails-root>/.causcope
```

rather than `.causcope` relative to an unrelated shell working directory.

This prevents scoping state and runtime evidence from silently landing in different workspaces.

If `diagnosis.json` already exists, `why --observe` refuses to start another initial observation session. The user should continue with normal `causcope why` or explicitly authorize a later provider read with `causcope why --acquire`.

## Revision and identity policy

The application command is launched through the existing revision-bound Rails runtime wrapper.

The pinned static revision is passed explicitly to that wrapper, and the wrapper still enforces the Causcope system/revision environment identity used by Rails instrumentation.

The receiver is bound to the current Investigation identity and writes the standard snapshot:

```text
.causcope/runtime/<investigation-id>.json
```

## Receiver lifecycle

The command starts the existing OTLP receiver and waits until its health endpoint is available before launching the application command.

For this first slice the receiver port must be non-zero. Dynamic port discovery is deferred.

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

Optional `--code-symbol` and `--trace-id` selectors on the lower-level primitive are forwarded to the existing seed path.

Existing seed artifacts are not overwritten unless the lower-level `--force-seed` is explicit.

## Product-front-door authorization boundaries

`why --observe` and `why --acquire` are intentionally different operations.

```text
--observe
  -> execute the explicit local bounded application command supplied by the user
  -> collect first-party runtime evidence
  -> seed diagnosis revision 1

--acquire
  -> execute one already-ranked safe read-only diagnostic provider operation
  -> append evidence to an existing Investigation
  -> rerank
```

They cannot be combined in one invocation.

`why --observe` also cannot be combined with the specialized golden-proof inputs or `--require-confirmed`.

This preserves a visible authorization boundary between reproducing/observing the problem and querying another diagnostic provider.

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

A successful lower-level bounded session returns a result containing:

```text
Investigation identity
system + revision
OTLP endpoint
runtime snapshot path
application exit code = 0
existing incident_seed_result
```

The canonical evidence and diagnosis remain standard workspace artifacts.

A successful `why --observe` invocation does not invent another wrapper diagnosis format. After observation it returns the ordinary `causcope why` projection from those persisted artifacts.

## Implemented CI proof

CI now proves:

1. workspace objectives are checked before the application command runs;
2. the receiver is ready before the application command starts;
3. a bounded command can emit exact OTLP request + ActiveRecord pool evidence;
4. the runtime snapshot is persisted under the current Investigation;
5. revision 1 is seeded through the existing incident-bootstrap implementation;
6. the result resolves the exact PostgreSQL target and existing next discriminator;
7. a missing objective prevents application execution;
8. a non-zero application exit does not create a diagnosis;
9. `why --observe` creates/resumes the same Investigation and defaults to `<rails-root>/.causcope`;
10. `why --observe` returns the normal persisted diagnosis projection and does not auto-acquire provider evidence;
11. a second initial `why --observe` is rejected when diagnosis already exists;
12. `--observe` and `--acquire` cannot be combined;
13. existing Investigator, acquisition, Rails golden, and D3.1 proof paths remain green.

## Next step

The next product question is no longer whether Causcope can enter the investigation loop from `why`.

For the bounded Rails/PostgreSQL path, it can.

The next useful work should focus on one of these concrete product gaps:

```text
interactive long-running observation with explicit lifecycle semantics
further convergence of ordinal Investigation diagnosis with confirmed D3.1 X-Ray proof
additional empirically grounded symptom bootstrap paths
shared Dashboard projection of the same Investigation state
```

Any next abstraction should preserve the current property that local UX improvements compose existing contracts instead of creating parallel reasoning paths.

# Local Agent First flow

Status: Implemented bounded Rails/PostgreSQL path

This page is the shortest product-level description of the current local Causcope flow.

It is intentionally a projection of existing contracts, not a separate architecture.

## One-time setup

Discover the Rails/PostgreSQL system, exact ActiveRecord pool mapping, PostgreSQL target, and safe pgbot provider binding:

```bash
causcope bootstrap . \
  --database app_production \
  --database-url-env CAUSCOPE_PRODUCTION_DATABASE_URL
```

Install the portable Rails runtime integration if it is not already present:

```bash
causcope rails install .
```

Declare the explicit comparison objectives used by the current bounded incident-bootstrap slice:

```bash
causcope objectives set . \
  --request-latency-ms 200 \
  --pool-wait-ms 50
```

Causcope does not invent these numbers and does not treat one incident trace as a learned baseline.

## Start and observe an Investigation

The current product-shaped bounded path is:

```bash
causcope why "checkout is slow" \
  --observe . \
  -- <bounded-application-command>
```

When `--workspace` is omitted, this uses:

```text
<rails-root>/.causcope
```

The command composes existing layers:

```text
problem statement
  -> create/resume Investigation
  -> validate workspace objectives
  -> start existing OTLP receiver
  -> wait until receiver is ready
  -> run the explicit bounded command through revision-bound Rails instrumentation
  -> collect exact request + ActiveRecord pool runtime facts
  -> stop receiver
  -> project runtime relationships
  -> seed canonical evidence revision 1
  -> rank empirically grounded alternatives
  -> choose next discriminator
  -> resolve exact operational target
  -> render ordinary persisted `causcope why` diagnosis
```

For the current Rails connection-pool slice, a representative revision-1 result is:

```text
observed
  request latency above declared objective
  ActiveRecord checkout wait above declared objective

candidates
  1. hypothesis.database.connection_pool_exhaustion
  2. hypothesis.latency.database

next discriminator
  probe.database.measure_query_latency

exact target
  pool:active_record.primary
    -> db.<database>.prod
```

This is candidate ranking, not root-cause confirmation.

## Continue the Investigation

Plain:

```bash
causcope why
```

reads the persisted Investigation state and does not execute a live diagnostic provider.

When Causcope has one current, exact, safe, read-only provider route, the user may explicitly authorize the next evidence acquisition step:

```bash
causcope why --acquire
```

That path is:

```text
current diagnosis revision N
  -> ranked next probe
  -> exact target
  -> configured provider instance
  -> revalidate revision + route + provider + target
  -> execute one safe read-only evidence operation
  -> append canonical evidence
  -> atomic diagnosis commit
  -> revision N + 1
  -> rerank
```

Observation and provider acquisition remain separate authorization boundaries.

```text
--observe
  local user explicitly runs one bounded instrumented application command

--acquire
  user explicitly authorizes one ranked read-only diagnostic provider operation
```

They cannot be combined in one `why` invocation.

## Lower-level/debugging surfaces

The composed front door does not remove the lower-level commands.

For debugging or workflows that need manual lifecycle control, Causcope still exposes:

```bash
causcope runtime start .
# reproduce / emit traces
causcope runtime seed .
causcope why
```

The bounded lifecycle primitive is also directly available:

```bash
causcope runtime observe . -- <bounded-application-command>
```

These commands produce and consume the same canonical workspace artifacts.

## Canonical workspace artifacts

The current path uses:

```text
.causcope/
  concrete-system-facts.json
  resource-topology.yaml
  pgbot-postgresql.yaml
  provider-bindings.yaml
  objectives.yaml
  incident-context.yaml        # compatibility name; Investigation is the intended parent concept
  runtime/<investigation-id>.json
  runtime-evidence.json
  runtime-relationships.json
  diagnosis.json
```

Cloud, Dashboard, Relay, Helm, and enterprise integrations should project or transport these semantic contracts rather than introduce a second reasoning model.

## Safety invariants

The current local flow intentionally fails closed on conditions such as:

```text
missing objectives
wrong Investigation identity
wrong revision
missing exact runtime binding
ambiguous target
provider drift
wrong database identity
stale diagnosis revision
non-zero bounded application exit
no bound runtime facts
partial provider execution failure
```

Unknown evidence remains unknown.

Natural-language similarity does not authorize target selection or provider execution.

## What this proves

For one bounded Rails/PostgreSQL slice, Causcope now has a product path from:

```text
human problem statement
  -> observed runtime evidence
  -> causal alternatives
  -> best next discriminator
  -> exact operational target
  -> optional explicit evidence acquisition
  -> reranked diagnosis
```

without requiring Causcope Cloud.

The next product work should improve lifecycle ergonomics, knowledge breadth, and human/team projections without weakening this contract.

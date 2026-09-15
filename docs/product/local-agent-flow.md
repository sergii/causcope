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
  -> choose next discriminator per diagnosis
  -> resolve exact operational targets
  -> form safe read-only execution sets
  -> if one set has a unique best semantic discrimination priority, acquire it
  -> atomically commit the next evidence revision
  -> rerank
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

is now both the persisted Investigation projection and the autonomous diagnostic continuation point.

When Causcope has one or more current, exact, safe, read-only provider execution sets, it compares their current top semantic probes using the existing deterministic discrimination priority. If one set is strictly better, Causcope executes it without asking the operator to choose the semantic probe, target, provider, or acquisition command.

```text
current diagnosis revision N
  -> ranked next semantic probe per diagnosis
  -> exact targets
  -> configured provider instances
  -> ready read-only execution sets
  -> unique best semantic diagnostic question
  -> revalidate revision + route + provider + target
  -> execute one safe read-only evidence operation/set
  -> append canonical evidence
  -> atomic diagnosis commit
  -> revision N + 1
  -> rerank before choosing anything else
```

If no execution set is ready, `causcope why` only renders current state. If several sets share the same best semantic priority, Causcope also renders without mutation rather than using target, probe, scope, provider, or execution-set names as an arbitrary tie-break.

The old `--acquire` parser input may remain temporarily for compatibility, but it is not operator-visible product UX and is not required by the canonical flow.

Observation remains a distinct boundary because the bounded application command is chosen by the operator:

```text
--observe -- <command>
  explicit bounded application execution

normal why continuation
  only semantic-probe-ranked, exact-target, capability-constrained read-only provider execution
```

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
semantic priority tie across ready diagnostic questions
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
  -> best next discriminator per diagnosis
  -> exact operational targets
  -> bounded selection among multiple ready diagnostic questions
  -> autonomous bounded read-only evidence acquisition
  -> reranked diagnosis
  -> causal verification when the required intervention evidence exists
```

without requiring Causcope Cloud and without exposing the internal acquisition step as operator UX.

The next product work should improve lifecycle ergonomics, knowledge breadth, and human/team projections without weakening this contract.
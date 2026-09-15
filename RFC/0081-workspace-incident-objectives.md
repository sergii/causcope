# RFC 0081: Workspace incident objectives

- Status: Proposed implementation slice
- Date: 2026-09-15

## Decision

Add a small machine-readable workspace contract for explicit incident-bootstrap objectives:

```text
.causcope/objectives.yaml
```

The first version supports exactly two observations used by the bounded Rails/PostgreSQL incident bootstrap:

```text
observation.http.request_latency
observation.database.connection_pool_wait_time
```

Both use milliseconds and an `above` threshold supplied explicitly by the user.

## Why

`causcope runtime seed` currently requires two threshold flags on every invocation. Those values are not incidental command parameters. They are part of the evidence interpretation contract that decides whether a runtime measurement is materially outside the expected operating objective.

Persisting them in the workspace makes the investigation reproducible and keeps the values inspectable instead of hiding them in shell history.

## Non-goals

This RFC does not define a general SLO platform, adaptive baseline engine, percentile objective model, error budget, or automatic threshold discovery.

Causcope must not infer these objectives from a single incident trace.

Learned baselines and declared objectives are different semantic objects and may be modeled separately later.

## Contract

Example:

```yaml
schema_version: "0.1"
kind: workspace_objectives
objectives:
  - observation: observation.http.request_latency
    operator: above
    threshold:
      value: 200.0
      unit: ms
    source:
      type: user_declared
  - observation: observation.database.connection_pool_wait_time
    operator: above
    threshold:
      value: 50.0
      unit: ms
    source:
      type: user_declared
```

The source is explicit because a future workspace may contain objectives imported from another control plane. v0.1 only accepts `user_declared`.

## CLI

Configure once:

```bash
causcope objectives set . \
  --request-latency-ms 200 \
  --pool-wait-ms 50
```

Inspect:

```bash
causcope objectives show .
```

Then incident bootstrap can use:

```bash
causcope runtime seed .
```

without repeating threshold flags.

## Precedence

The resolution rule is deterministic:

```text
explicit CLI threshold
  > workspace objective
  > fail closed
```

A CLI threshold is an explicit one-run override. It does not mutate the workspace objective.

If either required objective is missing and no CLI override supplies it, incident bootstrap stops. There are no built-in numeric defaults.

## Safety properties

The objectives only decide whether already-observed measurements cross an explicit boundary. They do not establish causal diagnosis.

The existing incident-bootstrap requirements remain unchanged:

```text
same Investigation
revision-bound runtime facts
exact trace identity
exact ActiveRecord pool interaction
exact runtime relationship
exact topology target
existing deterministic causal ranking
```

Crossing both objectives is therefore necessary for this bounded seed path, but it is not equivalent to confirming connection-pool exhaustion.

## Relationship to evidence

The resolved objective threshold becomes the `baseline` value of the canonical measurement emitted by the current bounded seed path.

This is a product-level comparison baseline, not a statement that historical runtime behavior was measured at exactly that value.

## Future extension

A later model may distinguish at least:

```text
declared objective
historical baseline
learned anomaly boundary
provider-native alert threshold
SLO target
```

Those should not be collapsed into one field merely because each can be represented numerically.

# Operational terminology

Status: Product terminology guide

This document summarizes the intended operational meaning of the main Causcope concepts. The canonical semantic definitions remain in the repository vocabulary and RFCs.

## Signal

Something emitted, reported, or received that may be relevant.

Examples:

```text
Datadog monitor fired
Sentry issue created
Kubernetes OOMKilled event
engineer says checkout is failing
```

A signal is an input. It is not automatically evidence and does not automatically imply an incident.

## Symptom

An observed deviation from expected behavior and an entry point into the diagnostic graph.

Examples:

```text
S1 High CPU
S3 High latency
S4 Transaction failed
S6 Database connection failed
```

A symptom answers roughly:

> What appears wrong?

It does not answer why.

## Observation

A concrete scoped fact measured or reported about the system.

Examples:

```text
PostgreSQL returned SQLSTATE 40P01
CPU user time = 92%
connection pool checkout wait = 2.4s
```

## Context

Relevant surrounding information that may help discriminate hypotheses but is not yet evidence of causality.

Examples:

```text
deploy occurred two minutes before onset
customer is on iOS 7.42
failure occurs only in eu-central-1
```

Context can become evidence when connected to a specific prediction or investigation question.

## Evidence

An observation interpreted in a diagnostic context.

Evidence may:

```text
support a hypothesis
contradict a hypothesis
constrain scope
falsify a candidate explanation
```

Evidence should preserve provenance.

## Failure mechanism

A reusable mechanism by which a system can fail or degrade.

Examples:

```text
D2.2 Deadlock
D2.3 Serialization failure
D3.1 Application DB connection-pool exhaustion
N2.3 TCP connection establishment timeout
Q2.2 ACK before durable effect
```

The short catalog code is a navigation address. Canonical semantic IDs remain authoritative identity.

## Hypothesis

A candidate explanation under consideration in one investigation.

A catalogued failure mechanism can become a hypothesis when the current symptom/scope makes it plausible.

A useful hypothesis predicts observations that can be checked and defines evidence that would make it less likely.

## Probe

A diagnostic operation intended to gather discriminating evidence.

Examples:

```text
inspect PostgreSQL deadlock counters/errors
inspect blocked sessions
query connection pool wait
compare recent deploys
inspect DNS resolution result
```

## Finding

The interpreted result of a probe or experiment.

A finding should be connected back to the observation/evidence it produced and the hypotheses it changes.

## Investigation

The canonical Causcope case/state object.

It collects:

```text
trigger
scope
context
observations
evidence
hypotheses
probe history
diagnosis
timeline
recommendations
verification
external incident links
```

An Investigation may exist without a formal incident.

## Incident

An operational lifecycle object representing a problem serious enough to be managed as an incident under a team's policy.

It normally carries concepts such as:

```text
severity
ownership
acknowledgement
paging
escalation
status
communications
```

PagerDuty, ServiceNow, Jira Service Management, or another system may be the incident system of record.

Causcope should not equate:

```text
signal == incident
symptom == incident
error == incident
investigation == incident
```

## Diagnosis

The best currently supported explanation of the observed problem, including contributing factors and relevant uncertainty.

Causcope should not assume every failure has one singular root cause.

## Cause and contributing factor

A cause participates in the mechanism that explains the failure.

A contributing factor increases likelihood or impact without necessarily being sufficient by itself.

Useful additional causal roles include:

```text
trigger
necessary condition
latent condition
proximate cause
failed defense
amplifier
mitigating factor
```

## Mitigation vs fix

```text
Mitigation
  reduces or stops current impact

Fix
  addresses the underlying mechanism or causal factor
```

A rollback may be a mitigation even when it does not explain the mechanism.

## Verification

Evidence that a mitigation or fix produced the intended outcome and did not merely coincide with recovery.

## Failure domain vs mechanism

The top-level catalog domains are navigation families, not incidents or error types:

```text
R  Resource and runtime
D  Database and persistence
N  Network and transport
Q  Queue and messaging
E  External dependencies
A  Application and logic
I  Infrastructure and operating system
F  Filesystem and storage
X  Security and identity
```

A mechanism such as `D2.2 Deadlock` lives primarily under one catalog domain while still participating in a broader ontology graph.

## Compact investigation chain

```text
Signal
  -> Symptom
  -> scoped Observations / Context
  -> candidate Hypotheses / Failure Mechanisms
  -> discriminating Probe
  -> Evidence / Finding
  -> hypothesis update
  -> Diagnosis
  -> Mitigation / Fix
  -> Verification
```

A formal Incident can be attached at the beginning, created later by policy, or never exist at all.

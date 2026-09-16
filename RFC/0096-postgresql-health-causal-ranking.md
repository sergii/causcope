# RFC 0096: PostgreSQL health causal reachability

Status: Implemented proof
Date: 2026-09-16

## Context

RFC 0095 added a direct read-only PostgreSQL health provider for blocking chains, long-running transactions, and vacuum/autovacuum health. The provider could execute those semantic probes, but two of the new hypotheses and the existing lock-contention hypothesis were not upstream nodes of `observation.http.request_latency` in the causal graph.

That meant provider capability existed without product reachability: a normal request-latency Investigation could not rank those hypotheses, so probe ranking could not select their PostgreSQL health questions for the bounded autonomous loop.

## Decision

Make the three PostgreSQL health hypotheses explicit upstream candidates for request latency with conservative causal edges:

```text
hypothesis.database.lock_contention
  -> observation.http.request_latency
  strength: strong

hypothesis.database.long_running_transaction
  -> observation.http.request_latency
  strength: moderate

hypothesis.database.autovacuum_pressure
  -> observation.http.request_latency
  strength: weak
```

The strengths are intentionally different. A request-critical lock wait is a direct latency mechanism. A long-running transaction needs additional correlation to the affected request or a retained resource. Vacuum pressure is only a weak candidate until persistent maintenance pressure is connected to degraded request-critical database work.

## Ranking rule

No PostgreSQL-specific ranking code is added.

The existing causal ranking and probe ranking remain authoritative:

```text
request latency
  -> upstream causal candidates
  -> deterministic ordinal ranking
  -> semantic probe discrimination
  -> exact target/provider routing
  -> bounded autonomous acquisition
  -> rerank
```

Once the graph contains the missing causal relationships, the existing ranking machinery can expose:

```text
probe.database.inspect_lock_waits
probe.database.inspect_long_running_transactions
probe.database.inspect_vacuum_health
```

as ordinary read-only discriminating questions.

## Sequential investigation

Resolving one PostgreSQL health question must not collapse the remaining questions merely because they share one provider. Probe resolution remains semantic and observation-based. For example, resolving `observation.database.long_running_transaction` removes the long-transaction probe from the unresolved set while lock-wait and vacuum-health questions remain independently rankable when they still discriminate current candidates.

This is the property required by the bounded autonomous Investigation loop to move through more than one PostgreSQL discriminator across evidence revisions.

## Safety

This RFC adds only causal graph reachability. It does not expand provider permissions. All three PostgreSQL health probes remain `read_only`, exact-target routing remains required, and the direct PostgreSQL collector remains bounded to catalog reads.

The new edges also do not turn a point-in-time PostgreSQL finding into root-cause proof. Their conditions explicitly require request-critical-path or target correlation, and vacuum pressure remains a weak relationship.

## Contract-first verification

The acceptance contract was committed before implementation. On tests-only head `62d02834ad5c19c56af1c6fa05f6c88a43f34ebc`, the dedicated workflow failed all three tests because none of the PostgreSQL health hypotheses or probes were reachable from request latency.

The implementation adds only the missing causal edges. The tests were not relaxed or rewritten.

## Non-goals

This RFC does not claim that every long transaction is harmful, that every blocking chain affects the reported request, or that crossing an autovacuum threshold proves current latency impact. It does not add remediation, state-changing probes, probabilities, provider-specific ranking weights, or automatic causal verification for these hypotheses.

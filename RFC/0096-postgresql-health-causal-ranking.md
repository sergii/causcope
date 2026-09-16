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

No PostgreSQL-specific semantic ranking code is added.

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

## Provider-specific information gain

A semantic probe may have more possible outputs than one provider can measure. `probe.database.inspect_lock_waits`, for example, includes `lock_wait_time`, `lock_wait_event`, and `blocking_chain`, while the direct PostgreSQL health snapshot intentionally maps only `lock_wait_event` and `blocking_chain` because a point-in-time catalog read cannot measure wait duration precisely.

After the provider has resolved the observations it can measure, the semantic probe can still remain unresolved because another instrument could answer `lock_wait_time`. The information-gain router must therefore distinguish:

```text
safe provider
  != informative provider for the remaining discriminator
```

A base-safe provider with zero provider-mapped discriminating candidate pairs is no longer selected. Routing stops with `no_informative_provider` instead of re-executing a provider that cannot add evidence for the remaining question. This prevents bounded autonomous investigation from spending revisions on no-op repeated reads while preserving the semantic probe for another capable instrument.

This is a generic information-gain guard, not a PostgreSQL-specific ranking weight.

## Safety

This RFC does not expand provider permissions. All three PostgreSQL health probes remain `read_only`, exact-target routing remains required, and the direct PostgreSQL collector remains bounded to catalog reads.

The new edges also do not turn a point-in-time PostgreSQL finding into root-cause proof. Their conditions explicitly require request-critical-path or target correlation, and vacuum pressure remains a weak relationship.

## Contract-first verification

The causal-reachability acceptance contract was committed before implementation. On tests-only head `62d02834ad5c19c56af1c6fa05f6c88a43f34ebc`, the dedicated workflow failed all three tests because none of the PostgreSQL health hypotheses or probes were reachable from request latency.

While checking the resulting autonomous path, a second independent regression was found: the information-gain router would still select a safe provider even when that provider mapped none of the remaining discriminating observations. A new regression test was committed before that router fix; on head `2794e4cd709450160288ee99a432fa3c00040dda`, the zero-gain provider test failed while the causal-ranking tests already passed.

Neither contract was relaxed after implementation.

## Non-goals

This RFC does not claim that every long transaction is harmful, that every blocking chain affects the reported request, or that crossing an autovacuum threshold proves current latency impact. It does not add remediation, state-changing probes, probabilities, provider-specific ranking weights, or automatic causal verification for these hypotheses.

# RFC 0052: Concrete retry-induced duplicate side-effect X-Ray

- Status: Proposed
- Date: 2026-09-14
- Scope: WP-7 of RFC 0045, second non-database Concrete System X-Ray proof

## Summary

RFC 0051 completes the first Concrete System X-Ray vertical slice for PostgreSQL D2.2 deadlocks. RFC 0045 requires a second proof in a different domain so the model is not accidentally database-specific.

This RFC binds existing duplicate-delivery/idempotency semantics to one concrete retryable Ruby job and an external business side effect:

```text
revision-pinned retryable job
  + external charge side effect
  + bounded source evidence that the supported client path sends no idempotency key
  -> PRECONDITIONS_PRESENT

+ first exact job execution commits provider effect
+ caller observes timeout / ambiguous outcome
+ same stable job and business identity retries
+ second exact execution commits a second provider effect
+ canonical duplicate-side-effect observation
+ idempotency-key recovery preserves retry shape but applies one provider effect
  -> CAUSAL_DIAGNOSIS_CONFIRMED
```

The proof reuses:

```text
hypothesis.messaging.duplicate_delivery
symptom.messaging.duplicate_business_effect_observed
observation.application.duplicate_side_effect
```

No new global failure ontology is introduced.

## Why Q2.1 is reused

The existing Q2.1 claim already captures the important generic mechanism: a stable unit of work can be delivered again after processing fails to become durably successful, and a non-idempotent handler can apply the protected effect twice.

The concrete fixture is intentionally transport-neutral. It models a stable retryable job identity rather than claiming that a particular Sidekiq/Redis acknowledgement protocol was observed.

Therefore:

```text
same stable job retried after failed processing
```

is used as the concrete binding to the generic duplicate-delivery family, while broker-specific observations remain unknown unless a broker provider supplies them.

## Concrete static facts

The fixture contains:

```text
CapturePaymentJob#perform()
  retry policy: enabled, max 3
  -> PaymentsClient.charge(payment_id)
  -> external:payments
```

A conservative source enrichment adds existing `concrete_system_facts` entities and relations:

```text
code:CapturePaymentJob#perform()
  maps_to job:CapturePaymentJob

job:CapturePaymentJob
  depends_on external:payments
```

The dependency fact carries bounded context:

```text
retry_enabled=true
retry_max=3
effect_operation=charge
business_identity=payment_id
idempotency_key=absent_in_supported_client_source
negative_evidence_scope=app/services/payments_client.rb
```

No schema extension is required.

## Negative evidence boundary

The static scanner is deliberately narrow. It recognizes only the supported fixture shape and checks the supported `PaymentsClient` source for an `Idempotency-Key` request path.

Thus:

```text
absent_in_supported_client_source
```

means exactly that.

It does not mean:

```text
provider has no deduplication
another middleware cannot add a key
all application paths are non-idempotent
```

If the supported client source contains idempotency-key evidence, the unsafe static precondition is no longer emitted.

## Live ambiguous-outcome proof

The integration test runs the real Ruby job and `PaymentsClient` source against an in-process HTTP payments provider.

Unsafe scenario:

1. attempt 1 sends a charge without an idempotency key;
2. provider commits effect #1;
3. provider delays its response;
4. Ruby client times out, so the caller cannot know whether the effect happened;
5. the same stable job/business identity is retried;
6. provider commits effect #2;
7. retry returns successfully.

The expected evidence is:

```text
client attempt 1: timeout
provider effect 1: committed
client attempt 2: success
provider effect 2: committed
same job_id
same business_event_id
two distinct provider effect IDs
```

## Exact execution binding

Each unsafe Ruby execution is wrapped in an OTel-shaped concrete execution span carrying:

```text
causcope.code_symbol
causcope.system_id
causcope.revision
causcope.job_id
causcope.business_event_id
```

Provider requests carry exact trace/span identifiers. Causal confirmation requires each provider effect to bind one-to-one to one of the two exact revision-bound job executions.

Nearest-time guessing and fuzzy symbol matching are not allowed.

## Canonical runtime evidence

The live lab also emits existing canonical runtime evidence:

```text
observation.application.duplicate_side_effect = observed
measurement.value = 2 provider_effects
boundary = boundary.application.external_dependency
```

This keeps concrete provider correlation separate from reusable diagnostic semantics.

## Counterfactual idempotency recovery

The same provider is then exercised with:

```text
same timeout
same retry shape
same business identity
stable Idempotency-Key
```

The first request commits one effect and times out. The retry is accepted but deduplicated to the existing effect.

Expected result:

```text
attempts = 2
provider effects = 1
retry_deduplicated = true
```

The recovery is an experimental counterfactual. It does not rewrite the revision-pinned unsafe source facts.

## Confirmation rule

`CAUSAL_DIAGNOSIS_CONFIRMED` is reachable only when all of the following are true:

1. revision-pinned static facts contain the retry + external-side-effect + bounded missing-idempotency precondition;
2. the effect evidence, concrete runtime facts and static facts identify the same system and revision;
3. both unsafe attempts share one stable job ID and business-event identity;
4. attempt 1 is an exact concrete execution whose provider effect committed before the caller observed a timeout;
5. attempt 2 is another exact execution of the same concrete code path;
6. attempt 2 commits a second distinct provider effect for the same business identity;
7. canonical runtime evidence records `observation.application.duplicate_side_effect = observed` with effect count 2;
8. the protected counterfactual uses one stable idempotency key, preserves timeout + retry, and commits exactly one provider effect.

Any broken identity or missing discriminating fact fails closed.

## Epistemic progression

The second vertical slice uses the same principle as D2.2:

```text
PRECONDITIONS_PRESENT
  retryable concrete job + external effect + bounded missing idempotency evidence

AMBIGUOUS_OUTCOME_OBSERVED
  provider effect committed but caller timed out

RETRY_OBSERVED
  same stable job/business identity executes again

EVENT_OBSERVED
  second distinct provider effect is applied

CAUSAL_DIAGNOSIS_CONFIRMED
  exact execution/effect binding + canonical duplicate observation + idempotency counterfactual
```

These are derived proof stages, not persisted probabilities.

## Security and execution model

The live provider and timeout injection are test-harness interventions only.

Production Causcope MUST NOT create duplicate charges or destructive external side effects to test a hypothesis. Production diagnosis should consume passive traces, provider logs/audit APIs, application logs, queue metadata and safe read-only probes.

## Fail-closed cases

The verifier rejects:

- tampered trace/span identity;
- changed business identity on one provider effect;
- cross-incident canonical evidence;
- missing idempotent counterfactual recovery;
- revision mismatch;
- static idempotency evidence changing from bounded-absent to present;
- provider effects that do not bind one-to-one to exact unsafe executions.

## Non-goals

This RFC does not add:

- a production Sidekiq/Redis provider;
- a universal HTTP client static analyzer;
- provider-specific Stripe semantics;
- a claim that every retry is unsafe;
- a claim that source-level key absence proves downstream non-idempotency;
- production side-effect execution by autonomous probes;
- automatic remediation.

## Result for RFC 0045

This is the requested second non-database Concrete System X-Ray proof. The reusable architecture now spans at least two qualitatively different mechanisms:

```text
D2.2 database deadlock
  static resource ordering + runtime concurrency + DB wait cycle

Q2.1-style duplicate side effect
  static retry/effect path + ambiguous runtime outcome + retry + provider effect identity
```

Both use the same separation:

```text
generic knowledge
  x concrete revision-bound facts
  x runtime evidence
  -> inspectable risk / event / causal confirmation
```

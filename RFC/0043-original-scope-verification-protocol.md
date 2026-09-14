# RFC 0043: Original-scope incident verification protocol

- Status: Accepted
- Date: 2026-09-14

## Summary

Causcope must not close an incident merely because a broad metric becomes green after a fix.

Verification is a first-class runtime protocol bound to the original failing diagnosis scope and baseline evidence revision.

```text
original failing diagnosis
        ↓
freeze target + exact scope + baseline revision
        ↓
fix applied
        ↓
collect post-fix canonical evidence
        ↓
evaluate only the original scope
        ↓
resolved | regressed | inconclusive
```

The first implementation introduces two runtime record kinds:

- `verification_contract`
- `verification_result`

They are runtime records, not reusable ontology concepts.

## Contract

A verification contract freezes:

- `incident_id`;
- `baseline_evidence_revision`;
- the original diagnosis `target`;
- the exact normalized `original_scope`;
- `fix_applied_at`;
- one or more canonical observation criteria.

For v0 every criterion asks for an explicit post-fix `absent` state.

The contract may only be created for an exact `target + scope` diagnosis that exists in the pinned baseline snapshot. This prevents a caller from silently widening or changing the failing cohort during verification.

## Why exact original scope matters

A fixed control cohort is not evidence that the failing cohort recovered.

For example:

```text
incident:
  checkout fails for iOS 7.42.0

invalid verification:
  web checkout succeeds

valid verification:
  checkout failure is explicitly absent
  for the original iOS 7.42.0 scope
```

Verification therefore retains the same exact-scope isolation used by diagnosis and routed probes.

## Evidence semantics

Missing evidence is never success.

An `absent` result must already exist as explicit canonical runtime evidence. The verification protocol does not turn provider silence, missing findings, or lack of errors into absence.

Only evidence satisfying all of the following participates:

1. same incident;
2. same exact normalized scope;
3. same criterion observation;
4. `observed_at >= fix_applied_at`;
5. `observed_at <= evaluated_at`;
6. not expired at `evaluated_at`.

Pre-fix evidence, future evidence, expired evidence, and evidence from another cohort are ignored.

## Latest-state rule

For each criterion, the latest eligible timestamp decides the current verification state.

- latest state `absent` -> criterion `resolved`;
- latest state `observed` -> criterion `regressed`;
- no eligible evidence -> criterion `inconclusive`.

If both `observed` and `absent` exist at the same latest timestamp, verification fails toward `regressed`. A simultaneous failure observation must never be hidden by a green sample.

## Overall outcome

```text
any criterion regressed
  -> regressed

all criteria resolved
  -> resolved

otherwise
  -> inconclusive
```

This deliberately makes `resolved` the strongest state. It requires affirmative post-fix evidence for every declared criterion.

## Relationship to diagnosis

Diagnosis and verification answer different questions:

```text
diagnosis:
  what most plausibly explains the incident?

verification:
  does the original failing cohort still exhibit the declared failure condition after the fix?
```

A diagnosis becoming lower confidence does not imply resolution. Likewise, a successful verification does not retroactively prove that the chosen root-cause hypothesis was correct.

## v0 command surface

`scripts/verification_protocol.py` provides two deterministic operations:

```bash
python scripts/verification_protocol.py create \
  --snapshot diagnosis.json \
  --target observation.http.request_failure \
  --scope original-scope.json \
  --fix-applied-at 2026-09-14T12:00:00Z
```

and:

```bash
python scripts/verification_protocol.py evaluate \
  --contract verification-contract.json \
  --evidence runtime-evidence.json \
  --as-of 2026-09-14T12:05:00Z
```

The protocol reuses canonical observations and runtime evidence rather than inventing a second evidence system.

## Deliberate boundaries

v0 does not:

- execute fixes;
- infer absence from silence;
- widen a verification scope;
- automatically choose a waiting period;
- define statistical SLO recovery thresholds;
- verify unrelated cohorts as substitutes;
- claim that a green metric alone closes the incident;
- mutate incident status.

Those can be added later without weakening the core invariant:

> A resolved incident requires affirmative post-fix evidence against the original failing scope.

## Next work

The next useful slice is to connect this protocol to the routed agent plan so that, after a fix is recorded, the agent receives a verification plan and can route the required read-only verification probes through the same instrument-selection machinery used for diagnosis.

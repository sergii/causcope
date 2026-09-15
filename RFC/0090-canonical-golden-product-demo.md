# RFC 0090: Canonical golden product demo

- Status: Implemented proof
- Date: 2026-09-15
- Scope: Make the live Rails connection-pool demonstration prove the normal canonical Investigation path end to end, without invoking the legacy three-artifact X-Ray renderer.

## Decision

The primary live golden demo is now a product proof, not a compatibility proof.

It must start from the normal front door and end at canonical causal verification:

```text
causcope bootstrap
  -> causcope why "checkout is slow"
  -> one persisted Investigation
  -> real Rails request + OTLP runtime facts
  -> exact ActiveRecord pool interaction
  -> canonical diagnosis revision 1
  -> bounded pool mechanism/control/recovery evidence
  -> canonical evidence revision 2
  -> causal_verification.status = verified
  -> causcope why --require-confirmed
```

The demo must not pass `--static`, `--runtime`, or `--pool` to `causcope why`.

Those flags remain an explicit compatibility surface under RFC 0089, but they are no longer the live golden product path.

## Why this is the product boundary

The earlier D3.1 live demo proved a real failure mechanism and a useful X-Ray projection, but the final confirmation still entered through a Rails-specific renderer.

RFCs 0085 through 0089 moved the epistemic authority into persisted canonical Investigation state. The missing proof was compositional: demonstrate that the same real Rails/PostgreSQL experiment can travel through that authority from beginning to end.

RFC 0090 closes that gap.

## Live path

`scripts/demo_canonical_rails_pool.sh` performs seven bounded stages.

### 1. Bootstrap system state

The normal bootstrap command creates revision-bound system facts, exact resource topology, and provider bindings in one workspace. It creates no runtime evidence and no diagnosis.

### 2. Start one Investigation

The normal `causcope why "checkout is slow"` front door creates the persisted Investigation/scoping state. The demo reads the generated incident identity and reuses it for all later runtime facts.

The problem statement does not create a diagnosis by itself.

### 3. Observe the real mechanism

The existing OTLP receiver and portable Rails runtime capture a real request against `lab/rails-connection-pool` while the concrete probe forces ActiveRecord pool contention with `DB_POOL=1`.

The same bounded probe also records the independent PostgreSQL control and the post-release recovery sample.

### 4. Seed canonical diagnosis revision 1

`causcope runtime seed` selects one exact slow request that also has elevated pool checkout wait and exactly one runtime target binding.

It writes ordinary canonical runtime evidence and the first diagnosis revision. The leading hypothesis must emerge from the causal graph rather than from the concrete probe.

### 5. Import canonical verification evidence

`causcope runtime import-pool` binds the concrete proof back to the exact canonical seed and atomically projects mechanism, control, and recovery evidence into revision 2.

The resource-pool artifact remains an evidence source. It is not a diagnosis authority.

### 6. Require canonical causal verification

The normal product command is:

```bash
./bin/causcope why "checkout is slow" \
  --workspace <workspace> \
  --require-confirmed
```

`--require-confirmed` succeeds only when the canonical `causal_verification` projection contains a verified claim.

### 7. Preserve the proof

The workspace remains inspectable after the demo. Its authority is:

```text
runtime-evidence.json
  + diagnosis.json
  -> causal_verification
```

No legacy X-Ray artifact flags participate in the final result.

## CI contract

`.github/workflows/golden-rails-demo.yml` is now the live canonical golden-product workflow.

It starts a real PostgreSQL 17 service, installs the Rails lab dependencies, runs the full demo, then invokes `causcope why --require-confirmed --json` again from the persisted workspace.

The exact-head CI assertion requires:

- `kind = causcope_why`;
- `status = diagnosis_available`;
- `diagnosis.evidence_revision = 2`;
- exactly one causal-verification claim;
- claim status `verified`;
- hypothesis `hypothesis.database.connection_pool_exhaustion`;
- intervention kind `resource_capacity_release`;
- intervention resource `pool:active_record.primary`.

This is intentionally a live integration proof rather than a fixture-only unit test.

## Compatibility demo

`scripts/demo_rails_pool.sh` remains available as the explicit Rails X-Ray compatibility proof defined by RFC 0089.

It is no longer the workflow named or treated as the golden product demo.

## Non-goals

This RFC does not generalize arbitrary interventions, authorize production remediation, make Rails the product architecture, replace the autonomous read-only investigation loop, or claim that every diagnosis can already reach canonical verification automatically.

It proves one complete product path with real runtime behavior and one canonical epistemic authority.

## Product rule

New golden slices should terminate in canonical Investigation state and normal product surfaces.

A mechanism-specific proof may remain useful as an instrument or compatibility projection, but it must not become a parallel diagnosis or verification authority.

## Next step

Use this demo as the acceptance boundary for the next generalization: connect autonomous semantic probe selection and provider execution to canonical verification so a bounded Investigation can progress from symptom to verified claim without a mechanism-specific import command being the operator-visible step.

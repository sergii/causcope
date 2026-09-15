# RFC 0092: Implicit semantic-probe acquisition

Status: Implemented proof

Date: 2026-09-16

## Decision

Once a canonical Investigation has a diagnosis revision, exact target resolution, and exactly one safe ready read-only execution set, normal `causcope why` may execute that set without a separate operator-visible acquisition flag.

The product path becomes:

```text
problem
  -> bounded observation
  -> canonical evidence revision 1
  -> ranked hypotheses
  -> ranked semantic probe
  -> exact runtime target
  -> safe provider selection
  -> bounded read-only acquisition
  -> one atomic evidence revision
  -> rerank
  -> causal verification
```

The operator asks the debugging question. Causcope owns the next diagnostic read when the existing routing contracts prove that the read is safe and unambiguous.

## Why

`--acquire` exposed an internal orchestration boundary as product UX. By revision 1 Causcope already knows:

- the ranked semantic probe;
- the exact operational target;
- eligible provider instances;
- runner capabilities;
- whether the route is read-only and executable;
- the revision-bound execution-set contract.

Requiring a human to repeat authorization for that deterministic diagnostic read did not add diagnostic information. It only leaked the internal execution model into the CLI.

## Safety boundary

Implicit acquisition is deliberately narrower than arbitrary autonomous execution.

It happens only when:

1. canonical runtime evidence exists;
2. exact target resolution exists;
3. at least one direct provider binding exists;
4. the existing InstrumentRouter and information-gain router produce executable read-only routing;
5. `build_routed_execution_sets` produces exactly one `ready` execution set.

If zero sets are ready, `causcope why` remains a read-only projection of current state.

If more than one set is ready, Causcope does not choose an arbitrary set in this proof. A later policy may rank multiple independent ready sets, but that decision must be explicit and tested.

No write/remediation capability is introduced by this RFC.

## Existing machinery remains authoritative

Implicit acquisition does not bypass or duplicate the existing execution path. It still uses:

```text
semantic probe ranking
  -> runtime target resolution
  -> InstrumentRouter
  -> information-gain provider selection
  -> routed execution set
  -> execution-set journal
  -> incident mutation claim
  -> provider provenance validation
  -> one atomic evidence + diagnosis commit
```

The acquisition flag is removed from operator-visible help and from the canonical golden demo. The parser may temporarily accept the old flag as a hidden compatibility input, but product documentation must not require it.

## Tests-first contract

The behavior was locked before implementation.

The tests require that:

- the canonical Rails demo contains no `--acquire`;
- `causcope why --help` does not advertise `--acquire`;
- plain `causcope why --json` executes the one safe ready exact-target semantic probe;
- the result advances exactly one evidence revision through the existing routed execution-set controller;
- exact target identity remains present in acquired evidence scope and provenance;
- the human projection reports the acquisition;
- the Rails golden proof reaches `--require-confirmed` without a manual acquisition flag.

Those contract tests were committed before the implementation and were not weakened to make the implementation pass.

## Relationship to earlier RFCs

This RFC supersedes the operator-authorization part of RFC 0078 for bounded read-only provider acquisition. RFC 0078 remains authoritative for workspace provider bindings, provider identity, credential indirection, and fail-closed target validation.

It also advances RFC 0091. RFC 0091 removed the manual `runtime import-pool` step but still exposed `why --acquire`; this RFC removes that remaining operator-visible orchestration step.

RFC 0082's explicit bounded application command remains a separate boundary. `--observe -- <command>` executes application code selected by the operator. Provider evidence acquisition after the resulting revision is different: it is constrained by semantic probe ranking, exact-target routing, provider capabilities, and the read-only execution-set contract.

## Golden product command

After revision 1 exists, the canonical proof is now:

```bash
causcope why "checkout is slow" --workspace .causcope --require-confirmed
```

There is no manual semantic-probe choice, provider choice, target choice, evidence import, or acquisition flag in that command.

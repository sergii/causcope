# RFC 0042: Crash-recoverable incident state commit

- Status: Accepted
- Date: 2026-09-14

## Summary

Routed external-provider execution now persists its runtime evidence and deterministic diagnosis projection through a small write-ahead commit journal instead of two unrelated atomic file replacements.

The goal is narrow: if the process dies after a routed provider has produced justified canonical evidence, the next routed mutation deterministically rolls the exact evidence + diagnosis revision forward rather than continuing from a torn pair.

This is crash recovery for the current filesystem architecture. It is deliberately **not** described as a general ACID database or globally atomic multi-file visibility.

## Problem

RFC 0041 serialized cooperative writers with the incident filesystem claim and atomically replaced each file:

```text
runtime-evidence.json
        ↓
diagnosis.json
```

A process crash between those replacements can leave new evidence beside the previous diagnosis revision. The evidence remains authoritative and diagnosis is rebuildable, but a routed agent should not have to reason about this transient torn state.

## Commit protocol

Before publishing either target file, Causcope creates a durable journal next to the diagnosis snapshot:

```text
diagnosis.json.commit.json
```

The journal contains:

- incident identity;
- previous and next evidence revision;
- canonical hash of the complete next runtime evidence document;
- canonical hash of the complete next diagnosis snapshot;
- the complete next runtime evidence document;
- the complete next diagnosis snapshot.

The sequence is:

```text
provider returns canonical evidence
        ↓
compose evidence + build diagnosis revision N+1
        ↓
write + fsync commit journal
        ↓
fsync journal directory
        ↓
replace + fsync runtime evidence
        ↓
replace + fsync diagnosis snapshot
        ↓
unlink commit journal + fsync directory
```

The durable journal is the commit point. Once it exists, recovery rolls forward to the exact documents captured by it.

## Recovery

Every routed mutation runs recovery while holding the existing incident mutation claim **before** reading and validating the caller's diagnosis revision.

If a valid pending journal exists:

1. validate its exact shape, incident identity, revision transition, and both document hashes;
2. durably replace runtime evidence with the journal copy;
3. durably replace diagnosis with the journal copy;
4. durably remove the journal;
5. only then validate the new caller's `evidenceRevision` and route identity.

Therefore a caller holding revision `N` cannot overwrite a recovered revision `N+1`; after recovery it fails the existing stale-revision check.

A malformed or hash-mismatched journal fails closed. Causcope does not guess which document is correct and does not silently discard the journal.

## Durability details

Each JSON publication uses:

```text
write temporary file
flush
fsync(file)
os.replace(temp, target)
fsync(parent directory)
```

Journal removal also fsyncs its parent directory.

This is stronger than the previous `Path.replace()` behavior because the protocol explicitly asks the operating system to persist both file contents and directory-entry changes before advancing stages.

## Safety invariants

The existing RFC 0041 invariants remain unchanged:

- only the exact current top-ranked canonical probe can execute;
- only the router-selected exact-scope direct provider can execute;
- only read-only diagnostic actions are eligible;
- insufficient provider evidence never becomes negative evidence;
- cooperative writers are serialized by the incident filesystem claim.

The commit layer adds:

```text
durable journal => exact roll-forward intent
journal hashes   => no recovery from mutated payload
revision N -> N+1 => one evidence revision per routed commit
recovery first   => stale caller cannot overwrite recovered state
```

## Explicit non-goals

This RFC does not claim:

- simultaneous visibility of two POSIX files to arbitrary readers;
- rollback after the durable journal commit point;
- a general transaction manager;
- multi-incident transactions;
- remediation transactions;
- protection from non-cooperative writers that bypass Causcope's claim protocol.

If Causcope later needs strict atomic read visibility across evidence and projections, the appropriate next storage step is a single transactional state store (for example SQLite) or an atomic generation-pointer architecture. The write-ahead journal should not be stretched into pretending to provide that property.

## Verification

Fault-injection tests cover crashes:

- immediately after the journal becomes durable;
- after runtime evidence has been replaced but before diagnosis publication.

Both states recover to the exact revision `N+1` pair. A tampered journal fails closed, and the existing routed MCP integration test continues to cover the normal successful path.

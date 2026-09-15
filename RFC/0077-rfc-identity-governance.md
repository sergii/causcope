# RFC 0077: RFC identity governance and legacy collision handling

- Status: Proposed
- Date: 2026-09-15

## Summary

Causcope RFC numbers are intended to be stable human- and machine-addressable decision identifiers. The repository currently contains several historical numeric collisions created by parallel work:

```text
0022-agent-plan-probe-session-state.md
0022-incident-context-and-scoping.md

0033-external-diagnostic-adapters.md
0033-testbed-runtime-evidence-bridge.md

0040-resource-topology-provider-instances.md
0040-routing-aware-agent-plan-and-mcp.md

0059-investigator-cli-diagnosis-front-door.md
0059-rails-product-cli.md

0068-recommendation-investigator-cli-mcp-surface.md
0068-runtime-target-aware-investigation.md
```

This makes references such as `RFC 0059` ambiguous.

This RFC defines an immutable identity rule for future RFCs and a migration-safe policy for historical collisions.

## Decision

For all new RFCs:

> The four-digit RFC numeric prefix is a unique immutable identifier within the repository.

A valid filename follows:

```text
RFC/NNNN-short-descriptive-name.md
```

Once published on the default branch, an RFC number MUST NOT be reused for another decision, even if the original RFC is rejected, superseded, or withdrawn.

## Legacy collisions

Existing collisions are historical defects and are grandfathered temporarily through an explicit machine-readable exception registry:

```text
vocabulary/rfc-id-exceptions.yaml
```

The exception registry records the exact filenames that currently share an identifier.

It is not permission to create additional duplicates.

For example, if `0059` currently contains exactly two registered legacy files, a third `0059-*.md` MUST fail validation.

## Why not renumber immediately

Blind renumbering can break or silently corrupt:

- cross-RFC references;
- code comments;
- documentation links;
- issue descriptions;
- agent context;
- external references;
- commit history discussions.

Therefore existing collisions should be resolved only after references are inventoried.

## Validator

Add a repository validator that:

1. scans numbered Markdown files under `RFC/`;
2. groups them by four-digit prefix;
3. rejects every duplicate group not explicitly registered as a legacy collision;
4. rejects changes to a legacy collision group that do not exactly match its registered filenames;
5. rejects stale exception entries whose files no longer exist;
6. exits successfully for unique RFC IDs and unchanged registered historical collisions.

The first version deliberately validates filename identity only. More metadata checks can be added later without coupling identity governance to RFC prose formatting.

## Allocation policy

New RFC IDs should be allocated from the next unused numeric identifier.

Parallel agents MUST search or list the current RFC namespace immediately before creating a new RFC.

Longer term, RFC creation may use a small allocator command such as:

```text
causcope rfc next
```

or a repository automation that reserves the identifier atomically.

Until such a mechanism exists, the validator is the final safety net.

## Stable references

When a numeric ID is unique, references may use:

```text
RFC 0075
```

For a grandfathered collision, references MUST use the full filename until the collision is resolved:

```text
RFC/0059-investigator-cli-diagnosis-front-door.md
```

rather than:

```text
RFC 0059
```

This removes ambiguity immediately without rewriting history.

## Collision resolution strategy

Historical collisions may later be repaired using one of these approaches:

### A. Preserve one number, assign a new number to the other RFC

Use when one document is clearly the earlier or more widely referenced owner of the original number.

The moved RFC should record:

```text
former_id: 0059
```

or equivalent explicit alias metadata if a metadata convention is introduced.

### B. Introduce canonical document IDs independent of filenames

Use only if repository scale justifies a richer RFC registry.

### C. Leave the historical pair grandfathered

Acceptable when renumbering cost exceeds the practical ambiguity, provided all new references use full filenames.

No collision should be repaired by deleting history or silently changing a document identity.

## Relationship to agents

RFC identity is increasingly machine-consumed. Agents may:

- generate RFCs;
- build implementation plans from RFCs;
- cite prior decisions;
- compare accepted and proposed work;
- derive backlog items.

Stable unique IDs therefore become part of the agent-facing repository contract, not merely a documentation preference.

## Invariants

- New RFC numeric IDs are unique.
- Published IDs are immutable.
- Rejected or superseded IDs are never recycled.
- Historical collisions are explicit, bounded, and machine-readable.
- A legacy exception cannot expand silently.
- Ambiguous historical IDs are referenced by full filename.
- Automated validation prevents recurrence.

## Follow-up work

1. add `vocabulary/rfc-id-exceptions.yaml` with the known collision groups;
2. add `scripts/validate_rfc_ids.py`;
3. run the validator from repository validation/CI;
4. inventory references to the five known collision groups before deciding whether to renumber them;
5. optionally add an RFC allocator once parallel authoring becomes frequent enough to justify it.

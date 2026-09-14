# Competitive research

This directory contains structured market and product research relevant to CauScope.

## Canonical registry

`competitors.yaml` is the canonical registry for competitors, adjacent products, evidence providers, and historical references.

It is intentionally machine-readable so the same source can later generate internal landscape reports, capability matrices, website comparison tables, competitor pages, positioning notes, and integration or adapter candidates.

## Classification

Entries currently use these classes:

- `direct` - overlaps materially with CauScope's diagnosis, causal reasoning, proactive-risk, or AI-SRE product surface;
- `overlapping` - competes on a meaningful subset such as RCA, observability intelligence, or code-to-production debugging;
- `adjacent` - solves a neighboring workflow and may be an integration target;
- `evidence_provider` - can provide structured facts or runtime evidence to CauScope rather than primarily competing with it;
- `historical_reference` - useful precedent for understanding how the market evolved.

A product can strategically play more than one role even though the registry keeps one primary class for simple filtering.

## Comparison axes

The registry compares products on reasoning substrate, not only surface features. Current axes include telemetry context, code context, live topology, failure ontology, explicit causal graph, change context, hypothesis testing, falsification/verification, blast radius, proactive risk, live runtime probes, remediation, incident workflow, deployment model, and open-source availability.

These axes should evolve when a newly discovered product reveals a meaningful dimension that CauScope should track.

## Adding a product

When adding a product:

1. Prefer first-party product documentation, engineering posts, and repositories as sources.
2. Record what makes the product relevant to CauScope, not only the vendor's marketing description.
3. Distinguish a direct competitor from an evidence source or integration candidate.
4. Mark uncertain capabilities as `unknown` rather than guessing.
5. Keep capability judgments conservative and date the registry review.
6. Re-verify claims before publishing any public comparison table.

## Important interpretation rule

Do not optimize CauScope for feature-count parity.

The strategically important question is what each product reasons over:

```text
telemetry
+ code
+ topology
+ changes
+ explicit failure knowledge
+ causal relationships
+ predictions and falsifiers
+ discriminating probes
+ confirmation evidence
```

CauScope's differentiation should be evaluated primarily at this reasoning-model level.

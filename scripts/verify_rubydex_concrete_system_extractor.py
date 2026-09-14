#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from concrete_system_facts import (
    load_document,
    load_schema,
    opposing_access_orders,
    validate_schema,
    validate_semantics,
)

EXPECTED_LABELS = {
    "Account",
    "Account#touch!()",
    "CheckoutService",
    "CheckoutService#call()",
    "LedgerEntry",
    "LedgerEntry#persist!()",
    "SettlementJob",
    "SettlementJob#perform()",
}

EXPECTED_CONTAINMENT = {
    ("code:Account", "code:Account#touch!()"),
    ("code:CheckoutService", "code:CheckoutService#call()"),
    ("code:LedgerEntry", "code:LedgerEntry#persist!()"),
    ("code:SettlementJob", "code:SettlementJob#perform()"),
}


def verify(path: Path) -> None:
    document = load_document(path)
    validate_schema(document, load_schema())
    validate_semantics(document)

    if document["system_id"] != "rubydex-fixture":
        raise ValueError(f"unexpected system_id: {document['system_id']}")
    if document["revision"] != {
        "type": "git",
        "value": "fixture-revision",
        "repository": "sergii/causcope",
    }:
        raise ValueError(f"unexpected revision: {document['revision']}")

    entities = document["entities"]
    labels = {entity["label"] for entity in entities}
    missing_labels = sorted(EXPECTED_LABELS - labels)
    if missing_labels:
        raise ValueError("Rubydex export is missing code symbols: " + ", ".join(missing_labels))

    for entity in entities:
        if entity["certainty"] != "direct":
            raise ValueError(f"v0 Rubydex entity is not direct: {entity['id']}")
        provenance = entity["provenance"]
        if provenance["source_type"] != "static_analysis" or provenance["name"] != "rubydex":
            raise ValueError(f"unexpected entity provenance: {entity['id']} -> {provenance}")
        if "source_location" not in entity:
            raise ValueError(f"workspace code symbol lacks source location: {entity['id']}")

    containment = {
        (fact["subject"], fact["object"])
        for fact in document["facts"]
        if fact["relation"] == "contains"
    }
    missing_containment = sorted(EXPECTED_CONTAINMENT - containment)
    if missing_containment:
        raise ValueError(f"Rubydex export is missing ownership facts: {missing_containment}")

    for fact in document["facts"]:
        if fact["relation"] != "contains" or fact["certainty"] != "direct":
            raise ValueError(f"v0 exporter invented non-direct semantic fact: {fact['id']}")
        provenance = fact["provenance"]
        if provenance["source_type"] != "static_analysis" or provenance["name"] != "rubydex":
            raise ValueError(f"unexpected fact provenance: {fact['id']} -> {provenance}")

    if opposing_access_orders(document):
        raise ValueError("direct Rubydex symbol extraction must not invent D2.2 access ordering")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the live Rubydex -> concrete_system_facts bridge.")
    parser.add_argument("document", type=Path)
    args = parser.parse_args()

    try:
        verify(args.document)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print("Rubydex concrete-system facts verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

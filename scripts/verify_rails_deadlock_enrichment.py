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

CHECKOUT = "code:CheckoutService#call()"
SETTLEMENT = "code:SettlementJob#perform()"
ACCOUNT = "db:public.accounts"
LEDGER = "db:public.ledger_entries"


def verify(path: Path) -> None:
    document = load_document(path)
    validate_schema(document, load_schema())
    validate_semantics(document)

    entities = {entity["id"]: entity for entity in document["entities"]}
    for entity_id in (ACCOUNT, LEDGER):
        entity = entities.get(entity_id)
        if entity is None:
            raise ValueError(f"missing Rails-derived data resource: {entity_id}")
        if entity["certainty"] != "inferred":
            raise ValueError(f"Rails-derived resource must be inferred: {entity_id}")
        if entity["provenance"].get("rule") != "rails.explicit_table_name.v0":
            raise ValueError(f"unexpected table mapping rule: {entity_id}")

    direct_rubydex = [
        entity
        for entity in document["entities"]
        if entity.get("provenance", {}).get("name") == "rubydex"
    ]
    if not direct_rubydex or any(entity["certainty"] != "direct" for entity in direct_rubydex):
        raise ValueError("Rails enrichment must preserve direct Rubydex evidence as direct")

    order_facts = [fact for fact in document["facts"] if fact["relation"] == "accesses_before"]
    expected_orders = {
        (ACCOUNT, LEDGER, CHECKOUT),
        (LEDGER, ACCOUNT, SETTLEMENT),
    }
    actual_orders = {
        (fact["subject"], fact["object"], fact["context"]["code_path"])
        for fact in order_facts
    }
    missing = sorted(expected_orders - actual_orders)
    if missing:
        raise ValueError(f"missing D2.2 static ordering facts: {missing}")

    for fact in order_facts:
        if fact["certainty"] != "inferred":
            raise ValueError(f"static Rails access order must be inferred: {fact['id']}")
        if fact["confidence"] != "moderate":
            raise ValueError(f"static Rails access order must remain moderate confidence: {fact['id']}")
        if fact["provenance"].get("rule") != "rails.source_ordered_writes.v0":
            raise ValueError(f"unexpected access-order rule: {fact['id']}")

    projections = opposing_access_orders(document)
    if len(projections) != 1:
        raise ValueError(f"expected exactly one D2.2 structural precondition, got {projections}")

    projection = projections[0]
    if projection["deadlock_observed"] is not False:
        raise ValueError("static Rails enrichment must never claim an observed deadlock")
    paths = {projection["left"]["code_path"], projection["right"]["code_path"]}
    if paths != {CHECKOUT, SETTLEMENT}:
        raise ValueError(f"unexpected D2.2 code paths: {sorted(paths)}")
    if set(projection["resources"]) != {ACCOUNT, LEDGER}:
        raise ValueError(f"unexpected D2.2 resources: {projection['resources']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Rails static enrichment for the D2.2 slice.")
    parser.add_argument("document", type=Path)
    args = parser.parse_args()

    try:
        verify(args.document)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print("Rails D2.2 static enrichment verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

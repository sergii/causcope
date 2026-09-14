#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schema" / "concrete-system-facts.schema.json"


def load_document(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        if path.suffix.lower() == ".json":
            payload = json.load(handle)
        else:
            payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError("concrete system facts document must be an object")
    return payload


def load_schema(path: Path = DEFAULT_SCHEMA) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("concrete system facts schema must be an object")
    return payload


def validate_schema(document: dict[str, Any], schema: dict[str, Any]) -> None:
    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    )
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        rendered = []
        for error in errors:
            path = ".".join(str(part) for part in error.path) or "<root>"
            rendered.append(f"{path}: {error.message}")
        raise ValueError("schema validation failed:\n" + "\n".join(rendered))


def validate_semantics(document: dict[str, Any]) -> None:
    entities = document["entities"]
    facts = document["facts"]

    entity_ids = [entity["id"] for entity in entities]
    if len(entity_ids) != len(set(entity_ids)):
        raise ValueError("entity ids must be unique")

    fact_ids = [fact["id"] for fact in facts]
    if len(fact_ids) != len(set(fact_ids)):
        raise ValueError("fact ids must be unique")

    entity_by_id = {entity["id"]: entity for entity in entities}

    for entity in entities:
        if entity["certainty"] == "inferred" and not entity["provenance"].get("rule"):
            raise ValueError(f"inferred entity {entity['id']} must identify its deriving rule")

    for fact in facts:
        for field in ("subject", "object"):
            ref = fact[field]
            if ref not in entity_by_id:
                raise ValueError(f"fact {fact['id']} references unknown {field} {ref}")

        context = fact.get("context", {})
        for field in ("transaction", "code_path"):
            ref = context.get(field)
            if ref is not None and ref not in entity_by_id:
                raise ValueError(f"fact {fact['id']} references unknown context {field} {ref}")

        if fact["certainty"] == "inferred" and not fact["provenance"].get("rule"):
            raise ValueError(f"inferred fact {fact['id']} must identify its deriving rule")

        if fact["relation"] == "accesses_before":
            subject = entity_by_id[fact["subject"]]
            obj = entity_by_id[fact["object"]]
            transaction = entity_by_id[fact["context"]["transaction"]]
            code_path = entity_by_id[fact["context"]["code_path"]]

            if subject["kind"] != "data_resource" or obj["kind"] != "data_resource":
                raise ValueError(
                    f"accesses_before fact {fact['id']} must connect data_resource entities"
                )
            if transaction["kind"] != "transaction":
                raise ValueError(
                    f"accesses_before fact {fact['id']} must reference a transaction context"
                )
            if code_path["kind"] not in {"code_symbol", "job"}:
                raise ValueError(
                    f"accesses_before fact {fact['id']} must reference a code_symbol or job path"
                )


def opposing_access_orders(document: dict[str, Any]) -> list[dict[str, Any]]:
    order_facts = [
        fact for fact in document["facts"] if fact["relation"] == "accesses_before"
    ]
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for left in order_facts:
        for right in order_facts:
            if left["id"] >= right["id"]:
                continue
            if left["subject"] != right["object"] or left["object"] != right["subject"]:
                continue

            left_context = left["context"]
            right_context = right["context"]
            if left_context["code_path"] == right_context["code_path"]:
                continue

            key = (
                min(left["subject"], left["object"]),
                max(left["subject"], left["object"]),
                min(left_context["code_path"], right_context["code_path"]),
                max(left_context["code_path"], right_context["code_path"]),
            )
            if key in seen:
                continue
            seen.add(key)

            results.append(
                {
                    "kind": "opposing_access_order_precondition",
                    "resources": [left["subject"], left["object"]],
                    "left": {
                        "fact": left["id"],
                        "code_path": left_context["code_path"],
                        "transaction": left_context["transaction"],
                    },
                    "right": {
                        "fact": right["id"],
                        "code_path": right_context["code_path"],
                        "transaction": right_context["transaction"],
                    },
                    "deadlock_observed": False,
                    "interpretation": (
                        "Structural D2.2 precondition only. Runtime overlap and a concrete "
                        "wait-for cycle are still required before claiming an observed deadlock."
                    ),
                }
            )

    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate sourced concrete-system facts and project structural access-order preconditions."
    )
    parser.add_argument("document", type=Path)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    document = load_document(args.document)
    schema = load_schema(args.schema)
    validate_schema(document, schema)
    validate_semantics(document)

    output = {
        "kind": "concrete_system_fact_validation",
        "system_id": document["system_id"],
        "revision": document["revision"],
        "entity_count": len(document["entities"]),
        "fact_count": len(document["facts"]),
        "structural_preconditions": opposing_access_orders(document),
    }
    print(json.dumps(output, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

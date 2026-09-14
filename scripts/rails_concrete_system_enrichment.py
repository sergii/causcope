#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from concrete_system_facts import load_document, load_schema, validate_schema, validate_semantics

MODEL_BASE_RE_TEMPLATE = r"class\s+{name}\s*<\s*(?:ApplicationRecord|ActiveRecord::Base)\b"
TABLE_NAME_RE = re.compile(r"self\.table_name\s*=\s*['\"](?P<table>[A-Za-z0-9_.]+)['\"]")
TRANSACTION_RE = re.compile(r"\b(?:ApplicationRecord|ActiveRecord::Base)\.transaction\s+do\b")
WRITE_RE = re.compile(
    r"^\s*(?P<model>[A-Z][A-Za-z0-9_:]*)\."
    r"(?P<method>create!?|update!?|update_all|delete_all|destroy_all|insert_all!?|upsert_all!?)\b"
)


def stable_fact_id(relation: str, subject: str, obj: str, context: str = "") -> str:
    digest = hashlib.sha256(
        "\0".join((relation, subject, obj, context)).encode("utf-8")
    ).hexdigest()[:16]
    return f"fact.rails_{relation}.{digest}"


def source_location(path: str, line: int, text: str) -> dict[str, Any]:
    return {
        "path": path,
        "start_line": line,
        "start_column": len(text) - len(text.lstrip()) + 1,
        "end_line": line,
        "end_column": max(len(text.rstrip()) + 1, 1),
    }


def inferred_provenance(rule: str, reference: str) -> dict[str, str]:
    return {
        "source_type": "source",
        "name": "rails_static_enricher",
        "reference": reference,
        "rule": rule,
    }


def read_source(workspace: Path, relative_path: str) -> tuple[list[str], str]:
    path = (workspace / relative_path).resolve()
    try:
        path.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(f"source path escapes workspace: {relative_path}") from exc
    text = path.read_text(encoding="utf-8")
    return text.splitlines(), text


def discover_model_tables(
    document: dict[str, Any], workspace: Path
) -> tuple[dict[str, str], list[dict[str, Any]], list[dict[str, Any]]]:
    model_to_resource: dict[str, str] = {}
    new_entities: list[dict[str, Any]] = []
    new_facts: list[dict[str, Any]] = []
    existing_entity_ids = {entity["id"] for entity in document["entities"]}

    for entity in document["entities"]:
        if entity["kind"] != "code_symbol":
            continue
        if entity.get("attributes", {}).get("rubydex_kind") != "Class":
            continue
        location = entity.get("source_location")
        if not location:
            continue

        label = entity["label"]
        _lines, text = read_source(workspace, location["path"])
        base_re = re.compile(MODEL_BASE_RE_TEMPLATE.format(name=re.escape(label)))
        if not base_re.search(text):
            continue

        table_match = TABLE_NAME_RE.search(text)
        if table_match is None:
            continue

        table = table_match.group("table")
        resource_id = f"db:public.{table}"
        model_to_resource[label] = resource_id

        rule = "rails.explicit_table_name.v0"
        reference = f"{location['path']}:{location['start_line']}"
        if resource_id not in existing_entity_ids:
            new_entities.append(
                {
                    "id": resource_id,
                    "kind": "data_resource",
                    "label": f"public.{table}",
                    "certainty": "inferred",
                    "confidence": "high",
                    "provenance": inferred_provenance(rule, reference),
                    "source_location": copy.deepcopy(location),
                    "attributes": {
                        "database_kind": "postgresql_table",
                        "rails_model": label,
                    },
                }
            )
            existing_entity_ids.add(resource_id)

        new_facts.append(
            {
                "id": stable_fact_id("maps_to", entity["id"], resource_id),
                "subject": entity["id"],
                "relation": "maps_to",
                "object": resource_id,
                "certainty": "inferred",
                "confidence": "high",
                "provenance": inferred_provenance(rule, reference),
                "note": "Explicit Rails self.table_name mapping recognized from source.",
            }
        )

    return model_to_resource, new_entities, new_facts


def transaction_ranges(lines: list[str]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        if not TRANSACTION_RE.search(line):
            continue
        indent = len(line) - len(line.lstrip())
        end_index: int | None = None
        for candidate in range(index + 1, len(lines)):
            current = lines[candidate]
            if current.strip() != "end":
                continue
            current_indent = len(current) - len(current.lstrip())
            if current_indent == indent:
                end_index = candidate
                break
        if end_index is not None:
            ranges.append((index, end_index))
    return ranges


def discover_transactions_and_writes(
    document: dict[str, Any],
    workspace: Path,
    model_to_resource: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    new_entities: list[dict[str, Any]] = []
    new_facts: list[dict[str, Any]] = []

    for code_path in document["entities"]:
        if code_path["kind"] != "code_symbol":
            continue
        if code_path.get("attributes", {}).get("rubydex_kind") != "Method":
            continue
        location = code_path.get("source_location")
        if not location:
            continue

        file_lines, _text = read_source(workspace, location["path"])
        start_line = location["start_line"]
        end_line = min(location.get("end_line", start_line), len(file_lines))
        method_lines = file_lines[start_line - 1 : end_line]

        for tx_index, tx_end in transaction_ranges(method_lines):
            absolute_line = start_line + tx_index
            tx_id = f"tx:{code_path['label']}:L{absolute_line}"
            tx_rule = "rails.transaction_block.v0"
            tx_reference = f"{location['path']}:{absolute_line}"
            tx_line = method_lines[tx_index]

            new_entities.append(
                {
                    "id": tx_id,
                    "kind": "transaction",
                    "label": f"{code_path['label']} transaction at {tx_reference}",
                    "certainty": "inferred",
                    "confidence": "high",
                    "provenance": inferred_provenance(tx_rule, tx_reference),
                    "source_location": source_location(location["path"], absolute_line, tx_line),
                    "attributes": {"framework": "rails", "database": "postgresql"},
                }
            )
            new_facts.append(
                {
                    "id": stable_fact_id("executes_in", code_path["id"], tx_id),
                    "subject": code_path["id"],
                    "relation": "executes_in",
                    "object": tx_id,
                    "certainty": "inferred",
                    "confidence": "high",
                    "provenance": inferred_provenance(tx_rule, tx_reference),
                }
            )

            writes: list[tuple[str, str, int]] = []
            for relative_index in range(tx_index + 1, tx_end):
                statement = method_lines[relative_index]
                match = WRITE_RE.match(statement)
                if match is None:
                    continue
                model = match.group("model")
                resource_id = model_to_resource.get(model)
                if resource_id is None:
                    continue
                statement_line = start_line + relative_index
                writes.append((model, resource_id, statement_line))

            unique_resources: list[tuple[str, str, int]] = []
            seen_resources: set[str] = set()
            for write in writes:
                if write[1] in seen_resources:
                    continue
                seen_resources.add(write[1])
                unique_resources.append(write)

            write_rule = "rails.constant_receiver_write.v0"
            for model, resource_id, statement_line in unique_resources:
                reference = f"{location['path']}:{statement_line}"
                new_facts.append(
                    {
                        "id": stable_fact_id("writes", tx_id, resource_id, code_path["id"]),
                        "subject": tx_id,
                        "relation": "writes",
                        "object": resource_id,
                        "certainty": "inferred",
                        "confidence": "moderate",
                        "provenance": inferred_provenance(write_rule, reference),
                        "context": {
                            "transaction": tx_id,
                            "code_path": code_path["id"],
                        },
                        "note": f"Recognized constant-receiver Rails write call for {model}.",
                    }
                )

            order_rule = "rails.source_ordered_writes.v0"
            for left_index, left in enumerate(unique_resources):
                for right in unique_resources[left_index + 1 :]:
                    if left[1] == right[1]:
                        continue
                    reference = f"{location['path']}:{left[2]}-{right[2]}"
                    new_facts.append(
                        {
                            "id": stable_fact_id(
                                "accesses_before",
                                left[1],
                                right[1],
                                f"{tx_id}\0{code_path['id']}",
                            ),
                            "subject": left[1],
                            "relation": "accesses_before",
                            "object": right[1],
                            "certainty": "inferred",
                            "confidence": "moderate",
                            "provenance": inferred_provenance(order_rule, reference),
                            "context": {
                                "transaction": tx_id,
                                "code_path": code_path["id"],
                            },
                            "note": (
                                "Source-order precondition only; this is not proof of PostgreSQL "
                                "lock acquisition order or a runtime wait-for cycle."
                            ),
                        }
                    )

    return new_entities, new_facts


def enrich(document: dict[str, Any], workspace: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    enriched = copy.deepcopy(document)

    model_to_resource, resource_entities, mapping_facts = discover_model_tables(enriched, workspace)
    enriched["entities"].extend(resource_entities)
    enriched["facts"].extend(mapping_facts)

    transaction_entities, transaction_facts = discover_transactions_and_writes(
        enriched, workspace, model_to_resource
    )
    enriched["entities"].extend(transaction_entities)
    enriched["facts"].extend(transaction_facts)

    enriched["entities"] = sorted(
        {entity["id"]: entity for entity in enriched["entities"]}.values(),
        key=lambda entity: entity["id"],
    )
    enriched["facts"] = sorted(
        {fact["id"]: fact for fact in enriched["facts"]}.values(),
        key=lambda fact: fact["id"],
    )

    limitations = list(enriched.get("limitations", []))
    additions = [
        "Rails enrichment v0 recognizes only explicit self.table_name mappings on top-level model classes.",
        "Transaction inference recognizes only ApplicationRecord.transaction or ActiveRecord::Base.transaction do blocks whose closing end matches indentation.",
        "Write inference recognizes only constant-receiver Rails write calls from a conservative allow-list.",
        "accesses_before reflects source order of recognized writes, not proven PostgreSQL lock acquisition order.",
        "Callbacks, associations, SQL fragments, dynamic dispatch, metaprogramming, implicit writes, and nested framework semantics remain unknown unless another deterministic rule models them.",
    ]
    for item in additions:
        if item not in limitations:
            limitations.append(item)
    enriched["limitations"] = limitations

    validate_schema(enriched, load_schema())
    validate_semantics(enriched)
    return enriched


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deterministically enrich direct Rubydex facts with a conservative Rails static slice."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        document = load_document(args.input)
        output = enrich(document, args.workspace)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    rendered = json.dumps(output, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

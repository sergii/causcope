#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from concrete_system_facts import load_document, load_schema, validate_schema, validate_semantics

RULE_ID = "ruby.retry_external_side_effect.v0"
JOB_PATTERN = re.compile(r"class\s+([A-Za-z_][A-Za-z0-9_:]*Job)\b")
RETRY_PATTERN = re.compile(r"sidekiq_options\s+retry:\s*(true|false|\d+)")
CALL_PATTERN = re.compile(r"PaymentsClient\.charge\s*\(")


def fact_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"fact.{prefix}.{digest}"


def source_location(path: Path, workspace: Path, needle: str) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines, start=1):
        if needle in line:
            return {"path": str(path.relative_to(workspace)), "start_line": index}
    return {"path": str(path.relative_to(workspace))}


def parse_retry(value: str) -> tuple[bool, str]:
    if value == "false":
        return False, "0"
    if value == "true":
        return True, "framework_default"
    count = int(value)
    return count > 0, str(count)


def enrich(document: dict[str, Any], workspace: Path) -> dict[str, Any]:
    validate_schema(document, load_schema())
    validate_semantics(document)

    job_files = sorted((workspace / "app" / "jobs").glob("*.rb"))
    if not job_files:
        raise ValueError("duplicate-side-effect enrichment found no Ruby job files")

    client_path = workspace / "app" / "services" / "payments_client.rb"
    if not client_path.is_file():
        raise ValueError("duplicate-side-effect enrichment requires app/services/payments_client.rb")
    client_source = client_path.read_text(encoding="utf-8")
    idempotency_state = (
        "present_in_supported_client_source"
        if "Idempotency-Key" in client_source
        else "absent_in_supported_client_source"
    )

    entities = list(document["entities"])
    facts = list(document["facts"])
    entity_ids = {entity["id"] for entity in entities}

    matched = 0
    for path in job_files:
        source = path.read_text(encoding="utf-8")
        class_match = JOB_PATTERN.search(source)
        retry_match = RETRY_PATTERN.search(source)
        if class_match is None or retry_match is None or CALL_PATTERN.search(source) is None:
            continue

        class_name = class_match.group(1)
        code_symbol = f"code:{class_name}#perform()"
        if code_symbol not in entity_ids:
            raise ValueError(f"Rubydex did not export expected job perform symbol: {code_symbol}")

        retry_enabled, retry_max = parse_retry(retry_match.group(1))
        job_id = f"job:{class_name}"
        dependency_id = "external:payments"

        if job_id not in entity_ids:
            entities.append(
                {
                    "id": job_id,
                    "kind": "job",
                    "label": class_name,
                    "certainty": "inferred",
                    "confidence": "high",
                    "provenance": {
                        "source_type": "source",
                        "name": "retry-side-effect-enrichment",
                        "reference": str(path.relative_to(workspace)),
                        "rule": RULE_ID,
                    },
                    "source_location": source_location(path, workspace, "class "),
                    "attributes": {
                        "framework": "sidekiq-compatible",
                        "retry_enabled": str(retry_enabled).lower(),
                        "retry_max": retry_max,
                    },
                }
            )
            entity_ids.add(job_id)

        if dependency_id not in entity_ids:
            entities.append(
                {
                    "id": dependency_id,
                    "kind": "external_dependency",
                    "label": "payments",
                    "certainty": "inferred",
                    "confidence": "high",
                    "provenance": {
                        "source_type": "source",
                        "name": "retry-side-effect-enrichment",
                        "reference": str(client_path.relative_to(workspace)),
                        "rule": RULE_ID,
                    },
                    "source_location": source_location(client_path, workspace, "class PaymentsClient"),
                    "attributes": {
                        "operation": "charge",
                        "effect_semantics": "external_business_side_effect",
                    },
                }
            )
            entity_ids.add(dependency_id)

        facts.append(
            {
                "id": fact_id("side_effect_maps_to", code_symbol, job_id),
                "subject": code_symbol,
                "relation": "maps_to",
                "object": job_id,
                "certainty": "inferred",
                "confidence": "high",
                "provenance": {
                    "source_type": "source",
                    "name": "retry-side-effect-enrichment",
                    "reference": str(path.relative_to(workspace)),
                    "rule": RULE_ID,
                },
                "context": {"code_path": code_symbol},
            }
        )
        facts.append(
            {
                "id": fact_id("side_effect_depends_on", job_id, dependency_id, code_symbol),
                "subject": job_id,
                "relation": "depends_on",
                "object": dependency_id,
                "certainty": "inferred",
                "confidence": "high",
                "provenance": {
                    "source_type": "source",
                    "name": "retry-side-effect-enrichment",
                    "reference": f"{path.relative_to(workspace)} + {client_path.relative_to(workspace)}",
                    "rule": RULE_ID,
                },
                "context": {
                    "code_path": code_symbol,
                    "boundary": "boundary.application.external_dependency",
                    "attributes": {
                        "retry_enabled": str(retry_enabled).lower(),
                        "retry_max": retry_max,
                        "effect_operation": "charge",
                        "business_identity": "payment_id",
                        "idempotency_key": idempotency_state,
                        "negative_evidence_scope": str(client_path.relative_to(workspace)),
                    },
                },
                "note": (
                    "The idempotency statement is bounded to the supported PaymentsClient source scan; "
                    "absence here is not proof that the provider has no independent deduplication."
                ),
            }
        )
        matched += 1

    if matched == 0:
        raise ValueError("no supported retry + PaymentsClient.charge job path found")

    output = dict(document)
    output["entities"] = sorted({item["id"]: item for item in entities}.values(), key=lambda item: item["id"])
    output["facts"] = sorted({item["id"]: item for item in facts}.values(), key=lambda item: item["id"])
    limitations = list(output.get("limitations", []))
    limitations.extend(
        [
            "Retry and external-effect enrichment recognizes only the narrow Ruby source patterns documented by rule ruby.retry_external_side_effect.v0.",
            "A missing Idempotency-Key is bounded negative evidence for the supported PaymentsClient source file, not proof that every downstream layer lacks deduplication.",
            "Static retry configuration and an external side-effect call establish a precondition only; they do not prove an ambiguous outcome, retry, or duplicate business effect occurred.",
        ]
    )
    output["limitations"] = sorted(set(limitations))
    validate_schema(output, load_schema())
    validate_semantics(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Add conservative retry/external-side-effect facts to Rubydex concrete facts.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        document = load_document(args.input)
        output = enrich(document, args.workspace.resolve())
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

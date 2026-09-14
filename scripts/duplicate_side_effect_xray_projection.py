#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from concrete_system_facts import load_document, load_schema, validate_schema, validate_semantics

GENERIC_HYPOTHESIS = "hypothesis.messaging.duplicate_delivery"
GENERIC_SYMPTOM = "symptom.messaging.duplicate_business_effect_observed"
DUPLICATE_EFFECT_OBSERVATION = "observation.application.duplicate_side_effect"


def preconditions(document: dict[str, Any]) -> list[dict[str, Any]]:
    entities = {entity["id"]: entity for entity in document["entities"]}
    code_by_job: dict[str, str] = {}
    for fact in document["facts"]:
        if fact["relation"] != "maps_to":
            continue
        subject = entities.get(fact["subject"], {})
        obj = entities.get(fact["object"], {})
        if subject.get("kind") == "code_symbol" and obj.get("kind") == "job":
            code_by_job[fact["object"]] = fact["subject"]

    matches: list[dict[str, Any]] = []
    for fact in document["facts"]:
        if fact["relation"] != "depends_on":
            continue
        job = entities.get(fact["subject"], {})
        dependency = entities.get(fact["object"], {})
        if job.get("kind") != "job" or dependency.get("kind") != "external_dependency":
            continue
        attrs = fact.get("context", {}).get("attributes", {})
        if attrs.get("retry_enabled") != "true":
            continue
        if attrs.get("effect_operation") != "charge":
            continue
        if attrs.get("idempotency_key") != "absent_in_supported_client_source":
            continue
        code_symbol = code_by_job.get(fact["subject"])
        if code_symbol is None:
            continue
        matches.append(
            {
                "job": fact["subject"],
                "code_symbol": code_symbol,
                "dependency": fact["object"],
                "fact": fact["id"],
                "retry_max": attrs.get("retry_max", "unknown"),
                "effect_operation": attrs["effect_operation"],
                "business_identity": attrs.get("business_identity", "unknown"),
                "idempotency_key": attrs["idempotency_key"],
                "negative_evidence_scope": attrs.get("negative_evidence_scope", "unknown"),
            }
        )
    return sorted(matches, key=lambda item: (item["job"], item["dependency"], item["fact"]))


def project(document: dict[str, Any]) -> dict[str, Any]:
    validate_schema(document, load_schema())
    validate_semantics(document)
    matches = preconditions(document)
    has_preconditions = bool(matches)
    return {
        "schema_version": "0.1",
        "kind": "duplicate_side_effect_xray_projection",
        "catalog_code": "Q2.1",
        "hypothesis": GENERIC_HYPOTHESIS,
        "symptom": GENERIC_SYMPTOM,
        "canonical_observation": DUPLICATE_EFFECT_OBSERVATION,
        "system_id": document["system_id"],
        "revision": document["revision"],
        "structural_preconditions": {
            "state": "present" if has_preconditions else "unknown",
            "matches": matches,
        },
        "idempotency_evidence": {
            "state": "bounded_absence_observed" if has_preconditions else "unknown",
            "interpretation": (
                "The supported client source contains no Idempotency-Key path for the matched charge call. "
                "This is bounded negative evidence, not a claim that the provider lacks independent deduplication."
            ),
        },
        "risk_state": "PRECONDITIONS_PRESENT" if has_preconditions else "UNKNOWN",
        "next_evidence_needed": [
            "an exact execution of the matched retryable job",
            "an external side effect committed before the first attempt observes an ambiguous timeout",
            "a retry of the same logical job/business identity",
            "provider evidence showing whether the retry applied the business effect again",
        ],
        "limitations": [
            "PRECONDITIONS_PRESENT is a concrete risk path, not evidence that a retry or duplicate business effect occurred.",
            "The generic duplicate-delivery hypothesis is reused because the same stable job can be delivered again after failed processing; this projection does not assert a particular broker implementation.",
            "Source-level absence of an idempotency header remains bounded to the supported client source and cannot establish provider behavior by itself.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Project retry + external side-effect concrete risk facts.")
    parser.add_argument("--static-facts", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        output = project(load_document(args.static_facts))
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

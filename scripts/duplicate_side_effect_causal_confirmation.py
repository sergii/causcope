#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import jsonschema

from concrete_system_facts import load_document, load_schema, validate_schema, validate_semantics
from otel_concrete_runtime_facts import load_json as load_runtime_json, validate_runtime_document
from runtime_evidence import load_runtime_evidence, validate_runtime_references
from causal_projection import load_concepts

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_SCHEMA = ROOT / "schema" / "concrete-duplicate-side-effect-evidence.schema.json"
DUPLICATE_EFFECT_OBSERVATION = "observation.application.duplicate_side_effect"


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def validate_effect_evidence(document: dict[str, Any]) -> None:
    schema = json.loads(EVIDENCE_SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        raise ValueError(
            "duplicate side-effect evidence schema validation failed: "
            + "; ".join(error.message for error in errors)
        )


def execution_key(item: dict[str, Any]) -> tuple[str, str]:
    return str(item["trace_id"]), str(item["span_id"])


def confirm(
    static: dict[str, Any],
    runtime: dict[str, Any],
    xray: dict[str, Any],
    effect_evidence: dict[str, Any],
    canonical_evidence: dict[str, Any],
) -> dict[str, Any]:
    validate_schema(static, load_schema())
    validate_semantics(static)
    validate_runtime_document(runtime)
    validate_effect_evidence(effect_evidence)
    validate_runtime_references(canonical_evidence, load_concepts(ROOT))

    if xray.get("kind") != "duplicate_side_effect_xray_projection":
        raise ValueError("static X-Ray input has the wrong kind")
    if xray.get("risk_state") != "PRECONDITIONS_PRESENT":
        raise ValueError("causal confirmation requires the concrete static preconditions")

    identities = [
        (runtime["system_id"], runtime["revision"]),
        (xray["system_id"], xray["revision"]),
        (effect_evidence["system_id"], effect_evidence["revision"]),
    ]
    if any(item != (static["system_id"], static["revision"]) for item in identities):
        raise ValueError("static, runtime, X-Ray and effect evidence are not revision-aligned")
    if runtime["incident_id"] != effect_evidence["incident_id"]:
        raise ValueError("concrete runtime and effect evidence belong to different incidents")
    if canonical_evidence["incident_id"] != effect_evidence["incident_id"]:
        raise ValueError("canonical runtime evidence belongs to a different incident")

    matches = xray["structural_preconditions"]["matches"]
    if len(matches) != 1:
        raise ValueError("confirmation requires exactly one static duplicate-effect precondition")
    precondition = matches[0]
    code_symbol = precondition["code_symbol"]
    if effect_evidence["code_symbol"] != code_symbol:
        raise ValueError("effect evidence code symbol does not match the static X-Ray path")

    executions = {
        execution_key(item): item
        for item in runtime["executions"]
        if item["code_symbol"] == code_symbol
    }
    unsafe = effect_evidence["unsafe"]
    protected = effect_evidence["protected"]
    unsafe_attempts = sorted(unsafe["attempts"], key=lambda item: item["attempt"])
    if len(unsafe_attempts) != 2:
        raise ValueError("first proof requires exactly two unsafe delivery attempts")

    bound_executions: list[dict[str, Any]] = []
    for attempt in unsafe_attempts:
        key = execution_key(attempt)
        execution = executions.get(key)
        if execution is None:
            raise ValueError(f"unsafe attempt does not bind to an exact concrete OTel execution: {key}")
        bound_executions.append(execution)

    if len({attempt["job_id"] for attempt in unsafe_attempts}) != 1:
        raise ValueError("unsafe retry attempts do not share one stable job identity")
    if len({attempt["business_event_id"] for attempt in unsafe_attempts}) != 1:
        raise ValueError("unsafe retry attempts do not share one stable business identity")
    if [attempt["client_outcome"] for attempt in unsafe_attempts] != ["timeout", "success"]:
        raise ValueError("unsafe path must observe ambiguous timeout followed by successful retry")
    if not all(attempt["provider_effect_committed"] for attempt in unsafe_attempts):
        raise ValueError("both unsafe attempts must bind to committed provider effects")
    if any(attempt["idempotency_key"] is not None for attempt in unsafe_attempts):
        raise ValueError("unsafe path unexpectedly carried an idempotency key")

    unsafe_effects = unsafe["provider_effects"]
    if len(unsafe_effects) != 2:
        raise ValueError("unsafe retry must have exactly two committed provider effects")
    if len({effect["effect_id"] for effect in unsafe_effects}) != 2:
        raise ValueError("unsafe provider effects must have distinct effect identities")
    if {effect["business_event_id"] for effect in unsafe_effects} != {unsafe["business_event_id"]}:
        raise ValueError("unsafe provider effects do not share the same logical business identity")
    if any(effect["idempotency_key"] is not None for effect in unsafe_effects):
        raise ValueError("unsafe provider effects unexpectedly carry an idempotency key")
    unsafe_effect_keys = {execution_key(effect) for effect in unsafe_effects}
    if unsafe_effect_keys != {execution_key(attempt) for attempt in unsafe_attempts}:
        raise ValueError("provider effects do not bind one-to-one to the exact unsafe OTel executions")

    protected_attempts = sorted(protected["attempts"], key=lambda item: item["attempt"])
    if len(protected_attempts) != 2:
        raise ValueError("protected recovery requires exactly two attempts")
    if [attempt["client_outcome"] for attempt in protected_attempts] != ["timeout", "success"]:
        raise ValueError("protected recovery must preserve timeout then retry")
    protected_keys = {attempt["idempotency_key"] for attempt in protected_attempts}
    if len(protected_keys) != 1 or None in protected_keys:
        raise ValueError("protected recovery must use one stable non-empty idempotency key")
    if len(protected["provider_effects"]) != 1:
        raise ValueError("protected recovery must apply the provider effect exactly once")
    if not protected_attempts[1].get("provider_deduplicated"):
        raise ValueError("protected retry must be explicitly deduplicated by the provider")

    duplicate_instances = [
        item
        for item in canonical_evidence["instances"]
        if item["observation"] == DUPLICATE_EFFECT_OBSERVATION and item["state"] == "observed"
    ]
    if len(duplicate_instances) != 1:
        raise ValueError("canonical runtime evidence must contain one observed duplicate-side-effect instance")
    measurement = duplicate_instances[0].get("measurement", {})
    if measurement.get("value") != 2:
        raise ValueError("canonical duplicate-side-effect evidence must report two provider effects")

    return {
        "schema_version": "0.1",
        "kind": "duplicate_side_effect_causal_confirmation",
        "catalog_code": "Q2.1",
        "hypothesis": "hypothesis.messaging.duplicate_delivery",
        "symptom": "symptom.messaging.duplicate_business_effect_observed",
        "observation": DUPLICATE_EFFECT_OBSERVATION,
        "system_id": static["system_id"],
        "revision": static["revision"],
        "incident_id": runtime["incident_id"],
        "epistemic_state": "CAUSAL_DIAGNOSIS_CONFIRMED",
        "causal_diagnosis": {
            "state": "confirmed",
            "mechanism": "retry_after_ambiguous_external_side_effect_without_idempotency",
            "reason": (
                "The same revision-bound retryable job executed twice for one stable business identity. "
                "The first attempt committed the external effect before timing out, the retry committed a "
                "second distinct effect, and the exact provider effects bind one-to-one to the two OTel executions. "
                "A stable idempotency key preserved the same timeout/retry shape while reducing the provider effect count to one."
            ),
        },
        "binding": {
            "job": precondition["job"],
            "code_symbol": code_symbol,
            "dependency": precondition["dependency"],
            "job_id": unsafe["job_id"],
            "business_event_id": unsafe["business_event_id"],
            "execution_ids": [item["id"] for item in bound_executions],
            "provider_effect_ids": [item["effect_id"] for item in unsafe_effects],
            "first_client_outcome": unsafe_attempts[0]["client_outcome"],
            "retry_client_outcome": unsafe_attempts[1]["client_outcome"],
        },
        "counterfactual_recovery": {
            "idempotency_key": next(iter(protected_keys)),
            "attempts": len(protected_attempts),
            "provider_effect_count": len(protected["provider_effects"]),
            "retry_deduplicated": True,
        },
        "limitations": [
            "The retry scheduler is a bounded harness, so this confirms the retry/idempotency mechanism rather than a specific Sidekiq/Redis transport implementation.",
            "The supported static negative evidence is limited to the scanned PaymentsClient source; runtime provider behavior supplies the stronger evidence used for confirmation.",
            "Other duplicate-effect mechanisms remain competing explanations outside this exact correlated incident path.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Confirm an exact concrete retry-induced duplicate side effect.")
    parser.add_argument("--static-facts", required=True, type=Path)
    parser.add_argument("--runtime-facts", required=True, type=Path)
    parser.add_argument("--xray", required=True, type=Path)
    parser.add_argument("--effect-evidence", required=True, type=Path)
    parser.add_argument("--runtime-evidence", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        output = confirm(
            load_document(args.static_facts),
            load_runtime_json(args.runtime_facts),
            load_json(args.xray),
            load_json(args.effect_evidence),
            load_runtime_evidence(args.runtime_evidence),
        )
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

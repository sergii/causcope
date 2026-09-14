#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

from concrete_system_facts import (
    load_document as load_static_document,
    load_schema as load_static_schema,
    validate_schema as validate_static_schema,
    validate_semantics as validate_static_semantics,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "concrete-runtime-facts.schema.json"
CODE_SYMBOL_ATTRIBUTE = "causcope.code_symbol"
SYSTEM_ID_ATTRIBUTE = "causcope.system_id"
REVISION_ATTRIBUTE = "causcope.revision"
POOL_CHECKOUT_EVENT = "causcope.pool.checkout"
POOL_ID_ATTRIBUTE = "causcope.pool_id"
POOL_TECHNOLOGY_ATTRIBUTE = "causcope.pool.technology"
POOL_CONFIG_NAME_ATTRIBUTE = "causcope.pool.config_name"
POOL_ROLE_ATTRIBUTE = "causcope.pool.role"
POOL_SHARD_ATTRIBUTE = "causcope.pool.shard"
POOL_CHECKOUT_WAIT_ATTRIBUTE = "causcope.pool.checkout_wait_ms"
POOL_SIZE_ATTRIBUTE = "causcope.pool.checkout_size"
POOL_BUSY_ATTRIBUTE = "causcope.pool.checkout_busy"
POOL_WAITING_ATTRIBUTE = "causcope.pool.checkout_waiting"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def decode_any_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    for key in ("stringValue", "boolValue", "intValue", "doubleValue"):
        if key not in value:
            continue
        raw = value[key]
        if key == "intValue":
            return int(raw)
        if key == "doubleValue":
            return float(raw)
        return raw
    return None


def decode_attributes(items: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if isinstance(key, str) and key:
            result[key] = decode_any_value(item.get("value"))
    return result


def iter_spans(payload: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    output: list[tuple[dict[str, Any], dict[str, Any]]] = []
    resource_spans = payload.get("resourceSpans", payload.get("resource_spans", []))
    if not isinstance(resource_spans, list):
        raise ValueError("OTLP resourceSpans must be an array")

    for resource_index, resource_span in enumerate(resource_spans):
        if not isinstance(resource_span, dict):
            raise ValueError(f"resourceSpans[{resource_index}] must be an object")
        resource = resource_span.get("resource", {})
        resource_attributes = (
            decode_attributes(resource.get("attributes", []))
            if isinstance(resource, dict)
            else {}
        )
        scope_spans = resource_span.get("scopeSpans", resource_span.get("scope_spans", []))
        if not isinstance(scope_spans, list):
            raise ValueError(f"resourceSpans[{resource_index}].scopeSpans must be an array")

        for scope_index, scope_span in enumerate(scope_spans):
            if not isinstance(scope_span, dict):
                raise ValueError(f"scopeSpans[{scope_index}] must be an object")
            spans = scope_span.get("spans", [])
            if not isinstance(spans, list):
                raise ValueError("scopeSpans.spans must be an array")
            for span_index, span in enumerate(spans):
                if not isinstance(span, dict):
                    raise ValueError(f"spans[{span_index}] must be an object")
                attributes = dict(resource_attributes)
                attributes.update(decode_attributes(span.get("attributes", [])))
                output.append((span, attributes))

    return output


def parse_nanos(value: Any, label: str) -> int:
    try:
        nanos = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer nanosecond timestamp") from exc
    if nanos < 0:
        raise ValueError(f"{label} must not be negative")
    return nanos


def format_nanos(nanos: int) -> str:
    value = datetime.fromtimestamp(nanos / 1_000_000_000, tz=timezone.utc)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def execution_id(
    system_id: str,
    revision: str,
    code_symbol: str,
    trace_id: str,
    span_id: str,
) -> str:
    digest = hashlib.sha256(
        "\0".join((system_id, revision, code_symbol, trace_id, span_id)).encode("utf-8")
    ).hexdigest()[:16]
    return f"execution.opentelemetry.{digest}"


def pool_interaction_id(
    system_id: str,
    revision: str,
    execution: str,
    pool_id: str,
    event_index: int,
    observed_nanos: int,
) -> str:
    digest = hashlib.sha256(
        "\0".join(
            (
                system_id,
                revision,
                execution,
                pool_id,
                str(event_index),
                str(observed_nanos),
            )
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"pool_interaction.opentelemetry.{digest}"


def validate_static_document(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    validate_static_schema(document, load_static_schema())
    validate_static_semantics(document)
    return {entity["id"]: entity for entity in document["entities"]}


def trace_source(source_uri: str | None) -> dict[str, Any]:
    source: dict[str, Any] = {"type": "trace", "name": "opentelemetry"}
    if source_uri:
        source["uri"] = source_uri
    return source


def span_to_execution(
    span: dict[str, Any],
    attributes: dict[str, Any],
    *,
    static_document: dict[str, Any],
    entities: dict[str, dict[str, Any]],
    source_uri: str | None,
) -> dict[str, Any] | None:
    code_symbol = attributes.get(CODE_SYMBOL_ATTRIBUTE)
    if code_symbol is None:
        return None
    if not isinstance(code_symbol, str) or not code_symbol:
        raise ValueError(f"{CODE_SYMBOL_ATTRIBUTE} must be a non-empty string")

    entity = entities.get(code_symbol)
    if entity is None:
        raise ValueError(f"OTel span references unknown concrete code symbol: {code_symbol}")
    if entity.get("kind") != "code_symbol":
        raise ValueError(f"OTel span code symbol is not a code_symbol entity: {code_symbol}")

    expected_system = static_document["system_id"]
    observed_system = attributes.get(SYSTEM_ID_ATTRIBUTE)
    if observed_system != expected_system:
        raise ValueError(
            f"OTel span system mismatch: expected {expected_system!r}, got {observed_system!r}"
        )

    expected_revision = static_document["revision"]["value"]
    observed_revision = attributes.get(REVISION_ATTRIBUTE)
    if observed_revision != expected_revision:
        raise ValueError(
            f"OTel span revision mismatch: expected {expected_revision!r}, got {observed_revision!r}"
        )

    trace_id = str(span.get("traceId", ""))
    span_id = str(span.get("spanId", ""))
    if not trace_id or not span_id:
        raise ValueError("concrete OTel span must carry non-empty traceId and spanId")

    start = parse_nanos(span.get("startTimeUnixNano"), f"{span_id}.startTimeUnixNano")
    end = parse_nanos(span.get("endTimeUnixNano"), f"{span_id}.endTimeUnixNano")
    if end < start:
        raise ValueError(f"OTel span {span_id} ends before it starts")

    return {
        "id": execution_id(expected_system, expected_revision, code_symbol, trace_id, span_id),
        "code_symbol": code_symbol,
        "start_time": format_nanos(start),
        "end_time": format_nanos(end),
        "duration_ms": (end - start) / 1_000_000,
        "trace_id": trace_id,
        "span_id": span_id,
        "source": trace_source(source_uri),
        "_start_nanos": start,
        "_end_nanos": end,
    }


def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def optional_non_empty_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return require_non_empty_string(value, label)


def require_non_negative_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a non-negative number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a non-negative number") from exc
    if number < 0:
        raise ValueError(f"{label} must be a non-negative number")
    return number


def optional_non_negative_integer(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a non-negative integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a non-negative integer") from exc
    if number < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return number


def span_pool_interactions(
    span: dict[str, Any],
    execution: dict[str, Any],
    *,
    static_document: dict[str, Any],
    entities: dict[str, dict[str, Any]],
    source_uri: str | None,
) -> list[dict[str, Any]]:
    events = span.get("events", [])
    if events is None:
        return []
    if not isinstance(events, list):
        raise ValueError("OTel span events must be an array")

    interactions: list[dict[str, Any]] = []
    expected_system = static_document["system_id"]
    expected_revision = static_document["revision"]["value"]

    for event_index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"OTel span event {event_index} must be an object")
        if event.get("name") != POOL_CHECKOUT_EVENT:
            continue

        attributes = decode_attributes(event.get("attributes", []))
        pool_id = require_non_empty_string(attributes.get(POOL_ID_ATTRIBUTE), POOL_ID_ATTRIBUTE)
        pool_entity = entities.get(pool_id)
        if pool_entity is None:
            raise ValueError(f"pool checkout event references unknown concrete resource pool: {pool_id}")
        if pool_entity.get("kind") != "resource_pool":
            raise ValueError(f"pool checkout event target is not a resource_pool entity: {pool_id}")

        technology = require_non_empty_string(
            attributes.get(POOL_TECHNOLOGY_ATTRIBUTE), POOL_TECHNOLOGY_ATTRIBUTE
        )
        static_technology = pool_entity.get("attributes", {}).get("technology")
        if technology != static_technology:
            raise ValueError(
                f"pool checkout technology mismatch for {pool_id}: "
                f"expected {static_technology!r}, got {technology!r}"
            )

        config_name = require_non_empty_string(
            attributes.get(POOL_CONFIG_NAME_ATTRIBUTE), POOL_CONFIG_NAME_ATTRIBUTE
        )
        static_config_name = pool_entity.get("attributes", {}).get("config_name")
        if config_name != static_config_name:
            raise ValueError(
                f"pool checkout config mismatch for {pool_id}: "
                f"expected {static_config_name!r}, got {config_name!r}"
            )

        observed_nanos = parse_nanos(
            event.get("timeUnixNano"), f"{execution['span_id']}.events[{event_index}].timeUnixNano"
        )
        wait_ms = require_non_negative_number(
            attributes.get(POOL_CHECKOUT_WAIT_ATTRIBUTE), POOL_CHECKOUT_WAIT_ATTRIBUTE
        )
        role = optional_non_empty_string(attributes.get(POOL_ROLE_ATTRIBUTE), POOL_ROLE_ATTRIBUTE)
        shard = optional_non_empty_string(attributes.get(POOL_SHARD_ATTRIBUTE), POOL_SHARD_ATTRIBUTE)

        interaction: dict[str, Any] = {
            "id": pool_interaction_id(
                expected_system,
                expected_revision,
                execution["id"],
                pool_id,
                event_index,
                observed_nanos,
            ),
            "execution_id": execution["id"],
            "code_symbol": execution["code_symbol"],
            "pool_id": pool_id,
            "technology": technology,
            "config_name": config_name,
            "trace_id": execution["trace_id"],
            "span_id": execution["span_id"],
            "event_index": event_index,
            "observed_at": format_nanos(observed_nanos),
            "checkout_wait_ms": wait_ms,
            "source": trace_source(source_uri),
        }
        if role is not None:
            interaction["role"] = role
        if shard is not None:
            interaction["shard"] = shard

        for source_key, target_key in (
            (POOL_SIZE_ATTRIBUTE, "observed_size"),
            (POOL_BUSY_ATTRIBUTE, "observed_busy"),
            (POOL_WAITING_ATTRIBUTE, "observed_waiting"),
        ):
            value = optional_non_negative_integer(attributes.get(source_key), source_key)
            if value is not None:
                interaction[target_key] = value

        interactions.append(interaction)

    return interactions


def derive_overlaps(executions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    overlaps: list[dict[str, Any]] = []
    ordered = sorted(executions, key=lambda item: item["id"])
    for left_index, left in enumerate(ordered):
        for right in ordered[left_index + 1 :]:
            if left["code_symbol"] == right["code_symbol"]:
                continue
            overlap_nanos = min(left["_end_nanos"], right["_end_nanos"]) - max(
                left["_start_nanos"], right["_start_nanos"]
            )
            if overlap_nanos <= 0:
                continue
            overlaps.append(
                {
                    "left_execution": left["id"],
                    "right_execution": right["id"],
                    "left_code_symbol": left["code_symbol"],
                    "right_code_symbol": right["code_symbol"],
                    "overlap_ms": overlap_nanos / 1_000_000,
                }
            )
    return overlaps


def load_runtime_schema() -> dict[str, Any]:
    return load_json(SCHEMA_PATH)


def validate_runtime_document(document: dict[str, Any]) -> None:
    schema = load_runtime_schema()
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
        raise ValueError("concrete runtime facts validation failed:\n" + "\n".join(rendered))

    executions = {execution["id"]: execution for execution in document["executions"]}
    if len(executions) != len(document["executions"]):
        raise ValueError("concrete runtime execution ids must be unique")
    for overlap in document["overlaps"]:
        left = executions.get(overlap["left_execution"])
        right = executions.get(overlap["right_execution"])
        if left is None or right is None:
            raise ValueError("overlap references an unknown execution")
        if left["code_symbol"] != overlap["left_code_symbol"]:
            raise ValueError("overlap left code symbol does not match execution")
        if right["code_symbol"] != overlap["right_code_symbol"]:
            raise ValueError("overlap right code symbol does not match execution")

    interactions = document.get("pool_interactions", [])
    interaction_ids = {interaction["id"] for interaction in interactions}
    if len(interaction_ids) != len(interactions):
        raise ValueError("concrete runtime pool interaction ids must be unique")
    for interaction in interactions:
        execution = executions.get(interaction["execution_id"])
        if execution is None:
            raise ValueError("pool interaction references an unknown execution")
        for field in ("code_symbol", "trace_id", "span_id"):
            if interaction[field] != execution[field]:
                raise ValueError(f"pool interaction {field} does not match its execution")


def build_document(
    static_document: dict[str, Any],
    payload: dict[str, Any],
    *,
    incident_id: str,
    source_uri: str | None,
) -> dict[str, Any]:
    entities = validate_static_document(static_document)
    executions: list[dict[str, Any]] = []
    pool_interactions: list[dict[str, Any]] = []
    for span, attributes in iter_spans(payload):
        execution = span_to_execution(
            span,
            attributes,
            static_document=static_document,
            entities=entities,
            source_uri=source_uri,
        )
        if execution is None:
            continue
        pool_interactions.extend(
            span_pool_interactions(
                span,
                execution,
                static_document=static_document,
                entities=entities,
                source_uri=source_uri,
            )
        )
        executions.append(execution)

    if not executions:
        raise ValueError(
            f"OTel payload contains no spans with {CODE_SYMBOL_ATTRIBUTE} concrete bindings"
        )

    deduplicated = {execution["id"]: execution for execution in executions}
    executions = sorted(deduplicated.values(), key=lambda item: item["id"])
    pool_interactions = sorted(
        {interaction["id"]: interaction for interaction in pool_interactions}.values(),
        key=lambda item: item["id"],
    )
    overlaps = derive_overlaps(executions)

    for execution in executions:
        execution.pop("_start_nanos", None)
        execution.pop("_end_nanos", None)

    document = {
        "schema_version": "0.1",
        "kind": "concrete_runtime_facts",
        "system_id": static_document["system_id"],
        "revision": static_document["revision"],
        "incident_id": incident_id,
        "executions": executions,
        "overlaps": overlaps,
        "pool_interactions": pool_interactions,
        "limitations": [
            "An execution fact proves only that an explicitly bound OTel span was observed for the pinned concrete code symbol and revision.",
            "A pool interaction proves an explicit ActiveRecord checkout event from the bound request span and exact static resource-pool identity; it does not prove saturation by itself.",
            "Temporal overlap proves concurrent span intervals, not simultaneous database lock ownership or a PostgreSQL wait-for cycle.",
            "Unannotated spans and unresolved pool checkouts remain unknown and are not converted into absent facts.",
        ],
    }
    validate_runtime_document(document)
    return document


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Project explicitly bound OpenTelemetry spans into revision-bound concrete runtime facts."
    )
    parser.add_argument("--static-facts", required=True, type=Path)
    parser.add_argument("--otlp", required=True, type=Path)
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--source-uri")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        static_document = load_static_document(args.static_facts)
        payload = load_json(args.otlp)
        document = build_document(
            static_document,
            payload,
            incident_id=args.incident_id,
            source_uri=args.source_uri or str(args.otlp),
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    rendered = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

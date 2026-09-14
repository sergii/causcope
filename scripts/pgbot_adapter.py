#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from causal_projection import ROOT, load_concepts
from runtime_evidence import format_timestamp, parse_timestamp, validate_runtime_references

SCHEMA_PATH = ROOT / "schema" / "pgbot-adapter.schema.json"
DEFAULT_TTL_SECONDS = 300
DEFAULT_CONFIDENCE = "high"


def load_adapter(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict):
        raise ValueError("pgbot adapter document must be an object")

    with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ValueError(
            "pgbot adapter schema validation failed: "
            + "; ".join(error.message for error in errors)
        )
    return document


def load_context(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise ValueError("pgbot JSON context must be an object")
    if not isinstance(document.get("schema_version"), str):
        raise ValueError("pgbot JSON context must include schema_version")
    if not isinstance(document.get("collected_at"), str):
        raise ValueError("pgbot JSON context must include collected_at")
    if not isinstance(document.get("findings"), list):
        raise ValueError("pgbot JSON context must include a findings array")
    parse_timestamp(document["collected_at"], "pgbot.collected_at")
    return document


def validate_context_contract(
    adapter: dict[str, Any],
    context: dict[str, Any],
) -> None:
    version = context["schema_version"]
    accepted = adapter["accepted_schema_versions"]
    if version not in accepted:
        raise ValueError(
            "unsupported pgbot schema_version "
            f"{version}; adapter accepts: {', '.join(accepted)}"
        )


def validate_adapter_references(
    adapter: dict[str, Any],
    concepts: dict[str, dict[str, Any]],
) -> None:
    errors: list[str] = []
    mapping_ids: set[str] = set()
    source_findings: set[str] = set()

    for mapping in adapter["mappings"]:
        mapping_id = mapping["id"]
        source_finding = mapping["source_finding"]

        if mapping_id in mapping_ids:
            errors.append(f"duplicate pgbot mapping id: {mapping_id}")
        mapping_ids.add(mapping_id)

        if source_finding in source_findings:
            errors.append(f"duplicate pgbot source finding mapping: {source_finding}")
        source_findings.add(source_finding)

        observation_id = mapping["observation"]
        concept = concepts.get(observation_id)
        if concept is None:
            errors.append(f"{mapping_id}: unknown observation concept: {observation_id}")
        elif concept.get("kind") != "observation":
            errors.append(
                f"{mapping_id}: mapping must reference an observation: {observation_id}"
            )

    scope = adapter["scope"]
    for entity_id in scope.get("entities", []):
        concept = concepts.get(entity_id)
        if concept is None:
            errors.append(f"unknown pgbot scope entity: {entity_id}")
        elif concept.get("kind") != "system_entity":
            errors.append(f"pgbot scope entity must be a system_entity: {entity_id}")

    for boundary_id in scope.get("boundaries", []):
        concept = concepts.get(boundary_id)
        if concept is None:
            errors.append(f"unknown pgbot scope boundary: {boundary_id}")
        elif concept.get("kind") != "boundary":
            errors.append(f"pgbot scope boundary must be a boundary: {boundary_id}")

    if errors:
        raise ValueError("; ".join(errors))


def confidence_label(value: Any, fallback: str) -> str:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        if value >= 0.8:
            return "high"
        if value >= 0.5:
            return "moderate"
        return "low"
    return fallback


def build_scope(adapter: dict[str, Any]) -> dict[str, Any]:
    configured = adapter["scope"]
    scope: dict[str, Any] = {}
    if configured.get("entities"):
        scope["entities"] = sorted(configured["entities"])
    if configured.get("boundaries"):
        scope["boundaries"] = sorted(configured["boundaries"])
    if configured.get("attributes"):
        scope["attributes"] = dict(sorted(configured["attributes"].items()))
    return scope


def instance_id(
    adapter_id: str,
    finding: dict[str, Any],
    context: dict[str, Any],
) -> str:
    identity = json.dumps(
        {
            "adapter": adapter_id,
            "finding": finding.get("id"),
            "object": finding.get("object"),
            "objects": finding.get("objects", []),
            "collected_at": context.get("collected_at"),
            "fingerprint": context.get("fingerprint"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"evidence.pgbot.{finding.get('id', 'unknown')}.{digest}"


def finding_note(finding: dict[str, Any]) -> str:
    parts: list[str] = []
    detail = finding.get("detail")
    if isinstance(detail, str) and detail:
        parts.append(detail)

    caveats = finding.get("caveats")
    if isinstance(caveats, list):
        clean = [item for item in caveats if isinstance(item, str) and item]
        if clean:
            parts.append("Caveats: " + " | ".join(clean))
    return " ".join(parts)


def build_runtime_evidence(
    adapter: dict[str, Any],
    context: dict[str, Any],
    concepts: dict[str, dict[str, Any]],
    *,
    incident_id: str,
    source_uri: str | None = None,
) -> dict[str, Any]:
    validate_context_contract(adapter, context)
    validate_adapter_references(adapter, concepts)

    mappings = {
        mapping["source_finding"]: mapping
        for mapping in adapter["mappings"]
    }
    collected_at = parse_timestamp(context["collected_at"], "pgbot.collected_at")
    default_ttl = adapter.get("default_ttl_seconds", DEFAULT_TTL_SECONDS)
    default_confidence = adapter.get("default_confidence", DEFAULT_CONFIDENCE)
    scope = build_scope(adapter)

    instances: list[dict[str, Any]] = []
    suppressed_count = 0

    for finding in context["findings"]:
        if not isinstance(finding, dict):
            raise ValueError("pgbot findings must contain objects")

        finding_id = finding.get("id")
        if not isinstance(finding_id, str) or not finding_id:
            raise ValueError("pgbot finding must include a non-empty id")

        mapping = mappings.get(finding_id)
        if mapping is None:
            continue

        if finding.get("suppressed") is True:
            suppressed_count += 1
            continue

        ttl_seconds = default_ttl
        confidence = mapping.get(
            "confidence",
            confidence_label(finding.get("confidence"), default_confidence),
        )

        source_attributes = {
            "pgbot.schema_version": str(context["schema_version"]),
            "pgbot.finding_id": finding_id,
            "pgbot.severity": str(finding.get("severity", "")),
            "pgbot.confidence": str(finding.get("confidence", "")),
        }
        fingerprint = context.get("fingerprint")
        if isinstance(fingerprint, str) and fingerprint:
            source_attributes["pgbot.fingerprint"] = fingerprint

        object_name = finding.get("object")
        if isinstance(object_name, str) and object_name:
            source_attributes["pgbot.object"] = object_name

        source: dict[str, Any] = {
            "type": "other",
            "name": f"pgbot:{finding_id}",
            "attributes": source_attributes,
        }
        if source_uri is not None:
            source["uri"] = source_uri

        labels = {
            "adapter": adapter["id"],
            "mapping": mapping["id"],
            "source_finding": finding_id,
            "severity": str(finding.get("severity", "")),
        }
        impact = finding.get("impact")
        if isinstance(impact, dict):
            dimension = impact.get("dimension")
            if isinstance(dimension, str) and dimension:
                labels["impact_dimension"] = dimension

        instance: dict[str, Any] = {
            "id": instance_id(adapter["id"], finding, context),
            "observation": mapping["observation"],
            "state": "observed",
            "observed_at": format_timestamp(collected_at),
            "expires_at": format_timestamp(
                collected_at + timedelta(seconds=ttl_seconds)
            ),
            "confidence": confidence,
            "source": source,
            "scope": scope,
            "labels": labels,
        }

        note = finding_note(finding)
        if note:
            instance["note"] = note

        instances.append(instance)

    if not instances:
        raise ValueError("pgbot context matched no active mapped findings")

    instances.sort(key=lambda instance: instance["id"])
    description = f"Generated by pgbot adapter {adapter['id']}."
    if suppressed_count:
        description += (
            f" Skipped {suppressed_count} source-suppressed mapped finding(s); "
            "suppressed findings are not converted to absent evidence."
        )

    document = {
        "schema_version": "0.1",
        "kind": "runtime_evidence",
        "incident_id": incident_id,
        "description": description,
        "instances": instances,
    }
    validate_runtime_references(document, concepts)
    return document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Translate pgbot JSON findings into Causcope runtime evidence."
    )
    parser.add_argument("adapter", type=Path, help="pgbot adapter mapping YAML")
    parser.add_argument("context", type=Path, help="pgbot --json context")
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--source-uri")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(root: Path = ROOT) -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        adapter = load_adapter(args.adapter)
        context = load_context(args.context)
        concepts = load_concepts(root)
        document = build_runtime_evidence(
            adapter,
            context,
            concepts,
            incident_id=args.incident_id,
            source_uri=args.source_uri,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(
        json.dumps(
            document,
            indent=2 if args.pretty else None,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

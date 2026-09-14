#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator

from causal_projection import ROOT, load_concepts
from pgbot_adapter import load_adapter
from pgbot_autonomous_provider import PgbotAutonomousProbeProvider, file_context_supplier

SCHEMA_PATH = ROOT / "schema" / "diagnostic-provider-capabilities.schema.json"


class CapabilityProvider(Protocol):
    def capability_projection(self) -> dict[str, Any]: ...


def validate_provider_capabilities(document: dict[str, Any]) -> None:
    with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ValueError(
            "diagnostic provider capabilities schema validation failed: "
            + "; ".join(error.message for error in errors)
        )


def build_provider_capabilities(
    providers: list[CapabilityProvider],
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for provider in providers:
        projection = provider.capability_projection()
        provider_id = projection.get("id")
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError("diagnostic provider projection must include a non-empty id")
        if provider_id in seen:
            raise ValueError(f"duplicate diagnostic provider id: {provider_id}")
        seen.add(provider_id)
        entries.append(projection)

    entries.sort(key=lambda item: item["id"])
    document = {
        "schema_version": "0.1",
        "kind": "diagnostic_provider_capabilities",
        "providers": entries,
    }
    validate_provider_capabilities(document)
    return document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Discover configured external diagnostic provider capabilities without executing probes."
    )
    parser.add_argument("--pgbot-adapter", type=Path)
    parser.add_argument("--pgbot-report", type=Path)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(root: Path = ROOT) -> int:
    parser = build_parser()
    args = parser.parse_args()
    if (args.pgbot_adapter is None) != (args.pgbot_report is None):
        parser.error("--pgbot-adapter and --pgbot-report must be provided together")

    providers: list[CapabilityProvider] = []
    try:
        if args.pgbot_adapter is not None:
            concepts = load_concepts(root)
            adapter = load_adapter(args.pgbot_adapter)
            providers.append(
                PgbotAutonomousProbeProvider(
                    adapter=adapter,
                    concepts=concepts,
                    context_supplier=file_context_supplier(args.pgbot_report),
                )
            )
        document = build_provider_capabilities(providers)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(json.dumps(document, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from causal_projection import ROOT
from pgbot_adapter import load_adapter, load_context
from pgbot_autonomous_provider import (
    PGBOT_PROVIDER_ID,
    PgbotAutonomousProbeProvider,
    file_context_supplier,
)
from resource_topology import ResourceTopology

SCHEMA_PATH = ROOT / "schema" / "provider-bindings.schema.json"


def _load_schema() -> dict[str, Any]:
    document = yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{SCHEMA_PATH} must contain an object")
    Draft202012Validator.check_schema(document)
    return document


def load_provider_bindings_document(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain an object")
    errors = sorted(
        Draft202012Validator(_load_schema()).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ValueError(
            f"provider bindings schema validation failed for {path}: "
            + "; ".join(error.message for error in errors)
        )
    provider_instances = [item["provider_instance"] for item in document["bindings"]]
    duplicates = sorted(
        provider_instance
        for provider_instance in set(provider_instances)
        if provider_instances.count(provider_instance) > 1
    )
    if duplicates:
        raise ValueError("duplicate provider bindings: " + ", ".join(duplicates))
    return document


def _resolve_path(config_path: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (config_path.parent / candidate).resolve()


def _validate_pgbot_target_identity(
    *,
    provider_instance: str,
    topology: ResourceTopology,
    context: dict[str, Any],
) -> None:
    instance = topology.provider_instance(provider_instance)
    target = topology.resource(instance["target"])
    expected_database = target.get("attributes", {}).get("database")
    if not isinstance(expected_database, str) or not expected_database:
        return
    observed_database = context.get("server", {}).get("database")
    if observed_database != expected_database:
        raise ValueError(
            f"pgbot provider binding {provider_instance} database identity mismatch: "
            f"topology target expects {expected_database!r}, report contains {observed_database!r}"
        )


def load_provider_instance_bindings(
    path: Path,
    *,
    topology: ResourceTopology,
    concepts: dict[str, dict[str, Any]],
    incident_id: str,
) -> dict[str, PgbotAutonomousProbeProvider]:
    if not incident_id:
        raise ValueError("provider bindings require a non-empty incident_id")
    document = load_provider_bindings_document(path)
    bindings: dict[str, PgbotAutonomousProbeProvider] = {}

    for entry in document["bindings"]:
        provider_instance = entry["provider_instance"]
        instance = topology.provider_instance(provider_instance)
        provider_type = topology.provider_type(instance["provider_type"])
        driver = entry["driver"]

        if driver != "pgbot_file":
            raise ValueError(f"unsupported provider binding driver: {driver}")
        if provider_type.get("instrument") != "pgbot":
            raise ValueError(
                f"provider binding {provider_instance} uses pgbot_file but topology provider type "
                f"instrument is {provider_type.get('instrument')!r}"
            )
        if provider_type.get("provider_id") != PGBOT_PROVIDER_ID:
            raise ValueError(
                f"provider binding {provider_instance} expects provider id "
                f"{provider_type.get('provider_id')!r}, not {PGBOT_PROVIDER_ID!r}"
            )

        adapter_path = _resolve_path(path, entry["adapter"])
        context_path = _resolve_path(path, entry["context"])
        adapter = load_adapter(adapter_path)
        context = load_context(context_path)
        _validate_pgbot_target_identity(
            provider_instance=provider_instance,
            topology=topology,
            context=context,
        )

        provider = PgbotAutonomousProbeProvider(
            adapter=adapter,
            concepts=concepts,
            context_supplier=file_context_supplier(context_path),
            incident_id=incident_id,
            source_uri=f"provider-instance:{provider_instance}",
        )
        projection = provider.capability_projection()
        if projection["id"] != provider_type["provider_id"]:
            raise ValueError(
                f"provider binding {provider_instance} runtime provider id {projection['id']!r} "
                f"does not match topology provider id {provider_type['provider_id']!r}"
            )
        bindings[provider_instance] = provider

    return bindings

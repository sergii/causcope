#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml
from jsonschema import Draft202012Validator

from causal_projection import ROOT
from pgbot_adapter import load_adapter, load_context
from pgbot_autonomous_provider import (
    PGBOT_PROVIDER_ID,
    FileContextSupplier,
    PgbotAutonomousProbeProvider,
    file_context_supplier,
)
from pgbot_cli_context import PgbotCliContextSupplier
from rails_pool_autonomous_provider import (
    RAILS_POOL_INSTRUMENT,
    RAILS_POOL_PROVIDER_ID,
    RailsPoolAutonomousProvider,
)
from resource_topology import ResourceTopology

SCHEMA_PATH = ROOT / "schema" / "provider-bindings.schema.json"
PgbotContextSupplier = Callable[[], dict[str, Any]]


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


def _expected_database(*, provider_instance: str, topology: ResourceTopology) -> str | None:
    instance = topology.provider_instance(provider_instance)
    target = topology.resource(instance["target"])
    value = target.get("attributes", {}).get("database")
    return value if isinstance(value, str) and value else None


def _validate_pgbot_database_identity(
    *, provider_instance: str, expected_database: str | None, context: dict[str, Any]
) -> None:
    if expected_database is None:
        return
    observed_database = context.get("server", {}).get("database")
    if observed_database != expected_database:
        raise ValueError(
            f"pgbot provider binding {provider_instance} database identity mismatch: "
            f"topology target expects {expected_database!r}, report contains {observed_database!r}"
        )


@dataclass(frozen=True)
class TargetValidatedPgbotContextSupplier:
    provider_instance: str
    expected_database: str | None
    delegate: PgbotContextSupplier

    def __call__(self) -> dict[str, Any]:
        context = self.delegate()
        _validate_pgbot_database_identity(
            provider_instance=self.provider_instance,
            expected_database=self.expected_database,
            context=context,
        )
        return context

    def availability(self, adapter: dict[str, Any]) -> tuple[bool, str | None]:
        checker = getattr(self.delegate, "availability", None)
        if not callable(checker):
            return False, "pgbot context supplier does not expose an availability check"
        available, reason = checker(adapter)
        if not available:
            return available, reason
        if isinstance(self.delegate, FileContextSupplier):
            context = self.delegate()
            _validate_pgbot_database_identity(
                provider_instance=self.provider_instance,
                expected_database=self.expected_database,
                context=context,
            )
        return True, None


def _pgbot_supplier(
    *, config_path: Path, entry: dict[str, Any], provider_instance: str, topology: ResourceTopology
) -> TargetValidatedPgbotContextSupplier:
    expected_database = _expected_database(provider_instance=provider_instance, topology=topology)
    driver = entry["driver"]
    if driver == "pgbot_file":
        context_path = _resolve_path(config_path, entry["context"])
        context = load_context(context_path)
        _validate_pgbot_database_identity(
            provider_instance=provider_instance,
            expected_database=expected_database,
            context=context,
        )
        delegate: PgbotContextSupplier = file_context_supplier(context_path)
    elif driver == "pgbot_cli":
        delegate = PgbotCliContextSupplier(
            database_url_env=entry["database_url_env"],
            timeout_seconds=int(entry.get("timeout_seconds", 30)),
        )
    else:
        raise ValueError(f"unsupported pgbot provider binding driver: {driver}")
    return TargetValidatedPgbotContextSupplier(
        provider_instance=provider_instance,
        expected_database=expected_database,
        delegate=delegate,
    )


def load_provider_instance_bindings(
    path: Path,
    *,
    topology: ResourceTopology,
    concepts: dict[str, dict[str, Any]],
    incident_id: str,
) -> dict[str, Any]:
    if not incident_id:
        raise ValueError("provider bindings require a non-empty incident_id")
    document = load_provider_bindings_document(path)
    bindings: dict[str, Any] = {}

    for entry in document["bindings"]:
        provider_instance = entry["provider_instance"]
        instance = topology.provider_instance(provider_instance)
        provider_type = topology.provider_type(instance["provider_type"])
        driver = entry["driver"]

        if driver == "rails_pool_file":
            if provider_type.get("instrument") != RAILS_POOL_INSTRUMENT:
                raise ValueError(
                    f"provider binding {provider_instance} uses {driver} but topology provider type "
                    f"instrument is {provider_type.get('instrument')!r}"
                )
            if provider_type.get("provider_id") != RAILS_POOL_PROVIDER_ID:
                raise ValueError(
                    f"provider binding {provider_instance} expects provider id "
                    f"{provider_type.get('provider_id')!r}, not {RAILS_POOL_PROVIDER_ID!r}"
                )
            provider: Any = RailsPoolAutonomousProvider(
                pool_path=_resolve_path(path, entry["pool_evidence"]),
                runtime_evidence_path=_resolve_path(path, entry["runtime_evidence"]),
                diagnosis_path=_resolve_path(path, entry["diagnosis"]),
                concepts=concepts,
                incident_id=incident_id,
                source_uri=f"provider-instance:{provider_instance}",
            )
        else:
            if driver not in {"pgbot_file", "pgbot_cli"}:
                raise ValueError(f"unsupported provider binding driver: {driver}")
            if provider_type.get("instrument") != "pgbot":
                raise ValueError(
                    f"provider binding {provider_instance} uses {driver} but topology provider type "
                    f"instrument is {provider_type.get('instrument')!r}"
                )
            if provider_type.get("provider_id") != PGBOT_PROVIDER_ID:
                raise ValueError(
                    f"provider binding {provider_instance} expects provider id "
                    f"{provider_type.get('provider_id')!r}, not {PGBOT_PROVIDER_ID!r}"
                )
            adapter = load_adapter(_resolve_path(path, entry["adapter"]))
            supplier = _pgbot_supplier(
                config_path=path,
                entry=entry,
                provider_instance=provider_instance,
                topology=topology,
            )
            provider = PgbotAutonomousProbeProvider(
                adapter=adapter,
                concepts=concepts,
                context_supplier=supplier,
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

#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "resource-topology.schema.json"


def _load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_resource_topology(document: dict[str, Any]) -> None:
    validator = Draft202012Validator(_load_schema())
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        raise ValueError(
            "resource topology schema validation failed: "
            + "; ".join(error.message for error in errors)
        )

    registries = {
        "resource": document["resources"],
        "runner": document["runners"],
        "provider_type": document["provider_types"],
        "provider_instance": document["provider_instances"],
    }
    ids: dict[str, str] = {}
    for registry_name, entries in registries.items():
        for entry in entries:
            entry_id = entry["id"]
            previous = ids.get(entry_id)
            if previous is not None:
                raise ValueError(
                    f"duplicate topology id {entry_id}: {previous} and {registry_name}"
                )
            ids[entry_id] = registry_name

    resource_ids = {entry["id"] for entry in document["resources"]}
    runner_ids = {entry["id"] for entry in document["runners"]}
    provider_type_ids = {entry["id"] for entry in document["provider_types"]}

    relationship_keys: set[tuple[str, str, str]] = set()
    for relationship in document["relationships"]:
        source = relationship["from"]
        target = relationship["to"]
        if source not in resource_ids:
            raise ValueError(f"relationship references unknown source resource: {source}")
        if target not in resource_ids:
            raise ValueError(f"relationship references unknown target resource: {target}")
        key = (source, relationship["relation"], target)
        if key in relationship_keys:
            raise ValueError(f"duplicate topology relationship: {key}")
        relationship_keys.add(key)

    for instance in document["provider_instances"]:
        provider_type = instance["provider_type"]
        target = instance["target"]
        runner = instance["runner"]
        endpoint_resource = instance.get("endpoint_resource", target)
        if provider_type not in provider_type_ids:
            raise ValueError(
                f"provider instance {instance['id']} references unknown provider type: {provider_type}"
            )
        if target not in resource_ids:
            raise ValueError(
                f"provider instance {instance['id']} references unknown target resource: {target}"
            )
        if endpoint_resource not in resource_ids:
            raise ValueError(
                f"provider instance {instance['id']} references unknown endpoint resource: "
                f"{endpoint_resource}"
            )
        if runner not in runner_ids:
            raise ValueError(
                f"provider instance {instance['id']} references unknown runner: {runner}"
            )


class ResourceTopology:
    def __init__(self, document: dict[str, Any]) -> None:
        validate_resource_topology(document)
        self._document = copy.deepcopy(document)
        self._resources = {entry["id"]: entry for entry in self._document["resources"]}
        self._runners = {entry["id"]: entry for entry in self._document["runners"]}
        self._provider_types = {
            entry["id"]: entry for entry in self._document["provider_types"]
        }
        self._provider_instances = {
            entry["id"]: entry for entry in self._document["provider_instances"]
        }

    def resource(self, resource_id: str) -> dict[str, Any]:
        try:
            return copy.deepcopy(self._resources[resource_id])
        except KeyError as exc:
            raise ValueError(f"unknown topology resource: {resource_id}") from exc

    def runner(self, runner_id: str) -> dict[str, Any]:
        try:
            return copy.deepcopy(self._runners[runner_id])
        except KeyError as exc:
            raise ValueError(f"unknown topology runner: {runner_id}") from exc

    def provider_type(self, provider_type_id: str) -> dict[str, Any]:
        try:
            return copy.deepcopy(self._provider_types[provider_type_id])
        except KeyError as exc:
            raise ValueError(f"unknown topology provider type: {provider_type_id}") from exc

    def provider_instance(self, provider_instance_id: str) -> dict[str, Any]:
        try:
            return copy.deepcopy(self._provider_instances[provider_instance_id])
        except KeyError as exc:
            raise ValueError(
                f"unknown topology provider instance: {provider_instance_id}"
            ) from exc

    def provider_endpoint(self, provider_instance_id: str) -> dict[str, Any]:
        instance = self.provider_instance(provider_instance_id)
        return self.resource(instance.get("endpoint_resource", instance["target"]))

    @property
    def provider_instances(self) -> list[dict[str, Any]]:
        return [
            copy.deepcopy(self._provider_instances[instance_id])
            for instance_id in sorted(self._provider_instances)
        ]

    def provider_instances_for_target(self, resource_id: str) -> list[dict[str, Any]]:
        self.resource(resource_id)
        return [
            instance
            for instance in self.provider_instances
            if instance["target"] == resource_id
        ]

    def dependencies_from(self, resource_id: str) -> list[dict[str, Any]]:
        self.resource(resource_id)
        relationships = [
            copy.deepcopy(relationship)
            for relationship in self._document["relationships"]
            if relationship["from"] == resource_id
        ]
        return sorted(
            relationships,
            key=lambda relationship: (
                relationship["relation"],
                relationship["to"],
            ),
        )

    def canonical_document(self) -> dict[str, Any]:
        document = copy.deepcopy(self._document)
        for key in ("resources", "runners", "provider_types", "provider_instances"):
            document[key] = sorted(document[key], key=lambda entry: entry["id"])
        document["relationships"] = sorted(
            document["relationships"],
            key=lambda relationship: (
                relationship["from"],
                relationship["relation"],
                relationship["to"],
            ),
        )
        return document


def load_resource_topology(path: Path) -> ResourceTopology:
    with path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict):
        raise ValueError("resource topology must be a YAML object")
    return ResourceTopology(document)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and project a Causcope resource topology."
    )
    parser.add_argument("path", type=Path, help="Resource topology YAML file")
    parser.add_argument(
        "--target",
        help="Show provider instances bound to one resource target",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        topology = load_resource_topology(args.path)
        if args.target:
            output: Any = {
                "target": topology.resource(args.target),
                "provider_instances": topology.provider_instances_for_target(args.target),
            }
        else:
            output = topology.canonical_document()
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(json.dumps(output, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

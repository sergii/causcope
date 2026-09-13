#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_SCHEMA = ROOT / "schema" / "testbed-scenario.schema.json"
ORACLE_SCHEMA = ROOT / "schema" / "testbed-scenario-oracle.schema.json"
TESTBED_ROOT = ROOT / "testbed"
FORBIDDEN_PUBLIC_KEYS = {"root_cause", "hidden_truth", "expected_evidence", "causal_notes"}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate(document: Any, schema: dict[str, Any], label: str) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        details = "; ".join(error.message for error in errors)
        raise ValueError(f"{label}: {details}")


def walk_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key))
            keys.update(walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(walk_keys(child))
    return keys


def compose_services(compose_path: Path) -> set[str]:
    document = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("services"), dict):
        raise ValueError(f"invalid compose file: {compose_path}")
    return set(document["services"])


def main() -> int:
    scenario_schema = load_json(SCENARIO_SCHEMA)
    oracle_schema = load_json(ORACLE_SCHEMA)
    scenario_files = sorted(TESTBED_ROOT.glob("*/scenarios/*/scenario.json"))
    if not scenario_files:
        raise ValueError("no testbed scenarios found")

    ids: set[str] = set()
    slugs: set[str] = set()
    validated = 0

    for scenario_path in scenario_files:
        scenario = load_json(scenario_path)
        validate(scenario, scenario_schema, str(scenario_path.relative_to(ROOT)))

        scenario_id = scenario["id"]
        slug = scenario["slug"]
        if scenario_id in ids:
            raise ValueError(f"duplicate testbed scenario id: {scenario_id}")
        if slug in slugs:
            raise ValueError(f"duplicate testbed scenario slug: {slug}")
        ids.add(scenario_id)
        slugs.add(slug)

        if scenario_path.parent.name != slug:
            raise ValueError(
                f"scenario directory {scenario_path.parent.name!r} must match slug {slug!r}"
            )

        leaked = walk_keys(scenario).intersection(FORBIDDEN_PUBLIC_KEYS)
        if leaked:
            raise ValueError(
                f"public scenario {slug} leaks oracle-only keys: {sorted(leaked)}"
            )

        oracle_path = scenario_path.parent / scenario["oracle_file"]
        if not oracle_path.exists():
            raise ValueError(f"missing oracle for {slug}: {oracle_path}")
        oracle = load_json(oracle_path)
        validate(oracle, oracle_schema, str(oracle_path.relative_to(ROOT)))
        if oracle["scenario_id"] != scenario_id:
            raise ValueError(
                f"oracle scenario_id {oracle['scenario_id']!r} does not match {scenario_id!r}"
            )

        shop_root = scenario_path.parents[2]
        compose_path = shop_root / "compose.yaml"
        services = compose_services(compose_path)
        service = scenario["activation"]["service"]
        if service not in services:
            raise ValueError(
                f"scenario {slug} references unknown compose service {service!r}"
            )

        validated += 1

    print(f"testbed scenarios: {validated} valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

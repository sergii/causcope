#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from scoping_projection import ROOT, build_scoping_projection, load_incident_context

SCENARIO_SCHEMA = ROOT / "schema" / "investigation-scenario.schema.json"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_scenario(path: Path) -> dict[str, Any]:
    document = load_yaml(path)
    if not isinstance(document, dict):
        raise ValueError("investigation scenario must be an object")
    validator = Draft202012Validator(load_json(SCENARIO_SCHEMA))
    errors = sorted(validator.iter_errors(document), key=lambda item: list(item.path))
    if errors:
        raise ValueError(
            "invalid investigation scenario: "
            + "; ".join(error.message for error in errors)
        )
    return document


def repo_path(relative_path: str) -> Path:
    candidate = (ROOT / relative_path).resolve()
    try:
        candidate.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError(f"scenario path escapes repository: {relative_path}") from exc
    return candidate


def run_baseline(scenario: dict[str, Any]) -> dict[str, Any]:
    context_path = repo_path(scenario["initial_context_file"])
    context = load_incident_context(context_path)
    projection = build_scoping_projection(context)
    next_action = projection.get("next_action")
    actual_dimension = next_action.get("dimension") if next_action else None
    expected_dimension = scenario["evaluation"]["expected_first_dimension"]
    passed = actual_dimension == expected_dimension

    return {
        "schema_version": "0.1",
        "kind": "investigation_lab_result",
        "scenario_id": scenario["id"],
        "incident_id": context["incident_id"],
        "baseline": "deterministic_scoping_projection",
        "passed": passed,
        "expected_first_dimension": expected_dimension,
        "actual_first_dimension": actual_dimension,
        "scoping_completeness": projection["completeness"],
        "known_count": projection["known_count"],
        "partial_count": projection["partial_count"],
        "unknown_count": projection["unknown_count"],
        "required_behaviors": scenario["evaluation"]["required_behaviors"],
        "forbidden_behaviors": scenario["evaluation"]["forbidden_behaviors"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the deterministic baseline for an investigation-lab scenario."
    )
    parser.add_argument("scenario", type=Path, help="Investigation scenario YAML file")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    scenario = load_scenario(args.scenario)
    result = run_baseline(scenario)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
DIMENSIONS_PATH = ROOT / "vocabulary" / "investigation-dimensions.yaml"
INCIDENT_CONTEXT_SCHEMA = ROOT / "schema" / "incident-context.schema.json"
SCOPING_PROJECTION_SCHEMA = ROOT / "schema" / "scoping-projection.schema.json"

STATE_SCORE = {"known": 1.0, "partial": 0.5, "unknown": 0.0}


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _validate(document: dict[str, Any], schema_path: Path, label: str) -> None:
    validator = Draft202012Validator(load_json(schema_path))
    errors = sorted(validator.iter_errors(document), key=lambda item: list(item.path))
    if not errors:
        return
    details = "; ".join(error.message for error in errors)
    raise ValueError(f"invalid {label}: {details}")


def load_incident_context(path: Path) -> dict[str, Any]:
    document = load_yaml(path)
    if not isinstance(document, dict):
        raise ValueError("incident context must be an object")
    _validate(document, INCIDENT_CONTEXT_SCHEMA, "incident context")
    return document


def load_dimension_registry(path: Path = DIMENSIONS_PATH) -> list[dict[str, Any]]:
    document = load_yaml(path)
    if not isinstance(document, dict) or document.get("kind") != "investigation_dimension_registry":
        raise ValueError("invalid investigation dimension registry")
    dimensions = document.get("dimensions")
    if not isinstance(dimensions, list) or len(dimensions) != 10:
        raise ValueError("investigation dimension registry must contain exactly 10 dimensions")
    ids = [item.get("id") for item in dimensions if isinstance(item, dict)]
    orders = [item.get("order") for item in dimensions if isinstance(item, dict)]
    if len(ids) != 10 or len(set(ids)) != 10:
        raise ValueError("investigation dimension ids must be unique")
    if sorted(orders) != list(range(1, 11)):
        raise ValueError("investigation dimension orders must be 1 through 10")
    return sorted(dimensions, key=lambda item: item["order"])


def _explicit_unknown(context: dict[str, Any], dimension: dict[str, Any]) -> bool:
    unknowns = set(context.get("unknowns", []))
    return bool(unknowns.intersection(dimension.get("legacy_unknowns", [])))


def _apply_explicit_unknown(state: str, signals: list[str], explicit_unknown: bool) -> str:
    if not explicit_unknown:
        return state
    return "partial" if signals else "unknown"


def _dimension_state(
    context: dict[str, Any],
    dimension: dict[str, Any],
) -> tuple[str, list[str]]:
    dimension_id = dimension["id"]
    scope = context.get("scope", {})
    time = context.get("time", {})
    impact = context.get("impact", {})
    reproduction = context.get("reproduction", {})
    signals: list[str] = []
    state = "unknown"

    if dimension_id == "investigation.blast_radius":
        subjects = scope.get("subjects", [])
        populations = impact.get("populations", [])
        if subjects:
            signals.append("scope.subjects")
        if any("affected" in population for population in populations):
            signals.append("impact.populations.affected")
        if any("total" in population for population in populations):
            signals.append("impact.populations.total")
        complete_population = any(
            "affected" in population and "total" in population
            for population in populations
        )
        state = "known" if complete_population else ("partial" if signals else "unknown")

    elif dimension_id == "investigation.where":
        for field in ("environments", "regions", "availability_zones", "datacenters"):
            if scope.get(field):
                signals.append(f"scope.{field}")
        state = "known" if signals else "unknown"

    elif dimension_id == "investigation.when":
        for field in ("onset_at", "last_known_good_at", "first_reported_at"):
            if time.get(field):
                signals.append(f"time.{field}")
        if time.get("pattern") and time.get("pattern") != "unknown":
            signals.append("time.pattern")
        state = (
            "known"
            if time.get("onset_at") and time.get("pattern") not in (None, "unknown")
            else ("partial" if signals else "unknown")
        )

    elif dimension_id == "investigation.flow":
        for field in ("features", "operations"):
            if scope.get(field):
                signals.append(f"scope.{field}")
        state = "known" if signals else "unknown"

    elif dimension_id == "investigation.client":
        if scope.get("clients"):
            signals.append("scope.clients")
        state = "known" if signals else "unknown"

    elif dimension_id == "investigation.change":
        if "changes" in context:
            signals.append("changes" if context.get("changes") else "changes.explicit_none")
            state = "known"

    elif dimension_id == "investigation.dependency":
        if scope.get("dependencies"):
            signals.append("scope.dependencies")
        if scope.get("boundaries"):
            signals.append("scope.boundaries")
        if not signals and "dependencies" in scope:
            signals.append("scope.dependencies.explicit_none")
        state = "known" if signals else "unknown"

    elif dimension_id == "investigation.data":
        if scope.get("data"):
            signals.append("scope.data")
        elif "data" in scope:
            signals.append("scope.data.explicit_none")
        state = "known" if signals else "unknown"

    elif dimension_id == "investigation.reproducibility":
        status = reproduction.get("status")
        if status and status != "unknown":
            signals.append("reproduction.status")
        if reproduction.get("conditions"):
            signals.append("reproduction.conditions")
        if reproduction.get("steps"):
            signals.append("reproduction.steps")
        state = "known" if status and status != "unknown" else ("partial" if signals else "unknown")

    elif dimension_id == "investigation.impact":
        severity = impact.get("severity")
        if severity and severity != "unknown":
            signals.append("impact.severity")
        if impact.get("user_effect"):
            signals.append("impact.user_effect")
        if impact.get("business_effect"):
            signals.append("impact.business_effect")
        if impact.get("populations"):
            signals.append("impact.populations")
        state = (
            "known"
            if severity and severity != "unknown" and len(signals) >= 2
            else ("partial" if signals else "unknown")
        )

    else:
        raise ValueError(f"unsupported investigation dimension: {dimension_id}")

    state = _apply_explicit_unknown(state, signals, _explicit_unknown(context, dimension))
    return state, signals


def build_scoping_projection(
    context: dict[str, Any],
    *,
    dimensions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registry = dimensions or load_dimension_registry()
    projected_dimensions: list[dict[str, Any]] = []

    for dimension in registry:
        state, signals = _dimension_state(context, dimension)
        projected_dimensions.append(
            {
                "id": dimension["id"],
                "order": dimension["order"],
                "title": dimension["title"],
                "state": state,
                "question": dimension["question"],
                "reason": dimension["rationale"],
                "signals": signals,
            }
        )

    known_count = sum(item["state"] == "known" for item in projected_dimensions)
    partial_count = sum(item["state"] == "partial" for item in projected_dimensions)
    unknown_count = sum(item["state"] == "unknown" for item in projected_dimensions)
    completeness = round(
        sum(STATE_SCORE[item["state"]] for item in projected_dimensions) / len(projected_dimensions),
        3,
    )

    candidates = [item for item in projected_dimensions if item["state"] != "known"]
    candidates.sort(key=lambda item: item["order"])
    next_action = None
    if candidates:
        candidate = candidates[0]
        next_action = {
            "kind": "ask_question",
            "dimension": candidate["id"],
            "priority": candidate["order"],
            "question": candidate["question"],
            "reason": candidate["reason"],
            "expected_information_gain": "high" if candidate["order"] <= 7 else "medium",
        }

    projection = {
        "schema_version": "0.1",
        "kind": "scoping_projection",
        "incident_id": context["incident_id"],
        "completeness": completeness,
        "known_count": known_count,
        "partial_count": partial_count,
        "unknown_count": unknown_count,
        "dimensions": projected_dimensions,
        "next_action": next_action,
    }
    _validate(projection, SCOPING_PROJECTION_SCHEMA, "scoping projection")
    return projection


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Project incident context into deterministic investigation scoping state."
    )
    parser.add_argument("context", type=Path, help="Incident context YAML file")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    context = load_incident_context(args.context)
    projection = build_scoping_projection(context)
    print(json.dumps(projection, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

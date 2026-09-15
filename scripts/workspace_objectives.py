#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "workspace-objectives.schema.json"
DEFAULT_FILENAME = "objectives.yaml"
REQUEST_LATENCY_OBSERVATION = "observation.http.request_latency"
POOL_WAIT_OBSERVATION = "observation.database.connection_pool_wait_time"
SUPPORTED_OBSERVATIONS = {
    REQUEST_LATENCY_OBSERVATION,
    POOL_WAIT_OBSERVATION,
}


def build_workspace_objectives(
    *, request_latency_ms: float, pool_wait_ms: float
) -> dict[str, Any]:
    if request_latency_ms <= 0:
        raise ValueError("request latency objective must be positive")
    if pool_wait_ms < 0:
        raise ValueError("pool wait objective must be non-negative")
    return {
        "schema_version": "0.1",
        "kind": "workspace_objectives",
        "objectives": [
            {
                "observation": REQUEST_LATENCY_OBSERVATION,
                "operator": "above",
                "threshold": {"value": float(request_latency_ms), "unit": "ms"},
                "source": {"type": "user_declared"},
            },
            {
                "observation": POOL_WAIT_OBSERVATION,
                "operator": "above",
                "threshold": {"value": float(pool_wait_ms), "unit": "ms"},
                "source": {"type": "user_declared"},
            },
        ],
    }


def validate_workspace_objectives(document: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ValueError(
            "workspace objectives schema validation failed: "
            + "; ".join(error.message for error in errors)
        )

    seen: set[str] = set()
    for objective in document.get("objectives", []):
        observation = objective.get("observation")
        if observation not in SUPPORTED_OBSERVATIONS:
            raise ValueError(
                f"workspace objectives v0.1 does not support observation {observation!r}"
            )
        if observation in seen:
            raise ValueError(f"duplicate workspace objective for {observation}")
        seen.add(observation)


def load_workspace_objectives(path: Path) -> dict[str, Any]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"workspace objectives not found at {path}") from error
    except yaml.YAMLError as error:
        raise ValueError(f"workspace objectives are not valid YAML: {path}") from error
    if not isinstance(document, dict):
        raise ValueError(f"workspace objectives must be a YAML object: {path}")
    validate_workspace_objectives(document)
    return document


def objective_threshold_ms(document: dict[str, Any], observation: str) -> float:
    matching = [
        item
        for item in document.get("objectives", [])
        if item.get("observation") == observation
    ]
    if len(matching) != 1:
        raise ValueError(f"workspace objective missing for {observation}")
    objective = matching[0]
    threshold = objective["threshold"]
    if objective["operator"] != "above" or threshold["unit"] != "ms":
        raise ValueError(
            f"workspace objective for {observation} must use operator=above and unit=ms"
        )
    return float(threshold["value"])


def write_workspace_objectives(path: Path, document: dict[str, Any]) -> None:
    validate_workspace_objectives(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    temporary.replace(path)

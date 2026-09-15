#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from agent_plan import validate_agent_plan
from causal_projection import ROOT
from instrument_routing_projection import (
    build_instrument_routing_projection,
    validate_instrument_routing_projection,
)
from instrument_router import InstrumentRouter
from routed_execution_sets import build_routed_execution_sets

SCHEMA_PATH = ROOT / "schema" / "routed-agent-plan.schema.json"


def validate_routed_agent_plan(document: dict[str, Any]) -> None:
    with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ValueError(
            "routed agent plan schema validation failed: "
            + "; ".join(error.message for error in errors)
        )


def build_routed_agent_plan(
    snapshot: dict[str, Any],
    base_plan: dict[str, Any],
    router: InstrumentRouter,
    *,
    external_mcp_execution_enabled: bool = False,
    routing_projection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_agent_plan(base_plan)
    if base_plan.get("incident_id") != snapshot.get("incident_id"):
        raise ValueError("agent plan and diagnosis snapshot incident_id differ")
    if base_plan.get("evidence_revision") != snapshot.get("evidence_revision"):
        raise ValueError("agent plan and diagnosis snapshot evidence_revision differ")

    if routing_projection is None:
        routing = build_instrument_routing_projection(
            snapshot,
            router,
            external_mcp_execution_enabled=external_mcp_execution_enabled,
        )
    else:
        routing = copy.deepcopy(routing_projection)
        if routing.get("incident_id") != base_plan["incident_id"]:
            raise ValueError("routing projection belongs to another incident")
        if routing.get("evidence_revision") != base_plan["evidence_revision"]:
            raise ValueError("routing projection revision does not match agent plan")
    validate_instrument_routing_projection(routing)

    execution_projection = build_routed_execution_sets(routing)
    document = {
        "schema_version": "0.1",
        "kind": "routed_agent_plan",
        "incident_id": base_plan["incident_id"],
        "evidence_revision": base_plan["evidence_revision"],
        "plan": copy.deepcopy(base_plan),
        "routing": routing,
        "execution_sets": copy.deepcopy(execution_projection["sets"]),
    }
    validate_routed_agent_plan(document)
    return document

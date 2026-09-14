#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from causal_projection import ROOT
from instrument_router import InstrumentRouter

SCHEMA_PATH = ROOT / "schema" / "instrument-routing-projection.schema.json"


def validate_instrument_routing_projection(document: dict[str, Any]) -> None:
    with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ValueError(
            "instrument routing projection schema validation failed: "
            + "; ".join(error.message for error in errors)
        )


def _route_agent_action(
    decision: dict[str, Any],
    *,
    external_mcp_execution_enabled: bool,
) -> dict[str, Any]:
    selection = decision.get("selection")
    if not isinstance(selection, dict):
        return {
            "kind": "stop",
            "mcp_execution_available": False,
            "reason": decision.get("stop_reason") or "no safe instrument route is available",
        }

    instrument = selection["instrument"]
    if instrument["kind"] == "host_executor":
        return {
            "kind": "begin_host_probe_session",
            "mcp_execution_available": True,
            "reason": (
                "selected host executor uses the existing MCP begin/finish read-only probe session lifecycle"
            ),
        }

    if external_mcp_execution_enabled and instrument.get("execution_mode") == "direct":
        return {
            "kind": "use_external_instrument",
            "mcp_execution_available": True,
            "reason": (
                "selected external diagnostic provider is safe, exact-scope compatible, direct-execution "
                "capable, and the revision-bound routed MCP mutation is enabled"
            ),
        }

    return {
        "kind": "use_external_instrument",
        "mcp_execution_available": False,
        "reason": (
            "selected external diagnostic provider is safe and scope-compatible, but direct provider "
            "execution is not enabled as an MCP mutation"
        ),
    }


def build_instrument_routing_projection(
    snapshot: dict[str, Any],
    router: InstrumentRouter,
    *,
    external_mcp_execution_enabled: bool = False,
) -> dict[str, Any]:
    if snapshot.get("kind") != "diagnosis_snapshot":
        raise ValueError("instrument routing projection requires a diagnosis_snapshot")
    incident_id = snapshot.get("incident_id")
    evidence_revision = snapshot.get("evidence_revision")
    if not isinstance(incident_id, str) or not incident_id:
        raise ValueError("diagnosis snapshot must include incident_id")
    if not isinstance(evidence_revision, int) or evidence_revision < 0:
        raise ValueError("diagnosis snapshot must include a non-negative evidence_revision")

    routes: list[dict[str, Any]] = []
    for partition in snapshot.get("partitions", []):
        if not isinstance(partition, dict):
            continue
        scope = partition.get("scope")
        for diagnosis in partition.get("diagnoses", []):
            if not isinstance(diagnosis, dict):
                continue
            target = diagnosis.get("target")
            ranking = diagnosis.get("probe_ranking")
            if not isinstance(target, str) or not isinstance(ranking, dict):
                continue
            if ranking.get("found") is not True:
                continue
            probes = ranking.get("probes")
            if not isinstance(probes, list) or not probes:
                continue
            probe_id = probes[0].get("probe", {}).get("id")
            if not isinstance(probe_id, str) or not probe_id:
                continue

            decision = router.route(probe_id, scope, execution_requirement="any")
            selection = decision.get("selection")
            selected_instrument = (
                copy.deepcopy(selection["instrument"])
                if isinstance(selection, dict)
                else None
            )
            routes.append(
                {
                    "scope": copy.deepcopy(decision.get("scope")),
                    "target": target,
                    "probe_id": probe_id,
                    "decision": {
                        "selected_instrument": selected_instrument,
                        "stop_reason": decision.get("stop_reason"),
                        "selection_reason": (
                            selection.get("reason") if isinstance(selection, dict) else None
                        ),
                    },
                    "agent_action": _route_agent_action(
                        decision,
                        external_mcp_execution_enabled=external_mcp_execution_enabled,
                    ),
                }
            )

    routes.sort(
        key=lambda item: (
            json.dumps(item["scope"], sort_keys=True, separators=(",", ":")),
            item["target"],
            item["probe_id"],
        )
    )
    document = {
        "schema_version": "0.1",
        "kind": "instrument_routing_projection",
        "incident_id": incident_id,
        "evidence_revision": evidence_revision,
        "routes": routes,
    }
    validate_instrument_routing_projection(document)
    return document


def overlay_agent_plan_routing(
    plan: dict[str, Any],
    routing_projection: dict[str, Any],
) -> dict[str, Any]:
    if plan.get("kind") != "agent_plan":
        raise ValueError("routing overlay requires an agent_plan")
    if routing_projection.get("incident_id") != plan.get("incident_id"):
        raise ValueError("routing projection belongs to another incident")
    if routing_projection.get("evidence_revision") != plan.get("evidence_revision"):
        raise ValueError("routing projection revision does not match agent plan")

    indexed = {
        (
            json.dumps(route.get("scope"), sort_keys=True, separators=(",", ":")),
            route["target"],
            route["probe_id"],
        ): route
        for route in routing_projection.get("routes", [])
    }
    output = copy.deepcopy(plan)
    for step in output.get("steps", []):
        step["routing"] = None
        probe_id = step.get("recommended_probe")
        target = step.get("target")
        if not isinstance(probe_id, str) or not isinstance(target, str):
            continue
        if isinstance(step.get("session"), dict):
            continue
        key = (
            json.dumps(step.get("scope"), sort_keys=True, separators=(",", ":")),
            target,
            probe_id,
        )
        route = indexed.get(key)
        if route is None:
            continue
        step["routing"] = {
            "selected_instrument": copy.deepcopy(route["decision"]["selected_instrument"]),
            "stop_reason": route["decision"]["stop_reason"],
            "selection_reason": route["decision"]["selection_reason"],
            "agent_action": copy.deepcopy(route["agent_action"]),
        }
    return output

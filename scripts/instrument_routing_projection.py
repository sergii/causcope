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


def _scope_key(scope: dict[str, Any] | None) -> str:
    return json.dumps(scope, sort_keys=True, separators=(",", ":"))


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


def _selection_fields(decision: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    selection = decision.get("selection")
    if not isinstance(selection, dict):
        return None, None
    return copy.deepcopy(selection["instrument"]), selection.get("reason")


def _target_resolution_index(
    target_resolution: dict[str, Any],
    *,
    incident_id: str,
    evidence_revision: int,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    if target_resolution.get("kind") != "runtime_target_resolution":
        raise ValueError("target-aware routing requires runtime_target_resolution")
    if target_resolution.get("incident_id") != incident_id:
        raise ValueError("runtime target resolution belongs to another incident")
    if target_resolution.get("evidence_revision") != evidence_revision:
        raise ValueError("runtime target resolution revision does not match diagnosis snapshot")

    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for resolution in target_resolution.get("resolutions", []):
        key = (
            _scope_key(resolution.get("scope")),
            resolution["diagnosis_target"],
            resolution["probe_id"],
        )
        if key in index:
            raise ValueError(f"duplicate runtime target resolution entry: {key}")
        index[key] = resolution
    return index


def build_instrument_routing_projection(
    snapshot: dict[str, Any],
    router: InstrumentRouter,
    *,
    external_mcp_execution_enabled: bool = False,
    target_resolution: dict[str, Any] | None = None,
    information_gain_router: Any | None = None,
) -> dict[str, Any]:
    if snapshot.get("kind") != "diagnosis_snapshot":
        raise ValueError("instrument routing projection requires a diagnosis_snapshot")
    incident_id = snapshot.get("incident_id")
    evidence_revision = snapshot.get("evidence_revision")
    if not isinstance(incident_id, str) or not incident_id:
        raise ValueError("diagnosis snapshot must include incident_id")
    if not isinstance(evidence_revision, int) or evidence_revision < 0:
        raise ValueError("diagnosis snapshot must include a non-negative evidence_revision")
    if information_gain_router is not None and target_resolution is None:
        raise ValueError("information-gain routing requires runtime target resolution")

    resolution_index = (
        _target_resolution_index(
            target_resolution,
            incident_id=incident_id,
            evidence_revision=evidence_revision,
        )
        if target_resolution is not None
        else None
    )

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
            probe_candidate = probes[0]
            probe_id = probe_candidate.get("probe", {}).get("id")
            if not isinstance(probe_id, str) or not probe_id:
                continue

            if resolution_index is None:
                decision = router.route(probe_id, scope, execution_requirement="any")
                selected_instrument, selection_reason = _selection_fields(decision)
                routes.append(
                    {
                        "scope": copy.deepcopy(decision.get("scope")),
                        "target": target,
                        "probe_id": probe_id,
                        "decision": {
                            "selected_instrument": selected_instrument,
                            "stop_reason": decision.get("stop_reason"),
                            "selection_reason": selection_reason,
                        },
                        "agent_action": _route_agent_action(
                            decision,
                            external_mcp_execution_enabled=external_mcp_execution_enabled,
                        ),
                    }
                )
                continue

            key = (_scope_key(scope), target, probe_id)
            resolution = resolution_index.get(key)
            if resolution is None:
                raise ValueError(f"missing runtime target resolution for diagnosis route: {key}")

            if resolution.get("status") != "resolved":
                stop_reason = (
                    "target_resource_unresolved: "
                    + str(resolution.get("unresolved_reason") or "unknown")
                )
                routes.append(
                    {
                        "scope": copy.deepcopy(scope),
                        "target": target,
                        "probe_id": probe_id,
                        "target_resource": None,
                        "routing_strategy": (
                            "target_aware_information_gain"
                            if information_gain_router is not None
                            else "target_aware_safe_route"
                        ),
                        "target_resolution": {
                            "status": "unresolved",
                            "unresolved_reason": resolution.get("unresolved_reason"),
                            "supporting_relationship_ids": [],
                        },
                        "decision": {
                            "selected_instrument": None,
                            "stop_reason": stop_reason,
                            "selection_reason": None,
                        },
                        "agent_action": {
                            "kind": "stop",
                            "mcp_execution_available": False,
                            "reason": stop_reason,
                        },
                    }
                )
                continue

            for binding in resolution.get("target_bindings", []):
                target_resource = binding["target_resource"]
                if information_gain_router is not None:
                    decision = information_gain_router.route(
                        probe_candidate,
                        scope,
                        target_resource=target_resource,
                        execution_requirement="any",
                    )
                    routing_strategy = "target_aware_information_gain"
                else:
                    decision = router.route(
                        probe_id,
                        scope,
                        execution_requirement="any",
                        target_resource=target_resource,
                    )
                    routing_strategy = "target_aware_safe_route"
                selected_instrument, selection_reason = _selection_fields(decision)
                routes.append(
                    {
                        "scope": copy.deepcopy(decision.get("scope")),
                        "target": target,
                        "probe_id": probe_id,
                        "target_resource": target_resource,
                        "routing_strategy": routing_strategy,
                        "target_resolution": {
                            "status": "resolved",
                            "unresolved_reason": None,
                            "supporting_relationship_ids": sorted(binding["relationship_ids"]),
                        },
                        "decision": {
                            "selected_instrument": selected_instrument,
                            "stop_reason": decision.get("stop_reason"),
                            "selection_reason": selection_reason,
                        },
                        "agent_action": _route_agent_action(
                            decision,
                            external_mcp_execution_enabled=external_mcp_execution_enabled,
                        ),
                    }
                )

    routes.sort(
        key=lambda item: (
            _scope_key(item["scope"]),
            item["target"],
            item["probe_id"],
            item.get("target_resource") or "",
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

    indexed: dict[tuple[str, str, str], dict[str, Any]] = {}
    for route in routing_projection.get("routes", []):
        key = (
            _scope_key(route.get("scope")),
            route["target"],
            route["probe_id"],
        )
        if key in indexed:
            raise ValueError(
                "agent-plan routing overlay cannot collapse multiple exact target routes; "
                "consume instrument_routing_projection directly for fan-out"
            )
        indexed[key] = route

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
            _scope_key(step.get("scope")),
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

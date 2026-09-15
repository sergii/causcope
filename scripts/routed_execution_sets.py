#!/usr/bin/env python3

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from causal_projection import ROOT

SCHEMA_PATH = ROOT / "schema" / "routed-execution-sets.schema.json"
EXECUTE_SET_OPERATION = "causcope.instrument.execute_set"


def _schema() -> dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_routed_execution_sets(document: dict[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(_schema()).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ValueError(
            "routed execution sets schema validation failed: "
            + "; ".join(error.message for error in errors)
        )

    for item in document.get("sets", []):
        state = item["state"]
        if state == "ready":
            if not item["members"]:
                raise ValueError(f"ready execution set has no members: {item['id']}")
            if item["operation"] != EXECUTE_SET_OPERATION or not isinstance(item["arguments"], dict):
                raise ValueError(f"ready execution set must advertise exact execution operation: {item['id']}")
        else:
            if item["operation"] is not None or item["arguments"] is not None:
                raise ValueError(f"blocked execution set must not advertise execution: {item['id']}")


def _scope_key(scope: dict[str, Any] | None) -> str:
    return json.dumps(scope, sort_keys=True, separators=(",", ":"))


def _group_key(route: dict[str, Any]) -> tuple[str, str, str]:
    return (_scope_key(route.get("scope")), route["target"], route["probe_id"])


def _stable_set_id(
    incident_id: str,
    evidence_revision: int,
    scope: dict[str, Any] | None,
    diagnosis_target: str,
    probe_id: str,
    routes: list[dict[str, Any]],
) -> str:
    route_identity = []
    for route in sorted(routes, key=lambda item: item.get("target_resource") or ""):
        instrument = route.get("decision", {}).get("selected_instrument")
        route_identity.append(
            {
                "target_resource": route.get("target_resource"),
                "instrument_id": instrument.get("id") if isinstance(instrument, dict) else None,
                "supporting_relationship_ids": sorted(
                    route.get("target_resolution", {}).get("supporting_relationship_ids", [])
                ),
                "stop_reason": route.get("decision", {}).get("stop_reason"),
            }
        )
    payload = json.dumps(
        {
            "incident_id": incident_id,
            "evidence_revision": evidence_revision,
            "scope": scope,
            "diagnosis_target": diagnosis_target,
            "probe_id": probe_id,
            "routes": route_identity,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"execution-set.{digest}"


def _is_target_aware(route: dict[str, Any]) -> bool:
    strategy = route.get("routing_strategy")
    return strategy in {"target_aware_safe_route", "target_aware_information_gain"}


def _member(route: dict[str, Any], ordinal: int) -> dict[str, Any] | None:
    target_resource = route.get("target_resource")
    instrument = route.get("decision", {}).get("selected_instrument")
    if not isinstance(target_resource, str) or not target_resource:
        return None
    if not isinstance(instrument, dict):
        return None
    if instrument.get("kind") != "diagnostic_provider" or instrument.get("execution_mode") != "direct":
        return None
    return {
        "ordinal": ordinal,
        "target_resource": target_resource,
        "instrument": copy.deepcopy(instrument),
        "supporting_relationship_ids": sorted(
            route.get("target_resolution", {}).get("supporting_relationship_ids", [])
        ),
    }


def build_routed_execution_sets(routing_projection: dict[str, Any]) -> dict[str, Any]:
    if routing_projection.get("kind") != "instrument_routing_projection":
        raise ValueError("execution set projection requires instrument_routing_projection")
    incident_id = routing_projection.get("incident_id")
    evidence_revision = routing_projection.get("evidence_revision")
    if not isinstance(incident_id, str) or not incident_id:
        raise ValueError("routing projection must include incident_id")
    if not isinstance(evidence_revision, int) or evidence_revision < 0:
        raise ValueError("routing projection must include a non-negative evidence_revision")

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    scopes: dict[tuple[str, str, str], dict[str, Any] | None] = {}
    for route in routing_projection.get("routes", []):
        if not isinstance(route, dict) or not _is_target_aware(route):
            continue
        key = _group_key(route)
        grouped.setdefault(key, []).append(route)
        scopes[key] = copy.deepcopy(route.get("scope"))

    sets: list[dict[str, Any]] = []
    for key in sorted(grouped):
        routes = sorted(grouped[key], key=lambda item: item.get("target_resource") or "")
        scope = scopes[key]
        diagnosis_target = key[1]
        probe_id = key[2]
        set_id = _stable_set_id(
            incident_id,
            evidence_revision,
            scope,
            diagnosis_target,
            probe_id,
            routes,
        )

        members: list[dict[str, Any]] = []
        blocked_reasons: list[str] = []
        for route in routes:
            member = _member(route, len(members) + 1)
            action = route.get("agent_action", {})
            if member is None:
                blocked_reasons.append(
                    route.get("decision", {}).get("stop_reason")
                    or "route_missing_direct_provider"
                )
                continue
            if action.get("mcp_execution_available") is not True:
                blocked_reasons.append("mcp_execution_unavailable")
            members.append(member)

        if blocked_reasons:
            state = "blocked"
            reason = "; ".join(sorted(set(blocked_reasons)))
            operation = None
            arguments = None
        else:
            state = "ready"
            reason = "all exact target routes are direct, safe, and MCP-executable"
            operation = EXECUTE_SET_OPERATION
            arguments = {
                "incidentId": incident_id,
                "evidenceRevision": evidence_revision,
                "executionSetId": set_id,
            }

        sets.append(
            {
                "id": set_id,
                "scope": scope,
                "diagnosis_target": diagnosis_target,
                "probe_id": probe_id,
                "state": state,
                "reason": reason,
                "members": members,
                "operation": operation,
                "arguments": arguments,
                "atomic_evidence_commit": True,
                "rerank_policy": "after_all_members",
                "failure_policy": "no_state_commit_on_member_failure",
            }
        )

    document = {
        "schema_version": "0.1",
        "kind": "routed_execution_sets",
        "incident_id": incident_id,
        "evidence_revision": evidence_revision,
        "sets": sets,
    }
    validate_routed_execution_sets(document)
    return document

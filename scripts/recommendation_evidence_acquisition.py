#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from causal_projection import ROOT, load_concepts
from database_read_model_recommendation import (
    CONTEXT_SCHEMA,
    load_json,
    project_from_runtime_evidence,
    validate_schema,
)
from instrument_router import InstrumentRouter
from pgbot_adapter import load_adapter, load_context
from pgbot_autonomous_provider import PgbotAutonomousProbeProvider, file_context_supplier
from recommendation_information_gaps import project as project_information_gaps
from resource_topology import load_resource_topology
from runtime_evidence import parse_timestamp, validate_runtime_references
from runtime_evidence_composition import validate_runtime_evidence_document

RESULT_SCHEMA = ROOT / "schema" / "recommendation-evidence-acquisition-result.schema.json"

LIMITATIONS = [
    "Recommendation evidence acquisition executes only an explicit RFC 0067 read-only probe through the existing InstrumentRouter safety checks.",
    "The first RFC 0069 proof remains bound to a pgbot provider instance because the current read-model recommendation requires exact query-object identity.",
    "Fresh evidence may advance recommendation maturity, but this bridge never authorizes a schema, application, or data change.",
]


def _empty_host_capabilities() -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "kind": "probe_execution_capabilities",
        "platform": "linux",
        "executors": [],
    }


def _canonical_time(value: str | datetime) -> str:
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            raise ValueError("recommendation acquisition time must be timezone-aware")
    else:
        parsed = parse_timestamp(value, "recommendation.acquisition_time")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_identity(context: dict[str, Any], projection: dict[str, Any]) -> None:
    for key in (
        "system_id",
        "revision",
        "incident_id",
        "recommendation_id",
        "subject_resource",
        "provider_instance",
    ):
        if projection.get(key) != context.get(key):
            raise ValueError(f"current recommendation projection {key} does not match context")
    if "evidence_scope" in context and projection.get("evidence_scope") != context["evidence_scope"]:
        raise ValueError("current recommendation projection evidence_scope does not match context")


def _matching_evidence_ids(
    evidence: dict[str, Any],
    *,
    observation: str,
    target_resource: str,
    instrument_id: str,
) -> list[str]:
    matches: list[str] = []
    for instance in evidence.get("instances", []):
        if instance.get("observation") != observation or instance.get("state") != "observed":
            continue
        attributes = instance.get("source", {}).get("attributes", {})
        labels = instance.get("labels", {})
        if attributes.get("routing.target_resource") != target_resource:
            continue
        if attributes.get("routing.instrument_id") != instrument_id:
            continue
        if labels.get("instrument") != instrument_id:
            continue
        matches.append(instance["id"])
    return sorted(matches)


def _next_action_summary(action: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "kind": action["kind"],
        "execution_boundary": action["execution_boundary"],
    }
    for key in ("gap_id", "probe_id", "requested_observation"):
        if key in action:
            summary[key] = action[key]
    return summary


def _validate_result(document: dict[str, Any]) -> None:
    schema = load_json(RESULT_SCHEMA)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ValueError(
            "recommendation evidence acquisition result schema validation failed: "
            + "; ".join(error.message for error in errors)
        )


def acquire_and_reproject(
    *,
    context: dict[str, Any],
    current_projection: dict[str, Any],
    topology_path: Path,
    router: InstrumentRouter,
    acquisition_time: str | datetime,
) -> dict[str, Any]:
    validate_schema(context, CONTEXT_SCHEMA, "recommendation context")
    _validate_identity(context, current_projection)

    current_gaps = project_information_gaps(current_projection)
    action = current_gaps["next_action"]
    if action.get("kind") != "read_only_probe":
        raise ValueError(
            "recommendation evidence acquisition requires current next_action kind read_only_probe"
        )
    if action.get("execution_boundary") != "existing_read_only_probe":
        raise ValueError("recommendation read-only probe action has an unexpected execution boundary")
    probe_id = action.get("probe_id")
    requested_observation = action.get("requested_observation")
    scope = action.get("scope")
    if not isinstance(probe_id, str) or not probe_id:
        raise ValueError("recommendation read-only probe action has no probe_id")
    if not isinstance(requested_observation, str) or not requested_observation:
        raise ValueError("recommendation read-only probe action has no requested_observation")
    if not isinstance(scope, dict):
        raise ValueError(
            "recommendation read-only probe action has no exact evidence scope; acquire no evidence"
        )

    target_resource = current_projection["subject_resource"]
    route = router.route(
        probe_id,
        copy.deepcopy(scope),
        execution_requirement="direct",
        target_resource=target_resource,
    )
    selection = route.get("selection")
    if not isinstance(selection, dict):
        raise ValueError(
            "recommendation evidence acquisition has no safe direct route: "
            + str(route.get("stop_reason"))
        )
    instrument = selection["instrument"]
    if instrument.get("id") != context["provider_instance"]:
        raise ValueError(
            "selected recommendation evidence provider differs from the provider_instance pinned by context"
        )
    if instrument.get("kind") != "diagnostic_provider" or instrument.get("execution_mode") != "direct":
        raise ValueError("selected recommendation evidence instrument is not a direct diagnostic provider")
    if instrument.get("target_resource") != target_resource:
        raise ValueError("selected recommendation evidence instrument target does not match subject_resource")

    evidence = router.execute(
        probe_id,
        context["recommendation_id"],
        copy.deepcopy(scope),
        target_resource=target_resource,
    )
    concepts = load_concepts(ROOT)
    validate_runtime_evidence_document(evidence)
    validate_runtime_references(evidence, concepts)
    if evidence["incident_id"] != context["incident_id"]:
        raise ValueError("acquired recommendation evidence belongs to another incident")

    matching_ids = _matching_evidence_ids(
        evidence,
        observation=requested_observation,
        target_resource=target_resource,
        instrument_id=instrument["id"],
    )
    if not matching_ids:
        raise ValueError(
            "routed provider returned no observed evidence for the requested observation and exact resource"
        )

    as_of = _canonical_time(acquisition_time)
    updated_context = copy.deepcopy(context)
    updated_context["evaluation_time"] = as_of
    next_projection = project_from_runtime_evidence(
        context=updated_context,
        topology_path=topology_path,
        runtime_evidence=evidence,
        require_routed_identity=True,
    )
    next_gaps = project_information_gaps(next_projection)

    progressed = (
        next_projection["state"] != current_projection["state"]
        or next_gaps["status"] != current_gaps["status"]
        or next_gaps["next_action"] != current_gaps["next_action"]
    )
    routing_summary: dict[str, Any] = {
        "instrument_id": instrument["id"],
        "instrument_kind": instrument["kind"],
        "execution_mode": instrument["execution_mode"],
        "target_resource": target_resource,
    }
    for key in ("provider_type", "runner", "endpoint_resource"):
        if key in instrument:
            routing_summary[key] = instrument[key]

    result = {
        "schema_version": "0.1",
        "kind": "recommendation_evidence_acquisition_result",
        "system_id": context["system_id"],
        "revision": copy.deepcopy(context["revision"]),
        "incident_id": context["incident_id"],
        "recommendation_id": context["recommendation_id"],
        "subject_resource": target_resource,
        "acquisition_time": as_of,
        "previous_state": current_projection["state"],
        "probe_id": probe_id,
        "requested_observation": requested_observation,
        "routing": routing_summary,
        "evidence": {
            "instance_ids": sorted(instance["id"] for instance in evidence["instances"]),
            "matching_instance_ids": matching_ids,
        },
        "recommendation_state": next_projection["state"],
        "information_gap_status": next_gaps["status"],
        "progressed": progressed,
        "next_action": _next_action_summary(next_gaps["next_action"]),
        "limitations": list(LIMITATIONS),
    }
    _validate_result(result)
    return {
        "result": result,
        "routing_decision": route,
        "runtime_evidence": evidence,
        "updated_context": updated_context,
        "recommendation_projection": next_projection,
        "information_gap_projection": next_gaps,
    }


def build_pgbot_router(
    *,
    context: dict[str, Any],
    topology_path: Path,
    adapter_path: Path,
    pgbot_context_path: Path,
) -> InstrumentRouter:
    concepts = load_concepts(ROOT)
    topology = load_resource_topology(topology_path)
    instance = topology.provider_instance(context["provider_instance"])
    if instance["target"] != context["subject_resource"]:
        raise ValueError("provider instance target does not match recommendation subject_resource")
    provider_type = topology.provider_type(instance["provider_type"])
    if provider_type.get("instrument") != "pgbot":
        raise ValueError("RFC 0069 pgbot CLI proof requires a pgbot provider instance")

    resource = topology.resource(context["subject_resource"])
    adapter = load_adapter(adapter_path)
    pgbot_context = load_context(pgbot_context_path)
    expected_database = resource.get("attributes", {}).get("database")
    observed_database = pgbot_context.get("server", {}).get("database")
    if expected_database and observed_database != expected_database:
        raise ValueError(
            "pgbot database identity does not match topology target: "
            f"expected {expected_database}, observed {observed_database}"
        )

    provider = PgbotAutonomousProbeProvider(
        adapter=adapter,
        concepts=concepts,
        incident_id=context["incident_id"],
        context_supplier=file_context_supplier(pgbot_context_path),
        source_uri=f"provider-instance:{instance['id']}",
    )
    return InstrumentRouter(
        concepts=concepts,
        host_capabilities=_empty_host_capabilities(),
        providers=[],
        resource_topology=topology,
        provider_instance_bindings={instance["id"]: provider},
    )


def _write_json(path: Path, document: dict[str, Any], *, pretty: bool) -> None:
    path.write_text(
        json.dumps(document, indent=2 if pretty else None, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Acquire one exact read-only recommendation evidence gap and recompute recommendation maturity."
    )
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--current-projection", type=Path, required=True)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--pgbot-adapter", type=Path, required=True)
    parser.add_argument("--pgbot-context", type=Path, required=True)
    parser.add_argument("--as-of", help="Acquisition evaluation time; defaults to current UTC time")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path)
    parser.add_argument("--recommendation-output", type=Path)
    parser.add_argument("--gaps-output", type=Path)
    parser.add_argument("--updated-context-output", type=Path)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        context = load_json(args.context)
        current_projection = load_json(args.current_projection)
        router = build_pgbot_router(
            context=context,
            topology_path=args.topology,
            adapter_path=args.pgbot_adapter,
            pgbot_context_path=args.pgbot_context,
        )
        bundle = acquire_and_reproject(
            context=context,
            current_projection=current_projection,
            topology_path=args.topology,
            router=router,
            acquisition_time=args.as_of or datetime.now(timezone.utc),
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    _write_json(args.output, bundle["result"], pretty=args.pretty)
    optional_outputs = (
        (args.evidence_output, "runtime_evidence"),
        (args.recommendation_output, "recommendation_projection"),
        (args.gaps_output, "information_gap_projection"),
        (args.updated_context_output, "updated_context"),
    )
    for path, key in optional_outputs:
        if path is not None:
            _write_json(path, bundle[key], pretty=args.pretty)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

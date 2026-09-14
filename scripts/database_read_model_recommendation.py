#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from causal_projection import load_concepts
from pgbot_adapter import build_runtime_evidence, load_adapter, load_context
from resource_topology import load_resource_topology
from runtime_evidence import parse_timestamp

ROOT = Path(__file__).resolve().parents[1]
CONTEXT_SCHEMA = ROOT / "schema" / "database-read-model-recommendation-context.schema.json"
PROJECTION_SCHEMA = ROOT / "schema" / "architectural-recommendation-projection.schema.json"

BASE_LIMITATIONS = [
    "PostgreSQL query-latency evidence does not by itself justify normalization or denormalization.",
    "This projection expresses evidence maturity for a design candidate and never authorizes a schema or application change.",
]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return document


def validate_schema(document: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        raise ValueError(
            f"{label} schema validation failed: "
            + "; ".join(error.message for error in errors)
        )


def active_query_latency_evidence(
    runtime_evidence: dict[str, Any],
    *,
    query_object: str,
    evaluation_time: str,
) -> dict[str, Any] | None:
    evaluated_at = parse_timestamp(evaluation_time, "recommendation.evaluation_time")
    matches: list[dict[str, Any]] = []
    for instance in runtime_evidence.get("instances", []):
        if instance.get("observation") != "observation.database.query_latency":
            continue
        if instance.get("state") != "observed":
            continue
        attributes = instance.get("source", {}).get("attributes", {})
        if attributes.get("pgbot.object") != query_object:
            continue
        observed_at = parse_timestamp(instance["observed_at"], f"{instance['id']}.observed_at")
        expires_at = parse_timestamp(instance["expires_at"], f"{instance['id']}.expires_at")
        if observed_at <= evaluated_at < expires_at:
            matches.append(instance)

    if len(matches) > 1:
        raise ValueError(f"multiple active query-latency evidence instances match {query_object}")
    return matches[0] if matches else None


def missing_context(context: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    workload = context["workload"]
    if workload["read_frequency_per_minute"] <= 0:
        missing.append("workload.read_frequency_per_minute_positive")
    if workload["query_contribution"] == "unknown":
        missing.append("workload.query_contribution_known")

    for section in (
        "proposed_change",
        "business_semantics",
        "maintenance",
        "cost",
        "verification",
    ):
        if section not in context:
            missing.append(section)
    return sorted(missing)


def benefit_state(context: dict[str, Any]) -> str:
    benefit = context.get("benefit")
    if benefit is None:
        return "EXPERIMENT_REQUIRED"

    basis = benefit["basis"]
    if basis in {"unknown", "expected"}:
        return "EXPERIMENT_REQUIRED"
    if benefit["after"] >= benefit["before"]:
        return "BENEFIT_NOT_DEMONSTRATED"
    if basis in {"planner_experiment", "benchmark"}:
        return "ESTIMATED_BENEFIT"
    if basis == "measured":
        return "READY_FOR_HUMAN_REVIEW"
    raise ValueError(f"unsupported benefit basis: {basis}")


def projected_benefit(context: dict[str, Any]) -> dict[str, Any] | None:
    benefit = context.get("benefit")
    if benefit is None:
        return None
    projected = dict(benefit)
    before = benefit["before"]
    after = benefit["after"]
    projected["improvement_percent"] = round(((before - after) / before) * 100.0, 2)
    return projected


def project(
    *,
    context: dict[str, Any],
    topology_path: Path,
    adapter_path: Path,
    pgbot_context_path: Path,
) -> dict[str, Any]:
    validate_schema(context, CONTEXT_SCHEMA, "recommendation context")

    concepts = load_concepts(ROOT)
    recommendation = concepts.get(context["recommendation_id"])
    if recommendation is None:
        raise ValueError(f"unknown recommendation concept: {context['recommendation_id']}")
    if recommendation.get("kind") != "architectural_recommendation":
        raise ValueError("recommendation_id must reference architectural_recommendation")
    if recommendation.get("human_approval_required") is not True:
        raise ValueError("architectural recommendation must require human approval")

    topology = load_resource_topology(topology_path)
    resource = topology.resource(context["subject_resource"])
    if resource.get("kind") != "postgresql_database":
        raise ValueError("database read-model recommendation requires a postgresql_database target")

    provider_instance = topology.provider_instance(context["provider_instance"])
    if provider_instance["target"] != context["subject_resource"]:
        raise ValueError("provider instance target does not match recommendation subject_resource")
    provider_type = topology.provider_type(provider_instance["provider_type"])
    if provider_type.get("instrument") != "pgbot":
        raise ValueError("database read-model recommendation proof requires a pgbot provider instance")

    adapter = load_adapter(adapter_path)
    pgbot_context = load_context(pgbot_context_path)
    expected_database = resource.get("attributes", {}).get("database")
    observed_database = pgbot_context.get("server", {}).get("database")
    if expected_database and observed_database != expected_database:
        raise ValueError(
            "pgbot database identity does not match topology target: "
            f"expected {expected_database}, observed {observed_database}"
        )

    runtime_evidence = build_runtime_evidence(
        adapter,
        pgbot_context,
        concepts,
        incident_id=context["incident_id"],
        source_uri=f"provider-instance:{provider_instance['id']}",
    )
    query_object = context["workload"]["query_object"]
    query_evidence = active_query_latency_evidence(
        runtime_evidence,
        query_object=query_object,
        evaluation_time=context["evaluation_time"],
    )

    causal_basis: dict[str, Any] = {
        "observation": "observation.database.query_latency",
        "query_object": query_object,
    }
    if query_evidence is not None:
        causal_basis["evidence_id"] = query_evidence["id"]
        causal_basis["source_name"] = query_evidence["source"]["name"]
        source_uri = query_evidence["source"].get("uri")
        if source_uri:
            causal_basis["source_uri"] = source_uri

    missing = missing_context(context)
    if query_evidence is None:
        state = "NO_PROBLEM_EVIDENCE"
    elif missing:
        state = "INSUFFICIENT_CONTEXT"
    else:
        state = benefit_state(context)

    projection: dict[str, Any] = {
        "schema_version": "0.1",
        "kind": "architectural_recommendation_projection",
        "system_id": context["system_id"],
        "revision": context["revision"],
        "incident_id": context["incident_id"],
        "recommendation_id": context["recommendation_id"],
        "subject_resource": context["subject_resource"],
        "provider_instance": context["provider_instance"],
        "state": state,
        "human_approval_required": True,
        "causal_basis": causal_basis,
        "problem": context["workload"],
        "missing_assumptions": missing,
        "limitations": list(BASE_LIMITATIONS),
    }

    for key in ("proposed_change", "cost", "verification"):
        if key in context:
            projection[key] = context[key]

    if "business_semantics" in context or "maintenance" in context:
        consistency: dict[str, Any] = {}
        consistency.update(context.get("business_semantics", {}))
        consistency.update(context.get("maintenance", {}))
        projection["consistency"] = consistency

    benefit = projected_benefit(context)
    if benefit is not None:
        projection["benefit"] = benefit
        if benefit["basis"] in {"planner_experiment", "benchmark"}:
            projection["limitations"].append(
                "Estimated or benchmark benefit is not a measured production improvement."
            )

    validate_schema(projection, PROJECTION_SCHEMA, "recommendation projection")
    return projection


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gate a concrete database read-model recommendation on evidence and context."
    )
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--pgbot-context", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        context = load_json(args.context)
        projection = project(
            context=context,
            topology_path=args.topology,
            adapter_path=args.adapter,
            pgbot_context_path=args.pgbot_context,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    args.output.write_text(
        json.dumps(projection, indent=2 if args.pretty else None, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

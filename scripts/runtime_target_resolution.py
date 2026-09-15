#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from causal_projection import ROOT
from resource_topology import ResourceTopology, load_resource_topology

SCHEMA_PATH = ROOT / "schema" / "runtime-target-resolution.schema.json"
RESOLUTION_POLICY = "exact_trace_relationships_then_explicit_runtime_bindings"


def _load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_runtime_target_resolution(document: dict[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(_load_schema()).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ValueError(
            "runtime target resolution schema validation failed: "
            + "; ".join(error.message for error in errors)
        )


def _scope_key(scope: dict[str, Any] | None) -> str:
    return json.dumps(scope, sort_keys=True, separators=(",", ":"))


def _top_probe_id(diagnosis: dict[str, Any]) -> str | None:
    ranking = diagnosis.get("probe_ranking")
    if not isinstance(ranking, dict) or ranking.get("found") is not True:
        return None
    probes = ranking.get("probes")
    if not isinstance(probes, list) or not probes:
        return None
    probe_id = probes[0].get("probe", {}).get("id")
    return probe_id if isinstance(probe_id, str) and probe_id else None


def _unresolved(
    *,
    scope: dict[str, Any] | None,
    diagnosis_target: str,
    probe_id: str,
    reason: str,
    evidence_ids: list[str],
    trace_ids: list[str],
) -> dict[str, Any]:
    return {
        "scope": copy.deepcopy(scope),
        "diagnosis_target": diagnosis_target,
        "probe_id": probe_id,
        "status": "unresolved",
        "unresolved_reason": reason,
        "supporting_evidence_instance_ids": sorted(set(evidence_ids)),
        "trace_ids": sorted(set(trace_ids)),
        "target_bindings": [],
    }


def build_runtime_target_resolution(
    snapshot: dict[str, Any],
    runtime_evidence: dict[str, Any],
    relationships: dict[str, Any],
    topology: ResourceTopology,
) -> dict[str, Any]:
    if snapshot.get("kind") != "diagnosis_snapshot":
        raise ValueError("target resolution requires a diagnosis_snapshot")
    if runtime_evidence.get("kind") != "runtime_evidence":
        raise ValueError("target resolution requires runtime_evidence")
    if relationships.get("kind") != "runtime_resolved_relationships":
        raise ValueError("target resolution requires runtime_resolved_relationships")

    incident_id = snapshot.get("incident_id")
    if not isinstance(incident_id, str) or not incident_id:
        raise ValueError("diagnosis snapshot must include incident_id")
    if runtime_evidence.get("incident_id") != incident_id:
        raise ValueError("runtime evidence belongs to another incident")
    if relationships.get("incident_id") != incident_id:
        raise ValueError("runtime relationships belong to another incident")

    evidence_revision = snapshot.get("evidence_revision")
    if not isinstance(evidence_revision, int) or evidence_revision < 0:
        raise ValueError("diagnosis snapshot must include a non-negative evidence_revision")

    instances: dict[str, dict[str, Any]] = {}
    for instance in runtime_evidence.get("instances", []):
        instance_id = instance.get("id")
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError("runtime evidence instance is missing id")
        if instance_id in instances:
            raise ValueError(f"duplicate runtime evidence instance id: {instance_id}")
        instances[instance_id] = instance

    relationships_by_trace: dict[str, list[dict[str, Any]]] = {}
    for relationship in relationships.get("relationships", []):
        if relationship.get("relation") != "used_resource":
            continue
        trace_id = relationship.get("trace_id")
        if not isinstance(trace_id, str) or not trace_id:
            raise ValueError("runtime relationship is missing trace_id")
        relationships_by_trace.setdefault(trace_id, []).append(relationship)

    resolutions: list[dict[str, Any]] = []
    for partition in snapshot.get("partitions", []):
        if not isinstance(partition, dict):
            continue
        scope = partition.get("scope")
        active_ids = partition.get("active_instance_ids", [])
        if not isinstance(active_ids, list):
            raise ValueError("diagnosis partition active_instance_ids must be a list")
        active_instances: list[dict[str, Any]] = []
        for instance_id in active_ids:
            if instance_id not in instances:
                raise ValueError(
                    f"diagnosis snapshot references unknown active evidence instance: {instance_id}"
                )
            active_instances.append(instances[instance_id])

        for diagnosis in partition.get("diagnoses", []):
            if not isinstance(diagnosis, dict):
                continue
            diagnosis_target = diagnosis.get("target")
            probe_id = _top_probe_id(diagnosis)
            if not isinstance(diagnosis_target, str) or not diagnosis_target or probe_id is None:
                continue

            target_instances = [
                instance
                for instance in active_instances
                if instance.get("observation") == diagnosis_target
                and instance.get("state") == "observed"
            ]
            evidence_ids = sorted(
                instance["id"] for instance in target_instances if isinstance(instance.get("id"), str)
            )
            if not target_instances:
                resolutions.append(
                    _unresolved(
                        scope=scope,
                        diagnosis_target=diagnosis_target,
                        probe_id=probe_id,
                        reason="no_active_target_evidence",
                        evidence_ids=[],
                        trace_ids=[],
                    )
                )
                continue

            trace_ids = sorted(
                {
                    trace_id
                    for instance in target_instances
                    for trace_id in [
                        instance.get("source", {}).get("attributes", {}).get("otel.trace_id")
                    ]
                    if isinstance(trace_id, str) and trace_id
                }
            )
            if not trace_ids:
                resolutions.append(
                    _unresolved(
                        scope=scope,
                        diagnosis_target=diagnosis_target,
                        probe_id=probe_id,
                        reason="no_exact_trace_context",
                        evidence_ids=evidence_ids,
                        trace_ids=[],
                    )
                )
                continue

            matched_relationships = sorted(
                [
                    relationship
                    for trace_id in trace_ids
                    for relationship in relationships_by_trace.get(trace_id, [])
                ],
                key=lambda relationship: relationship["id"],
            )
            if not matched_relationships:
                resolutions.append(
                    _unresolved(
                        scope=scope,
                        diagnosis_target=diagnosis_target,
                        probe_id=probe_id,
                        reason="no_runtime_resource_relationships",
                        evidence_ids=evidence_ids,
                        trace_ids=trace_ids,
                    )
                )
                continue

            grouped: dict[str, dict[str, set[str]]] = {}
            binding_failed = False
            for relationship in matched_relationships:
                runtime_resource = relationship.get("object_resource")
                if not isinstance(runtime_resource, str) or not runtime_resource:
                    raise ValueError(
                        f"runtime relationship {relationship.get('id')} is missing object_resource"
                    )
                try:
                    target_resource = topology.target_for_runtime_resource(runtime_resource)
                except ValueError:
                    binding_failed = True
                    break
                entry = grouped.setdefault(
                    target_resource,
                    {
                        "runtime_resources": set(),
                        "relationship_ids": set(),
                        "execution_ids": set(),
                        "trace_ids": set(),
                    },
                )
                entry["runtime_resources"].add(runtime_resource)
                entry["relationship_ids"].add(relationship["id"])
                entry["execution_ids"].add(relationship["subject_execution"])
                entry["trace_ids"].add(relationship["trace_id"])

            if binding_failed:
                resolutions.append(
                    _unresolved(
                        scope=scope,
                        diagnosis_target=diagnosis_target,
                        probe_id=probe_id,
                        reason="runtime_resource_unbound",
                        evidence_ids=evidence_ids,
                        trace_ids=trace_ids,
                    )
                )
                continue

            target_bindings = [
                {
                    "target_resource": target_resource,
                    "runtime_resources": sorted(values["runtime_resources"]),
                    "relationship_ids": sorted(values["relationship_ids"]),
                    "execution_ids": sorted(values["execution_ids"]),
                    "trace_ids": sorted(values["trace_ids"]),
                }
                for target_resource, values in sorted(grouped.items())
            ]
            resolutions.append(
                {
                    "scope": copy.deepcopy(scope),
                    "diagnosis_target": diagnosis_target,
                    "probe_id": probe_id,
                    "status": "resolved",
                    "unresolved_reason": None,
                    "supporting_evidence_instance_ids": evidence_ids,
                    "trace_ids": trace_ids,
                    "target_bindings": target_bindings,
                }
            )

    resolutions.sort(
        key=lambda item: (
            _scope_key(item["scope"]),
            item["diagnosis_target"],
            item["probe_id"],
        )
    )
    document = {
        "schema_version": "0.1",
        "kind": "runtime_target_resolution",
        "incident_id": incident_id,
        "evidence_revision": evidence_revision,
        "resolution_policy": RESOLUTION_POLICY,
        "resolutions": resolutions,
    }
    validate_runtime_target_resolution(document)
    return document


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve exact runtime-used resources into RFC 0040 operational targets for live diagnoses."
        )
    )
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--runtime-evidence", type=Path, required=True)
    parser.add_argument("--runtime-relationships", type=Path, required=True)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        document = build_runtime_target_resolution(
            load_json(args.snapshot),
            load_json(args.runtime_evidence),
            load_json(args.runtime_relationships),
            load_resource_topology(args.topology),
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(document, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

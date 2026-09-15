#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from causal_projection import ROOT, load_concepts, load_edges
from concrete_system_facts import load_document as load_static_document
from live_diagnosis import build_diagnosis_snapshot
from otel_concrete_runtime_facts import load_json as load_runtime_document
from otel_concrete_runtime_facts import validate_runtime_document
from resource_topology import ResourceTopology, load_resource_topology
from runtime_evidence import SCHEMA_PATH as RUNTIME_EVIDENCE_SCHEMA_PATH
from runtime_evidence import parse_timestamp, validate_runtime_references
from runtime_resolved_relationships import project as project_runtime_relationships
from runtime_target_resolution import build_runtime_target_resolution

DEFAULT_WORKSPACE = Path(".causcope")
DEFAULT_STATIC_FACTS = "concrete-system-facts.json"
DEFAULT_TOPOLOGY = "resource-topology.yaml"
DEFAULT_CONTEXT = "incident-context.yaml"
DEFAULT_RUNTIME_EVIDENCE = "runtime-evidence.json"
DEFAULT_RUNTIME_RELATIONSHIPS = "runtime-relationships.json"
DEFAULT_DIAGNOSIS = "diagnosis.json"
REQUEST_LATENCY_OBSERVATION = "observation.http.request_latency"
POOL_WAIT_OBSERVATION = "observation.database.connection_pool_wait_time"
SELECTION_POLICY = "slowest_request_with_elevated_pool_wait_and_exact_single_target_binding"


def workspace_path(root: Path, configured: Path | None) -> Path:
    if configured is None:
        return (root / DEFAULT_WORKSPACE).resolve()
    return configured.resolve() if configured.is_absolute() else (root / configured).resolve()


def safe_incident_slug(incident_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", incident_id).strip("-") or "incident"


def default_runtime_snapshot_path(workspace: Path, incident_id: str) -> Path:
    return workspace / "runtime" / f"{safe_incident_slug(incident_id)}.json"


def load_workspace_incident_id(workspace: Path) -> str:
    context_path = workspace / DEFAULT_CONTEXT
    try:
        document = yaml.safe_load(context_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(
            f"investigation context not found at {context_path}; run `causcope why <problem>` first"
        ) from error
    except yaml.YAMLError as error:
        raise ValueError(f"investigation context is not valid YAML: {context_path}") from error
    if not isinstance(document, dict) or document.get("kind") != "incident_context":
        raise ValueError(f"{context_path} is not an incident_context document")
    incident_id = document.get("incident_id")
    if not isinstance(incident_id, str) or not incident_id:
        raise ValueError(f"{context_path} does not contain a valid incident_id")
    return incident_id


def validate_runtime_evidence_document(
    document: dict[str, Any], concepts: dict[str, dict[str, Any]]
) -> None:
    schema = json.loads(RUNTIME_EVIDENCE_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ValueError(
            "runtime evidence schema validation failed: "
            + "; ".join(error.message for error in errors)
        )
    validate_runtime_references(document, concepts)


def execution_relationship_targets(
    execution_id: str,
    relationships: dict[str, Any],
    topology: ResourceTopology,
) -> tuple[list[dict[str, Any]], set[str]]:
    matched = [
        item
        for item in relationships.get("relationships", [])
        if item.get("subject_execution") == execution_id and item.get("relation") == "used_resource"
    ]
    targets: set[str] = set()
    for relationship in matched:
        runtime_resource = relationship.get("object_resource")
        if not isinstance(runtime_resource, str) or not runtime_resource:
            raise ValueError(
                f"runtime relationship {relationship.get('id')} has no object_resource"
            )
        targets.add(topology.target_for_runtime_resource(runtime_resource))
    return matched, targets


def interactions_for_execution(
    runtime: dict[str, Any], execution_id: str
) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: item
        for item in runtime.get("pool_interactions", [])
        if item.get("execution_id") == execution_id and isinstance(item.get("id"), str)
    }


def choose_execution(
    runtime: dict[str, Any],
    relationships: dict[str, Any],
    topology: ResourceTopology,
    *,
    request_threshold_ms: float,
    pool_wait_threshold_ms: float,
    code_symbol: str | None,
    trace_id: str | None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], str]:
    candidates: list[
        tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], str]
    ] = []
    rejected_multi_target: list[str] = []
    rejected_unbound: list[str] = []

    for execution in runtime.get("executions", []):
        if code_symbol is not None and execution.get("code_symbol") != code_symbol:
            continue
        if trace_id is not None and execution.get("trace_id") != trace_id:
            continue
        duration = execution.get("duration_ms")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool):
            continue
        if float(duration) <= request_threshold_ms:
            continue

        try:
            matched_relationships, targets = execution_relationship_targets(
                execution["id"], relationships, topology
            )
        except ValueError:
            rejected_unbound.append(execution["id"])
            continue
        if not matched_relationships:
            continue
        if len(targets) != 1:
            rejected_multi_target.append(execution["id"])
            continue

        interactions = interactions_for_execution(runtime, execution["id"])
        relevant_interactions = [
            interactions[relationship["evidence_ref"]]
            for relationship in matched_relationships
            if relationship.get("evidence_ref") in interactions
            and float(interactions[relationship["evidence_ref"]].get("checkout_wait_ms", 0.0))
            > pool_wait_threshold_ms
        ]
        if not relevant_interactions:
            continue

        relevant_interactions.sort(
            key=lambda item: (-float(item["checkout_wait_ms"]), item["id"])
        )
        selected_interaction = relevant_interactions[0]
        candidates.append(
            (
                execution,
                selected_interaction,
                matched_relationships,
                next(iter(targets)),
            )
        )

    if not candidates:
        details: list[str] = []
        if rejected_unbound:
            details.append("some slow executions used runtime resources without topology bindings")
        if rejected_multi_target:
            details.append("some slow executions touched multiple topology targets")
        selector = []
        if code_symbol is not None:
            selector.append(f"code_symbol={code_symbol}")
        if trace_id is not None:
            selector.append(f"trace_id={trace_id}")
        suffix = f" for {', '.join(selector)}" if selector else ""
        detail_suffix = f" ({'; '.join(details)})" if details else ""
        raise ValueError(
            "no request execution satisfied both explicit objectives "
            f"(request > {request_threshold_ms:g} ms, pool wait > {pool_wait_threshold_ms:g} ms) "
            f"with an exact single-target runtime binding{suffix}{detail_suffix}"
        )

    candidates.sort(
        key=lambda item: (
            -float(item[0]["duration_ms"]),
            -float(item[1]["checkout_wait_ms"]),
            item[0]["id"],
        )
    )
    return candidates[0]


def evidence_instance_id(
    incident_id: str, execution: dict[str, Any], observation: str
) -> str:
    payload = "\0".join((incident_id, execution["id"], observation))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    suffix = "request_latency" if observation == REQUEST_LATENCY_OBSERVATION else "pool_wait"
    return f"evidence.runtime.{suffix}.{digest}"


def trace_source(
    *,
    system_id: str,
    revision: str,
    execution: dict[str, Any],
    target_resource: str,
    pool_id: str,
) -> dict[str, Any]:
    source: dict[str, Any] = {
        "type": "trace",
        "name": "causcope.rails.runtime",
        "attributes": {
            "otel.trace_id": str(execution["trace_id"]),
            "otel.span_id": str(execution["span_id"]),
            "causcope.execution_id": str(execution["id"]),
            "causcope.code_symbol": str(execution["code_symbol"]),
            "causcope.system_id": system_id,
            "causcope.revision": revision,
            "causcope.runtime_resource": pool_id,
            "causcope.target_resource": target_resource,
        },
    }
    execution_source = execution.get("source", {})
    if isinstance(execution_source, dict):
        uri = execution_source.get("uri")
        if isinstance(uri, str) and uri:
            source["uri"] = uri
    return source


def build_initial_evidence(
    *,
    incident_id: str,
    system_id: str,
    revision: str,
    execution: dict[str, Any],
    interaction: dict[str, Any],
    request_threshold_ms: float,
    pool_wait_threshold_ms: float,
    target_resource: str,
) -> dict[str, Any]:
    scope = {
        "attributes": {
            "service": system_id,
            "code_symbol": str(execution["code_symbol"]),
            "runtime_resource": str(interaction["pool_id"]),
        }
    }
    source = trace_source(
        system_id=system_id,
        revision=revision,
        execution=execution,
        target_resource=target_resource,
        pool_id=str(interaction["pool_id"]),
    )
    duration_ms = float(execution["duration_ms"])
    pool_wait_ms = float(interaction["checkout_wait_ms"])

    return {
        "schema_version": "0.1",
        "kind": "runtime_evidence",
        "incident_id": incident_id,
        "description": (
            "Initial incident evidence projected from one exact Rails request and its "
            "ActiveRecord pool checkout interaction."
        ),
        "instances": [
            {
                "id": evidence_instance_id(
                    incident_id, execution, REQUEST_LATENCY_OBSERVATION
                ),
                "observation": REQUEST_LATENCY_OBSERVATION,
                "state": "observed",
                "observed_at": execution["end_time"],
                "confidence": "high",
                "source": dict(source),
                "scope": dict(scope),
                "measurement": {
                    "value": duration_ms,
                    "baseline": request_threshold_ms,
                    "delta": duration_ms - request_threshold_ms,
                    "unit": "ms",
                    "comparison": "above_baseline",
                },
                "labels": {
                    "selection_policy": SELECTION_POLICY,
                    "target_resource": target_resource,
                },
                "note": (
                    "Request duration exceeded the explicit latency objective; this is symptom "
                    "evidence and does not identify a mechanism by itself."
                ),
            },
            {
                "id": evidence_instance_id(
                    incident_id, execution, POOL_WAIT_OBSERVATION
                ),
                "observation": POOL_WAIT_OBSERVATION,
                "state": "observed",
                "observed_at": interaction["observed_at"],
                "confidence": "high",
                "source": dict(source),
                "scope": dict(scope),
                "measurement": {
                    "value": pool_wait_ms,
                    "baseline": pool_wait_threshold_ms,
                    "delta": pool_wait_ms - pool_wait_threshold_ms,
                    "unit": "ms",
                    "comparison": "above_baseline",
                },
                "labels": {
                    "selection_policy": SELECTION_POLICY,
                    "target_resource": target_resource,
                    "pool_interaction_id": str(interaction["id"]),
                },
                "note": (
                    "ActiveRecord checkout wait exceeded the explicit pool-wait objective on the "
                    "same request trace; database execution health remains unproven."
                ),
            },
        ],
    }


def atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def seed_workspace(
    *,
    root: Path,
    workspace: Path,
    runtime_path: Path,
    request_threshold_ms: float,
    pool_wait_threshold_ms: float,
    code_symbol: str | None,
    trace_id: str | None,
    force: bool,
) -> dict[str, Any]:
    if request_threshold_ms <= 0:
        raise ValueError("request latency threshold must be positive")
    if pool_wait_threshold_ms < 0:
        raise ValueError("pool wait threshold must be non-negative")

    incident_id = load_workspace_incident_id(workspace)
    static_path = workspace / DEFAULT_STATIC_FACTS
    topology_path = workspace / DEFAULT_TOPOLOGY
    if not static_path.is_file():
        raise ValueError(
            f"static facts not found at {static_path}; run `causcope bootstrap` first"
        )
    if not topology_path.is_file():
        raise ValueError(
            f"resource topology not found at {topology_path}; run `causcope bootstrap` first"
        )
    if not runtime_path.is_file():
        raise ValueError(
            f"runtime facts not found at {runtime_path}; start the receiver and reproduce the problem first"
        )

    static = load_static_document(static_path)
    runtime = load_runtime_document(runtime_path)
    validate_runtime_document(runtime)
    if runtime.get("incident_id") != incident_id:
        raise ValueError(
            f"runtime facts belong to {runtime.get('incident_id')!r}, expected current investigation {incident_id!r}"
        )

    relationships = project_runtime_relationships(static, runtime)
    topology = load_resource_topology(topology_path)
    execution, interaction, matched_relationships, target_resource = choose_execution(
        runtime,
        relationships,
        topology,
        request_threshold_ms=request_threshold_ms,
        pool_wait_threshold_ms=pool_wait_threshold_ms,
        code_symbol=code_symbol,
        trace_id=trace_id,
    )

    concepts = load_concepts(ROOT)
    edges = load_edges(ROOT)
    evidence = build_initial_evidence(
        incident_id=incident_id,
        system_id=static["system_id"],
        revision=static["revision"]["value"],
        execution=execution,
        interaction=interaction,
        request_threshold_ms=request_threshold_ms,
        pool_wait_threshold_ms=pool_wait_threshold_ms,
        target_resource=target_resource,
    )
    validate_runtime_evidence_document(evidence, concepts)

    as_of = parse_timestamp(execution["end_time"], "selected execution end_time")
    diagnosis = build_diagnosis_snapshot(
        evidence,
        concepts,
        edges,
        as_of=as_of,
        evidence_revision=1,
    )
    target_resolution = build_runtime_target_resolution(
        diagnosis,
        evidence,
        relationships,
        topology,
    )
    pool_wait_resolutions = [
        resolution
        for resolution in target_resolution.get("resolutions", [])
        if resolution.get("diagnosis_target") == POOL_WAIT_OBSERVATION
        and resolution.get("status") == "resolved"
    ]
    resolved_targets = {
        binding["target_resource"]
        for resolution in pool_wait_resolutions
        for binding in resolution.get("target_bindings", [])
    }
    if resolved_targets != {target_resource}:
        rendered = ", ".join(sorted(resolved_targets)) or "none"
        raise ValueError(
            f"initial pool-wait diagnosis could not be proven to resolve only to {target_resource}; "
            f"resolved targets: {rendered}"
        )

    output_paths = {
        "runtime_evidence": workspace / DEFAULT_RUNTIME_EVIDENCE,
        "runtime_relationships": workspace / DEFAULT_RUNTIME_RELATIONSHIPS,
        "diagnosis": workspace / DEFAULT_DIAGNOSIS,
    }
    existing = [path for path in output_paths.values() if path.exists()]
    if existing and not force:
        raise ValueError(
            "refusing to overwrite existing incident seed artifacts: "
            + ", ".join(str(path) for path in existing)
            + "; pass --force to replace them"
        )

    atomic_write_json(output_paths["runtime_evidence"], evidence)
    atomic_write_json(output_paths["runtime_relationships"], relationships)
    atomic_write_json(output_paths["diagnosis"], diagnosis)

    leading_hypothesis = None
    top_probe = None
    for partition in diagnosis.get("partitions", []):
        for item in partition.get("diagnoses", []):
            if item.get("target") != POOL_WAIT_OBSERVATION:
                continue
            candidates = item.get("ranking", {}).get("candidates", [])
            if candidates:
                leading_hypothesis = candidates[0].get("source", {}).get("id")
            probes = item.get("probe_ranking", {}).get("probes", [])
            if probes:
                top_probe = probes[0].get("probe", {}).get("id")
            break

    if leading_hypothesis is None:
        raise ValueError(
            "initial pool-wait observation produced no causal candidate; knowledge graph is incomplete"
        )

    return {
        "schema_version": "0.1",
        "kind": "incident_seed_result",
        "incident_id": incident_id,
        "evidence_revision": 1,
        "selection_policy": SELECTION_POLICY,
        "selected_execution": execution["id"],
        "selected_pool_interaction": interaction["id"],
        "code_symbol": execution["code_symbol"],
        "trace_id": execution["trace_id"],
        "request_duration_ms": float(execution["duration_ms"]),
        "request_latency_threshold_ms": request_threshold_ms,
        "pool_wait_ms": float(interaction["checkout_wait_ms"]),
        "pool_wait_threshold_ms": pool_wait_threshold_ms,
        "runtime_resource": interaction["pool_id"],
        "runtime_relationship_ids": sorted(
            item["id"] for item in matched_relationships
        ),
        "target_resource": target_resource,
        "leading_hypothesis": leading_hypothesis,
        "next_probe": top_probe,
        "outputs": {name: str(path) for name, path in output_paths.items()},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Seed diagnosis revision 1 from one exact slow Rails request and its "
            "elevated ActiveRecord pool checkout wait."
        )
    )
    parser.add_argument("path", type=Path, nargs="?", default=Path("."))
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--runtime-facts", type=Path)
    parser.add_argument("--request-latency-threshold-ms", type=float, required=True)
    parser.add_argument("--pool-wait-threshold-ms", type=float, required=True)
    parser.add_argument("--code-symbol")
    parser.add_argument("--trace-id")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        root = args.path.expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"application root does not exist: {root}")
        workspace = workspace_path(root, args.workspace)
        incident_id = load_workspace_incident_id(workspace)
        if args.runtime_facts is None:
            runtime_path = default_runtime_snapshot_path(workspace, incident_id)
        else:
            runtime_path = (
                args.runtime_facts.resolve()
                if args.runtime_facts.is_absolute()
                else (root / args.runtime_facts).resolve()
            )
        result = seed_workspace(
            root=root,
            workspace=workspace,
            runtime_path=runtime_path,
            request_threshold_ms=args.request_latency_threshold_ms,
            pool_wait_threshold_ms=args.pool_wait_threshold_ms,
            code_symbol=args.code_symbol,
            trace_id=args.trace_id,
            force=args.force,
        )
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"Investigation: {result['incident_id']}")
            print(f"Selected execution: {result['selected_execution']}")
            print(f"Request latency: {result['request_duration_ms']:.3f} ms")
            print(f"Request objective: {result['request_latency_threshold_ms']:.3f} ms")
            print(f"Pool wait: {result['pool_wait_ms']:.3f} ms")
            print(f"Pool-wait objective: {result['pool_wait_threshold_ms']:.3f} ms")
            print(f"Runtime resource: {result['runtime_resource']}")
            print(f"Exact target: {result['target_resource']}")
            print(f"Leading hypothesis: {result['leading_hypothesis']}")
            print(f"Next probe: {result['next_probe'] or '<none>'}")
            print("Wrote diagnosis revision 1")
        return 0
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"causcope runtime seed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

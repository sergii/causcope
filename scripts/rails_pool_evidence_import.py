#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from causal_projection import ROOT, load_concepts, load_edges
from diagnosis_http_api import DiagnosisSnapshotReader
from incident_state_commit import (
    IncidentStateCommitError,
    canonical_hash,
    commit_incident_state,
    default_commit_path,
    prepare_commit,
    recover_incident_state_commit,
)
from live_diagnosis import build_diagnosis_snapshot
from probe_filesystem_claim import (
    ProbeFilesystemClaimError,
    acquire_probe_filesystem_claim,
    incident_mutation_claim_identity,
)
from runtime_evidence import load_runtime_evidence, parse_timestamp
from runtime_evidence_composition import compose_runtime_evidence

POOL_SCHEMA = ROOT / "schema" / "resource-pool-runtime-evidence.schema.json"
RUNTIME_EVIDENCE = "runtime-evidence.json"
DIAGNOSIS = "diagnosis.json"
POOL_WAIT = "observation.database.connection_pool_wait_time"
POOL_UTILIZATION = "observation.database.connection_pool_utilization"
QUERY_LATENCY = "observation.database.query_latency"


class RailsPoolEvidenceImportError(ValueError):
    pass


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RailsPoolEvidenceImportError(f"{label} not found at {path}") from error
    except json.JSONDecodeError as error:
        raise RailsPoolEvidenceImportError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(document, dict):
        raise RailsPoolEvidenceImportError(f"{label} must contain a JSON object")
    return document


def validate_pool_document(document: dict[str, Any]) -> None:
    schema = _load_json_object(POOL_SCHEMA, "resource-pool runtime evidence schema")
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        raise RailsPoolEvidenceImportError(
            "resource-pool runtime evidence schema validation failed: "
            + "; ".join(error.message for error in errors)
        )


def _exact_seed_instance(
    existing: dict[str, Any], pool: dict[str, Any]
) -> dict[str, Any]:
    request = pool["request"]
    pool_id = pool["pool"]["id"]
    matches: list[dict[str, Any]] = []
    for instance in existing.get("instances", []):
        if instance.get("observation") != POOL_WAIT or instance.get("state") != "observed":
            continue
        source = instance.get("source", {})
        attributes = source.get("attributes", {}) if isinstance(source, dict) else {}
        if not isinstance(attributes, dict):
            continue
        if (
            attributes.get("otel.trace_id") == request["trace_id"]
            and attributes.get("otel.span_id") == request["span_id"]
            and attributes.get("causcope.code_symbol") == request["code_symbol"]
            and attributes.get("causcope.runtime_resource") == pool_id
        ):
            matches.append(instance)
    if len(matches) != 1:
        raise RailsPoolEvidenceImportError(
            "resource-pool evidence must bind to exactly one current canonical pool-wait instance; "
            f"found {len(matches)}"
        )
    return matches[0]


def _identity(seed: dict[str, Any], pool: dict[str, Any], incident_id: str) -> tuple[str, dict[str, Any]]:
    if pool.get("incident_id") != incident_id:
        raise RailsPoolEvidenceImportError(
            f"resource-pool evidence belongs to {pool.get('incident_id')!r}, expected {incident_id!r}"
        )
    attributes = seed.get("source", {}).get("attributes", {})
    if not isinstance(attributes, dict):
        raise RailsPoolEvidenceImportError("canonical seed evidence has no source attributes")
    expected = {
        "system_id": attributes.get("causcope.system_id"),
        "revision": attributes.get("causcope.revision"),
        "target_resource": attributes.get("causcope.target_resource"),
    }
    if pool.get("system_id") != expected["system_id"]:
        raise RailsPoolEvidenceImportError("resource-pool evidence system_id does not match canonical seed evidence")
    pool_revision = pool.get("revision", {}).get("value")
    if pool_revision != expected["revision"]:
        raise RailsPoolEvidenceImportError("resource-pool evidence revision does not match canonical seed evidence")
    target_resource = expected["target_resource"]
    if not isinstance(target_resource, str) or not target_resource:
        raise RailsPoolEvidenceImportError("canonical seed evidence has no exact target_resource binding")
    return target_resource, attributes


def _evidence_id(incident_id: str, pool: dict[str, Any], observation: str) -> str:
    payload = "\0".join(
        (
            incident_id,
            str(pool["request"]["trace_id"]),
            str(pool["request"]["span_id"]),
            str(pool["pool"]["id"]),
            observation,
            str(pool["observed_at"]),
        )
    )
    return "evidence.rails_pool." + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_canonical_pool_evidence(
    pool: dict[str, Any],
    existing: dict[str, Any],
) -> dict[str, Any]:
    validate_pool_document(pool)
    incident_id = existing.get("incident_id")
    if not isinstance(incident_id, str) or not incident_id:
        raise RailsPoolEvidenceImportError("current runtime evidence has no incident_id")
    seed = _exact_seed_instance(existing, pool)
    target_resource, seed_attributes = _identity(seed, pool, incident_id)
    scope = copy.deepcopy(seed.get("scope"))
    if not isinstance(scope, dict):
        raise RailsPoolEvidenceImportError("canonical seed evidence has no reusable exact scope")

    source = {
        "type": "probe",
        "name": "causcope.rails.connection_pool_probe",
        "attributes": {
            "otel.trace_id": str(pool["request"]["trace_id"]),
            "otel.span_id": str(pool["request"]["span_id"]),
            "causcope.code_symbol": str(pool["request"]["code_symbol"]),
            "causcope.system_id": str(pool["system_id"]),
            "causcope.revision": str(pool["revision"]["value"]),
            "causcope.runtime_resource": str(pool["pool"]["id"]),
            "causcope.target_resource": target_resource,
            "causcope.seed_evidence_id": str(seed["id"]),
        },
    }
    instances: list[dict[str, Any]] = []
    at_capacity = bool(pool["assertions"]["application_pool_was_at_capacity"])
    instances.append(
        {
            "id": _evidence_id(incident_id, pool, POOL_UTILIZATION),
            "observation": POOL_UTILIZATION,
            "state": "observed" if at_capacity else "absent",
            "observed_at": pool["observed_at"],
            "confidence": "high",
            "source": copy.deepcopy(source),
            "scope": copy.deepcopy(scope),
            "measurement": {
                "value": pool["pool"]["busy"],
                "baseline": pool["pool"]["observed_capacity"],
                "delta": pool["pool"]["busy"] - pool["pool"]["observed_capacity"],
                "unit": "slots",
                "comparison": "equal" if at_capacity else "below_baseline",
            },
            "labels": {
                "target_resource": target_resource,
                "projection": "resource_pool_runtime_evidence",
            },
            "note": (
                "Exact application pool occupancy projected from the bounded Rails probe; "
                "the observation is target-bound through the canonical seed evidence."
            ),
        }
    )

    if pool["assertions"]["query_latency_stayed_near_baseline"]:
        current = float(pool["request"]["dependency_latency_ms"])
        baseline = float(pool["baseline"]["dependency_latency_ms"])
        instances.append(
            {
                "id": _evidence_id(incident_id, pool, QUERY_LATENCY),
                "observation": QUERY_LATENCY,
                "state": "absent",
                "observed_at": pool["observed_at"],
                "confidence": "high",
                "source": copy.deepcopy(source),
                "scope": copy.deepcopy(scope),
                "measurement": {
                    "value": current,
                    "baseline": baseline,
                    "delta": current - baseline,
                    "unit": "ms",
                },
                "labels": {
                    "target_resource": target_resource,
                    "projection": "resource_pool_runtime_evidence",
                    "independent_database_control": (
                        "reachable"
                        if pool["assertions"]["database_still_accepts_direct_connections"]
                        else "not_established"
                    ),
                },
                "note": (
                    "Query latency stayed near the bounded baseline after checkout. State=absent means "
                    "the elevated-query-latency observation was not present; it does not mean the database was unused."
                ),
            }
        )

    return {
        "schema_version": "0.1",
        "kind": "runtime_evidence",
        "incident_id": incident_id,
        "description": (
            "Canonical observations projected from the exact Rails D3.1 resource-pool proof. "
            "Recovery and independent database admission remain provenance/verification facts until "
            "their semantic observations are modeled explicitly."
        ),
        "instances": instances,
    }


def import_pool_evidence(*, workspace: Path, pool_path: Path) -> dict[str, Any]:
    runtime_path = workspace / RUNTIME_EVIDENCE
    snapshot_path = workspace / DIAGNOSIS
    if not runtime_path.is_file() or not snapshot_path.is_file():
        raise RailsPoolEvidenceImportError(
            "canonical incident seed is required before importing resource-pool evidence; "
            "expected runtime-evidence.json and diagnosis.json"
        )

    pool = _load_json_object(pool_path, "resource-pool runtime evidence")
    concepts = load_concepts(ROOT)
    edges = load_edges(ROOT)
    reader = DiagnosisSnapshotReader(snapshot_path)
    commit_path = default_commit_path(snapshot_path)

    try:
        with acquire_probe_filesystem_claim(
            workspace,
            purpose="rails_pool_evidence_import",
            identity=incident_mutation_claim_identity(incident_id=pool.get("incident_id", "<invalid>")),
        ):
            recover_incident_state_commit(
                commit_path=commit_path,
                runtime_evidence_path=runtime_path,
                snapshot_path=snapshot_path,
            )
            snapshot, _etag = reader.read()
            existing = load_runtime_evidence(runtime_path)
            if existing["incident_id"] != snapshot["incident_id"]:
                raise RailsPoolEvidenceImportError("runtime evidence and diagnosis belong to different incidents")

            produced = build_canonical_pool_evidence(pool, existing)
            composed = compose_runtime_evidence([existing, produced], concepts)
            if canonical_hash(composed) == canonical_hash(existing):
                raise RailsPoolEvidenceImportError("resource-pool proof produced no new canonical evidence")
            old_ids = {item["id"] for item in existing["instances"]}
            added_ids = sorted(item["id"] for item in composed["instances"] if item["id"] not in old_ids)
            if not added_ids:
                raise RailsPoolEvidenceImportError("resource-pool proof produced no new canonical evidence instances")

            next_revision = snapshot["evidence_revision"] + 1
            as_of = parse_timestamp(pool["observed_at"], "resource-pool observed_at")
            next_snapshot = build_diagnosis_snapshot(
                composed,
                concepts,
                edges,
                as_of=as_of,
                evidence_revision=next_revision,
            )
            commit = prepare_commit(
                incident_id=snapshot["incident_id"],
                from_evidence_revision=snapshot["evidence_revision"],
                runtime_evidence=composed,
                diagnosis_snapshot=next_snapshot,
            )
            commit_incident_state(
                commit_path=commit_path,
                runtime_evidence_path=runtime_path,
                snapshot_path=snapshot_path,
                commit=commit,
            )
    except (ProbeFilesystemClaimError, IncidentStateCommitError) as error:
        raise RailsPoolEvidenceImportError(str(error)) from error

    return {
        "schema_version": "0.1",
        "kind": "rails_pool_evidence_import_result",
        "incident_id": snapshot["incident_id"],
        "previous_evidence_revision": snapshot["evidence_revision"],
        "evidence_revision": next_revision,
        "added_instance_ids": added_ids,
        "target_resource": produced["instances"][0]["source"]["attributes"]["causcope.target_resource"],
        "projected_observations": [item["observation"] for item in produced["instances"]],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Project one exact Rails D3.1 resource-pool proof into the current canonical runtime-evidence "
            "bundle and atomically rerank the persisted Investigation."
        )
    )
    parser.add_argument("--workspace", type=Path, default=Path(".causcope"))
    parser.add_argument("--pool-evidence", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = import_pool_evidence(
            workspace=args.workspace.expanduser().resolve(),
            pool_path=args.pool_evidence.expanduser().resolve(),
        )
    except (OSError, RailsPoolEvidenceImportError) as error:
        print(f"causcope runtime import-pool: {error}", file=__import__("sys").stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            f"Investigation {result['incident_id']}: evidence revision "
            f"{result['previous_evidence_revision']} -> {result['evidence_revision']}"
        )
        print("Projected: " + ", ".join(result["projected_observations"]))
        print(f"Exact target: {result['target_resource']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

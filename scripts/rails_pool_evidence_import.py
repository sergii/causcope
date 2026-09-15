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
REQUEST_LATENCY = "observation.http.request_latency"
POOL_EXHAUSTION = "hypothesis.database.connection_pool_exhaustion"
INTERVENTION_KIND = "resource_capacity_release"


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


def _exact_seed_instance(existing: dict[str, Any], pool: dict[str, Any]) -> dict[str, Any]:
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
    if pool.get("revision", {}).get("value") != expected["revision"]:
        raise RailsPoolEvidenceImportError("resource-pool evidence revision does not match canonical seed evidence")
    target_resource = expected["target_resource"]
    if not isinstance(target_resource, str) or not target_resource:
        raise RailsPoolEvidenceImportError("canonical seed evidence has no exact target_resource binding")
    return target_resource, attributes


def _evidence_id(incident_id: str, pool: dict[str, Any], observation: str, phase: str) -> str:
    payload = "\0".join(
        (
            incident_id,
            str(pool["request"]["trace_id"]),
            str(pool["request"]["span_id"]),
            str(pool["pool"]["id"]),
            observation,
            phase,
            str(pool["observed_at"]),
        )
    )
    return "evidence.rails_pool." + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _verification_id(incident_id: str, pool: dict[str, Any], target_resource: str) -> str:
    payload = "\0".join(
        (
            incident_id,
            target_resource,
            str(pool["request"]["trace_id"]),
            str(pool["request"]["span_id"]),
            str(pool["pool"]["id"]),
            INTERVENTION_KIND,
        )
    )
    return "verification.rails_pool." + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _leading_hypothesis(snapshot: dict[str, Any], scope: dict[str, Any]) -> tuple[str | None, int | None]:
    for partition in snapshot.get("partitions", []):
        if partition.get("scope") != scope:
            continue
        for diagnosis in partition.get("diagnoses", []):
            if diagnosis.get("target") != REQUEST_LATENCY:
                continue
            candidates = diagnosis.get("ranking", {}).get("candidates", [])
            if not candidates:
                return None, None
            source = candidates[0].get("source", {})
            hypothesis = source.get("id") if isinstance(source, dict) else None
            return (hypothesis if isinstance(hypothesis, str) else None, 1)
    return None, None


def _source(
    *,
    pool: dict[str, Any],
    seed: dict[str, Any],
    target_resource: str,
    verification_id: str,
    baseline_revision: int,
    baseline_hypothesis: str | None,
    phase: str,
) -> dict[str, Any]:
    attributes = {
        "otel.trace_id": str(pool["request"]["trace_id"]),
        "otel.span_id": str(pool["request"]["span_id"]),
        "causcope.code_symbol": str(pool["request"]["code_symbol"]),
        "causcope.system_id": str(pool["system_id"]),
        "causcope.revision": str(pool["revision"]["value"]),
        "causcope.runtime_resource": str(pool["pool"]["id"]),
        "causcope.target_resource": target_resource,
        "causcope.seed_evidence_id": str(seed["id"]),
        "causcope.verification_id": verification_id,
        "causcope.verification_phase": phase,
        "causcope.intervention_kind": INTERVENTION_KIND,
        "causcope.intervention_resource": str(pool["pool"]["id"]),
        "causcope.baseline_evidence_revision": str(baseline_revision),
    }
    if baseline_hypothesis is not None:
        attributes["causcope.baseline_leading_hypothesis"] = baseline_hypothesis
    return {
        "type": "experiment",
        "name": "causcope.rails.connection_pool_probe",
        "attributes": attributes,
    }


def _instance(
    *,
    incident_id: str,
    pool: dict[str, Any],
    observation: str,
    state: str,
    phase: str,
    source: dict[str, Any],
    scope: dict[str, Any],
    target_resource: str,
    measurement: dict[str, Any],
    note: str,
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    item_labels = {
        "target_resource": target_resource,
        "projection": "resource_pool_runtime_evidence",
        "verification_phase": phase,
    }
    if labels:
        item_labels.update(labels)
    return {
        "id": _evidence_id(incident_id, pool, observation, phase),
        "observation": observation,
        "state": state,
        "observed_at": pool["observed_at"],
        "confidence": "high",
        "source": source,
        "scope": copy.deepcopy(scope),
        "measurement": measurement,
        "labels": item_labels,
        "note": note,
    }


def build_canonical_pool_evidence(
    pool: dict[str, Any],
    existing: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    validate_pool_document(pool)
    incident_id = existing.get("incident_id")
    if not isinstance(incident_id, str) or not incident_id:
        raise RailsPoolEvidenceImportError("current runtime evidence has no incident_id")
    seed = _exact_seed_instance(existing, pool)
    target_resource, _seed_attributes = _identity(seed, pool, incident_id)
    scope = copy.deepcopy(seed.get("scope"))
    if not isinstance(scope, dict):
        raise RailsPoolEvidenceImportError("canonical seed evidence has no reusable exact scope")

    baseline_hypothesis, baseline_rank = _leading_hypothesis(snapshot, scope)
    verification_id = _verification_id(incident_id, pool, target_resource)
    baseline_revision = int(snapshot["evidence_revision"])

    def source(phase: str) -> dict[str, Any]:
        return _source(
            pool=pool,
            seed=seed,
            target_resource=target_resource,
            verification_id=verification_id,
            baseline_revision=baseline_revision,
            baseline_hypothesis=baseline_hypothesis,
            phase=phase,
        )

    instances: list[dict[str, Any]] = []
    at_capacity = bool(pool["assertions"]["application_pool_was_at_capacity"])
    instances.append(
        _instance(
            incident_id=incident_id,
            pool=pool,
            observation=POOL_UTILIZATION,
            state="observed" if at_capacity else "absent",
            phase="pre_intervention",
            source=source("pre_intervention"),
            scope=scope,
            target_resource=target_resource,
            measurement={
                "value": pool["pool"]["busy"],
                "baseline": pool["pool"]["observed_capacity"],
                "delta": pool["pool"]["busy"] - pool["pool"]["observed_capacity"],
                "unit": "slots",
                "comparison": "equal" if at_capacity else "below_baseline",
            },
            labels={
                "mechanism_explains_request_delta": str(bool(pool["assertions"]["checkout_wait_explains_request_delta"])).lower(),
                "baseline_hypothesis_rank": str(baseline_rank or 0),
            },
            note=(
                "Exact application pool occupancy before capacity release. The bounded experiment "
                "binds this mechanism observation to the canonical seed request and exact target."
            ),
        )
    )

    if pool["assertions"]["query_latency_stayed_near_baseline"]:
        current = float(pool["request"]["dependency_latency_ms"])
        baseline = float(pool["baseline"]["dependency_latency_ms"])
        instances.append(
            _instance(
                incident_id=incident_id,
                pool=pool,
                observation=QUERY_LATENCY,
                state="absent",
                phase="control",
                source=source("control"),
                scope=scope,
                target_resource=target_resource,
                measurement={"value": current, "baseline": baseline, "delta": current - baseline, "unit": "ms"},
                labels={
                    "independent_database_control": (
                        "reachable" if pool["assertions"]["database_still_accepts_direct_connections"] else "not_established"
                    )
                },
                note=(
                    "Query latency stayed near the bounded baseline while the application pool was saturated. "
                    "State=absent means elevated query latency was not present."
                ),
            )
        )

    if pool["assertions"]["recovery_checkout_wait_returned_to_baseline"]:
        current = float(pool["recovery"]["checkout_wait_ms"])
        baseline = float(pool["baseline"]["checkout_wait_ms"])
        instances.append(
            _instance(
                incident_id=incident_id,
                pool=pool,
                observation=POOL_WAIT,
                state="absent",
                phase="post_intervention",
                source=source("post_intervention"),
                scope=scope,
                target_resource=target_resource,
                measurement={"value": current, "baseline": baseline, "delta": current - baseline, "unit": "ms"},
                labels={"intervention_outcome": "predicted_recovery"},
                note=(
                    "After the bounded pool-capacity holder completed and released its slot, checkout wait "
                    "returned to the experiment baseline."
                ),
            )
        )

    if pool["assertions"]["recovery_request_latency_returned_to_baseline"]:
        current = float(pool["recovery"]["request_latency_ms"])
        baseline = float(pool["baseline"]["request_latency_ms"])
        instances.append(
            _instance(
                incident_id=incident_id,
                pool=pool,
                observation=REQUEST_LATENCY,
                state="absent",
                phase="post_intervention",
                source=source("post_intervention"),
                scope=scope,
                target_resource=target_resource,
                measurement={"value": current, "baseline": baseline, "delta": current - baseline, "unit": "ms"},
                labels={"intervention_outcome": "predicted_recovery"},
                note=(
                    "After the bounded pool-capacity holder completed and released its slot, request latency "
                    "returned to the experiment baseline."
                ),
            )
        )

    return {
        "schema_version": "0.1",
        "kind": "runtime_evidence",
        "incident_id": incident_id,
        "description": (
            "Canonical mechanism, control, and post-intervention recovery observations projected from "
            "the exact Rails D3.1 resource-pool experiment."
        ),
        "instances": instances,
    }


def import_pool_evidence(*, workspace: Path, pool_path: Path) -> dict[str, Any]:
    runtime_path = workspace / RUNTIME_EVIDENCE
    snapshot_path = workspace / DIAGNOSIS
    if not runtime_path.is_file() or not snapshot_path.is_file():
        raise RailsPoolEvidenceImportError(
            "canonical incident seed is required before importing resource-pool evidence; expected runtime-evidence.json and diagnosis.json"
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

            produced = build_canonical_pool_evidence(pool, existing, snapshot)
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
        "verification_id": produced["instances"][0]["source"]["attributes"]["causcope.verification_id"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Project one exact Rails D3.1 resource-pool experiment into canonical runtime evidence and "
            "atomically rerank the persisted Investigation."
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
        print(f"Verification: {result['verification_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

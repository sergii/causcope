#!/usr/bin/env python3

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from autonomous_investigation import ProbeInsufficientEvidence
from diagnosis_http_api import DiagnosisSnapshotReader
from incident_state_commit import (
    FaultHook,
    IncidentStateCommitError,
    canonical_hash,
    commit_incident_state,
    default_commit_path,
    prepare_commit,
    recover_incident_state_commit,
)
from live_diagnosis import build_diagnosis_snapshot, normalize_scope, scope_key
from probe_filesystem_claim import (
    ProbeFilesystemClaimError,
    acquire_probe_filesystem_claim,
    incident_mutation_claim_identity,
)
from routed_execution_sets import (
    EXECUTE_SET_OPERATION,
    build_routed_execution_sets,
)
from runtime_evidence import load_runtime_evidence
from runtime_evidence_composition import compose_runtime_evidence

TOOL_NAME = EXECUTE_SET_OPERATION
TARGET_SCOPE_ATTRIBUTE = "target_resource"


class RoutedExecutionSetInvocationError(ValueError):
    pass


def _find_diagnosis(
    snapshot: dict[str, Any],
    *,
    target: str,
    scope: dict[str, Any] | None,
) -> dict[str, Any]:
    wanted = scope_key(scope)
    matches = [
        diagnosis
        for partition in snapshot.get("partitions", [])
        if scope_key(partition.get("scope")) == wanted
        for diagnosis in partition.get("diagnoses", [])
        if diagnosis.get("target") == target
    ]
    if len(matches) != 1:
        raise RoutedExecutionSetInvocationError(
            f"expected exactly one current diagnosis for target {target} and selected scope, got {len(matches)}"
        )
    return matches[0]


def _bind_evidence_scope_to_target(
    produced: dict[str, Any],
    *,
    semantic_scope: dict[str, Any] | None,
    target_resource: str,
) -> None:
    """Make exact routed target identity part of evidence partitioning, not only provenance."""

    for instance in produced.get("instances", []):
        if not isinstance(instance, dict):
            continue
        instance_scope = copy.deepcopy(instance.get("scope") or semantic_scope or {})
        attributes = instance_scope.setdefault("attributes", {})
        existing = attributes.get(TARGET_SCOPE_ATTRIBUTE)
        if existing is not None and existing != target_resource:
            raise RoutedExecutionSetInvocationError(
                f"member evidence scope target mismatch: {target_resource}"
            )
        attributes[TARGET_SCOPE_ATTRIBUTE] = target_resource
        instance["scope"] = instance_scope


class RoutedExecutionSetToolController:
    """Execute one exact multi-target read-only set and commit one evidence revision."""

    def __init__(
        self,
        *,
        reader: DiagnosisSnapshotReader,
        snapshot_path: Path,
        runtime_evidence_path: Path,
        concepts: dict[str, dict[str, Any]],
        edges: list[dict[str, Any]],
        routing_projection_provider: Callable[[dict[str, Any]], dict[str, Any]],
        information_gain_router_provider: Callable[[], Any],
        mutation_lock_dir: Path,
        clock: Callable[[], datetime] | None = None,
        commit_path: Path | None = None,
        commit_fault_hook: FaultHook | None = None,
    ) -> None:
        self.reader = reader
        self.snapshot_path = snapshot_path
        self.runtime_evidence_path = runtime_evidence_path
        self.concepts = concepts
        self.edges = edges
        self.routing_projection_provider = routing_projection_provider
        self.information_gain_router_provider = information_gain_router_provider
        self.mutation_lock_dir = mutation_lock_dir
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.commit_path = commit_path or default_commit_path(snapshot_path)
        self.commit_fault_hook = commit_fault_hook

    @staticmethod
    def tool_names() -> set[str]:
        return {TOOL_NAME}

    @staticmethod
    def tool_descriptors() -> list[dict[str, Any]]:
        return [
            {
                "name": TOOL_NAME,
                "title": "Execute current routed target set",
                "description": (
                    "Execute every exact direct read-only provider member in the current bounded target set. "
                    "All provider reads must succeed before Causcope commits one composed evidence revision "
                    "and reranks the diagnosis once."
                ),
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["incidentId", "evidenceRevision", "executionSetId"],
                    "properties": {
                        "incidentId": {"type": "string", "minLength": 1},
                        "evidenceRevision": {"type": "integer", "minimum": 0},
                        "executionSetId": {
                            "type": "string",
                            "pattern": "^execution-set\\.[0-9a-f]{16}$"
                        }
                    }
                }
            }
        ]

    def _validated_arguments(self, arguments: Any) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise RoutedExecutionSetInvocationError("tool arguments must be an object")
        required = {"incidentId", "evidenceRevision", "executionSetId"}
        if set(arguments) != required:
            raise RoutedExecutionSetInvocationError(
                "tool arguments must exactly match the routed execution-set contract"
            )
        if not isinstance(arguments["evidenceRevision"], int) or arguments["evidenceRevision"] < 0:
            raise RoutedExecutionSetInvocationError("evidenceRevision must be a non-negative integer")
        for field in ("incidentId", "executionSetId"):
            if not isinstance(arguments[field], str) or not arguments[field]:
                raise RoutedExecutionSetInvocationError(f"{field} must be a non-empty string")
        return copy.deepcopy(arguments)

    def call(self, name: str, arguments: Any) -> dict[str, Any]:
        if name != TOOL_NAME:
            raise RoutedExecutionSetInvocationError(f"unsupported routed execution-set tool: {name}")
        args = self._validated_arguments(arguments)
        try:
            with acquire_probe_filesystem_claim(
                self.mutation_lock_dir,
                purpose="routed_execution_set_mutation",
                identity=incident_mutation_claim_identity(incident_id=args["incidentId"]),
            ):
                return self._execute_locked(args)
        except (ProbeFilesystemClaimError, IncidentStateCommitError) as exc:
            raise RoutedExecutionSetInvocationError(str(exc)) from exc

    def _execute_locked(self, args: dict[str, Any]) -> dict[str, Any]:
        recover_incident_state_commit(
            commit_path=self.commit_path,
            runtime_evidence_path=self.runtime_evidence_path,
            snapshot_path=self.snapshot_path,
        )

        snapshot, _etag = self.reader.read()
        if snapshot["incident_id"] != args["incidentId"]:
            raise RoutedExecutionSetInvocationError("incidentId does not match current diagnosis")
        if snapshot["evidence_revision"] != args["evidenceRevision"]:
            raise RoutedExecutionSetInvocationError(
                f"stale evidenceRevision: current diagnosis revision is {snapshot['evidence_revision']}"
            )

        try:
            routing = self.routing_projection_provider(snapshot)
            projection = build_routed_execution_sets(routing)
        except (OSError, ValueError) as exc:
            raise RoutedExecutionSetInvocationError(f"current execution-set projection failed: {exc}") from exc

        matches = [item for item in projection["sets"] if item["id"] == args["executionSetId"]]
        if len(matches) != 1:
            raise RoutedExecutionSetInvocationError(
                "executionSetId is stale or not present in the current routed plan"
            )
        execution_set = matches[0]
        if execution_set["state"] != "ready":
            raise RoutedExecutionSetInvocationError(
                f"execution set is not ready: {execution_set['reason']}"
            )

        scope = normalize_scope(execution_set["scope"], self.concepts)
        diagnosis = _find_diagnosis(
            snapshot,
            target=execution_set["diagnosis_target"],
            scope=scope,
        )
        ranking = diagnosis.get("probe_ranking", {})
        probes = ranking.get("probes", [])
        if ranking.get("found") is not True or not probes:
            raise RoutedExecutionSetInvocationError("current diagnosis has no top-ranked probe")
        probe_candidate = copy.deepcopy(probes[0])
        current_probe = probe_candidate.get("probe", {}).get("id")
        if current_probe != execution_set["probe_id"]:
            raise RoutedExecutionSetInvocationError(
                f"execution set probe is stale: current probe is {current_probe}"
            )

        evidence = load_runtime_evidence(self.runtime_evidence_path)
        if evidence["incident_id"] != args["incidentId"]:
            raise RoutedExecutionSetInvocationError("runtime evidence belongs to another incident")

        router = self.information_gain_router_provider()
        produced_documents: list[dict[str, Any]] = []
        member_results: list[dict[str, Any]] = []

        for member in execution_set["members"]:
            target_resource = member["target_resource"]
            expected_instrument = member["instrument"]["id"]
            try:
                decision = router.route(
                    probe_candidate,
                    scope,
                    target_resource=target_resource,
                    execution_requirement="direct",
                )
            except (OSError, ValueError) as exc:
                raise RoutedExecutionSetInvocationError(
                    f"member route failed for {target_resource}: {exc}"
                ) from exc
            selection = decision.get("selection")
            instrument = selection.get("instrument") if isinstance(selection, dict) else None
            if not isinstance(instrument, dict) or instrument.get("id") != expected_instrument:
                current = instrument.get("id") if isinstance(instrument, dict) else None
                raise RoutedExecutionSetInvocationError(
                    f"member route is stale for {target_resource}: current instrument is {current}"
                )

            try:
                produced = router.execute(
                    probe_candidate,
                    execution_set["diagnosis_target"],
                    scope,
                    target_resource=target_resource,
                )
            except (ProbeInsufficientEvidence, OSError, ValueError) as exc:
                raise RoutedExecutionSetInvocationError(
                    f"member execution failed for {target_resource}: {exc}"
                ) from exc

            if produced.get("incident_id") != args["incidentId"]:
                raise RoutedExecutionSetInvocationError(
                    f"member evidence belongs to another incident: {target_resource}"
                )
            instance_ids = sorted(
                instance["id"] for instance in produced.get("instances", []) if isinstance(instance, dict)
            )
            if not instance_ids:
                raise RoutedExecutionSetInvocationError(
                    f"member produced no canonical evidence: {target_resource}"
                )
            for instance in produced.get("instances", []):
                routing_target = (
                    instance.get("source", {})
                    .get("attributes", {})
                    .get("routing.target_resource")
                )
                if routing_target != target_resource:
                    raise RoutedExecutionSetInvocationError(
                        f"member evidence target provenance mismatch: {target_resource}"
                    )
            _bind_evidence_scope_to_target(
                produced,
                semantic_scope=scope,
                target_resource=target_resource,
            )
            produced_documents.append(produced)
            member_results.append(
                {
                    "ordinal": member["ordinal"],
                    "target_resource": target_resource,
                    "instrument_id": expected_instrument,
                    "produced_instance_ids": instance_ids,
                }
            )

        composed = compose_runtime_evidence([evidence, *produced_documents], self.concepts)
        old_ids = {instance["id"] for instance in evidence["instances"]}
        added_ids = sorted(
            instance["id"] for instance in composed["instances"] if instance["id"] not in old_ids
        )
        if not added_ids or canonical_hash(composed) == canonical_hash(evidence):
            raise RoutedExecutionSetInvocationError(
                "execution set produced no new canonical evidence"
            )

        produced_union = {
            instance_id
            for result in member_results
            for instance_id in result["produced_instance_ids"]
        }
        missing_contributions = sorted(produced_union - set(added_ids))
        if missing_contributions:
            raise RoutedExecutionSetInvocationError(
                "execution set contains evidence that would not contribute a new canonical instance"
            )

        next_revision = snapshot["evidence_revision"] + 1
        now = self.clock().astimezone(timezone.utc)
        next_snapshot = build_diagnosis_snapshot(
            composed,
            self.concepts,
            self.edges,
            as_of=now,
            evidence_revision=next_revision,
        )
        commit = prepare_commit(
            incident_id=args["incidentId"],
            from_evidence_revision=snapshot["evidence_revision"],
            runtime_evidence=composed,
            diagnosis_snapshot=next_snapshot,
        )
        commit_incident_state(
            commit_path=self.commit_path,
            runtime_evidence_path=self.runtime_evidence_path,
            snapshot_path=self.snapshot_path,
            commit=commit,
            fault_hook=self.commit_fault_hook,
        )

        return {
            "kind": "routed_execution_set_result",
            "incident_id": args["incidentId"],
            "execution_set_id": execution_set["id"],
            "previous_evidence_revision": snapshot["evidence_revision"],
            "evidence_revision": next_revision,
            "diagnosis_target": execution_set["diagnosis_target"],
            "probe_id": execution_set["probe_id"],
            "member_results": member_results,
            "added_instance_ids": added_ids,
            "rerank_count": 1,
            "diagnosis_generated_at": next_snapshot["generated_at"],
        }

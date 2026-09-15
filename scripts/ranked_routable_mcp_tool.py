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
from instrument_router import InstrumentRouter
from live_diagnosis import build_diagnosis_snapshot, normalize_scope, scope_key
from probe_filesystem_claim import (
    ProbeFilesystemClaimError,
    acquire_probe_filesystem_claim,
    incident_mutation_claim_identity,
)
from routable_probe_selection import select_highest_ranked_routable_probe
from runtime_evidence import load_runtime_evidence
from runtime_evidence_composition import compose_runtime_evidence

TOOL_NAME = "causcope.instrument.execute_ranked_routable"


class RankedRoutableInvocationError(ValueError):
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
        raise RankedRoutableInvocationError(
            f"expected exactly one current diagnosis for target {target} and selected scope, got {len(matches)}"
        )
    return matches[0]


class RankedRoutableInstrumentToolController:
    """Execute only the highest-ranked probe that has a current safe direct route."""

    def __init__(
        self,
        *,
        reader: DiagnosisSnapshotReader,
        snapshot_path: Path,
        runtime_evidence_path: Path,
        concepts: dict[str, dict[str, Any]],
        edges: list[dict[str, Any]],
        router_provider: Callable[[], InstrumentRouter],
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
        self.router_provider = router_provider
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
                "title": "Execute highest-ranked safely routable diagnostic probe",
                "description": (
                    "Execute only the server-selected highest-ranked semantically recommended read-only "
                    "probe that currently has a safe exact-scope direct route. Higher-ranked unroutable "
                    "probes remain higher-ranked in diagnosis and are not rewritten or treated as negative evidence."
                ),
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "incidentId",
                        "evidenceRevision",
                        "target",
                        "scope",
                        "probeId",
                        "instrumentId",
                    ],
                    "properties": {
                        "incidentId": {"type": "string", "minLength": 1},
                        "evidenceRevision": {"type": "integer", "minimum": 0},
                        "target": {"type": "string", "minLength": 1},
                        "scope": {"oneOf": [{"type": "null"}, {"type": "object"}]},
                        "probeId": {"type": "string", "minLength": 1},
                        "instrumentId": {"type": "string", "minLength": 1},
                    },
                },
            }
        ]

    def _validated_arguments(self, arguments: Any) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise RankedRoutableInvocationError("tool arguments must be an object")
        required = {
            "incidentId",
            "evidenceRevision",
            "target",
            "scope",
            "probeId",
            "instrumentId",
        }
        if set(arguments) != required:
            raise RankedRoutableInvocationError(
                "tool arguments must exactly match the ranked routable execution contract"
            )
        if not isinstance(arguments["evidenceRevision"], int) or arguments["evidenceRevision"] < 0:
            raise RankedRoutableInvocationError("evidenceRevision must be a non-negative integer")
        for field in ("incidentId", "target", "probeId", "instrumentId"):
            if not isinstance(arguments[field], str) or not arguments[field]:
                raise RankedRoutableInvocationError(f"{field} must be a non-empty string")
        if arguments["scope"] is not None and not isinstance(arguments["scope"], dict):
            raise RankedRoutableInvocationError("scope must be an object or null")
        return copy.deepcopy(arguments)

    def call(self, name: str, arguments: Any) -> dict[str, Any]:
        if name != TOOL_NAME:
            raise RankedRoutableInvocationError(f"unsupported ranked routable tool: {name}")
        args = self._validated_arguments(arguments)
        try:
            with acquire_probe_filesystem_claim(
                self.mutation_lock_dir,
                purpose="ranked_routable_instrument_mutation",
                identity=incident_mutation_claim_identity(incident_id=args["incidentId"]),
            ):
                return self._execute_locked(args)
        except (ProbeFilesystemClaimError, IncidentStateCommitError) as exc:
            raise RankedRoutableInvocationError(str(exc)) from exc

    def _execute_locked(self, args: dict[str, Any]) -> dict[str, Any]:
        recover_incident_state_commit(
            commit_path=self.commit_path,
            runtime_evidence_path=self.runtime_evidence_path,
            snapshot_path=self.snapshot_path,
        )
        snapshot, _etag = self.reader.read()
        if snapshot["incident_id"] != args["incidentId"]:
            raise RankedRoutableInvocationError("incidentId does not match current diagnosis")
        if snapshot["evidence_revision"] != args["evidenceRevision"]:
            raise RankedRoutableInvocationError(
                f"stale evidenceRevision: current diagnosis revision is {snapshot['evidence_revision']}"
            )

        scope = normalize_scope(args["scope"], self.concepts)
        diagnosis = _find_diagnosis(snapshot, target=args["target"], scope=scope)
        router = self.router_provider()
        selected = select_highest_ranked_routable_probe(
            diagnosis,
            router,
            scope,
            execution_requirement="direct",
        )
        if selected is None:
            raise RankedRoutableInvocationError(
                "current diagnosis has no semantically ranked probe with a safe direct route"
            )
        if selected["probe_id"] != args["probeId"]:
            raise RankedRoutableInvocationError(
                "probeId is stale or is not the highest-ranked currently routable probe: "
                f"current probe is {selected['probe_id']} at semantic rank {selected['probe_rank']}"
            )
        decision = selected["decision"]
        instrument = decision["selection"]["instrument"]
        if instrument.get("id") != args["instrumentId"]:
            raise RankedRoutableInvocationError(
                f"instrumentId is stale or not selected: current instrument is {instrument.get('id')}"
            )
        if instrument.get("execution_mode") != "direct":
            raise RankedRoutableInvocationError("selected instrument is not direct-execution capable")

        evidence = load_runtime_evidence(self.runtime_evidence_path)
        if evidence["incident_id"] != args["incidentId"]:
            raise RankedRoutableInvocationError("runtime evidence belongs to another incident")
        try:
            produced = router.execute(selected["probe_id"], args["target"], scope)
        except ProbeInsufficientEvidence as exc:
            raise RankedRoutableInvocationError(str(exc)) from exc

        composed = compose_runtime_evidence([evidence, produced], self.concepts)
        old_ids = {instance["id"] for instance in evidence["instances"]}
        added_ids = sorted(
            instance["id"] for instance in composed["instances"] if instance["id"] not in old_ids
        )
        if not added_ids or canonical_hash(composed) == canonical_hash(evidence):
            raise RankedRoutableInvocationError("routed instrument produced no new canonical evidence")

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
            "kind": "ranked_routable_instrument_execution_result",
            "incident_id": args["incidentId"],
            "previous_evidence_revision": snapshot["evidence_revision"],
            "evidence_revision": next_revision,
            "target": args["target"],
            "probe_id": selected["probe_id"],
            "probe_rank": selected["probe_rank"],
            "instrument": copy.deepcopy(instrument),
            "added_instance_ids": added_ids,
            "diagnosis_generated_at": next_snapshot["generated_at"],
        }

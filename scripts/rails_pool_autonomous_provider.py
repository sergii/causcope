#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from autonomous_investigation import ProbeInsufficientEvidence
from diagnosis_http_api import DiagnosisSnapshotReader
from live_diagnosis import normalize_scope, scope_key
from rails_pool_evidence_import import _exact_seed_instance, _identity, build_canonical_pool_evidence, validate_pool_document
from runtime_evidence import load_runtime_evidence

RAILS_POOL_PROVIDER_ID = "provider.rails.active_record_pool"
RAILS_POOL_INSTRUMENT = "rails_runtime_evidence"
RAILS_POOL_PROBE_ID = "probe.database.inspect_connection_pool"


class RailsPoolAutonomousProvider:
    """Expose one exact Rails pool experiment bundle behind a canonical read-only probe."""

    def __init__(self, *, pool_path: Path, runtime_evidence_path: Path, diagnosis_path: Path, concepts: dict[str, dict[str, Any]], incident_id: str, source_uri: str) -> None:
        if not incident_id:
            raise ValueError("Rails pool provider requires a non-empty incident_id")
        probe = concepts.get(RAILS_POOL_PROBE_ID)
        if not isinstance(probe, dict) or probe.get("kind") != "probe":
            raise ValueError(f"unknown canonical Rails pool probe: {RAILS_POOL_PROBE_ID}")
        if probe.get("risk") != "read_only":
            raise ValueError(f"Rails pool provider refuses non-read-only probe {RAILS_POOL_PROBE_ID}")
        self.pool_path = pool_path
        self.runtime_evidence_path = runtime_evidence_path
        self.diagnosis_path = diagnosis_path
        self.concepts = concepts
        self.incident_id = incident_id
        self.source_uri = source_uri

    @property
    def supported_probe_ids(self) -> set[str]:
        return {RAILS_POOL_PROBE_ID}

    def _load_pool(self) -> dict[str, Any]:
        document = json.loads(self.pool_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("Rails pool evidence must contain a JSON object")
        validate_pool_document(document)
        return document

    def _binding(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, dict[str, Any]]:
        pool = self._load_pool()
        existing = load_runtime_evidence(self.runtime_evidence_path)
        snapshot, _etag = DiagnosisSnapshotReader(self.diagnosis_path).read()
        if existing.get("incident_id") != self.incident_id or snapshot.get("incident_id") != self.incident_id:
            raise ValueError("Rails pool provider artifacts belong to another incident")
        seed = _exact_seed_instance(existing, pool)
        target_resource = _identity(seed, pool, self.incident_id)
        scope = normalize_scope(seed.get("scope"), self.concepts)
        return pool, existing, snapshot, target_resource, scope

    def _availability(self) -> dict[str, str | None]:
        for path in (self.pool_path, self.runtime_evidence_path, self.diagnosis_path):
            if not path.is_file():
                return {"state": "unavailable", "reason": f"required artifact does not exist: {path}"}
            if not os.access(path, os.R_OK):
                return {"state": "unavailable", "reason": f"required artifact is not readable: {path}"}
        try:
            self._binding()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {"state": "unavailable", "reason": str(exc)}
        return {"state": "available", "reason": None}

    def capability_projection(self) -> dict[str, Any]:
        availability = self._availability()
        scope: dict[str, Any] = {"attributes": {"provider_scope": "unresolved"}}
        if availability["state"] == "available":
            _pool, _existing, _snapshot, _target, scope = self._binding()
        probe = self.concepts[RAILS_POOL_PROBE_ID]
        return {
            "id": RAILS_POOL_PROVIDER_ID,
            "instrument": RAILS_POOL_INSTRUMENT,
            "transport": "workspace_file",
            "scope_mode": "fixed_exact",
            "scope": copy.deepcopy(scope),
            "availability": availability,
            "contract": {"name": "resource_pool_runtime_evidence", "accepted_schema_versions": ["0.1"]},
            "evidence_semantics": {
                "positive_findings_only": False,
                "missing_positive_finding": "insufficient_evidence",
                "suppressed_positive_finding": "insufficient_evidence",
                "provenance_preserved": True,
                "causal_authority": False,
            },
            "probes": [{
                "probe": {"id": RAILS_POOL_PROBE_ID, "title": probe.get("title", RAILS_POOL_PROBE_ID), "risk": "read_only"},
                "requires": sorted(item for item in probe.get("requires", []) if isinstance(item, str)),
                "mapped_observations": sorted(item for item in probe.get("produces", []) if isinstance(item, str)),
            }],
        }

    def execute(self, probe_id: str, target: str, scope: dict[str, Any] | None) -> dict[str, Any]:
        if probe_id != RAILS_POOL_PROBE_ID:
            raise ValueError(f"unsupported Rails pool autonomous probe: {probe_id}")
        pool, existing, snapshot, target_resource, expected_scope = self._binding()
        normalized_scope = normalize_scope(scope, self.concepts)
        if scope_key(normalized_scope) != scope_key(expected_scope):
            raise ProbeInsufficientEvidence("Rails pool evidence scope does not match the selected diagnosis scope")

        evidence = build_canonical_pool_evidence(pool, existing, snapshot)
        for instance in evidence.get("instances", []):
            source = instance.setdefault("source", {})
            attributes = source.setdefault("attributes", {})
            attributes["provider"] = RAILS_POOL_PROVIDER_ID
            attributes["instrument"] = RAILS_POOL_INSTRUMENT
            attributes["selected_semantic_probe"] = RAILS_POOL_PROBE_ID
            attributes["selected_diagnosis_target"] = target
            attributes["provider_bound_target_resource"] = target_resource
            if "uri" not in source:
                source["uri"] = self.source_uri
            labels = instance.setdefault("labels", {})
            labels["provider"] = RAILS_POOL_PROVIDER_ID
            labels["selected_semantic_probe"] = RAILS_POOL_PROBE_ID

        evidence["description"] = (
            "Causcope selected the canonical read-only ActiveRecord pool probe and the local Rails runtime "
            "provider supplied the already-captured, identity-bound experiment bundle. The selected probe "
            "authorizes inspection; linked control and recovery observations remain experiment evidence, not probe claims."
        )
        return evidence

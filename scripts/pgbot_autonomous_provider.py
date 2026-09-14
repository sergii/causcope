#!/usr/bin/env python3

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

from autonomous_investigation import ProbeInsufficientEvidence
from live_diagnosis import normalize_scope, scope_key
from pgbot_adapter import (
    build_runtime_evidence,
    build_scope,
    load_context,
    validate_adapter_references,
    validate_context_contract,
)

PGBOT_PROVIDER_ID = "provider.pgbot.postgresql"

# Mapping an external finding into the ontology does not grant execution
# permission. Every autonomous probe remains an explicit reviewed capability.
PGBOT_AUTONOMOUS_PROBE_ALLOWLIST = {
    "probe.database.inspect_lock_waits",
    "probe.database.measure_query_latency",
}

ContextSupplier = Callable[[], dict[str, Any]]


def file_context_supplier(path: Path) -> ContextSupplier:
    """Create a supplier for an already-produced pgbot JSON report."""

    def supply() -> dict[str, Any]:
        return load_context(path)

    return supply


class PgbotAutonomousProbeProvider:
    """Bind selected canonical read-only probes to deterministic pgbot findings."""

    def __init__(
        self,
        *,
        adapter: dict[str, Any],
        concepts: dict[str, dict[str, Any]],
        incident_id: str,
        context_supplier: ContextSupplier,
        source_uri: str = "pgbot://inspect",
        allowlist: set[str] | None = None,
    ) -> None:
        if not incident_id:
            raise ValueError("pgbot autonomous provider requires incident_id")
        validate_adapter_references(adapter, concepts)

        self.adapter = copy.deepcopy(adapter)
        self.concepts = concepts
        self.incident_id = incident_id
        self.context_supplier = context_supplier
        self.source_uri = source_uri
        self.allowlist = set(
            PGBOT_AUTONOMOUS_PROBE_ALLOWLIST if allowlist is None else allowlist
        )
        self.adapter_scope = normalize_scope(build_scope(self.adapter), self.concepts)
        self._supported_probe_ids = self._derive_supported_probe_ids()

        if not self._supported_probe_ids:
            raise ValueError("pgbot autonomous provider has no supported canonical probes")

    def _derive_supported_probe_ids(self) -> set[str]:
        mapped_observations = {
            mapping["observation"]
            for mapping in self.adapter.get("mappings", [])
            if isinstance(mapping, dict) and isinstance(mapping.get("observation"), str)
        }
        supported: set[str] = set()
        for probe_id in sorted(self.allowlist):
            probe = self.concepts.get(probe_id)
            if not isinstance(probe, dict) or probe.get("kind") != "probe":
                raise ValueError(f"pgbot allowlist references unknown probe: {probe_id}")
            if probe.get("risk") != "read_only":
                raise ValueError(
                    f"pgbot autonomous provider refuses non-read-only probe {probe_id}"
                )
            produced = {
                observation
                for observation in probe.get("produces", [])
                if isinstance(observation, str)
            }
            if produced & mapped_observations:
                supported.add(probe_id)
        return supported

    @property
    def supported_probe_ids(self) -> set[str]:
        return set(self._supported_probe_ids)

    def _relevant_mappings(self, probe_id: str) -> list[dict[str, Any]]:
        probe = self.concepts[probe_id]
        produced = {
            observation
            for observation in probe.get("produces", [])
            if isinstance(observation, str)
        }
        return [
            copy.deepcopy(mapping)
            for mapping in self.adapter.get("mappings", [])
            if isinstance(mapping, dict) and mapping.get("observation") in produced
        ]

    def _validate_scope(self, scope: dict[str, Any] | None) -> dict[str, Any]:
        normalized = normalize_scope(scope, self.concepts)
        if scope_key(normalized) != scope_key(self.adapter_scope):
            raise ProbeInsufficientEvidence(
                "pgbot provider scope does not match the selected diagnosis scope; "
                "provider will not widen, narrow, or relabel evidence heuristically"
            )
        return normalized

    def execute(
        self,
        probe_id: str,
        target: str,
        scope: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if probe_id not in self._supported_probe_ids:
            raise ValueError(f"unsupported pgbot autonomous probe: {probe_id}")

        normalized_scope = self._validate_scope(scope)
        context = self.context_supplier()
        validate_context_contract(self.adapter, context)

        relevant_mappings = self._relevant_mappings(probe_id)
        source_finding_ids = {
            mapping["source_finding"] for mapping in relevant_mappings
        }
        matching_findings = [
            copy.deepcopy(finding)
            for finding in context.get("findings", [])
            if isinstance(finding, dict) and finding.get("id") in source_finding_ids
        ]
        active_findings = [
            finding
            for finding in matching_findings
            if finding.get("suppressed") is not True
        ]

        if not active_findings:
            reason = (
                "pgbot produced only source-suppressed mapped findings"
                if matching_findings
                else "pgbot produced no mapped positive finding"
            )
            raise ProbeInsufficientEvidence(
                f"{reason} for {probe_id}; no finding is not converted to absent evidence"
            )

        filtered_adapter = copy.deepcopy(self.adapter)
        filtered_adapter["mappings"] = relevant_mappings
        filtered_context = copy.deepcopy(context)
        filtered_context["findings"] = active_findings
        evidence = build_runtime_evidence(
            filtered_adapter,
            filtered_context,
            self.concepts,
            incident_id=self.incident_id,
            source_uri=self.source_uri,
        )

        for instance in evidence["instances"]:
            original_source = instance["source"]
            attributes = {
                str(key): str(value)
                for key, value in original_source.get("attributes", {}).items()
            }
            attributes.update(
                {
                    "provider": PGBOT_PROVIDER_ID,
                    "instrument": "pgbot",
                    "pgbot.source_name": str(original_source.get("name", "")),
                    "pgbot.contract": str(context["schema_version"]),
                    "selected_target": target,
                }
            )
            instance["source"] = {
                "type": "probe",
                "name": probe_id,
                "uri": self.source_uri,
                "attributes": attributes,
            }
            instance["scope"] = copy.deepcopy(normalized_scope)
            labels = instance.setdefault("labels", {})
            labels["probe"] = probe_id
            labels["provider"] = PGBOT_PROVIDER_ID

            provider_note = (
                "Causcope selected this canonical read-only probe; pgbot supplied the "
                "deterministic PostgreSQL finding. The finding is evidence, not causal authority."
            )
            existing_note = instance.get("note")
            instance["note"] = (
                f"{existing_note} {provider_note}" if existing_note else provider_note
            )

        evidence["description"] = (
            f"Autonomous evidence for {probe_id} supplied by {PGBOT_PROVIDER_ID} "
            f"using pgbot contract {context['schema_version']}."
        )
        return evidence

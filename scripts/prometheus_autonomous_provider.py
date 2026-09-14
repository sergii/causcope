#!/usr/bin/env python3

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from urllib.request import Request, urlopen

from autonomous_investigation import ProbeInsufficientEvidence
from live_diagnosis import normalize_scope, scope_key
from prometheus_adapter import (
    build_runtime_evidence,
    build_scope,
    fetch_prometheus_response,
    validate_adapter_references,
)

PROMETHEUS_PROVIDER_ID = "provider.prometheus.metrics"
PROMETHEUS_TARGET_TOKEN = "{{target_resource}}"
DEFAULT_TARGET_LABEL = "causcope_resource"

# Autonomous execution remains explicitly reviewed even when an adapter maps
# more observations. Mapping telemetry is not itself execution authorization.
PROMETHEUS_AUTONOMOUS_PROBE_ALLOWLIST = {
    "probe.database.measure_query_latency",
}

QuerySupplier = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class FixturePrometheusQuerySupplier:
    """Supply deterministic Prometheus API responses without network access."""

    responses: dict[str, dict[str, Any]]

    def __call__(self, mapping: dict[str, Any]) -> dict[str, Any]:
        mapping_id = mapping["id"]
        if mapping_id not in self.responses:
            raise ValueError(f"missing Prometheus fixture response for mapping: {mapping_id}")
        return copy.deepcopy(self.responses[mapping_id])

    def availability(
        self,
        mapping_ids: set[str],
    ) -> tuple[bool, str | None]:
        missing = sorted(mapping_ids - set(self.responses))
        if missing:
            return False, "missing Prometheus fixture responses: " + ", ".join(missing)
        return True, None


@dataclass(frozen=True)
class HttpPrometheusQuerySupplier:
    """Execute read-only instant queries against one Prometheus HTTP endpoint."""

    base_url: str
    timeout_seconds: float = 10.0
    bearer_token: str | None = None
    at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.base_url:
            raise ValueError("Prometheus base_url must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("Prometheus timeout_seconds must be positive")

    def __call__(self, mapping: dict[str, Any]) -> dict[str, Any]:
        return fetch_prometheus_response(
            self.base_url,
            mapping["query"],
            at=self.at,
            timeout_seconds=self.timeout_seconds,
            bearer_token=self.bearer_token,
        )

    def availability(self, mapping_ids: set[str]) -> tuple[bool, str | None]:
        del mapping_ids
        request = Request(self.base_url.rstrip("/") + "/-/ready", headers={"Accept": "text/plain"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                status = getattr(response, "status", 200)
        except OSError as exc:
            return False, str(exc)
        if status < 200 or status >= 300:
            return False, f"Prometheus readiness endpoint returned HTTP {status}"
        return True, None


class PrometheusAutonomousProbeProvider:
    """Bind canonical read-only probes to one exact topology resource via Prometheus."""

    def __init__(
        self,
        *,
        adapter: dict[str, Any],
        concepts: dict[str, dict[str, Any]],
        target_resource: str,
        query_supplier: QuerySupplier,
        incident_id: str | None = None,
        source_uri: str = "prometheus://query",
        target_label: str = DEFAULT_TARGET_LABEL,
        allowlist: set[str] | None = None,
    ) -> None:
        if incident_id is not None and not incident_id:
            raise ValueError("Prometheus provider incident_id must not be empty")
        if not target_resource:
            raise ValueError("Prometheus provider target_resource must not be empty")
        if not target_label:
            raise ValueError("Prometheus provider target_label must not be empty")
        validate_adapter_references(adapter, concepts)

        self.adapter = copy.deepcopy(adapter)
        self.concepts = concepts
        self.target_resource = target_resource
        self.query_supplier = query_supplier
        self.incident_id = incident_id
        self.source_uri = source_uri
        self.target_label = target_label
        self.allowlist = set(
            PROMETHEUS_AUTONOMOUS_PROBE_ALLOWLIST if allowlist is None else allowlist
        )
        self.adapter_scope = self._derive_fixed_scope()
        self._supported_probe_ids = self._derive_supported_probe_ids()
        if not self._supported_probe_ids:
            raise ValueError("Prometheus autonomous provider has no supported canonical probes")
        self._validate_target_queries()

    def _derive_fixed_scope(self) -> dict[str, Any]:
        scopes: list[dict[str, Any] | None] = []
        for mapping in self.adapter.get("mappings", []):
            scope = mapping.get("scope")
            if not isinstance(scope, dict):
                raise ValueError(
                    f"Prometheus target-aware mapping {mapping.get('id')} must declare fixed scope"
                )
            if scope.get("entity_labels") or scope.get("boundary_labels") or scope.get("attribute_labels"):
                raise ValueError(
                    f"Prometheus target-aware mapping {mapping.get('id')} cannot use dynamic semantic scope labels"
                )
            scopes.append(normalize_scope(build_scope(mapping, {}, self.concepts), self.concepts))

        if not scopes or scopes[0] is None:
            raise ValueError("Prometheus target-aware provider requires a non-empty fixed scope")
        first = scopes[0]
        for current in scopes[1:]:
            if scope_key(current) != scope_key(first):
                raise ValueError("Prometheus target-aware mappings must share one exact semantic scope")
        return copy.deepcopy(first)

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
                raise ValueError(f"Prometheus allowlist references unknown probe: {probe_id}")
            if probe.get("risk") != "read_only":
                raise ValueError(
                    f"Prometheus autonomous provider refuses non-read-only probe {probe_id}"
                )
            produced = {
                observation
                for observation in probe.get("produces", [])
                if isinstance(observation, str)
            }
            if produced & mapped_observations:
                supported.add(probe_id)
        return supported

    def _validate_target_queries(self) -> None:
        relevant_ids = {
            mapping["id"]
            for probe_id in self._supported_probe_ids
            for mapping in self._relevant_mappings(probe_id)
        }
        for mapping in self.adapter.get("mappings", []):
            if mapping.get("id") not in relevant_ids:
                continue
            if PROMETHEUS_TARGET_TOKEN not in mapping["query"]:
                raise ValueError(
                    f"Prometheus target-aware mapping {mapping['id']} must include "
                    f"{PROMETHEUS_TARGET_TOKEN} in its query"
                )

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

    def _render_mapping(self, mapping: dict[str, Any]) -> dict[str, Any]:
        rendered = copy.deepcopy(mapping)
        rendered["query"] = rendered["query"].replace(
            PROMETHEUS_TARGET_TOKEN,
            self.target_resource,
        )
        return rendered

    def _availability(self) -> dict[str, str | None]:
        checker = getattr(self.query_supplier, "availability", None)
        if not callable(checker):
            return {
                "state": "unknown",
                "reason": (
                    "query supplier does not expose a non-invasive availability check; "
                    "discovery will not invoke an opaque supplier"
                ),
            }
        mapping_ids = {
            mapping["id"]
            for probe_id in self._supported_probe_ids
            for mapping in self._relevant_mappings(probe_id)
        }
        try:
            available, reason = checker(mapping_ids)
        except (OSError, ValueError) as exc:
            return {"state": "unavailable", "reason": str(exc)}
        if available:
            return {"state": "available", "reason": None}
        return {"state": "unavailable", "reason": reason or "Prometheus transport is unavailable"}

    def capability_projection(self) -> dict[str, Any]:
        probes: list[dict[str, Any]] = []
        for probe_id in sorted(self._supported_probe_ids):
            probe = self.concepts[probe_id]
            probes.append(
                {
                    "probe": {
                        "id": probe_id,
                        "title": probe.get("title", probe_id),
                        "risk": "read_only",
                    },
                    "requires": sorted(
                        capability
                        for capability in probe.get("requires", [])
                        if isinstance(capability, str)
                    ),
                    "mapped_observations": sorted(
                        {mapping["observation"] for mapping in self._relevant_mappings(probe_id)}
                    ),
                }
            )
        return {
            "id": PROMETHEUS_PROVIDER_ID,
            "instrument": "prometheus",
            "transport": "prometheus_http_query",
            "scope_mode": "fixed_exact",
            "scope": copy.deepcopy(self.adapter_scope),
            "availability": self._availability(),
            "contract": {
                "name": "prometheus_http_api",
                "accepted_schema_versions": ["v1"],
            },
            "evidence_semantics": {
                "positive_findings_only": False,
                "missing_positive_finding": "insufficient_evidence",
                "suppressed_positive_finding": "insufficient_evidence",
                "provenance_preserved": True,
                "causal_authority": False,
            },
            "probes": probes,
        }

    def _validate_scope(self, scope: dict[str, Any] | None) -> dict[str, Any]:
        normalized = normalize_scope(scope, self.concepts)
        if scope_key(normalized) != scope_key(self.adapter_scope):
            raise ProbeInsufficientEvidence(
                "Prometheus provider scope does not match the selected diagnosis scope; "
                "provider will not widen, narrow, or relabel evidence heuristically"
            )
        return normalized

    def _filter_exact_target_response(
        self,
        response: dict[str, Any],
        mapping_id: str,
    ) -> dict[str, Any]:
        if response.get("status") != "success":
            return copy.deepcopy(response)
        data = response.get("data")
        if not isinstance(data, dict) or data.get("resultType") != "vector":
            raise ProbeInsufficientEvidence(
                f"Prometheus target-aware mapping {mapping_id} requires vector results with "
                f"the {self.target_label} identity label"
            )
        result = data.get("result")
        if not isinstance(result, list):
            raise ValueError(f"{mapping_id}: Prometheus vector result must be a list")
        matches: list[dict[str, Any]] = []
        for item in result:
            metric = item.get("metric") if isinstance(item, dict) else None
            if isinstance(metric, dict) and metric.get(self.target_label) == self.target_resource:
                matches.append(copy.deepcopy(item))
        if not matches:
            raise ProbeInsufficientEvidence(
                f"Prometheus returned no sample with {self.target_label}={self.target_resource}; "
                "missing target series is not converted into absent evidence"
            )
        filtered = copy.deepcopy(response)
        filtered["data"]["result"] = matches
        return filtered

    def execute(
        self,
        probe_id: str,
        target: str,
        scope: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if self.incident_id is None:
            raise ValueError("Prometheus autonomous provider execution requires incident_id")
        if probe_id not in self._supported_probe_ids:
            raise ValueError(f"unsupported Prometheus autonomous probe: {probe_id}")

        normalized_scope = self._validate_scope(scope)
        rendered_mappings = [self._render_mapping(mapping) for mapping in self._relevant_mappings(probe_id)]
        responses: dict[str, dict[str, Any]] = {}
        for mapping in rendered_mappings:
            response = self.query_supplier(mapping)
            responses[mapping["id"]] = self._filter_exact_target_response(response, mapping["id"])

        filtered_adapter = copy.deepcopy(self.adapter)
        filtered_adapter["mappings"] = rendered_mappings
        evidence = build_runtime_evidence(
            filtered_adapter,
            responses,
            self.concepts,
            incident_id=self.incident_id,
            source_uri=self.source_uri,
        )

        for instance in evidence["instances"]:
            source = instance["source"]
            attributes = source.setdefault("attributes", {})
            attributes["provider"] = PROMETHEUS_PROVIDER_ID
            attributes["instrument"] = "prometheus"
            attributes["provider.target_resource"] = self.target_resource
            attributes["provider.target_label"] = self.target_label
            attributes["selected_target"] = target
            instance["scope"] = copy.deepcopy(normalized_scope)
            labels = instance.setdefault("labels", {})
            labels["probe"] = probe_id
            labels["provider"] = PROMETHEUS_PROVIDER_ID
            labels["target_resource"] = self.target_resource
            provider_note = (
                "Causcope selected this canonical read-only probe; Prometheus supplied an exact "
                "resource-labeled metric sample. The metric is evidence, not causal authority."
            )
            existing_note = instance.get("note")
            instance["note"] = f"{existing_note} {provider_note}" if existing_note else provider_note

        evidence["description"] = (
            f"Autonomous evidence for {probe_id} supplied by {PROMETHEUS_PROVIDER_ID} "
            f"for exact resource {self.target_resource}."
        )
        return evidence

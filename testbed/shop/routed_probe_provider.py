from __future__ import annotations

import copy
from typing import Any

from autonomous_investigation import ProbeInsufficientEvidence
from live_diagnosis import normalize_scope, scope_key
from read_only_probe_adapter import ShopStructuredLogProbeAdapter

SHOP_PROVIDER_ID = "provider.shop.structured_logs"


class ShopRoutedProbeProvider:
    """Expose the existing Shop read-only probe adapter through RoutedProvider."""

    def __init__(
        self,
        *,
        events: list[dict[str, Any]],
        incident_id: str,
        collected_at: str,
        concepts: dict[str, dict[str, Any]],
        scope: dict[str, Any],
        provider_id: str = SHOP_PROVIDER_ID,
    ) -> None:
        self.concepts = concepts
        self.provider_id = provider_id
        self.scope = normalize_scope(scope, concepts)
        if self.scope is None:
            raise ValueError("Shop routed provider requires an exact diagnosis scope")
        self.adapter = ShopStructuredLogProbeAdapter(
            events=events,
            incident_id=incident_id,
            collected_at=collected_at,
        )
        self._supported = self._supported_probe_ids()
        if not self._supported:
            raise ValueError("Shop routed provider has no canonical read-only probes")

    def _supported_probe_ids(self) -> set[str]:
        output: set[str] = set()
        for probe_id in sorted(self.adapter.supported_probe_ids):
            probe = self.concepts.get(probe_id)
            if not isinstance(probe, dict) or probe.get("kind") != "probe":
                raise ValueError(f"Shop provider references unknown probe: {probe_id}")
            if probe.get("risk") != "read_only":
                raise ValueError(f"Shop provider refuses non-read-only probe: {probe_id}")
            if probe.get("produces"):
                output.add(probe_id)
        return output

    def capability_projection(self) -> dict[str, Any]:
        probes: list[dict[str, Any]] = []
        for probe_id in sorted(self._supported):
            probe = self.concepts[probe_id]
            probes.append(
                {
                    "probe": {
                        "id": probe_id,
                        "title": probe.get("title", probe_id),
                        "risk": "read_only",
                    },
                    "requires": sorted(
                        item for item in probe.get("requires", []) if isinstance(item, str)
                    ),
                    "mapped_observations": sorted(
                        item for item in probe.get("produces", []) if isinstance(item, str)
                    ),
                }
            )
        return {
            "id": self.provider_id,
            "instrument": "shop_structured_logs",
            "transport": "captured_docker_compose_logs",
            "scope_mode": "fixed_exact",
            "scope": copy.deepcopy(self.scope),
            "availability": {"state": "available", "reason": None},
            "contract": {
                "name": "causcope_shop_structured_log_window",
                "accepted_schema_versions": ["0.1"],
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

    def execute(
        self,
        probe_id: str,
        target: str,
        scope: dict[str, Any] | None,
    ) -> dict[str, Any]:
        normalized = normalize_scope(scope, self.concepts)
        if scope_key(normalized) != scope_key(self.scope):
            raise ProbeInsufficientEvidence(
                "Shop routed provider scope does not match the selected diagnosis scope"
            )
        if probe_id not in self._supported:
            raise ValueError(f"unsupported Shop routed probe: {probe_id}")
        return self.adapter.execute(probe_id, target, normalized)

#!/usr/bin/env python3

from __future__ import annotations

import copy
import unittest
from pathlib import Path

from causal_projection import load_concepts
from information_gain_router import InformationGainInstrumentRouter
from instrument_router import InstrumentRouter
from pgbot_adapter import load_adapter as load_pgbot_adapter
from pgbot_autonomous_provider import PgbotAutonomousProbeProvider, file_context_supplier
from probe_executor_runtime import build_probe_execution_capabilities
from prometheus_adapter import load_adapter as load_prometheus_adapter, load_response_file
from prometheus_autonomous_provider import FixturePrometheusQuerySupplier, PrometheusAutonomousProbeProvider
from resource_topology import load_resource_topology

ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY_PATH = ROOT / "examples" / "topology" / "shop.yaml"
PGBOT_ADAPTER_PATH = ROOT / "examples" / "adapters" / "pgbot" / "postgresql.yaml"
PGBOT_REPORT_PATH = ROOT / "examples" / "telemetry" / "pgbot" / "postgresql-findings.json"
PROMETHEUS_ADAPTER_PATH = ROOT / "examples" / "adapters" / "prometheus" / "database-query-latency.yaml"
PROMETHEUS_RESPONSE_PATH = ROOT / "examples" / "telemetry" / "prometheus" / "database-query-latency.json"
PROBE_ID = "probe.database.measure_query_latency"
TARGET_RESOURCE = "db.orders.prod"
DIAGNOSIS_TARGET = "observation.database.query_latency"
PGBOT_INSTANCE = "provider.pgbot.orders-prod"
PROMETHEUS_INSTANCE = "provider.prometheus.orders-prod"
INCIDENT_ID = "incident.test.provider-information-gain"

PROBE_CANDIDATE = {
    "probe": {"id": PROBE_ID},
    "factors": {"top_candidate": "hypothesis.latency.database"},
    "outcome_analysis": [
        {
            "observation": "observation.database.query_latency",
            "observed_distinguishes_pairs": [
                [
                    "hypothesis.latency.database",
                    "hypothesis.database.connection_pool_exhaustion",
                ]
            ],
            "absent_distinguishes_pairs": [
                [
                    "hypothesis.latency.database",
                    "hypothesis.database.connection_pool_exhaustion",
                ]
            ],
        }
    ],
}


class InformationGainInstrumentRouterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.concepts = load_concepts(ROOT)
        cls.topology = load_resource_topology(TOPOLOGY_PATH)
        cls.pgbot_adapter = load_pgbot_adapter(PGBOT_ADAPTER_PATH)
        cls.prometheus_adapter = load_prometheus_adapter(PROMETHEUS_ADAPTER_PATH)
        cls.prometheus_response = load_response_file(PROMETHEUS_RESPONSE_PATH)

    def providers(self):
        pgbot = PgbotAutonomousProbeProvider(
            adapter=self.pgbot_adapter,
            concepts=self.concepts,
            context_supplier=file_context_supplier(PGBOT_REPORT_PATH),
            incident_id=INCIDENT_ID,
            source_uri="pgbot://test/provider-information-gain",
        )
        prometheus = PrometheusAutonomousProbeProvider(
            adapter=self.prometheus_adapter,
            concepts=self.concepts,
            target_resource=TARGET_RESOURCE,
            query_supplier=FixturePrometheusQuerySupplier(
                {"database_query_latency_p95": self.prometheus_response}
            ),
            incident_id=INCIDENT_ID,
            source_uri="prometheus://test/provider-information-gain",
        )
        return pgbot, prometheus

    def routers(self):
        pgbot, prometheus = self.providers()
        bindings = {
            PGBOT_INSTANCE: pgbot,
            PROMETHEUS_INSTANCE: prometheus,
        }
        base = InstrumentRouter(
            concepts=self.concepts,
            host_capabilities=build_probe_execution_capabilities(self.concepts),
            providers=[],
            resource_topology=self.topology,
            provider_instance_bindings=bindings,
        )
        information_aware = InformationGainInstrumentRouter(
            router=base,
            provider_instance_bindings=bindings,
        )
        return base, information_aware, pgbot

    def test_base_router_still_uses_stable_identity_tie_break(self) -> None:
        base, _, pgbot = self.routers()
        decision = base.route(
            PROBE_ID,
            copy.deepcopy(pgbot.adapter_scope),
            execution_requirement="direct",
            target_resource=TARGET_RESOURCE,
        )
        self.assertEqual(PGBOT_INSTANCE, decision["selection"]["instrument"]["id"])

    def test_information_gain_prefers_two_sided_prometheus_evidence(self) -> None:
        _, router, pgbot = self.routers()
        decision = router.route(
            PROBE_CANDIDATE,
            copy.deepcopy(pgbot.adapter_scope),
            target_resource=TARGET_RESOURCE,
            execution_requirement="direct",
        )
        self.assertEqual(
            PROMETHEUS_INSTANCE,
            decision["selection"]["instrument"]["id"],
        )
        by_id = {
            candidate["instrument"]["id"]: candidate
            for candidate in decision["provider_candidates"]
        }
        self.assertEqual(
            "positive_findings_only",
            by_id[PGBOT_INSTANCE]["information_gain_proxy"]["outcome_support"],
        )
        self.assertEqual(
            [],
            by_id[PGBOT_INSTANCE]["information_gain_proxy"]["absent_distinguishes_pairs"],
        )
        self.assertEqual(
            "observed_and_absent",
            by_id[PROMETHEUS_INSTANCE]["information_gain_proxy"]["outcome_support"],
        )
        self.assertEqual(
            1,
            len(
                by_id[PROMETHEUS_INSTANCE]["information_gain_proxy"][
                    "two_sided_candidate_pairs"
                ]
            ),
        )

    def test_execute_uses_selected_prometheus_provider_and_preserves_provenance(self) -> None:
        _, router, pgbot = self.routers()
        evidence = router.execute(
            PROBE_CANDIDATE,
            DIAGNOSIS_TARGET,
            copy.deepcopy(pgbot.adapter_scope),
            target_resource=TARGET_RESOURCE,
        )
        self.assertEqual(1, len(evidence["instances"]))
        instance = evidence["instances"][0]
        self.assertEqual(PROMETHEUS_INSTANCE, instance["labels"]["instrument"])
        self.assertEqual(240.0, instance["measurement"]["value"])
        attributes = instance["source"]["attributes"]
        self.assertEqual("information_gain_router.v0", attributes["routing.router"])
        self.assertEqual("instrument_router.v0", attributes["routing.base_router"])
        self.assertEqual(TARGET_RESOURCE, attributes["routing.target_resource"])
        self.assertEqual(
            "observability.prometheus.prod",
            attributes["routing.endpoint_resource"],
        )
        self.assertEqual(
            "safe_target_routes_then_information_gain_proxy",
            attributes["routing.selection_policy"],
        )

    def test_probe_candidate_requires_causal_outcome_analysis(self) -> None:
        _, router, pgbot = self.routers()
        broken = copy.deepcopy(PROBE_CANDIDATE)
        broken.pop("outcome_analysis")
        with self.assertRaisesRegex(ValueError, "outcome_analysis"):
            router.route(
                broken,
                copy.deepcopy(pgbot.adapter_scope),
                target_resource=TARGET_RESOURCE,
                execution_requirement="direct",
            )


if __name__ == "__main__":
    unittest.main()

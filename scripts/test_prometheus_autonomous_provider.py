#!/usr/bin/env python3

from __future__ import annotations

import copy
import unittest
from pathlib import Path

from autonomous_investigation import ProbeInsufficientEvidence
from causal_projection import load_concepts
from diagnostic_provider_capabilities import build_provider_capabilities
from instrument_router import InstrumentRouter
from probe_executor_runtime import build_probe_execution_capabilities
from prometheus_adapter import load_adapter, load_response_file
from prometheus_autonomous_provider import (
    PROMETHEUS_PROVIDER_ID,
    FixturePrometheusQuerySupplier,
    PrometheusAutonomousProbeProvider,
)
from resource_topology import load_resource_topology

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "examples" / "adapters" / "prometheus" / "database-query-latency.yaml"
RESPONSE_PATH = ROOT / "examples" / "telemetry" / "prometheus" / "database-query-latency.json"
TOPOLOGY_PATH = ROOT / "examples" / "topology" / "shop.yaml"
PROBE_ID = "probe.database.measure_query_latency"
DIAGNOSIS_TARGET = "observation.database.query_latency"
INCIDENT_ID = "incident.test.prometheus-target-provider"


class PrometheusAutonomousProviderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.concepts = load_concepts(ROOT)
        cls.adapter = load_adapter(ADAPTER_PATH)
        cls.response = load_response_file(RESPONSE_PATH)
        cls.topology = load_resource_topology(TOPOLOGY_PATH)

    def provider(self, target_resource: str) -> PrometheusAutonomousProbeProvider:
        return PrometheusAutonomousProbeProvider(
            adapter=self.adapter,
            concepts=self.concepts,
            target_resource=target_resource,
            query_supplier=FixturePrometheusQuerySupplier(
                {"database_query_latency_p95": self.response}
            ),
            incident_id=INCIDENT_ID,
            source_uri="prometheus://shop-prod",
        )

    def test_capability_projection_is_valid_and_read_only(self) -> None:
        provider = self.provider("db.orders.prod")
        document = build_provider_capabilities([provider])
        projection = document["providers"][0]
        self.assertEqual(PROMETHEUS_PROVIDER_ID, projection["id"])
        self.assertEqual("prometheus", projection["instrument"])
        self.assertEqual("available", projection["availability"]["state"])
        self.assertEqual(
            [PROBE_ID],
            [entry["probe"]["id"] for entry in projection["probes"]],
        )
        self.assertFalse(projection["evidence_semantics"]["positive_findings_only"])

    def test_orders_provider_renders_exact_target_and_uses_only_orders_sample(self) -> None:
        provider = self.provider("db.orders.prod")
        evidence = provider.execute(PROBE_ID, DIAGNOSIS_TARGET, provider.adapter_scope)
        self.assertEqual(1, len(evidence["instances"]))
        instance = evidence["instances"][0]
        self.assertEqual("observed", instance["state"])
        self.assertEqual(240.0, instance["measurement"]["value"])
        self.assertEqual("db.orders.prod", instance["labels"]["target_resource"])
        attributes = instance["source"]["attributes"]
        self.assertEqual("db.orders.prod", attributes["label.causcope_resource"])
        self.assertIn('causcope_resource="db.orders.prod"', attributes["prometheus.query"])
        self.assertNotIn("{{target_resource}}", attributes["prometheus.query"])

    def test_payments_provider_uses_only_payments_sample_and_can_emit_absence(self) -> None:
        provider = self.provider("db.payments.prod")
        evidence = provider.execute(PROBE_ID, DIAGNOSIS_TARGET, provider.adapter_scope)
        instance = evidence["instances"][0]
        self.assertEqual("absent", instance["state"])
        self.assertEqual(70.0, instance["measurement"]["value"])
        self.assertEqual("db.payments.prod", instance["source"]["attributes"]["label.causcope_resource"])

    def test_missing_exact_target_series_is_insufficient_not_absent(self) -> None:
        response = copy.deepcopy(self.response)
        response["data"]["result"] = [response["data"]["result"][1]]
        provider = PrometheusAutonomousProbeProvider(
            adapter=self.adapter,
            concepts=self.concepts,
            target_resource="db.orders.prod",
            query_supplier=FixturePrometheusQuerySupplier(
                {"database_query_latency_p95": response}
            ),
            incident_id=INCIDENT_ID,
        )
        with self.assertRaisesRegex(ProbeInsufficientEvidence, "no sample"):
            provider.execute(PROBE_ID, DIAGNOSIS_TARGET, provider.adapter_scope)

    def test_scalar_result_is_rejected_because_it_has_no_target_identity(self) -> None:
        scalar = {
            "status": "success",
            "data": {"resultType": "scalar", "result": [1789428600, "240"]},
        }
        provider = PrometheusAutonomousProbeProvider(
            adapter=self.adapter,
            concepts=self.concepts,
            target_resource="db.orders.prod",
            query_supplier=FixturePrometheusQuerySupplier(
                {"database_query_latency_p95": scalar}
            ),
            incident_id=INCIDENT_ID,
        )
        with self.assertRaisesRegex(ProbeInsufficientEvidence, "requires vector results"):
            provider.execute(PROBE_ID, DIAGNOSIS_TARGET, provider.adapter_scope)

    def test_scope_mismatch_fails_closed(self) -> None:
        provider = self.provider("db.orders.prod")
        wrong_scope = copy.deepcopy(provider.adapter_scope)
        wrong_scope["attributes"]["service"] = "billing-api"
        with self.assertRaisesRegex(ProbeInsufficientEvidence, "scope does not match"):
            provider.execute(PROBE_ID, DIAGNOSIS_TARGET, wrong_scope)

    def test_router_selects_exact_prometheus_instance_for_each_target(self) -> None:
        orders = self.provider("db.orders.prod")
        payments = self.provider("db.payments.prod")
        router = InstrumentRouter(
            concepts=self.concepts,
            host_capabilities=build_probe_execution_capabilities(self.concepts),
            providers=[],
            resource_topology=self.topology,
            provider_instance_bindings={
                "provider.prometheus.orders-prod": orders,
                "provider.prometheus.payments-prod": payments,
            },
        )

        orders_decision = router.route(
            PROBE_ID,
            orders.adapter_scope,
            execution_requirement="direct",
            target_resource="db.orders.prod",
        )
        instrument = orders_decision["selection"]["instrument"]
        self.assertEqual("provider.prometheus.orders-prod", instrument["id"])
        self.assertEqual("observability.prometheus.prod", instrument["endpoint_resource"])
        payment_candidate = next(
            candidate
            for candidate in orders_decision["candidates"]
            if candidate["instrument"]["id"] == "provider.prometheus.payments-prod"
        )
        self.assertEqual("mismatch", payment_candidate["target_match"])
        self.assertFalse(payment_candidate["eligible"])

        evidence = router.execute(
            PROBE_ID,
            DIAGNOSIS_TARGET,
            orders.adapter_scope,
            target_resource="db.orders.prod",
        )
        instance = evidence["instances"][0]
        self.assertEqual("provider.prometheus.orders-prod", instance["labels"]["instrument"])
        attributes = instance["source"]["attributes"]
        self.assertEqual("db.orders.prod", attributes["routing.target_resource"])
        self.assertEqual("observability.prometheus.prod", attributes["routing.endpoint_resource"])


if __name__ == "__main__":
    unittest.main()

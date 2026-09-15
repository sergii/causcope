#!/usr/bin/env python3

from __future__ import annotations

import copy
import unittest
from pathlib import Path

from causal_projection import load_concepts
from information_gain_router import InformationGainInstrumentRouter
from instrument_router import InstrumentRouter
from instrument_routing_projection import build_instrument_routing_projection
from pgbot_adapter import load_adapter as load_pgbot_adapter
from pgbot_autonomous_provider import PgbotAutonomousProbeProvider, file_context_supplier
from probe_executor_runtime import build_probe_execution_capabilities
from prometheus_adapter import load_adapter as load_prometheus_adapter, load_response_file
from prometheus_autonomous_provider import FixturePrometheusQuerySupplier, PrometheusAutonomousProbeProvider
from resource_topology import load_resource_topology
from runtime_target_resolution import build_runtime_target_resolution

ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY_PATH = ROOT / "examples" / "topology" / "shop.yaml"
PGBOT_ADAPTER_PATH = ROOT / "examples" / "adapters" / "pgbot" / "postgresql.yaml"
PGBOT_REPORT_PATH = ROOT / "examples" / "telemetry" / "pgbot" / "postgresql-findings.json"
PROMETHEUS_ADAPTER_PATH = ROOT / "examples" / "adapters" / "prometheus" / "database-query-latency.yaml"
PROMETHEUS_RESPONSE_PATH = ROOT / "examples" / "telemetry" / "prometheus" / "database-query-latency.json"

INCIDENT_ID = "incident.test.runtime-target-aware"
PROBE_ID = "probe.database.measure_query_latency"
DIAGNOSIS_TARGET = "observation.database.query_latency"
SCOPE = {
    "boundaries": ["boundary.application.database"],
    "attributes": {"service": "checkout-api", "dependency": "postgresql"},
}
PROBE_CANDIDATE = {
    "probe": {"id": PROBE_ID},
    "factors": {"top_candidate": "hypothesis.latency.database"},
    "outcome_analysis": [
        {
            "observation": DIAGNOSIS_TARGET,
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


class RuntimeTargetAwareInvestigationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.concepts = load_concepts(ROOT)
        cls.topology = load_resource_topology(TOPOLOGY_PATH)
        cls.pgbot_adapter = load_pgbot_adapter(PGBOT_ADAPTER_PATH)
        cls.prometheus_adapter = load_prometheus_adapter(PROMETHEUS_ADAPTER_PATH)
        cls.prometheus_response = load_response_file(PROMETHEUS_RESPONSE_PATH)

    def snapshot(self) -> dict:
        return {
            "schema_version": "0.1",
            "kind": "diagnosis_snapshot",
            "incident_id": INCIDENT_ID,
            "evidence_revision": 7,
            "partitions": [
                {
                    "scope": copy.deepcopy(SCOPE),
                    "active_instance_ids": ["evidence.opentelemetry.query.trace1"],
                    "diagnoses": [
                        {
                            "target": DIAGNOSIS_TARGET,
                            "probe_ranking": {
                                "found": True,
                                "probes": [copy.deepcopy(PROBE_CANDIDATE)],
                            },
                        }
                    ],
                }
            ],
        }

    def runtime_evidence(self) -> dict:
        return {
            "schema_version": "0.1",
            "kind": "runtime_evidence",
            "incident_id": INCIDENT_ID,
            "instances": [
                {
                    "id": "evidence.opentelemetry.query.trace1",
                    "observation": DIAGNOSIS_TARGET,
                    "state": "observed",
                    "source": {
                        "type": "trace",
                        "name": "opentelemetry:test",
                        "attributes": {
                            "otel.trace_id": "trace-1",
                            "otel.span_id": "span-query",
                        },
                    },
                }
            ],
        }

    def relationships(self) -> dict:
        return {
            "schema_version": "0.1",
            "kind": "runtime_resolved_relationships",
            "incident_id": INCIDENT_ID,
            "relationships": [
                {
                    "id": "runtime_relationship.opentelemetry.0000000000000001",
                    "subject_execution": "execution.opentelemetry.0000000000000001",
                    "relation": "used_resource",
                    "object_resource": "pool:active_record.primary",
                    "trace_id": "trace-1",
                },
                {
                    "id": "runtime_relationship.opentelemetry.0000000000000002",
                    "subject_execution": "execution.opentelemetry.0000000000000002",
                    "relation": "used_resource",
                    "object_resource": "pool:active_record.replica",
                    "trace_id": "trace-1",
                },
                {
                    "id": "runtime_relationship.opentelemetry.0000000000000003",
                    "subject_execution": "execution.opentelemetry.0000000000000003",
                    "relation": "used_resource",
                    "object_resource": "pool:active_record.primary",
                    "trace_id": "trace-other",
                },
            ],
        }

    def routers(self):
        pgbot = PgbotAutonomousProbeProvider(
            adapter=self.pgbot_adapter,
            concepts=self.concepts,
            context_supplier=file_context_supplier(PGBOT_REPORT_PATH),
            incident_id=INCIDENT_ID,
            source_uri="pgbot://test/runtime-target-aware",
        )
        orders_prometheus = PrometheusAutonomousProbeProvider(
            adapter=self.prometheus_adapter,
            concepts=self.concepts,
            target_resource="db.orders.prod",
            query_supplier=FixturePrometheusQuerySupplier(
                {"database_query_latency_p95": self.prometheus_response}
            ),
            incident_id=INCIDENT_ID,
            source_uri="prometheus://test/runtime-target-aware/orders",
        )
        payments_prometheus = PrometheusAutonomousProbeProvider(
            adapter=self.prometheus_adapter,
            concepts=self.concepts,
            target_resource="db.payments.prod",
            query_supplier=FixturePrometheusQuerySupplier(
                {"database_query_latency_p95": self.prometheus_response}
            ),
            incident_id=INCIDENT_ID,
            source_uri="prometheus://test/runtime-target-aware/payments",
        )
        bindings = {
            "provider.pgbot.orders-prod": pgbot,
            "provider.pgbot.payments-prod": pgbot,
            "provider.prometheus.orders-prod": orders_prometheus,
            "provider.prometheus.payments-prod": payments_prometheus,
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
        return base, information_aware

    def test_exact_trace_resolves_multi_target_set(self) -> None:
        resolution = build_runtime_target_resolution(
            self.snapshot(),
            self.runtime_evidence(),
            self.relationships(),
            self.topology,
        )
        self.assertEqual(1, len(resolution["resolutions"]))
        item = resolution["resolutions"][0]
        self.assertEqual("resolved", item["status"])
        self.assertEqual(["trace-1"], item["trace_ids"])
        self.assertEqual(
            ["db.orders.prod", "db.payments.prod"],
            sorted(binding["target_resource"] for binding in item["target_bindings"]),
        )
        relationship_ids = {
            relationship_id
            for binding in item["target_bindings"]
            for relationship_id in binding["relationship_ids"]
        }
        self.assertNotIn(
            "runtime_relationship.opentelemetry.0000000000000003",
            relationship_ids,
        )

    def test_routing_fans_out_and_uses_information_gain_per_target(self) -> None:
        resolution = build_runtime_target_resolution(
            self.snapshot(),
            self.runtime_evidence(),
            self.relationships(),
            self.topology,
        )
        base, information_aware = self.routers()
        projection = build_instrument_routing_projection(
            self.snapshot(),
            base,
            target_resolution=resolution,
            information_gain_router=information_aware,
        )
        self.assertEqual(2, len(projection["routes"]))
        routes = {route["target_resource"]: route for route in projection["routes"]}
        self.assertEqual(
            "provider.prometheus.orders-prod",
            routes["db.orders.prod"]["decision"]["selected_instrument"]["id"],
        )
        self.assertEqual(
            "provider.prometheus.payments-prod",
            routes["db.payments.prod"]["decision"]["selected_instrument"]["id"],
        )
        for route in routes.values():
            self.assertEqual("target_aware_information_gain", route["routing_strategy"])
            self.assertEqual("resolved", route["target_resolution"]["status"])
            self.assertEqual(1, len(route["target_resolution"]["supporting_relationship_ids"]))

    def test_selected_providers_execute_against_each_exact_target(self) -> None:
        _, information_aware = self.routers()
        orders = information_aware.execute(
            copy.deepcopy(PROBE_CANDIDATE),
            DIAGNOSIS_TARGET,
            copy.deepcopy(SCOPE),
            target_resource="db.orders.prod",
        )
        payments = information_aware.execute(
            copy.deepcopy(PROBE_CANDIDATE),
            DIAGNOSIS_TARGET,
            copy.deepcopy(SCOPE),
            target_resource="db.payments.prod",
        )
        self.assertEqual("observed", orders["instances"][0]["state"])
        self.assertEqual("absent", payments["instances"][0]["state"])
        self.assertEqual(
            "db.orders.prod",
            orders["instances"][0]["source"]["attributes"]["routing.target_resource"],
        )
        self.assertEqual(
            "db.payments.prod",
            payments["instances"][0]["source"]["attributes"]["routing.target_resource"],
        )

    def test_unbound_runtime_resource_stops_before_routing(self) -> None:
        relationships = self.relationships()
        relationships["relationships"][0]["object_resource"] = "pool:active_record.unknown"
        resolution = build_runtime_target_resolution(
            self.snapshot(),
            self.runtime_evidence(),
            relationships,
            self.topology,
        )
        item = resolution["resolutions"][0]
        self.assertEqual("unresolved", item["status"])
        self.assertEqual("runtime_resource_unbound", item["unresolved_reason"])
        self.assertEqual([], item["target_bindings"])

        base, information_aware = self.routers()
        projection = build_instrument_routing_projection(
            self.snapshot(),
            base,
            target_resolution=resolution,
            information_gain_router=information_aware,
        )
        self.assertEqual(1, len(projection["routes"]))
        route = projection["routes"][0]
        self.assertIsNone(route["target_resource"])
        self.assertIsNone(route["decision"]["selected_instrument"])
        self.assertEqual("stop", route["agent_action"]["kind"])
        self.assertIn("runtime_resource_unbound", route["decision"]["stop_reason"])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_plan import build_agent_plan
from causal_projection import load_concepts, load_edges
from diagnosis_http_api import DiagnosisSnapshotReader
from diagnosis_mcp_server import (
    CLIENT_CAPABILITIES_META_KEY,
    MODERN_PROTOCOL_VERSION,
    PROTOCOL_VERSION_META_KEY,
)
from information_gain_router import InformationGainInstrumentRouter
from instrument_router import InstrumentRouter
from instrument_routing_projection import build_instrument_routing_projection
from probe_executor_runtime import build_probe_execution_capabilities
from prometheus_adapter import load_adapter as load_prometheus_adapter, load_response_file
from prometheus_autonomous_provider import FixturePrometheusQuerySupplier, PrometheusAutonomousProbeProvider
from resource_topology import load_resource_topology
from routed_agent_plan import build_routed_agent_plan
from routed_execution_set_mcp_tool import (
    TOOL_NAME,
    RoutedExecutionSetInvocationError,
    RoutedExecutionSetToolController,
)
from routed_execution_sets import build_routed_execution_sets
from routing_mcp_server import ROUTED_AGENT_PLAN_URI, RoutingDiagnosisMcpServer
from runtime_evidence import load_runtime_evidence
from runtime_target_resolution import build_runtime_target_resolution

ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY_PATH = ROOT / "examples" / "topology" / "shop.yaml"
PROMETHEUS_ADAPTER_PATH = ROOT / "examples" / "adapters" / "prometheus" / "database-query-latency.yaml"
PROMETHEUS_RESPONSE_PATH = ROOT / "examples" / "telemetry" / "prometheus" / "database-query-latency.json"

INCIDENT_ID = "incident.test.multi-target-execution-set"
DIAGNOSIS_TARGET = "observation.database.query_latency"
PROBE_ID = "probe.database.measure_query_latency"
NOW = datetime(2026, 9, 14, 23, 31, 0, tzinfo=timezone.utc)
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


class MultiTargetExecutionSetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.concepts = load_concepts(ROOT)
        cls.edges = load_edges(ROOT)
        cls.topology = load_resource_topology(TOPOLOGY_PATH)
        cls.prometheus_adapter = load_prometheus_adapter(PROMETHEUS_ADAPTER_PATH)
        cls.prometheus_response = load_response_file(PROMETHEUS_RESPONSE_PATH)

    @staticmethod
    def modern_meta() -> dict:
        return {
            PROTOCOL_VERSION_META_KEY: MODERN_PROTOCOL_VERSION,
            CLIENT_CAPABILITIES_META_KEY: {},
        }

    def snapshot(self) -> dict:
        ranking = {
            "schema_version": "0.1",
            "kind": "causal_ranking",
            "query": {
                "target": DIAGNOSIS_TARGET,
                "observed": [DIAGNOSIS_TARGET],
                "absent": [],
                "max_depth": None,
            },
            "found": True,
            "ranking_method": {},
            "candidates": [
                {
                    "rank": 1,
                    "source": {"id": "hypothesis.latency.database"},
                    "path": [],
                    "factors": {},
                    "reasons": [],
                },
                {
                    "rank": 2,
                    "source": {"id": "hypothesis.database.connection_pool_exhaustion"},
                    "path": [],
                    "factors": {},
                    "reasons": [],
                },
            ],
        }
        probe_ranking = {
            "schema_version": "0.1",
            "kind": "probe_ranking",
            "query": {"target": DIAGNOSIS_TARGET},
            "found": True,
            "not_found_reason": None,
            "ranking_method": {},
            "probes": [copy.deepcopy(PROBE_CANDIDATE)],
        }
        probe_execution = {
            "schema_version": "0.1",
            "kind": "probe_execution_annotation",
            "affects_ranking": False,
            "platform": "test",
            "probe_id": PROBE_ID,
            "registered": False,
            "executable_here": False,
            "unavailable_reason": "host executor is intentionally absent in this provider-routing proof",
            "executor": None,
            "capability": None,
            "observation": DIAGNOSIS_TARGET,
            "source": "test",
            "policy": {},
        }
        return {
            "schema_version": "0.1",
            "kind": "diagnosis_snapshot",
            "incident_id": INCIDENT_ID,
            "generated_at": "2026-09-14T23:31:00Z",
            "as_of": "2026-09-14T23:31:00Z",
            "evidence_revision": 7,
            "next_recompute_at": None,
            "partitions": [
                {
                    "scope": copy.deepcopy(SCOPE),
                    "observed": [DIAGNOSIS_TARGET],
                    "absent": [],
                    "active_instance_ids": ["evidence.opentelemetry.query.trace1"],
                    "stale_instance_ids": [],
                    "future_instance_ids": [],
                    "diagnoses": [
                        {
                            "target": DIAGNOSIS_TARGET,
                            "ranking": ranking,
                            "probe_ranking": probe_ranking,
                            "probe_execution": probe_execution,
                        }
                    ],
                    "unranked_observations": [],
                }
            ],
        }

    def runtime_evidence(self) -> dict:
        return {
            "schema_version": "0.1",
            "kind": "runtime_evidence",
            "incident_id": INCIDENT_ID,
            "description": "Trace-backed latency evidence before bounded target fan-out.",
            "instances": [
                {
                    "id": "evidence.opentelemetry.query.trace1",
                    "observation": DIAGNOSIS_TARGET,
                    "state": "observed",
                    "observed_at": "2026-09-14T23:30:30Z",
                    "confidence": "high",
                    "source": {
                        "type": "trace",
                        "name": "opentelemetry:test",
                        "attributes": {
                            "otel.trace_id": "trace-1",
                            "otel.span_id": "span-query",
                        },
                    },
                    "scope": copy.deepcopy(SCOPE),
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
            ],
        }

    def routers(self, *, fail_payments: bool = False):
        orders_response = copy.deepcopy(self.prometheus_response)
        payments_response = copy.deepcopy(self.prometheus_response)
        if fail_payments:
            payments_response["data"]["result"] = [
                item
                for item in payments_response["data"]["result"]
                if item["metric"].get("causcope_resource") == "db.orders.prod"
            ]

        orders = PrometheusAutonomousProbeProvider(
            adapter=self.prometheus_adapter,
            concepts=self.concepts,
            target_resource="db.orders.prod",
            query_supplier=FixturePrometheusQuerySupplier(
                {"database_query_latency_p95": orders_response}
            ),
            incident_id=INCIDENT_ID,
            source_uri="prometheus://test/execution-set/orders",
        )
        payments = PrometheusAutonomousProbeProvider(
            adapter=self.prometheus_adapter,
            concepts=self.concepts,
            target_resource="db.payments.prod",
            query_supplier=FixturePrometheusQuerySupplier(
                {"database_query_latency_p95": payments_response}
            ),
            incident_id=INCIDENT_ID,
            source_uri="prometheus://test/execution-set/payments",
        )
        bindings = {
            "provider.prometheus.orders-prod": orders,
            "provider.prometheus.payments-prod": payments,
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

    def setup_runtime(self, directory: str, *, fail_payments: bool = False):
        root = Path(directory)
        snapshot_path = root / "diagnosis.json"
        evidence_path = root / "runtime-evidence.json"
        lock_dir = root / "locks"
        snapshot = self.snapshot()
        evidence = self.runtime_evidence()
        relationships = self.relationships()
        snapshot_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        reader = DiagnosisSnapshotReader(snapshot_path)

        def routing_provider(current_snapshot: dict) -> dict:
            current_evidence = load_runtime_evidence(evidence_path)
            resolution = build_runtime_target_resolution(
                current_snapshot,
                current_evidence,
                relationships,
                self.topology,
            )
            base, information_aware = self.routers(fail_payments=fail_payments)
            return build_instrument_routing_projection(
                current_snapshot,
                base,
                external_mcp_execution_enabled=True,
                target_resolution=resolution,
                information_gain_router=information_aware,
            )

        def base_router_provider() -> InstrumentRouter:
            return self.routers(fail_payments=fail_payments)[0]

        def information_router_provider() -> InformationGainInstrumentRouter:
            return self.routers(fail_payments=fail_payments)[1]

        controller = RoutedExecutionSetToolController(
            reader=reader,
            snapshot_path=snapshot_path,
            runtime_evidence_path=evidence_path,
            concepts=self.concepts,
            edges=self.edges,
            routing_projection_provider=routing_provider,
            information_gain_router_provider=information_router_provider,
            mutation_lock_dir=lock_dir,
            clock=lambda: NOW,
        )
        return (
            snapshot,
            evidence,
            snapshot_path,
            evidence_path,
            reader,
            routing_provider,
            base_router_provider,
            controller,
        )

    def test_routed_agent_plan_exposes_one_two_member_execution_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot, _evidence, _snapshot_path, _evidence_path, _reader, routing_provider, base_router_provider, _controller = self.setup_runtime(directory)
            routing = routing_provider(snapshot)
            projection = build_routed_execution_sets(routing)
            self.assertEqual(1, len(projection["sets"]))
            execution_set = projection["sets"][0]
            self.assertEqual("ready", execution_set["state"])
            self.assertEqual(TOOL_NAME, execution_set["operation"])
            self.assertEqual(
                ["db.orders.prod", "db.payments.prod"],
                [member["target_resource"] for member in execution_set["members"]],
            )
            self.assertTrue(execution_set["atomic_evidence_commit"])
            self.assertEqual("after_all_members", execution_set["rerank_policy"])

            base_plan = build_agent_plan(
                snapshot,
                active_execution_enabled=False,
                active_sessions=[],
            )
            routed_plan = build_routed_agent_plan(
                snapshot,
                base_plan,
                base_router_provider(),
                external_mcp_execution_enabled=True,
                routing_projection=routing,
            )
            self.assertEqual([execution_set], routed_plan["execution_sets"])

    def test_one_mcp_call_commits_two_targets_as_one_revision_and_one_rerank(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot, _evidence, snapshot_path, evidence_path, reader, routing_provider, base_router_provider, controller = self.setup_runtime(directory)
            server = RoutingDiagnosisMcpServer(
                reader,
                instrument_router_provider=base_router_provider,
                probe_capability_provider=lambda: build_probe_execution_capabilities(self.concepts),
                routed_tools=controller,
                routing_projection_provider=routing_provider,
            )

            resource = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "resources/read",
                    "params": {"uri": ROUTED_AGENT_PLAN_URI, "_meta": self.modern_meta()},
                }
            )
            plan = json.loads(resource["result"]["contents"][0]["text"])
            self.assertEqual(1, len(plan["execution_sets"]))
            execution_set = plan["execution_sets"][0]
            self.assertEqual(2, len(execution_set["members"]))

            tools = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {"_meta": self.modern_meta()},
                }
            )
            self.assertEqual([TOOL_NAME], [tool["name"] for tool in tools["result"]["tools"]])

            called = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": TOOL_NAME,
                        "arguments": execution_set["arguments"],
                        "_meta": self.modern_meta(),
                    },
                }
            )
            self.assertFalse(called["result"]["isError"])
            result = called["result"]["structuredContent"]
            self.assertEqual(7, result["previous_evidence_revision"])
            self.assertEqual(8, result["evidence_revision"])
            self.assertEqual(1, result["rerank_count"])
            self.assertEqual(2, len(result["member_results"]))
            self.assertEqual(
                ["db.orders.prod", "db.payments.prod"],
                [item["target_resource"] for item in result["member_results"]],
            )

            committed_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(8, committed_snapshot["evidence_revision"])
            committed_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            routed_targets = {
                instance.get("source", {}).get("attributes", {}).get("routing.target_resource")
                for instance in committed_evidence["instances"]
            }
            self.assertIn("db.orders.prod", routed_targets)
            self.assertIn("db.payments.prod", routed_targets)

            stale = controller.call
            with self.assertRaisesRegex(RoutedExecutionSetInvocationError, "stale evidenceRevision"):
                stale(TOOL_NAME, execution_set["arguments"])

    def test_second_member_failure_commits_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot, _evidence, snapshot_path, evidence_path, _reader, routing_provider, _base_router_provider, controller = self.setup_runtime(
                directory,
                fail_payments=True,
            )
            execution_set = build_routed_execution_sets(routing_provider(snapshot))["sets"][0]
            before_snapshot = snapshot_path.read_text(encoding="utf-8")
            before_evidence = evidence_path.read_text(encoding="utf-8")

            with self.assertRaisesRegex(
                RoutedExecutionSetInvocationError,
                "member execution failed for db.payments.prod",
            ):
                controller.call(TOOL_NAME, execution_set["arguments"])

            self.assertEqual(before_snapshot, snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(before_evidence, evidence_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

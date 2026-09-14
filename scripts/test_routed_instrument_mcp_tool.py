#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from causal_projection import load_concepts, load_edges
from diagnosis_http_api import DiagnosisSnapshotReader
from instrument_router import InstrumentRouter
from live_diagnosis import build_diagnosis_snapshot, normalize_scope, scope_key
from pgbot_adapter import load_adapter
from pgbot_autonomous_provider import PgbotAutonomousProbeProvider, file_context_supplier
from probe_executor_runtime import build_probe_execution_capabilities
from routed_instrument_mcp_tool import (
    TOOL_NAME,
    RoutedInstrumentInvocationError,
    RoutedInstrumentToolController,
)
from routing_mcp_server import RoutingDiagnosisMcpServer
from diagnosis_mcp_server import (
    CLIENT_CAPABILITIES_META_KEY,
    MODERN_PROTOCOL_VERSION,
    PROTOCOL_VERSION_META_KEY,
)

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "examples" / "adapters" / "pgbot" / "postgresql.yaml"
REPORT_PATH = ROOT / "examples" / "telemetry" / "pgbot" / "postgresql-findings.json"
INCIDENT_ID = "incident.test.routed-mcp"
TARGET = "observation.http.request_failure"
PROBE = "probe.database.inspect_lock_waits"
INSTRUMENT = "provider.pgbot.postgresql"
NOW = datetime(2026, 9, 14, 10, 15, tzinfo=timezone.utc)


class RoutedInstrumentMcpToolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.concepts = load_concepts(ROOT)
        cls.edges = load_edges(ROOT)
        cls.adapter = load_adapter(ADAPTER_PATH)

    @staticmethod
    def modern_meta() -> dict:
        return {
            PROTOCOL_VERSION_META_KEY: MODERN_PROTOCOL_VERSION,
            CLIENT_CAPABILITIES_META_KEY: {},
        }

    def setup_runtime(self, directory: str):
        root = Path(directory)
        snapshot_path = root / "diagnosis.json"
        evidence_path = root / "runtime-evidence.json"
        lock_dir = root / "locks"

        provider = PgbotAutonomousProbeProvider(
            adapter=self.adapter,
            concepts=self.concepts,
            incident_id=INCIDENT_ID,
            context_supplier=file_context_supplier(REPORT_PATH),
            source_uri="pgbot://test/routed-mcp",
        )
        scope = copy.deepcopy(provider.adapter_scope)
        evidence = {
            "schema_version": "0.1",
            "kind": "runtime_evidence",
            "incident_id": INCIDENT_ID,
            "description": "Initial symptom before routed MCP execution.",
            "instances": [
                {
                    "id": "evidence.routed-mcp.request-failure",
                    "observation": TARGET,
                    "state": "observed",
                    "observed_at": "2026-09-14T10:14:50Z",
                    "confidence": "high",
                    "source": {"type": "manual", "name": "incident-report"},
                    "scope": scope,
                }
            ],
        }
        snapshot = build_diagnosis_snapshot(
            evidence,
            self.concepts,
            self.edges,
            as_of=NOW,
            evidence_revision=1,
        )
        evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        snapshot_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        reader = DiagnosisSnapshotReader(snapshot_path)

        def router_provider() -> InstrumentRouter:
            fresh_provider = PgbotAutonomousProbeProvider(
                adapter=self.adapter,
                concepts=self.concepts,
                incident_id=INCIDENT_ID,
                context_supplier=file_context_supplier(REPORT_PATH),
                source_uri="pgbot://test/routed-mcp",
            )
            return InstrumentRouter(
                concepts=self.concepts,
                host_capabilities=build_probe_execution_capabilities(self.concepts),
                providers=[fresh_provider],
            )

        controller = RoutedInstrumentToolController(
            reader=reader,
            snapshot_path=snapshot_path,
            runtime_evidence_path=evidence_path,
            concepts=self.concepts,
            edges=self.edges,
            router_provider=router_provider,
            mutation_lock_dir=lock_dir,
            clock=lambda: NOW,
        )
        return snapshot, scope, snapshot_path, evidence_path, reader, router_provider, controller

    def arguments(self, scope: dict, *, revision: int = 1, probe: str = PROBE, instrument: str = INSTRUMENT) -> dict:
        return {
            "incidentId": INCIDENT_ID,
            "evidenceRevision": revision,
            "target": TARGET,
            "scope": copy.deepcopy(scope),
            "probeId": probe,
            "instrumentId": instrument,
        }

    def test_exact_current_route_appends_evidence_and_advances_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _snapshot, scope, snapshot_path, evidence_path, _reader, _router_provider, controller = self.setup_runtime(directory)
            result = controller.call(TOOL_NAME, self.arguments(scope))

            self.assertEqual(1, result["previous_evidence_revision"])
            self.assertEqual(2, result["evidence_revision"])
            self.assertEqual(PROBE, result["probe_id"])
            self.assertEqual(INSTRUMENT, result["instrument"]["id"])
            self.assertTrue(result["added_instance_ids"])

            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertTrue(
                any(instance["observation"] == "observation.database.lock_wait_time" for instance in evidence["instances"])
            )
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(2, snapshot["evidence_revision"])
            wanted = scope_key(normalize_scope(scope, self.concepts))
            diagnosis = next(
                diagnosis
                for partition in snapshot["partitions"]
                if scope_key(partition.get("scope")) == wanted
                for diagnosis in partition["diagnoses"]
                if diagnosis["target"] == TARGET
            )
            candidate_ids = {
                candidate["source"]["id"] for candidate in diagnosis["ranking"]["candidates"]
            }
            self.assertIn("hypothesis.database.lock_contention", candidate_ids)
            observed = {
                observation
                for partition in snapshot["partitions"]
                for observation in partition["observed"]
            }
            self.assertIn("observation.database.lock_wait_time", observed)

    def test_stale_revision_and_stale_route_fail_closed_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _snapshot, scope, snapshot_path, evidence_path, _reader, _router_provider, controller = self.setup_runtime(directory)
            before_evidence = evidence_path.read_text(encoding="utf-8")
            before_snapshot = snapshot_path.read_text(encoding="utf-8")

            with self.assertRaisesRegex(RoutedInstrumentInvocationError, "stale evidenceRevision"):
                controller.call(TOOL_NAME, self.arguments(scope, revision=0))
            with self.assertRaisesRegex(RoutedInstrumentInvocationError, "not top-ranked"):
                controller.call(TOOL_NAME, self.arguments(scope, probe="probe.database.measure_query_latency"))
            with self.assertRaisesRegex(RoutedInstrumentInvocationError, "instrumentId is stale"):
                controller.call(TOOL_NAME, self.arguments(scope, instrument="provider.fake"))

            self.assertEqual(before_evidence, evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(before_snapshot, snapshot_path.read_text(encoding="utf-8"))

    def test_mcp_advertises_execution_only_when_tool_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _snapshot, scope, _snapshot_path, _evidence_path, reader, router_provider, controller = self.setup_runtime(directory)
            server = RoutingDiagnosisMcpServer(
                reader,
                instrument_router_provider=router_provider,
                probe_capability_provider=lambda: build_probe_execution_capabilities(self.concepts),
                routed_tools=controller,
            )
            routed = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "resources/read",
                    "params": {
                        "uri": "causcope://diagnosis/instrument-routing",
                        "_meta": self.modern_meta(),
                    },
                }
            )
            document = json.loads(routed["result"]["contents"][0]["text"])
            route = next(item for item in document["routes"] if item["probe_id"] == PROBE)
            self.assertTrue(route["agent_action"]["mcp_execution_available"])

            tools = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {"_meta": self.modern_meta()},
                }
            )
            self.assertEqual(TOOL_NAME, tools["result"]["tools"][0]["name"])

            called = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": TOOL_NAME,
                        "arguments": self.arguments(scope),
                        "_meta": self.modern_meta(),
                    },
                }
            )
            self.assertFalse(called["result"]["isError"])
            self.assertEqual(2, called["result"]["structuredContent"]["evidence_revision"])


if __name__ == "__main__":
    unittest.main()

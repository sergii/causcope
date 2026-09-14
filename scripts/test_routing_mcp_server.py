#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml

from causal_projection import load_concepts, load_edges
from diagnosis_http_api import DiagnosisSnapshotReader
from diagnosis_mcp_server import (
    CLIENT_CAPABILITIES_META_KEY,
    MODERN_PROTOCOL_VERSION,
    PROTOCOL_VERSION_META_KEY,
)
from live_diagnosis import build_diagnosis_snapshot
from routing_mcp_server import (
    INSTRUMENT_ROUTING_URI,
    ROUTED_AGENT_PLAN_URI,
    RoutingDiagnosisMcpServer,
)

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "examples" / "runtime-evidence" / "network-corruption-chain.yaml"
AS_OF = datetime(2026, 9, 11, 14, 48, tzinfo=timezone.utc)
TARGET = "observation.network.tcp_retransmissions"


class FakeRouter:
    def route(self, probe_id: str, scope: dict | None, *, execution_requirement: str = "any") -> dict:
        return {
            "schema_version": "0.1",
            "kind": "instrument_routing_decision",
            "probe": {"id": probe_id, "title": probe_id, "risk": "read_only"},
            "scope": copy.deepcopy(scope),
            "execution_requirement": execution_requirement,
            "selection_policy": "safe_exact_scope_then_stable_identity",
            "candidates": [],
            "selection": {
                "instrument": {
                    "id": "provider.test.external",
                    "kind": "diagnostic_provider",
                    "execution_mode": "direct",
                },
                "reason": "test exact-scope external provider selected",
            },
            "stop_reason": None,
        }


class RoutingMcpServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.concepts = load_concepts(ROOT)
        cls.edges = load_edges(ROOT)
        with EVIDENCE_PATH.open("r", encoding="utf-8") as handle:
            evidence = yaml.safe_load(handle)
        cls.evidence = copy.deepcopy(evidence)
        cls.evidence["instances"] = [
            instance
            for instance in cls.evidence["instances"]
            if instance["observation"] == TARGET
        ]

    def snapshot(self) -> dict:
        return build_diagnosis_snapshot(
            copy.deepcopy(self.evidence),
            self.concepts,
            self.edges,
            as_of=AS_OF,
            evidence_revision=11,
        )

    @staticmethod
    def meta() -> dict:
        return {
            PROTOCOL_VERSION_META_KEY: MODERN_PROTOCOL_VERSION,
            CLIENT_CAPABILITIES_META_KEY: {},
        }

    def read(self, server: RoutingDiagnosisMcpServer, uri: str) -> dict:
        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "resources/read",
                "params": {"uri": uri, "_meta": self.meta()},
            }
        )
        self.assertNotIn("error", response)
        return json.loads(response["result"]["contents"][0]["text"])

    def test_routing_projection_and_routed_agent_plan_share_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diagnosis.json"
            path.write_text(json.dumps(self.snapshot()), encoding="utf-8")
            server = RoutingDiagnosisMcpServer(
                DiagnosisSnapshotReader(path),
                instrument_router_provider=FakeRouter,
            )

            routing = self.read(server, INSTRUMENT_ROUTING_URI)
            routed_plan = self.read(server, ROUTED_AGENT_PLAN_URI)

            self.assertEqual("instrument_routing_projection", routing["kind"])
            self.assertEqual("routed_agent_plan", routed_plan["kind"])
            self.assertEqual(11, routing["evidence_revision"])
            self.assertEqual(11, routed_plan["evidence_revision"])
            self.assertEqual(routing, routed_plan["routing"])
            self.assertEqual("agent_plan", routed_plan["plan"]["kind"])

            route = next(item for item in routing["routes"] if item["target"] == TARGET)
            self.assertEqual(
                "provider.test.external",
                route["decision"]["selected_instrument"]["id"],
            )
            self.assertEqual("use_external_instrument", route["agent_action"]["kind"])
            self.assertFalse(route["agent_action"]["mcp_execution_available"])

    def test_resource_list_exposes_routing_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diagnosis.json"
            path.write_text(json.dumps(self.snapshot()), encoding="utf-8")
            server = RoutingDiagnosisMcpServer(
                DiagnosisSnapshotReader(path),
                instrument_router_provider=FakeRouter,
            )
            descriptors = server._resource_descriptors(modern=True)
            uris = {item["uri"] for item in descriptors}
            self.assertIn(INSTRUMENT_ROUTING_URI, uris)
            self.assertIn(ROUTED_AGENT_PLAN_URI, uris)


if __name__ == "__main__":
    unittest.main()

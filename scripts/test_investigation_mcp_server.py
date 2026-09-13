#!/usr/bin/env python3

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from diagnosis_http_api import DiagnosisSnapshotReader
from diagnosis_mcp_server import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    MODERN_PROTOCOL_VERSION,
    PROTOCOL_VERSION_META_KEY,
)
from investigation_mcp_server import (
    INCIDENT_CONTEXT_URI,
    INCIDENT_SCOPING_URI,
    InvestigationMcpServer,
)
from scoping_projection import ROOT, load_incident_context


class InvestigationMcpServerTest(unittest.TestCase):
    @staticmethod
    def modern_meta() -> dict:
        return {
            PROTOCOL_VERSION_META_KEY: MODERN_PROTOCOL_VERSION,
            CLIENT_CAPABILITIES_META_KEY: {},
            CLIENT_INFO_META_KEY: {"name": "investigation-test", "version": "1.0.0"},
        }

    def request(self, server: InvestigationMcpServer, request_id: int, method: str, params: dict | None = None) -> dict:
        full_params = dict(params or {})
        full_params["_meta"] = self.modern_meta()
        response = server.handle_message(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": full_params}
        )
        self.assertIsNotNone(response)
        self.assertNotIn("error", response)
        return response["result"]

    def build_server(self, directory: str) -> InvestigationMcpServer:
        context_path = (
            ROOT / "lab" / "investigation" / "checkout-client-version" / "initial-context.yaml"
        )
        context = load_incident_context(context_path)
        return InvestigationMcpServer(
            DiagnosisSnapshotReader(Path(directory) / "missing-diagnosis.json"),
            incident_context_provider=lambda: context,
        )

    def test_lists_incident_context_and_scoping_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = self.build_server(directory)
            listed = self.request(server, 1, "resources/list")
            uris = [resource["uri"] for resource in listed["resources"]]

            self.assertIn(INCIDENT_CONTEXT_URI, uris)
            self.assertIn(INCIDENT_SCOPING_URI, uris)

    def test_reads_context_and_deterministic_scoping_projection_without_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = self.build_server(directory)

            context_result = self.request(
                server,
                1,
                "resources/read",
                {"uri": INCIDENT_CONTEXT_URI},
            )
            context = json.loads(context_result["contents"][0]["text"])
            self.assertEqual("incident.lab.checkout.client_version", context["incident_id"])

            scoping_result = self.request(
                server,
                2,
                "resources/read",
                {"uri": INCIDENT_SCOPING_URI},
            )
            projection = json.loads(scoping_result["contents"][0]["text"])
            self.assertEqual("scoping_projection", projection["kind"])
            self.assertEqual(
                "investigation.client",
                projection["next_action"]["dimension"],
            )


if __name__ == "__main__":
    unittest.main()

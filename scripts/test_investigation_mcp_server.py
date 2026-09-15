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
    RECOMMENDATION_CURRENT_URI,
    RECOMMENDATION_GAPS_URI,
    InvestigationMcpServer,
)
from scoping_projection import ROOT, load_incident_context


def recommendation_fixture() -> dict:
    return {
        "schema_version": "0.1",
        "kind": "architectural_recommendation_projection",
        "system_id": "shop-production",
        "revision": {
            "type": "git",
            "value": "recommendation-mcp-r1",
            "repository": "https://github.com/sergii/causcope",
        },
        "incident_id": "INC-RECOMMENDATION-MCP-001",
        "recommendation_id": "recommendation.database.denormalize_read_model",
        "subject_resource": "db.orders.prod",
        "provider_instance": "provider.pgbot.orders-prod",
        "state": "INSUFFICIENT_CONTEXT",
        "human_approval_required": True,
        "causal_basis": {
            "observation": "observation.database.query_latency",
            "evidence_id": "evidence.query.orders-summary",
            "query_object": "query:orders-summary",
            "source_name": "pgbot",
            "source_uri": "provider-instance:provider.pgbot.orders-prod",
        },
        "problem": {
            "query_object": "query:orders-summary",
            "request_path": "GET /reports/orders-summary",
            "read_frequency_per_minute": 120,
            "query_contribution": "dominant",
        },
        "proposed_change": {
            "type": "materialized_projection",
            "description": "Precompute the orders summary for the dominant reporting path.",
        },
        "missing_assumptions": [
            "business_semantics",
            "maintenance",
            "cost",
            "verification",
        ],
        "limitations": [
            "PostgreSQL query-latency evidence does not by itself justify denormalization."
        ],
    }


class InvestigationMcpServerTest(unittest.TestCase):
    @staticmethod
    def modern_meta() -> dict:
        return {
            PROTOCOL_VERSION_META_KEY: MODERN_PROTOCOL_VERSION,
            CLIENT_CAPABILITIES_META_KEY: {},
            CLIENT_INFO_META_KEY: {"name": "investigation-test", "version": "1.0.0"},
        }

    def request(
        self,
        server: InvestigationMcpServer,
        request_id: int,
        method: str,
        params: dict | None = None,
    ) -> dict:
        full_params = dict(params or {})
        full_params["_meta"] = self.modern_meta()
        response = server.handle_message(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": full_params}
        )
        self.assertIsNotNone(response)
        self.assertNotIn("error", response)
        return response["result"]

    def build_server(
        self,
        directory: str,
        *,
        with_recommendation: bool = False,
    ) -> InvestigationMcpServer:
        context_path = (
            ROOT / "lab" / "investigation" / "checkout-client-version" / "initial-context.yaml"
        )
        context = load_incident_context(context_path)
        recommendation = recommendation_fixture() if with_recommendation else None
        return InvestigationMcpServer(
            DiagnosisSnapshotReader(Path(directory) / "missing-diagnosis.json"),
            incident_context_provider=lambda: context,
            recommendation_projection_provider=(
                (lambda: recommendation) if recommendation is not None else None
            ),
        )

    def test_lists_incident_context_and_scoping_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = self.build_server(directory)
            listed = self.request(server, 1, "resources/list")
            uris = [resource["uri"] for resource in listed["resources"]]

            self.assertIn(INCIDENT_CONTEXT_URI, uris)
            self.assertIn(INCIDENT_SCOPING_URI, uris)
            self.assertNotIn(RECOMMENDATION_CURRENT_URI, uris)
            self.assertNotIn(RECOMMENDATION_GAPS_URI, uris)

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

    def test_lists_and_reads_recommendation_resources_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = self.build_server(directory, with_recommendation=True)
            listed = self.request(server, 1, "resources/list")
            uris = [resource["uri"] for resource in listed["resources"]]

            self.assertIn(RECOMMENDATION_CURRENT_URI, uris)
            self.assertIn(RECOMMENDATION_GAPS_URI, uris)

            current_result = self.request(
                server,
                2,
                "resources/read",
                {"uri": RECOMMENDATION_CURRENT_URI},
            )
            current = json.loads(current_result["contents"][0]["text"])
            self.assertEqual("INSUFFICIENT_CONTEXT", current["state"])
            self.assertEqual("db.orders.prod", current["subject_resource"])

            gaps_result = self.request(
                server,
                3,
                "resources/read",
                {"uri": RECOMMENDATION_GAPS_URI},
            )
            gaps = json.loads(gaps_result["contents"][0]["text"])
            self.assertEqual("recommendation_information_gap_projection", gaps["kind"])
            self.assertEqual("INFORMATION_GAP", gaps["status"])
            self.assertEqual("operator_question", gaps["next_action"]["kind"])
            self.assertEqual(
                "information_gap.business_semantics.consistency_contract",
                gaps["next_action"]["gap_id"],
            )
            self.assertEqual("question_only", gaps["next_action"]["execution_boundary"])


if __name__ == "__main__":
    unittest.main()

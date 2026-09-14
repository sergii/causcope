#!/usr/bin/env python3

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from causal_projection import load_concepts, load_edges
from live_diagnosis import build_diagnosis_snapshot
from opentelemetry_trace_adapter import (
    build_runtime_evidence as build_trace_evidence,
)
from opentelemetry_trace_adapter import load_adapter as load_trace_adapter
from opentelemetry_trace_adapter import load_payload
from pgbot_adapter import build_runtime_evidence as build_pgbot_evidence
from pgbot_adapter import load_adapter as load_pgbot_adapter
from pgbot_adapter import load_context as load_pgbot_context
from runtime_evidence_composition import compose_runtime_evidence

ROOT = Path(__file__).resolve().parents[1]
PGBOT_ADAPTER = ROOT / "examples" / "adapters" / "pgbot" / "postgresql.yaml"
PGBOT_CONTEXT = ROOT / "examples" / "telemetry" / "pgbot" / "postgresql-findings.json"
TRACE_ADAPTER = (
    ROOT / "examples" / "adapters" / "opentelemetry" / "postgresql-dependency.yaml"
)
TRACE_PAYLOAD = (
    ROOT / "examples" / "telemetry" / "opentelemetry" / "postgresql-query-trace.json"
)
INCIDENT_ID = "incident.checkout.postgresql"
AS_OF = datetime(2026, 9, 14, 0, 31, tzinfo=timezone.utc)


class PgbotOtelCompositionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.concepts = load_concepts(ROOT)
        cls.edges = load_edges(ROOT)
        cls.pgbot_adapter = load_pgbot_adapter(PGBOT_ADAPTER)
        cls.pgbot_context = load_pgbot_context(PGBOT_CONTEXT)
        cls.trace_adapter = load_trace_adapter(TRACE_ADAPTER)
        cls.trace_payload = load_payload(TRACE_PAYLOAD)

    def pgbot_evidence(self) -> dict:
        return build_pgbot_evidence(
            self.pgbot_adapter,
            self.pgbot_context,
            self.concepts,
            incident_id=INCIDENT_ID,
            source_uri="pgbot://app-production",
        )

    def trace_evidence(self) -> dict:
        return build_trace_evidence(
            self.trace_adapter,
            self.trace_payload,
            self.concepts,
            incident_id=INCIDENT_ID,
            source_uri="otlp://checkout-api",
        )

    def test_pgbot_and_otel_evidence_share_one_semantic_scope(self) -> None:
        composed = compose_runtime_evidence(
            [self.pgbot_evidence(), self.trace_evidence()],
            self.concepts,
        )

        self.assertEqual(6, len(composed["instances"]))
        self.assertEqual(
            {"other", "trace"},
            {instance["source"]["type"] for instance in composed["instances"]},
        )

        scopes = {
            json.dumps(instance["scope"], sort_keys=True)
            for instance in composed["instances"]
        }
        self.assertEqual(1, len(scopes))

        snapshot = build_diagnosis_snapshot(
            composed,
            self.concepts,
            self.edges,
            as_of=AS_OF,
            evidence_revision=1,
        )
        self.assertEqual(1, len(snapshot["partitions"]))
        partition = snapshot["partitions"][0]
        self.assertEqual(
            {
                "boundaries": ["boundary.application.database"],
                "attributes": {
                    "dependency": "postgresql",
                    "service": "checkout-api",
                },
            },
            partition["scope"],
        )
        self.assertEqual(
            {
                "observation.database.query_latency",
                "observation.database.connection_utilization",
                "observation.database.sequential_scan_pressure",
                "observation.database.lock_wait_time",
                "observation.database.transaction_id_age",
            },
            set(partition["observed"]),
        )

        query_latency_instances = [
            instance
            for instance in composed["instances"]
            if instance["observation"] == "observation.database.query_latency"
        ]
        self.assertEqual(2, len(query_latency_instances))
        self.assertEqual(
            {"other", "trace"},
            {instance["source"]["type"] for instance in query_latency_instances},
        )


if __name__ == "__main__":
    unittest.main()

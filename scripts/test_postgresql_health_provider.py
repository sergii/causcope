#!/usr/bin/env python3

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from causal_projection import load_concepts
from postgresql_health_provider import (
    POSTGRESQL_HEALTH_PROVIDER_ID,
    PostgresqlHealthAutonomousProvider,
    _blocking_chains,
)
from runtime_evidence import load_runtime_evidence, validate_runtime_references

ROOT = Path(__file__).resolve().parents[1]
INCIDENT_ID = "incident.test.postgresql-health"
SCOPE = {
    "boundaries": ["boundary.application.database"],
    "attributes": {"service": "checkout-api", "dependency": "postgresql"},
}
TARGET_RESOURCE = "db.postgresql.checkout.primary"


def snapshot() -> dict:
    return {
        "collected_at": "2026-09-16T00:10:00Z",
        "database": "checkout",
        "long_transaction_threshold_seconds": 60,
        "blocking_chains": [[301, 201, 101]],
        "long_running_transactions": [
            {"pid": 101, "state": "idle in transaction", "age_seconds": 180.0}
        ],
        "vacuum": {
            "autovacuum_enabled": True,
            "tables": [
                {
                    "schema": "public",
                    "table": "orders",
                    "dead_tuples": 5000.0,
                    "estimated_tuples": 10000.0,
                    "vacuum_trigger": 2050.0,
                    "pressure_ratio": 2.439,
                    "autovacuum_enabled": True,
                    "trigger_exceeded": True,
                },
                {
                    "schema": "public",
                    "table": "audit_log",
                    "dead_tuples": 10.0,
                    "estimated_tuples": 100.0,
                    "vacuum_trigger": 70.0,
                    "pressure_ratio": 0.143,
                    "autovacuum_enabled": False,
                    "trigger_exceeded": False,
                },
            ],
        },
    }


class PostgreSQLHealthProviderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.concepts = load_concepts(ROOT)

    def provider(self, document: dict | None = None) -> PostgresqlHealthAutonomousProvider:
        current = snapshot() if document is None else document
        return PostgresqlHealthAutonomousProvider(
            concepts=self.concepts,
            incident_id=INCIDENT_ID,
            scope=SCOPE,
            target_resource=TARGET_RESOURCE,
            collector=lambda: current,
            source_uri="postgresql://test/checkout",
        )

    def validate_evidence(self, evidence: dict) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(evidence), encoding="utf-8")
            loaded = load_runtime_evidence(path)
            validate_runtime_references(loaded, self.concepts)

    def test_blocking_chain_reconstruction_keeps_maximal_dependency_path(self) -> None:
        activity = [
            {"pid": 301, "blocking_pids": [201]},
            {"pid": 201, "blocking_pids": [101]},
            {"pid": 101, "blocking_pids": []},
        ]
        self.assertEqual([[301, 201, 101]], _blocking_chains(activity))

    def test_provider_exposes_three_explicit_read_only_probes(self) -> None:
        provider = self.provider()
        self.assertEqual(
            {
                "probe.database.inspect_blocking_chains",
                "probe.database.inspect_long_running_transactions",
                "probe.database.inspect_vacuum_health",
            },
            provider.supported_probe_ids,
        )
        projection = provider.capability_projection()
        self.assertEqual(POSTGRESQL_HEALTH_PROVIDER_ID, projection["id"])
        self.assertEqual("postgresql", projection["instrument"])
        self.assertTrue(projection["evidence_semantics"]["complete_snapshot"])
        self.assertFalse(projection["evidence_semantics"]["sql_text_collected"])

    def test_blocking_chain_probe_emits_target_bound_positive_evidence(self) -> None:
        provider = self.provider()
        evidence = provider.execute(
            "probe.database.inspect_blocking_chains",
            "observation.http.request_latency",
            SCOPE,
        )
        self.validate_evidence(evidence)
        self.assertEqual(2, len(evidence["instances"]))
        blocking = next(
            item for item in evidence["instances"]
            if item["observation"] == "observation.database.blocking_chain"
        )
        self.assertEqual("observed", blocking["state"])
        self.assertEqual(1, blocking["measurement"]["value"])
        self.assertEqual("2", blocking["labels"]["max_depth"])
        self.assertEqual(TARGET_RESOURCE, blocking["scope"]["attributes"]["target_resource"])
        self.assertNotIn("query", json.dumps(evidence).lower())

    def test_long_transaction_probe_preserves_threshold_as_evidence_policy(self) -> None:
        evidence = self.provider().execute(
            "probe.database.inspect_long_running_transactions",
            "observation.http.request_latency",
            SCOPE,
        )
        self.validate_evidence(evidence)
        instance = evidence["instances"][0]
        self.assertEqual("observed", instance["state"])
        self.assertEqual(180.0, instance["measurement"]["value"])
        self.assertEqual(60, instance["measurement"]["baseline"])
        self.assertEqual("60", instance["labels"]["threshold_seconds"])

    def test_vacuum_probe_separates_pressure_from_disabled_configuration(self) -> None:
        evidence = self.provider().execute(
            "probe.database.inspect_vacuum_health",
            "observation.database.query_latency",
            SCOPE,
        )
        self.validate_evidence(evidence)
        by_observation = {item["observation"]: item for item in evidence["instances"]}
        self.assertEqual("observed", by_observation["observation.database.vacuum_pressure"]["state"])
        self.assertEqual("1", by_observation["observation.database.vacuum_pressure"]["labels"]["pressured_table_count"])
        self.assertEqual("observed", by_observation["observation.database.autovacuum_disabled"]["state"])
        self.assertEqual("1", by_observation["observation.database.autovacuum_disabled"]["labels"]["disabled_table_count"])

    def test_complete_snapshot_can_emit_absent_evidence(self) -> None:
        document = snapshot()
        document["blocking_chains"] = []
        document["long_running_transactions"] = []
        for table in document["vacuum"]["tables"]:
            table["trigger_exceeded"] = False
            table["autovacuum_enabled"] = True
        provider = self.provider(document)
        for probe_id in provider.supported_probe_ids:
            evidence = provider.execute(probe_id, "observation.http.request_latency", SCOPE)
            self.validate_evidence(evidence)
            self.assertTrue(all(item["state"] == "absent" for item in evidence["instances"]))


if __name__ == "__main__":
    unittest.main()

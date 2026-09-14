#!/usr/bin/env python3

from __future__ import annotations

import copy
import unittest
from pathlib import Path

from causal_projection import load_concepts
from pgbot_adapter import build_runtime_evidence, load_adapter, load_context

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "examples" / "adapters" / "pgbot" / "postgresql.yaml"
CONTEXT = ROOT / "examples" / "telemetry" / "pgbot" / "postgresql-findings.json"
INCIDENT_ID = "incident.checkout.postgresql"


class PgbotAdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.concepts = load_concepts(ROOT)
        cls.adapter = load_adapter(ADAPTER)
        cls.context = load_context(CONTEXT)

    def evidence(self, context: dict | None = None) -> dict:
        return build_runtime_evidence(
            self.adapter,
            context if context is not None else self.context,
            self.concepts,
            incident_id=INCIDENT_ID,
            source_uri="pgbot://app-production",
        )

    def test_maps_five_real_pgbot_findings_to_canonical_observations(self) -> None:
        evidence = self.evidence()

        self.assertEqual(5, len(evidence["instances"]))
        self.assertEqual(
            {
                "observation.database.query_latency",
                "observation.database.connection_utilization",
                "observation.database.sequential_scan_pressure",
                "observation.database.lock_wait_time",
                "observation.database.transaction_id_age",
            },
            {instance["observation"] for instance in evidence["instances"]},
        )

        for instance in evidence["instances"]:
            self.assertEqual("observed", instance["state"])
            self.assertEqual("other", instance["source"]["type"])
            self.assertEqual(
                {
                    "boundaries": ["boundary.application.database"],
                    "attributes": {
                        "dependency": "postgresql",
                        "service": "checkout-api",
                    },
                },
                instance["scope"],
            )

    def test_output_is_deterministic(self) -> None:
        self.assertEqual(self.evidence(), self.evidence())

    def test_rejects_unaccepted_upstream_schema_version(self) -> None:
        context = copy.deepcopy(self.context)
        context["schema_version"] = "2.0.0"

        with self.assertRaisesRegex(ValueError, "unsupported pgbot schema_version"):
            self.evidence(context)

    def test_source_suppression_does_not_become_absent_evidence(self) -> None:
        context = copy.deepcopy(self.context)
        for finding in context["findings"]:
            if finding.get("id") == "query_slowdown":
                finding["suppressed"] = True
                finding["suppression_reason"] = "known batch window"

        evidence = self.evidence(context)
        self.assertEqual(4, len(evidence["instances"]))
        self.assertNotIn(
            "observation.database.query_latency",
            {instance["observation"] for instance in evidence["instances"]},
        )
        self.assertIn("suppressed", evidence["description"].lower())

    def test_unmapped_findings_are_not_invented_into_the_ontology(self) -> None:
        context = copy.deepcopy(self.context)
        context["findings"].append(
            {
                "id": "future_unknown_finding",
                "severity": "warn",
                "title": "future finding",
                "detail": "The adapter does not know this semantic mapping.",
                "impact": {
                    "score": 50,
                    "dimension": "risk",
                    "estimate": "unknown",
                    "basis": "fixture",
                },
                "confidence": 1.0,
            }
        )
        evidence = self.evidence(context)
        self.assertEqual(5, len(evidence["instances"]))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from autonomous_investigation import ProbeInsufficientEvidence, run_autonomous_read_only_loop
from causal_projection import load_concepts, load_edges
from live_diagnosis import build_diagnosis_snapshot, normalize_scope, scope_key
from pgbot_adapter import load_adapter
from pgbot_autonomous_provider import PGBOT_PROVIDER_ID, PgbotAutonomousProbeProvider

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "examples" / "adapters" / "pgbot" / "postgresql.yaml"
CONTEXT_PATH = ROOT / "examples" / "telemetry" / "pgbot" / "postgresql-findings.json"
INCIDENT_ID = "incident.test.pgbot-autonomous"
NOW = datetime(2026, 9, 14, 0, 30, 5, tzinfo=timezone.utc)


def clock() -> datetime:
    return NOW


def top_hypothesis(snapshot: dict, *, target: str, scope: dict, concepts: dict) -> str:
    wanted = scope_key(normalize_scope(scope, concepts))
    matches = [
        diagnosis
        for partition in snapshot["partitions"]
        if scope_key(partition.get("scope")) == wanted
        for diagnosis in partition["diagnoses"]
        if diagnosis["target"] == target
    ]
    assert len(matches) == 1, matches
    return matches[0]["ranking"]["candidates"][0]["source"]["id"]


class PgbotAutonomousProviderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.concepts = load_concepts(ROOT)
        cls.edges = load_edges(ROOT)
        cls.adapter = load_adapter(ADAPTER_PATH)
        cls.fixture = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))

    def provider(self, context: dict | None = None) -> PgbotAutonomousProbeProvider:
        current = copy.deepcopy(self.fixture if context is None else context)
        return PgbotAutonomousProbeProvider(
            adapter=self.adapter,
            concepts=self.concepts,
            incident_id=INCIDENT_ID,
            context_supplier=lambda: copy.deepcopy(current),
            source_uri="pgbot://test/app-production",
        )

    def test_supported_probes_are_explicit_read_only_mapped_intersection(self) -> None:
        provider = self.provider()
        self.assertEqual(
            {
                "probe.database.inspect_lock_waits",
                "probe.database.measure_query_latency",
            },
            provider.supported_probe_ids,
        )
        for probe_id in provider.supported_probe_ids:
            self.assertEqual("read_only", self.concepts[probe_id]["risk"])

    def test_lock_wait_probe_preserves_causcope_and_pgbot_provenance(self) -> None:
        provider = self.provider()
        evidence = provider.execute(
            "probe.database.inspect_lock_waits",
            "observation.http.request_failure",
            copy.deepcopy(provider.adapter_scope),
        )

        self.assertEqual("runtime_evidence", evidence["kind"])
        self.assertEqual(INCIDENT_ID, evidence["incident_id"])
        self.assertEqual(1, len(evidence["instances"]))
        instance = evidence["instances"][0]
        self.assertEqual("observation.database.lock_wait_time", instance["observation"])
        self.assertEqual("observed", instance["state"])
        self.assertEqual("probe", instance["source"]["type"])
        self.assertEqual("probe.database.inspect_lock_waits", instance["source"]["name"])
        self.assertEqual(PGBOT_PROVIDER_ID, instance["source"]["attributes"]["provider"])
        self.assertEqual(
            "pgbot:wait_lock_contention",
            instance["source"]["attributes"]["pgbot.source_name"],
        )
        self.assertEqual("1.2.0", instance["source"]["attributes"]["pgbot.contract"])
        self.assertEqual("probe.database.inspect_lock_waits", instance["labels"]["probe"])
        self.assertEqual(PGBOT_PROVIDER_ID, instance["labels"]["provider"])
        self.assertEqual(provider.adapter_scope, instance["scope"])

    def test_missing_or_suppressed_positive_finding_never_becomes_absent(self) -> None:
        context = copy.deepcopy(self.fixture)
        for finding in context["findings"]:
            if finding.get("id") == "wait_lock_contention":
                finding["suppressed"] = True
                finding["suppression_reason"] = "maintenance window"

        provider = self.provider(context)
        with self.assertRaisesRegex(ProbeInsufficientEvidence, "not converted to absent"):
            provider.execute(
                "probe.database.inspect_lock_waits",
                "observation.http.request_failure",
                copy.deepcopy(provider.adapter_scope),
            )

        context = copy.deepcopy(self.fixture)
        context["findings"] = [
            finding
            for finding in context["findings"]
            if finding.get("id") != "wait_lock_contention"
        ]
        provider = self.provider(context)
        with self.assertRaisesRegex(ProbeInsufficientEvidence, "not converted to absent"):
            provider.execute(
                "probe.database.inspect_lock_waits",
                "observation.http.request_failure",
                copy.deepcopy(provider.adapter_scope),
            )

    def test_provider_refuses_cross_scope_relabeling(self) -> None:
        provider = self.provider()
        wrong_scope = copy.deepcopy(provider.adapter_scope)
        wrong_scope["attributes"]["service"] = "billing-api"
        with self.assertRaisesRegex(ProbeInsufficientEvidence, "scope does not match"):
            provider.execute(
                "probe.database.inspect_lock_waits",
                "observation.http.request_failure",
                wrong_scope,
            )

    def test_upstream_contract_mismatch_fails_closed(self) -> None:
        context = copy.deepcopy(self.fixture)
        context["schema_version"] = "2.0.0"
        provider = self.provider(context)
        with self.assertRaisesRegex(ValueError, "unsupported pgbot schema_version"):
            provider.execute(
                "probe.database.inspect_lock_waits",
                "observation.http.request_failure",
                copy.deepcopy(provider.adapter_scope),
            )

    def test_autonomous_loop_selects_pgbot_probe_and_reranks_original_symptom(self) -> None:
        provider = self.provider()
        scope = copy.deepcopy(provider.adapter_scope)
        initial_evidence = {
            "schema_version": "0.1",
            "kind": "runtime_evidence",
            "incident_id": INCIDENT_ID,
            "description": "Passive symptom evidence before external PostgreSQL inspection.",
            "instances": [
                {
                    "id": "evidence.manual.request-failure",
                    "observation": "observation.http.request_failure",
                    "state": "observed",
                    "observed_at": "2026-09-14T00:29:55Z",
                    "confidence": "high",
                    "source": {"type": "manual", "name": "incident-report"},
                    "scope": scope,
                }
            ],
        }
        initial_snapshot = build_diagnosis_snapshot(
            initial_evidence,
            self.concepts,
            self.edges,
            as_of=NOW,
            evidence_revision=1,
        )

        final_evidence, final_snapshot, report = run_autonomous_read_only_loop(
            evidence=initial_evidence,
            snapshot=initial_snapshot,
            concepts=self.concepts,
            edges=self.edges,
            supported_probe_ids=provider.supported_probe_ids,
            execute_probe=provider.execute,
            max_steps=3,
            clock=clock,
        )

        completed = [step for step in report["steps"] if step["status"] == "completed"]
        self.assertTrue(completed, report)
        self.assertTrue(
            any(step["probe_id"] == "probe.database.inspect_lock_waits" for step in completed),
            report,
        )
        self.assertGreaterEqual(report["final_evidence_revision"], 2)

        lock_instance = next(
            instance
            for instance in final_evidence["instances"]
            if instance["observation"] == "observation.database.lock_wait_time"
        )
        self.assertEqual("probe", lock_instance["source"]["type"])
        self.assertEqual(PGBOT_PROVIDER_ID, lock_instance["labels"]["provider"])
        self.assertEqual(
            "hypothesis.database.lock_contention",
            top_hypothesis(
                final_snapshot,
                target="observation.http.request_failure",
                scope=scope,
                concepts=self.concepts,
            ),
        )


if __name__ == "__main__":
    unittest.main()

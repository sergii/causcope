#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from causal_projection import load_concepts
from diagnostic_provider_capabilities import (
    build_provider_capabilities,
    validate_provider_capabilities,
)
from pgbot_adapter import load_adapter
from pgbot_autonomous_provider import (
    PGBOT_PROVIDER_ID,
    PgbotAutonomousProbeProvider,
    file_context_supplier,
)

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "examples" / "adapters" / "pgbot" / "postgresql.yaml"
CONTEXT_PATH = ROOT / "examples" / "telemetry" / "pgbot" / "postgresql-findings.json"


class DiagnosticProviderCapabilitiesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.concepts = load_concepts(ROOT)
        cls.adapter = load_adapter(ADAPTER_PATH)

    def file_provider(self, path: Path = CONTEXT_PATH) -> PgbotAutonomousProbeProvider:
        return PgbotAutonomousProbeProvider(
            adapter=self.adapter,
            concepts=self.concepts,
            context_supplier=file_context_supplier(path),
        )

    def test_pgbot_projection_answers_instrument_scope_observations_and_availability(self) -> None:
        document = build_provider_capabilities([self.file_provider()])
        validate_provider_capabilities(document)

        self.assertEqual("diagnostic_provider_capabilities", document["kind"])
        self.assertEqual(1, len(document["providers"]))
        provider = document["providers"][0]
        self.assertEqual(PGBOT_PROVIDER_ID, provider["id"])
        self.assertEqual("pgbot", provider["instrument"])
        self.assertEqual("context_supplier", provider["transport"])
        self.assertEqual("fixed_exact", provider["scope_mode"])
        self.assertEqual("available", provider["availability"]["state"])
        self.assertIsNone(provider["availability"]["reason"])
        self.assertEqual(["1.2.0"], provider["contract"]["accepted_schema_versions"])
        self.assertFalse(provider["evidence_semantics"]["causal_authority"])
        self.assertTrue(provider["evidence_semantics"]["provenance_preserved"])

        probes = {item["probe"]["id"]: item for item in provider["probes"]}
        self.assertEqual(
            {
                "probe.database.inspect_lock_waits",
                "probe.database.measure_query_latency",
            },
            set(probes),
        )
        self.assertEqual(
            ["observation.database.lock_wait_time"],
            probes["probe.database.inspect_lock_waits"]["mapped_observations"],
        )
        self.assertEqual(
            ["observation.database.query_latency"],
            probes["probe.database.measure_query_latency"]["mapped_observations"],
        )
        self.assertEqual(
            ["capability.database.inspect_locks"],
            probes["probe.database.inspect_lock_waits"]["requires"],
        )

    def test_missing_report_is_unavailable_without_executing_a_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing-pgbot.json"
            document = build_provider_capabilities([self.file_provider(missing)])

        availability = document["providers"][0]["availability"]
        self.assertEqual("unavailable", availability["state"])
        self.assertIn("does not exist", availability["reason"])

    def test_opaque_supplier_is_unknown_and_is_not_invoked_by_discovery(self) -> None:
        calls = 0

        def opaque_supplier() -> dict:
            nonlocal calls
            calls += 1
            raise AssertionError("capability discovery must not invoke opaque suppliers")

        provider = PgbotAutonomousProbeProvider(
            adapter=self.adapter,
            concepts=self.concepts,
            context_supplier=opaque_supplier,
        )
        document = build_provider_capabilities([provider])

        self.assertEqual(0, calls)
        availability = document["providers"][0]["availability"]
        self.assertEqual("unknown", availability["state"])
        self.assertIn("non-invasive availability check", availability["reason"])

    def test_contract_mismatch_marks_file_transport_unavailable(self) -> None:
        context = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
        context["schema_version"] = "2.0.0"
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "pgbot.json"
            report.write_text(json.dumps(context), encoding="utf-8")
            document = build_provider_capabilities([self.file_provider(report)])

        availability = document["providers"][0]["availability"]
        self.assertEqual("unavailable", availability["state"])
        self.assertIn("unsupported pgbot schema_version", availability["reason"])

    def test_discovery_does_not_require_an_incident_but_execution_does(self) -> None:
        provider = self.file_provider()
        self.assertEqual("available", provider.capability_projection()["availability"]["state"])
        with self.assertRaisesRegex(ValueError, "execution requires incident_id"):
            provider.execute(
                "probe.database.inspect_lock_waits",
                "observation.http.request_failure",
                copy.deepcopy(provider.adapter_scope),
            )

    def test_duplicate_provider_ids_are_rejected(self) -> None:
        first = self.file_provider()
        second = self.file_provider()
        with self.assertRaisesRegex(ValueError, "duplicate diagnostic provider id"):
            build_provider_capabilities([first, second])


if __name__ == "__main__":
    unittest.main()

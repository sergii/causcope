#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any

from causal_projection import load_concepts
from instrument_router import InstrumentRouter, validate_instrument_routing_decision
from pgbot_adapter import load_adapter
from pgbot_autonomous_provider import PGBOT_PROVIDER_ID, PgbotAutonomousProbeProvider, file_context_supplier

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "examples" / "adapters" / "pgbot" / "postgresql.yaml"
CONTEXT_PATH = ROOT / "examples" / "telemetry" / "pgbot" / "postgresql-findings.json"
INCIDENT_ID = "incident.test.instrument-router"
CPU_PROBE = "probe.cpu.inspect_utilization"
CPU_EXECUTOR = "executor.linux.proc_stat.cpu_utilization"
LOCK_PROBE = "probe.database.inspect_lock_waits"


def host_capabilities(*, available: bool = True) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "kind": "probe_execution_capabilities",
        "platform": "linux",
        "executors": [
            {
                "probe": {
                    "id": CPU_PROBE,
                    "title": "Inspect CPU utilization",
                    "risk": "read_only",
                },
                "executor": {
                    "id": CPU_EXECUTOR,
                    "platform": "linux",
                },
                "capability": "capability.metrics.query",
                "observation": "observation.cpu.utilization",
                "source": "/proc/stat",
                "available": available,
                "unavailable_reason": None if available else "synthetic unavailable host",
                "policy": {},
            }
        ],
    }


class ProjectionOnlyProvider:
    def __init__(self, projection: dict[str, Any]) -> None:
        self.projection = copy.deepcopy(projection)

    def capability_projection(self) -> dict[str, Any]:
        return copy.deepcopy(self.projection)

    def execute(self, probe_id: str, target: str, scope: dict[str, Any] | None) -> dict[str, Any]:
        raise AssertionError("projection-only provider must not execute")


class InstrumentRouterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.concepts = load_concepts(ROOT)
        cls.adapter = load_adapter(ADAPTER_PATH)

    def pgbot_provider(
        self,
        *,
        incident_id: str | None = INCIDENT_ID,
        opaque_supplier: bool = False,
    ) -> PgbotAutonomousProbeProvider:
        if opaque_supplier:
            fixture = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))
            supplier = lambda: copy.deepcopy(fixture)
        else:
            supplier = file_context_supplier(CONTEXT_PATH)
        return PgbotAutonomousProbeProvider(
            adapter=self.adapter,
            concepts=self.concepts,
            incident_id=incident_id,
            context_supplier=supplier,
            source_uri="pgbot://test/instrument-router",
        )

    def test_routes_exact_scope_direct_probe_to_available_pgbot(self) -> None:
        provider = self.pgbot_provider()
        router = InstrumentRouter(
            concepts=self.concepts,
            host_capabilities=host_capabilities(),
            providers=[provider],
        )
        decision = router.route(
            LOCK_PROBE,
            copy.deepcopy(provider.adapter_scope),
            execution_requirement="direct",
        )
        validate_instrument_routing_decision(decision)
        self.assertIsNone(decision["stop_reason"])
        self.assertEqual(PGBOT_PROVIDER_ID, decision["selection"]["instrument"]["id"])
        self.assertEqual("diagnostic_provider", decision["selection"]["instrument"]["kind"])
        self.assertEqual("direct", decision["selection"]["instrument"]["execution_mode"])

    def test_execute_preserves_provider_evidence_and_adds_router_provenance(self) -> None:
        provider = self.pgbot_provider()
        router = InstrumentRouter(
            concepts=self.concepts,
            host_capabilities=host_capabilities(),
            providers=[provider],
        )
        evidence = router.execute(
            LOCK_PROBE,
            "observation.http.request_failure",
            copy.deepcopy(provider.adapter_scope),
        )
        self.assertEqual(1, len(evidence["instances"]))
        instance = evidence["instances"][0]
        self.assertEqual(PGBOT_PROVIDER_ID, instance["labels"]["provider"])
        self.assertEqual(PGBOT_PROVIDER_ID, instance["labels"]["instrument"])
        attributes = instance["source"]["attributes"]
        self.assertEqual("instrument_router.v0", attributes["routing.router"])
        self.assertEqual(PGBOT_PROVIDER_ID, attributes["routing.instrument_id"])
        self.assertEqual("diagnostic_provider", attributes["routing.instrument_kind"])
        self.assertEqual("direct", attributes["routing.execution_mode"])

    def test_external_provider_must_match_scope_exactly(self) -> None:
        provider = self.pgbot_provider()
        router = InstrumentRouter(
            concepts=self.concepts,
            host_capabilities=host_capabilities(),
            providers=[provider],
        )
        wrong_scope = copy.deepcopy(provider.adapter_scope)
        wrong_scope["attributes"]["service"] = "billing-api"
        decision = router.route(LOCK_PROBE, wrong_scope, execution_requirement="direct")
        self.assertIsNone(decision["selection"])
        self.assertEqual("no_safe_available_instrument", decision["stop_reason"])
        self.assertEqual("mismatch", decision["candidates"][0]["scope_match"])
        self.assertFalse(decision["candidates"][0]["eligible"])

    def test_unknown_provider_availability_is_visible_but_not_selected(self) -> None:
        provider = self.pgbot_provider(opaque_supplier=True)
        router = InstrumentRouter(
            concepts=self.concepts,
            host_capabilities=host_capabilities(),
            providers=[provider],
        )
        decision = router.route(
            LOCK_PROBE,
            copy.deepcopy(provider.adapter_scope),
            execution_requirement="direct",
        )
        self.assertIsNone(decision["selection"])
        self.assertEqual("unknown", decision["candidates"][0]["availability"]["state"])
        self.assertEqual("no_safe_available_instrument", decision["stop_reason"])
        self.assertNotIn(LOCK_PROBE, router.autonomous_probe_ids)

    def test_host_executor_is_session_routable_only_for_unscoped_diagnosis(self) -> None:
        router = InstrumentRouter(
            concepts=self.concepts,
            host_capabilities=host_capabilities(),
            providers=[],
        )
        decision = router.route(CPU_PROBE, None)
        self.assertEqual(CPU_EXECUTOR, decision["selection"]["instrument"]["id"])
        self.assertEqual("host_executor", decision["selection"]["instrument"]["kind"])
        self.assertEqual("session", decision["selection"]["instrument"]["execution_mode"])
        self.assertIn(CPU_PROBE, router.routable_probe_ids)
        self.assertNotIn(CPU_PROBE, router.autonomous_probe_ids)

        direct = router.route(CPU_PROBE, None, execution_requirement="direct")
        self.assertIsNone(direct["selection"])
        self.assertIn("session lifecycle", direct["candidates"][0]["reasons"][0])

    def test_host_executor_refuses_arbitrary_scoped_relabeling(self) -> None:
        router = InstrumentRouter(
            concepts=self.concepts,
            host_capabilities=host_capabilities(),
            providers=[],
        )
        decision = router.route(
            CPU_PROBE,
            {"attributes": {"service": "checkout-api"}},
        )
        self.assertIsNone(decision["selection"])
        candidate = decision["candidates"][0]
        self.assertEqual("mismatch", candidate["scope_match"])
        self.assertTrue(any("host-global evidence" in reason for reason in candidate["reasons"]))

    def test_stable_identity_breaks_ties_between_equally_safe_providers(self) -> None:
        pgbot = self.pgbot_provider()
        projection = pgbot.capability_projection()
        first_projection = copy.deepcopy(projection)
        first_projection["id"] = "provider.aaa.postgresql"
        first_projection["instrument"] = "pgbot-test-a"
        second_projection = copy.deepcopy(projection)
        second_projection["id"] = "provider.zzz.postgresql"
        second_projection["instrument"] = "pgbot-test-z"
        router = InstrumentRouter(
            concepts=self.concepts,
            host_capabilities=host_capabilities(),
            providers=[
                ProjectionOnlyProvider(second_projection),
                ProjectionOnlyProvider(first_projection),
            ],
        )
        decision = router.route(
            LOCK_PROBE,
            copy.deepcopy(pgbot.adapter_scope),
            execution_requirement="direct",
        )
        self.assertEqual("provider.aaa.postgresql", decision["selection"]["instrument"]["id"])
        self.assertEqual(
            ["provider.aaa.postgresql", "provider.zzz.postgresql"],
            [candidate["instrument"]["id"] for candidate in decision["candidates"]],
        )


if __name__ == "__main__":
    unittest.main()

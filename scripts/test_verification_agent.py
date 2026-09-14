#!/usr/bin/env python3

from __future__ import annotations

import copy
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from causal_projection import load_concepts, load_edges
from instrument_router import InstrumentRouter
from live_diagnosis import build_diagnosis_snapshot
from probe_executor_runtime import build_probe_execution_capabilities
from verification_agent import build_verification_agent_plan, run_autonomous_verification
from verification_protocol import build_verification_contract

ROOT = Path(__file__).resolve().parents[1]
INCIDENT_ID = "incident.test.verification-agent"
TARGET = "observation.http.request_failure"
CRITERION = "observation.database.lock_wait_time"
PROBE = "probe.database.inspect_lock_waits"
PROVIDER_ID = "provider.test.verification"
FIXED_AT = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 9, 14, 12, 5, tzinfo=timezone.utc)
SCOPE = {
    "boundaries": ["boundary.application.external_dependency"],
    "attributes": {"service": "checkout-api", "dependency": "postgresql"},
}


class VerificationProvider:
    def __init__(self, *, state: str, incident_id: str = INCIDENT_ID) -> None:
        self.state = state
        self.incident_id = incident_id

    def capability_projection(self) -> dict[str, Any]:
        return {
            "id": PROVIDER_ID,
            "instrument": "verification-test",
            "transport": "in_memory",
            "scope_mode": "fixed_exact",
            "scope": copy.deepcopy(SCOPE),
            "availability": {"state": "available", "reason": None},
            "contract": {"name": "verification_test", "accepted_schema_versions": ["0.1"]},
            "evidence_semantics": {
                "positive_findings_only": False,
                "missing_positive_finding": "insufficient_evidence",
                "suppressed_positive_finding": "insufficient_evidence",
                "provenance_preserved": True,
                "causal_authority": False,
            },
            "probes": [
                {
                    "probe": {"id": PROBE, "title": "Inspect database lock waits", "risk": "read_only"},
                    "requires": ["capability.database.inspect_locks"],
                    "mapped_observations": [CRITERION],
                }
            ],
        }

    def execute(self, probe_id: str, target: str, scope: dict[str, Any] | None) -> dict[str, Any]:
        assert probe_id == PROBE
        assert scope == SCOPE
        return {
            "schema_version": "0.1",
            "kind": "runtime_evidence",
            "incident_id": self.incident_id,
            "instances": [
                {
                    "id": f"evidence.verify-agent.{self.state}",
                    "observation": CRITERION,
                    "state": self.state,
                    "observed_at": "2026-09-14T12:04:00Z",
                    "confidence": "high",
                    "source": {"type": "probe", "name": probe_id},
                    "scope": copy.deepcopy(SCOPE),
                    "labels": {"probe": probe_id},
                }
            ],
        }


class VerificationAgentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.concepts = load_concepts(ROOT)
        cls.edges = load_edges(ROOT)

    def initial_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1",
            "kind": "runtime_evidence",
            "incident_id": INCIDENT_ID,
            "instances": [
                {
                    "id": "evidence.verify-agent.baseline",
                    "observation": TARGET,
                    "state": "observed",
                    "observed_at": "2026-09-14T11:55:00Z",
                    "confidence": "high",
                    "source": {"type": "manual", "name": "incident-report"},
                    "scope": copy.deepcopy(SCOPE),
                }
            ],
        }

    def contract(self) -> dict[str, Any]:
        evidence = self.initial_evidence()
        snapshot = build_diagnosis_snapshot(
            evidence,
            self.concepts,
            self.edges,
            as_of=datetime(2026, 9, 14, 11, 56, tzinfo=timezone.utc),
            evidence_revision=9,
        )
        return build_verification_contract(
            snapshot=snapshot,
            target=TARGET,
            scope=copy.deepcopy(SCOPE),
            fix_applied_at=FIXED_AT,
            created_at=datetime(2026, 9, 14, 12, 1, tzinfo=timezone.utc),
            concepts=self.concepts,
            criteria_observations=[CRITERION],
        )

    def router(self, state: str) -> InstrumentRouter:
        return InstrumentRouter(
            concepts=self.concepts,
            host_capabilities=build_probe_execution_capabilities(self.concepts),
            providers=[VerificationProvider(state=state)],
        )

    def test_plan_maps_verification_criterion_to_exact_scope_direct_instrument(self) -> None:
        plan = build_verification_agent_plan(
            contract=self.contract(),
            evidence=self.initial_evidence(),
            concepts=self.concepts,
            router=self.router("absent"),
            evaluated_at=NOW,
        )
        self.assertEqual("inconclusive", plan["outcome_before"])
        criterion = plan["criteria"][0]
        self.assertEqual("execute_direct_probe", criterion["action"])
        self.assertEqual(PROBE, criterion["selected_probe"])
        self.assertEqual(PROVIDER_ID, criterion["routing"]["selection"]["instrument"]["id"])
        self.assertTrue(plan["executable"])

    def test_absent_post_fix_probe_evidence_resolves_original_scope(self) -> None:
        evidence, result, report = run_autonomous_verification(
            contract=self.contract(),
            evidence=self.initial_evidence(),
            concepts=self.concepts,
            router=self.router("absent"),
            evaluated_at=NOW,
        )
        self.assertEqual("resolved", result["outcome"])
        self.assertEqual("resolved", report["stop_reason"])
        self.assertEqual("completed", report["steps"][0]["status"])
        self.assertTrue(any(item["observation"] == CRITERION for item in evidence["instances"]))

    def test_observed_post_fix_probe_evidence_marks_regression(self) -> None:
        _evidence, result, report = run_autonomous_verification(
            contract=self.contract(),
            evidence=self.initial_evidence(),
            concepts=self.concepts,
            router=self.router("observed"),
            evaluated_at=NOW,
        )
        self.assertEqual("regressed", result["outcome"])
        self.assertEqual("regressed", report["stop_reason"])

    def test_no_instrument_does_not_turn_missing_verification_into_success(self) -> None:
        router = InstrumentRouter(
            concepts=self.concepts,
            host_capabilities=build_probe_execution_capabilities(self.concepts),
            providers=[],
        )
        _evidence, result, report = run_autonomous_verification(
            contract=self.contract(),
            evidence=self.initial_evidence(),
            concepts=self.concepts,
            router=router,
            evaluated_at=NOW,
        )
        self.assertEqual("inconclusive", result["outcome"])
        self.assertEqual("no_executable_verification_route", report["stop_reason"])
        self.assertEqual([], report["steps"])


if __name__ == "__main__":
    unittest.main()

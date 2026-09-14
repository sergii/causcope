#!/usr/bin/env python3

from __future__ import annotations

import copy
import unittest
from datetime import datetime, timezone
from pathlib import Path

from causal_projection import load_concepts, load_edges
from live_diagnosis import build_diagnosis_snapshot
from verification_protocol import (
    VerificationProtocolError,
    build_verification_contract,
    evaluate_verification,
)

ROOT = Path(__file__).resolve().parents[1]
INCIDENT_ID = "incident.test.verify"
TARGET = "observation.http.request_failure"
FIXED_AT = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
EVALUATED_AT = datetime(2026, 9, 14, 12, 5, 0, tzinfo=timezone.utc)
SCOPE = {
    "boundaries": ["boundary.application.external_dependency"],
    "attributes": {"service": "checkout-api", "client": "iOS-7.42.0"},
}


class VerificationProtocolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.concepts = load_concepts(ROOT)
        cls.edges = load_edges(ROOT)

    def snapshot(self) -> dict:
        evidence = {
            "schema_version": "0.1",
            "kind": "runtime_evidence",
            "incident_id": INCIDENT_ID,
            "instances": [
                {
                    "id": "evidence.verify.baseline",
                    "observation": TARGET,
                    "state": "observed",
                    "observed_at": "2026-09-14T11:55:00Z",
                    "confidence": "high",
                    "source": {"type": "manual", "name": "incident-report"},
                    "scope": copy.deepcopy(SCOPE),
                }
            ],
        }
        return build_diagnosis_snapshot(
            evidence,
            self.concepts,
            self.edges,
            as_of=datetime(2026, 9, 14, 11, 56, tzinfo=timezone.utc),
            evidence_revision=7,
        )

    def contract(self) -> dict:
        return build_verification_contract(
            snapshot=self.snapshot(),
            target=TARGET,
            scope=copy.deepcopy(SCOPE),
            fix_applied_at=FIXED_AT,
            created_at=datetime(2026, 9, 14, 12, 1, tzinfo=timezone.utc),
            concepts=self.concepts,
        )

    def evidence(self, instances: list[dict]) -> dict:
        return {
            "schema_version": "0.1",
            "kind": "runtime_evidence",
            "incident_id": INCIDENT_ID,
            "instances": instances,
        }

    def instance(
        self,
        instance_id: str,
        *,
        state: str,
        observed_at: str,
        scope: dict | None = None,
        expires_at: str | None = None,
    ) -> dict:
        item = {
            "id": instance_id,
            "observation": TARGET,
            "state": state,
            "observed_at": observed_at,
            "confidence": "high",
            "source": {"type": "probe", "name": "probe.http.verify_original_flow"},
            "scope": copy.deepcopy(SCOPE if scope is None else scope),
        }
        if expires_at is not None:
            item["expires_at"] = expires_at
        return item

    def test_contract_freezes_original_scope_and_baseline_revision(self) -> None:
        contract = self.contract()
        self.assertEqual(INCIDENT_ID, contract["incident_id"])
        self.assertEqual(7, contract["baseline_evidence_revision"])
        self.assertEqual(TARGET, contract["target"])
        self.assertEqual(SCOPE, contract["original_scope"])
        self.assertEqual(
            [{"observation": TARGET, "expected_state": "absent"}],
            contract["criteria"],
        )

    def test_explicit_post_fix_absence_in_original_scope_resolves(self) -> None:
        result = evaluate_verification(
            contract=self.contract(),
            evidence=self.evidence([
                self.instance(
                    "evidence.verify.absent",
                    state="absent",
                    observed_at="2026-09-14T12:04:00Z",
                )
            ]),
            concepts=self.concepts,
            evaluated_at=EVALUATED_AT,
        )
        self.assertEqual("resolved", result["outcome"])
        self.assertEqual("resolved", result["criteria"][0]["status"])
        self.assertEqual(["evidence.verify.absent"], result["criteria"][0]["evidence_instance_ids"])

    def test_latest_post_fix_observation_regresses_even_after_earlier_green(self) -> None:
        result = evaluate_verification(
            contract=self.contract(),
            evidence=self.evidence([
                self.instance("evidence.verify.green", state="absent", observed_at="2026-09-14T12:02:00Z"),
                self.instance("evidence.verify.failed-again", state="observed", observed_at="2026-09-14T12:04:00Z"),
            ]),
            concepts=self.concepts,
            evaluated_at=EVALUATED_AT,
        )
        self.assertEqual("regressed", result["outcome"])
        self.assertEqual(["evidence.verify.failed-again"], result["criteria"][0]["evidence_instance_ids"])

    def test_cross_scope_pre_fix_future_and_expired_evidence_cannot_close_incident(self) -> None:
        other_scope = copy.deepcopy(SCOPE)
        other_scope["attributes"]["client"] = "web"
        result = evaluate_verification(
            contract=self.contract(),
            evidence=self.evidence([
                self.instance("evidence.verify.pre-fix", state="absent", observed_at="2026-09-14T11:59:59Z"),
                self.instance("evidence.verify.other-cohort", state="absent", observed_at="2026-09-14T12:04:00Z", scope=other_scope),
                self.instance(
                    "evidence.verify.expired",
                    state="absent",
                    observed_at="2026-09-14T12:02:00Z",
                    expires_at="2026-09-14T12:03:00Z",
                ),
                self.instance("evidence.verify.future", state="absent", observed_at="2026-09-14T12:06:00Z"),
            ]),
            concepts=self.concepts,
            evaluated_at=EVALUATED_AT,
        )
        self.assertEqual("inconclusive", result["outcome"])
        self.assertEqual([], result["criteria"][0]["evidence_instance_ids"])

    def test_same_timestamp_conflict_fails_toward_regression(self) -> None:
        result = evaluate_verification(
            contract=self.contract(),
            evidence=self.evidence([
                self.instance("evidence.verify.same-green", state="absent", observed_at="2026-09-14T12:04:00Z"),
                self.instance("evidence.verify.same-red", state="observed", observed_at="2026-09-14T12:04:00Z"),
            ]),
            concepts=self.concepts,
            evaluated_at=EVALUATED_AT,
        )
        self.assertEqual("regressed", result["outcome"])
        self.assertEqual(
            ["evidence.verify.same-green", "evidence.verify.same-red"],
            result["criteria"][0]["evidence_instance_ids"],
        )

    def test_contract_requires_existing_exact_scope_diagnosis(self) -> None:
        wrong_scope = copy.deepcopy(SCOPE)
        wrong_scope["attributes"]["client"] = "android"
        with self.assertRaisesRegex(VerificationProtocolError, "exactly one diagnosis"):
            build_verification_contract(
                snapshot=self.snapshot(),
                target=TARGET,
                scope=wrong_scope,
                fix_applied_at=FIXED_AT,
                created_at=datetime(2026, 9, 14, 12, 1, tzinfo=timezone.utc),
                concepts=self.concepts,
            )


if __name__ == "__main__":
    unittest.main()

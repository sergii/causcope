#!/usr/bin/env python3

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from routed_execution_set_journal import (
    append_execution_set_journal_event,
    execution_set_contract,
    journal_path,
)
from routed_execution_set_recovery import build_execution_set_recovery, main

INCIDENT_ID = "incident.test.execution-set-recovery"
OLD_SET_ID = "execution-set.1111111111111111"
CURRENT_SET_ID = "execution-set.2222222222222222"
NOW = datetime(2026, 9, 15, 10, 0, 0, tzinfo=timezone.utc)


def execution_set(execution_set_id: str, revision: int) -> dict:
    return {
        "id": execution_set_id,
        "scope": {
            "boundaries": ["boundary.application.database"],
            "attributes": {"service": "checkout-api", "dependency": "postgresql"},
        },
        "diagnosis_target": "observation.database.query_latency",
        "probe_id": "probe.database.measure_query_latency",
        "state": "ready",
        "reason": "all exact target routes are direct, safe, and MCP-executable",
        "members": [
            {
                "ordinal": 1,
                "target_resource": "db.orders.prod",
                "instrument": {
                    "id": "provider.prometheus.orders-prod",
                    "kind": "diagnostic_provider",
                    "execution_mode": "direct",
                },
                "supporting_relationship_ids": ["runtime_relationship.test.orders"],
            },
            {
                "ordinal": 2,
                "target_resource": "db.payments.prod",
                "instrument": {
                    "id": "provider.prometheus.payments-prod",
                    "kind": "diagnostic_provider",
                    "execution_mode": "direct",
                },
                "supporting_relationship_ids": ["runtime_relationship.test.payments"],
            },
        ],
        "operation": "causcope.instrument.execute_set",
        "arguments": {
            "incidentId": INCIDENT_ID,
            "evidenceRevision": revision,
            "executionSetId": execution_set_id,
        },
        "atomic_evidence_commit": True,
        "rerank_policy": "after_all_members",
        "failure_policy": "no_state_commit_on_member_failure",
    }


def document(*sets: dict, revision: int) -> dict:
    return {
        "schema_version": "0.1",
        "kind": "routed_execution_sets",
        "incident_id": INCIDENT_ID,
        "evidence_revision": revision,
        "sets": list(sets),
    }


def append_started(state_dir: Path, item: dict, revision: int) -> None:
    append_execution_set_journal_event(
        state_dir,
        event_type="set_started",
        incident_id=INCIDENT_ID,
        execution_set_id=item["id"],
        evidence_revision=revision,
        data={"contract": execution_set_contract(item)},
        recorded_at=NOW,
    )


def append_member(state_dir: Path, item: dict, ordinal: int, revision: int) -> None:
    member = item["members"][ordinal - 1]
    append_execution_set_journal_event(
        state_dir,
        event_type="member_succeeded",
        incident_id=INCIDENT_ID,
        execution_set_id=item["id"],
        evidence_revision=revision,
        data={
            "ordinal": ordinal,
            "target_resource": member["target_resource"],
            "instrument_id": member["instrument"]["id"],
            "produced_instance_ids": [f"evidence.test.{ordinal}"],
            "runtime_evidence": {
                "schema_version": "0.1",
                "kind": "runtime_evidence",
                "incident_id": INCIDENT_ID,
                "instances": [],
            },
        },
        recorded_at=NOW,
    )


def append_committed(state_dir: Path, item: dict, revision: int) -> None:
    append_execution_set_journal_event(
        state_dir,
        event_type="set_committed",
        incident_id=INCIDENT_ID,
        execution_set_id=item["id"],
        evidence_revision=revision,
        data={
            "previous_evidence_revision": revision,
            "evidence_revision": revision + 1,
            "added_instance_ids": ["evidence.test.1", "evidence.test.2"],
        },
        recorded_at=NOW,
    )


class RoutedExecutionSetRecoveryTest(unittest.TestCase):
    def test_current_verified_progress_is_safe_to_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "execution-sets"
            current = execution_set(CURRENT_SET_ID, 8)
            append_started(state_dir, current, 8)
            append_member(state_dir, current, 1, 8)

            projection = build_execution_set_recovery(document(current, revision=8), state_dir)
            candidate = projection["candidates"][0]
            self.assertEqual("safe_to_resume", candidate["classification"])
            self.assertEqual(CURRENT_SET_ID, candidate["current_execution_set_id"])
            self.assertTrue(candidate["advisory_only"])
            self.assertFalse(candidate["automatic_cleanup_allowed"])

    def test_old_verified_progress_can_replay_only_through_equivalent_current_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "execution-sets"
            old = execution_set(OLD_SET_ID, 7)
            current = execution_set(CURRENT_SET_ID, 8)
            append_started(state_dir, old, 7)
            append_member(state_dir, old, 1, 7)

            projection = build_execution_set_recovery(document(current, revision=8), state_dir)
            candidate = next(item for item in projection["candidates"] if item["execution_set_id"] == OLD_SET_ID)
            self.assertEqual("safe_to_replay", candidate["classification"])
            self.assertEqual(CURRENT_SET_ID, candidate["current_execution_set_id"])
            self.assertIn("from scratch", candidate["reason"])

    def test_old_progress_without_equivalent_current_contract_is_superseded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "execution-sets"
            old = execution_set(OLD_SET_ID, 7)
            append_started(state_dir, old, 7)
            append_member(state_dir, old, 1, 7)

            projection = build_execution_set_recovery(document(revision=8), state_dir)
            candidate = projection["candidates"][0]
            self.assertEqual("superseded", candidate["classification"])
            self.assertIsNone(candidate["current_execution_set_id"])

    def test_invalid_current_journal_requires_operator_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "execution-sets"
            current = execution_set(CURRENT_SET_ID, 8)
            append_started(state_dir, current, 8)
            path = journal_path(state_dir, CURRENT_SET_ID)
            path.write_text(
                path.read_text(encoding="utf-8").replace("db.orders.prod", "db.orders.bad", 1),
                encoding="utf-8",
            )

            projection = build_execution_set_recovery(document(current, revision=8), state_dir)
            candidate = projection["candidates"][0]
            self.assertEqual("requires_operator_review", candidate["classification"])
            self.assertEqual("invalid", candidate["journal_integrity"])

    def test_historical_committed_journal_is_only_a_gc_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "execution-sets"
            old = execution_set(OLD_SET_ID, 7)
            append_started(state_dir, old, 7)
            append_member(state_dir, old, 1, 7)
            append_member(state_dir, old, 2, 7)
            append_committed(state_dir, old, 7)

            projection = build_execution_set_recovery(document(revision=8), state_dir)
            candidate = projection["candidates"][0]
            self.assertEqual("garbage_collectable", candidate["classification"])
            self.assertFalse(candidate["automatic_cleanup_allowed"])
            self.assertIn("never deletes", candidate["reason"])

    def test_cli_is_advisory_and_does_not_expose_runtime_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_dir = root / "execution-sets"
            current = execution_set(CURRENT_SET_ID, 8)
            append_started(state_dir, current, 8)
            append_member(state_dir, current, 1, 8)
            input_path = root / "sets.json"
            input_path.write_text(json.dumps(document(current, revision=8)), encoding="utf-8")

            output = io.StringIO()
            with redirect_stdout(output):
                result = main(["--execution-sets", str(input_path), "--state-dir", str(state_dir)])
            self.assertEqual(0, result)
            projected = json.loads(output.getvalue())
            self.assertEqual("routed_execution_set_recovery", projected["kind"])
            self.assertNotIn("runtime_evidence", json.dumps(projected))


if __name__ == "__main__":
    unittest.main()

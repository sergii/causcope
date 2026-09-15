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
from routed_execution_set_status import build_execution_set_status, main

INCIDENT_ID = "incident.test.execution-set-status"
SET_ID = "execution-set.1111111111111111"
OTHER_SET_ID = "execution-set.2222222222222222"
NOW = datetime(2026, 9, 15, 9, 0, 0, tzinfo=timezone.utc)


def execution_set(execution_set_id: str = SET_ID) -> dict:
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
            "evidenceRevision": 7,
            "executionSetId": execution_set_id,
        },
        "atomic_evidence_commit": True,
        "rerank_policy": "after_all_members",
        "failure_policy": "no_state_commit_on_member_failure",
    }


def execution_sets_document(*sets: dict, revision: int = 7) -> dict:
    normalized = []
    for item in sets:
        item = json.loads(json.dumps(item))
        if item.get("arguments") is not None:
            item["arguments"]["evidenceRevision"] = revision
        normalized.append(item)
    return {
        "schema_version": "0.1",
        "kind": "routed_execution_sets",
        "incident_id": INCIDENT_ID,
        "evidence_revision": revision,
        "sets": normalized,
    }


def append_started(state_dir: Path, item: dict, revision: int = 7) -> None:
    append_execution_set_journal_event(
        state_dir,
        event_type="set_started",
        incident_id=INCIDENT_ID,
        execution_set_id=item["id"],
        evidence_revision=revision,
        data={"contract": execution_set_contract(item)},
        recorded_at=NOW,
    )


def append_member(
    state_dir: Path,
    item: dict,
    ordinal: int,
    revision: int = 7,
) -> None:
    member = item["members"][ordinal - 1]
    target = member["target_resource"]
    append_execution_set_journal_event(
        state_dir,
        event_type="member_succeeded",
        incident_id=INCIDENT_ID,
        execution_set_id=item["id"],
        evidence_revision=revision,
        data={
            "ordinal": ordinal,
            "target_resource": target,
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


def append_committed(state_dir: Path, item: dict, revision: int = 7) -> None:
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


class RoutedExecutionSetStatusTest(unittest.TestCase):
    def test_current_lifecycle_moves_from_pending_to_ready_to_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "execution-sets"
            item = execution_set()
            current = execution_sets_document(item)

            pending = build_execution_set_status(current, state_dir)
            self.assertEqual("pending", pending["sets"][0]["state"])
            self.assertTrue(pending["sets"][0]["executable"])
            self.assertEqual(2, pending["sets"][0]["progress"]["remaining_members"])

            append_started(state_dir, item)
            started = build_execution_set_status(current, state_dir)
            self.assertEqual("in_progress", started["sets"][0]["state"])
            self.assertEqual(0, started["sets"][0]["progress"]["completed_members"])

            append_member(state_dir, item, 1)
            partial = build_execution_set_status(current, state_dir)
            self.assertEqual("in_progress", partial["sets"][0]["state"])
            self.assertEqual(1, partial["sets"][0]["progress"]["completed_members"])
            self.assertEqual(
                ["succeeded", "pending"],
                [member["state"] for member in partial["sets"][0]["members"]],
            )

            append_member(state_dir, item, 2)
            ready = build_execution_set_status(current, state_dir)
            self.assertEqual("ready_to_commit", ready["sets"][0]["state"])
            self.assertEqual(2, ready["sets"][0]["progress"]["completed_members"])
            self.assertTrue(ready["sets"][0]["executable"])

    def test_committed_journal_remains_visible_after_revision_advances(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "execution-sets"
            item = execution_set()
            append_started(state_dir, item)
            append_member(state_dir, item, 1)
            append_member(state_dir, item, 2)
            append_committed(state_dir, item)

            current = execution_sets_document(revision=8)
            projection = build_execution_set_status(current, state_dir)

            self.assertEqual(1, projection["summary"]["historical"])
            self.assertEqual(1, projection["summary"]["committed"])
            status = projection["sets"][0]
            self.assertFalse(status["current"])
            self.assertEqual("committed", status["state"])
            self.assertEqual(7, status["evidence_revision"])
            self.assertEqual(2, status["progress"]["completed_members"])
            self.assertIsNotNone(status["committed_at"])

    def test_unfinished_historical_journal_is_stranded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "execution-sets"
            item = execution_set(OTHER_SET_ID)
            append_started(state_dir, item)
            append_member(state_dir, item, 1)

            projection = build_execution_set_status(
                execution_sets_document(revision=8),
                state_dir,
            )

            self.assertEqual(1, projection["summary"]["stranded"])
            status = projection["sets"][0]
            self.assertEqual("stranded", status["state"])
            self.assertFalse(status["current"])
            self.assertFalse(status["executable"])
            self.assertEqual(1, status["progress"]["completed_members"])

    def test_invalid_current_journal_is_visible_but_never_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "execution-sets"
            item = execution_set()
            append_started(state_dir, item)
            path = journal_path(state_dir, item["id"])
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace("db.orders.prod", "db.orders.bad", 1),
                encoding="utf-8",
            )

            projection = build_execution_set_status(
                execution_sets_document(item),
                state_dir,
            )

            status = projection["sets"][0]
            self.assertEqual("stranded", status["state"])
            self.assertFalse(status["executable"])
            self.assertEqual("invalid", status["journal"]["integrity"])
            self.assertIn("journal verification", status["reason"])

    def test_cli_projects_status_without_exposing_raw_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_dir = root / "execution-sets"
            input_path = root / "execution-sets.json"
            input_path.write_text(
                json.dumps(execution_sets_document(execution_set())),
                encoding="utf-8",
            )

            output = io.StringIO()
            with redirect_stdout(output):
                result = main(
                    [
                        "--execution-sets",
                        str(input_path),
                        "--state-dir",
                        str(state_dir),
                    ]
                )
            self.assertEqual(0, result)
            document = json.loads(output.getvalue())
            self.assertEqual("routed_execution_set_status", document["kind"])
            self.assertEqual("pending", document["sets"][0]["state"])
            self.assertNotIn("runtime_evidence", json.dumps(document))


if __name__ == "__main__":
    unittest.main()

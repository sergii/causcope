#!/usr/bin/env python3

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from incident_state_commit import (
    IncidentStateCommitError,
    commit_incident_state,
    default_commit_path,
    durable_atomic_write_json,
    prepare_commit,
    recover_incident_state_commit,
)

INCIDENT_ID = "incident.test.durable-commit"


class SimulatedCrash(RuntimeError):
    pass


def evidence(instance_id: str) -> dict:
    return {
        "schema_version": "0.1",
        "kind": "runtime_evidence",
        "incident_id": INCIDENT_ID,
        "instances": [
            {
                "id": instance_id,
                "observation": "observation.http.request_failure",
                "state": "observed",
                "observed_at": "2026-09-14T10:30:00Z",
                "confidence": "high",
                "source": {"type": "manual", "name": "test"},
            }
        ],
    }


def snapshot(revision: int) -> dict:
    return {
        "incident_id": INCIDENT_ID,
        "evidence_revision": revision,
        "generated_at": "2026-09-14T10:30:00Z",
    }


class IncidentStateCommitTest(unittest.TestCase):
    def setup_paths(self, directory: str):
        root = Path(directory)
        evidence_path = root / "runtime-evidence.json"
        snapshot_path = root / "diagnosis.json"
        commit_path = default_commit_path(snapshot_path)
        durable_atomic_write_json(evidence_path, evidence("evidence.old"))
        durable_atomic_write_json(snapshot_path, snapshot(1))
        commit = prepare_commit(
            incident_id=INCIDENT_ID,
            from_evidence_revision=1,
            runtime_evidence=evidence("evidence.new"),
            diagnosis_snapshot=snapshot(2),
        )
        return evidence_path, snapshot_path, commit_path, commit

    def test_success_publishes_pair_and_clears_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence_path, snapshot_path, commit_path, commit = self.setup_paths(directory)
            commit_incident_state(
                commit_path=commit_path,
                runtime_evidence_path=evidence_path,
                snapshot_path=snapshot_path,
                commit=commit,
            )
            self.assertFalse(commit_path.exists())
            self.assertEqual("evidence.new", json.loads(evidence_path.read_text())["instances"][0]["id"])
            self.assertEqual(2, json.loads(snapshot_path.read_text())["evidence_revision"])

    def test_crash_after_durable_journal_rolls_forward_exact_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence_path, snapshot_path, commit_path, commit = self.setup_paths(directory)

            def crash(stage: str) -> None:
                if stage == "journal_durable":
                    raise SimulatedCrash(stage)

            with self.assertRaises(SimulatedCrash):
                commit_incident_state(
                    commit_path=commit_path,
                    runtime_evidence_path=evidence_path,
                    snapshot_path=snapshot_path,
                    commit=commit,
                    fault_hook=crash,
                )
            self.assertTrue(commit_path.exists())
            self.assertEqual("evidence.old", json.loads(evidence_path.read_text())["instances"][0]["id"])
            self.assertEqual(1, json.loads(snapshot_path.read_text())["evidence_revision"])

            recovered = recover_incident_state_commit(
                commit_path=commit_path,
                runtime_evidence_path=evidence_path,
                snapshot_path=snapshot_path,
            )
            self.assertEqual(2, recovered["evidence_revision"])
            self.assertFalse(commit_path.exists())
            self.assertEqual("evidence.new", json.loads(evidence_path.read_text())["instances"][0]["id"])
            self.assertEqual(2, json.loads(snapshot_path.read_text())["evidence_revision"])

    def test_crash_between_file_replacements_is_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence_path, snapshot_path, commit_path, commit = self.setup_paths(directory)

            def crash(stage: str) -> None:
                if stage == "evidence_replaced":
                    raise SimulatedCrash(stage)

            with self.assertRaises(SimulatedCrash):
                commit_incident_state(
                    commit_path=commit_path,
                    runtime_evidence_path=evidence_path,
                    snapshot_path=snapshot_path,
                    commit=commit,
                    fault_hook=crash,
                )
            self.assertEqual("evidence.new", json.loads(evidence_path.read_text())["instances"][0]["id"])
            self.assertEqual(1, json.loads(snapshot_path.read_text())["evidence_revision"])

            recover_incident_state_commit(
                commit_path=commit_path,
                runtime_evidence_path=evidence_path,
                snapshot_path=snapshot_path,
            )
            self.assertFalse(commit_path.exists())
            self.assertEqual("evidence.new", json.loads(evidence_path.read_text())["instances"][0]["id"])
            self.assertEqual(2, json.loads(snapshot_path.read_text())["evidence_revision"])

    def test_tampered_journal_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence_path, snapshot_path, commit_path, commit = self.setup_paths(directory)
            durable_atomic_write_json(commit_path, commit)
            tampered = json.loads(commit_path.read_text())
            tampered["runtime_evidence"]["instances"][0]["id"] = "evidence.tampered"
            commit_path.write_text(json.dumps(tampered), encoding="utf-8")

            with self.assertRaisesRegex(IncidentStateCommitError, "evidence hash mismatch"):
                recover_incident_state_commit(
                    commit_path=commit_path,
                    runtime_evidence_path=evidence_path,
                    snapshot_path=snapshot_path,
                )
            self.assertEqual("evidence.old", json.loads(evidence_path.read_text())["instances"][0]["id"])
            self.assertEqual(1, json.loads(snapshot_path.read_text())["evidence_revision"])


if __name__ == "__main__":
    unittest.main()

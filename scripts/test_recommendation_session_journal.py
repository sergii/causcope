#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from database_read_model_recommendation import project as project_recommendation
from recommendation_evidence_acquisition import acquire_and_reproject, build_pgbot_router
from recommendation_information_gaps import project as project_information_gaps
from recommendation_session_journal import (
    recommendation_session_path,
    record_recommendation_action_result,
    start_recommendation_session,
    verify_recommendation_session,
)

ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY = ROOT / "examples" / "topology" / "shop.yaml"
ADAPTER = ROOT / "examples" / "adapters" / "pgbot" / "postgresql.yaml"
OLD_PGBOT = ROOT / "examples" / "recommendations" / "database-read-model" / "pgbot-orders-findings.json"
FRESH_PGBOT = ROOT / "examples" / "recommendations" / "database-read-model" / "pgbot-orders-findings-fresh.json"
INSUFFICIENT = ROOT / "examples" / "recommendations" / "database-read-model" / "insufficient-context.json"
MEASURED = ROOT / "examples" / "recommendations" / "database-read-model" / "measured-context.json"

EVIDENCE_SCOPE = {
    "boundaries": ["boundary.application.database"],
    "attributes": {"service": "checkout-api", "dependency": "postgresql"},
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def projections(context: dict, pgbot_path: Path = OLD_PGBOT) -> tuple[dict, dict]:
    recommendation = project_recommendation(
        context=context,
        topology_path=TOPOLOGY,
        adapter_path=ADAPTER,
        pgbot_context_path=pgbot_path,
    )
    return recommendation, project_information_gaps(recommendation)


def stale_context() -> dict:
    context = load(INSUFFICIENT)
    context["evaluation_time"] = "2026-09-15T00:10:00Z"
    context["evidence_scope"] = copy.deepcopy(EVIDENCE_SCOPE)
    return context


class RecommendationSessionJournalTest(unittest.TestCase):
    def test_read_only_probe_progression_is_persisted_and_retry_safe(self) -> None:
        context = stale_context()
        recommendation, gaps = projections(context)
        self.assertEqual("NO_PROBLEM_EVIDENCE", recommendation["state"])
        self.assertEqual("read_only_probe", gaps["next_action"]["kind"])

        with tempfile.TemporaryDirectory() as directory:
            session_dir = Path(directory)
            started = start_recommendation_session(
                session_dir,
                recommendation_projection=recommendation,
                information_gap_projection=gaps,
                recorded_at=datetime(2026, 9, 15, 0, 10, 0, tzinfo=timezone.utc),
            )
            session_id = started["session"]["session_id"]
            self.assertEqual(1, started["session"]["session_revision"])
            self.assertEqual("active", started["session"]["status"])

            bundle = acquire_and_reproject(
                context=context,
                current_projection=recommendation,
                topology_path=TOPOLOGY,
                router=build_pgbot_router(
                    context=context,
                    topology_path=TOPOLOGY,
                    adapter_path=ADAPTER,
                    pgbot_context_path=FRESH_PGBOT,
                ),
                acquisition_time="2026-09-15T00:10:00Z",
            )
            result = {
                "kind": "read_only_probe",
                "acquisition_result": bundle["result"],
            }
            recorded = record_recommendation_action_result(
                session_dir,
                session_id=session_id,
                expected_session_revision=1,
                result=result,
                next_recommendation_projection=bundle["recommendation_projection"],
                next_information_gap_projection=bundle["information_gap_projection"],
                recorded_at=datetime(2026, 9, 15, 0, 10, 1, tzinfo=timezone.utc),
            )
            self.assertEqual(2, recorded["session"]["session_revision"])
            self.assertEqual("INSUFFICIENT_CONTEXT", recorded["session"]["recommendation_state"])
            self.assertEqual("INFORMATION_GAP", recorded["session"]["information_gap_status"])
            self.assertEqual("operator_question", recorded["session"]["next_action"]["kind"])
            self.assertFalse(recorded["journal_event"]["already_recorded"])

            retried = record_recommendation_action_result(
                session_dir,
                session_id=session_id,
                expected_session_revision=1,
                result=result,
                next_recommendation_projection=bundle["recommendation_projection"],
                next_information_gap_projection=bundle["information_gap_projection"],
                recorded_at=datetime(2026, 9, 15, 0, 10, 2, tzinfo=timezone.utc),
            )
            self.assertEqual(2, retried["session"]["session_revision"])
            self.assertTrue(retried["journal_event"]["already_recorded"])

            verified = verify_recommendation_session(session_dir, session_id)
            self.assertEqual(recorded["session"], verified)

    def test_operator_answer_records_input_but_projection_decides_progress(self) -> None:
        context = load(INSUFFICIENT)
        recommendation, gaps = projections(context)
        self.assertEqual("INSUFFICIENT_CONTEXT", recommendation["state"])
        self.assertEqual("operator_question", gaps["next_action"]["kind"])
        self.assertEqual(
            "information_gap.business_semantics.consistency_contract",
            gaps["next_action"]["gap_id"],
        )

        next_context = copy.deepcopy(context)
        next_context["business_semantics"] = {
            "source_of_truth": "orders and order_line_items",
            "consistency_invariant": "The projection must match committed source totals after the allowed lag.",
            "staleness_budget_ms": 5000,
        }
        next_recommendation, next_gaps = projections(next_context)
        self.assertEqual("INSUFFICIENT_CONTEXT", next_recommendation["state"])
        self.assertEqual(
            "information_gap.maintenance.consistency_strategy",
            next_gaps["next_action"]["gap_id"],
        )

        with tempfile.TemporaryDirectory() as directory:
            session_dir = Path(directory)
            started = start_recommendation_session(
                session_dir,
                recommendation_projection=recommendation,
                information_gap_projection=gaps,
            )
            session_id = started["session"]["session_id"]
            recorded = record_recommendation_action_result(
                session_dir,
                session_id=session_id,
                expected_session_revision=1,
                result={
                    "kind": "operator_question",
                    "gap_id": gaps["next_action"]["gap_id"],
                    "source": "human",
                    "answer": "Orders and order_line_items are authoritative; a 5 second projection lag is acceptable.",
                },
                next_recommendation_projection=next_recommendation,
                next_information_gap_projection=next_gaps,
            )
            self.assertEqual(2, recorded["session"]["session_revision"])
            self.assertEqual(
                "information_gap.maintenance.consistency_strategy",
                recorded["session"]["next_action"]["gap_id"],
            )

            with self.assertRaisesRegex(ValueError, "stale recommendation session revision"):
                record_recommendation_action_result(
                    session_dir,
                    session_id=session_id,
                    expected_session_revision=1,
                    result={
                        "kind": "operator_question",
                        "gap_id": gaps["next_action"]["gap_id"],
                        "source": "human",
                        "answer": "A conflicting retry must not overwrite history.",
                    },
                    next_recommendation_projection=next_recommendation,
                    next_information_gap_projection=next_gaps,
                )

    def test_safe_experiment_can_reach_human_review_then_human_closes_session(self) -> None:
        expected_context = load(MEASURED)
        expected_context["benefit"]["basis"] = "expected"
        expected_recommendation, expected_gaps = projections(expected_context)
        self.assertEqual("EXPERIMENT_REQUIRED", expected_recommendation["state"])
        self.assertEqual("safe_experiment", expected_gaps["next_action"]["kind"])

        measured_context = load(MEASURED)
        measured_recommendation, measured_gaps = projections(measured_context)
        self.assertEqual("READY_FOR_HUMAN_REVIEW", measured_recommendation["state"])
        self.assertEqual("human_decision", measured_gaps["next_action"]["kind"])

        with tempfile.TemporaryDirectory() as directory:
            session_dir = Path(directory)
            started = start_recommendation_session(
                session_dir,
                recommendation_projection=expected_recommendation,
                information_gap_projection=expected_gaps,
            )
            session_id = started["session"]["session_id"]
            experiment = record_recommendation_action_result(
                session_dir,
                session_id=session_id,
                expected_session_revision=1,
                result={
                    "kind": "safe_experiment",
                    "gap_id": expected_gaps["next_action"]["gap_id"],
                    "result_ref": measured_context["benefit"]["evidence_ref"],
                    "reported_outcome": "demonstrated",
                    "summary": "The bounded shadow-read experiment demonstrated the measured latency improvement.",
                },
                next_recommendation_projection=measured_recommendation,
                next_information_gap_projection=measured_gaps,
            )
            self.assertEqual("awaiting_human_decision", experiment["session"]["status"])
            self.assertEqual(2, experiment["session"]["session_revision"])

            decided = record_recommendation_action_result(
                session_dir,
                session_id=session_id,
                expected_session_revision=2,
                result={
                    "kind": "human_decision",
                    "decision": "approved",
                    "note": "Approved for a separately controlled implementation workflow.",
                },
                next_recommendation_projection=measured_recommendation,
                next_information_gap_projection=measured_gaps,
            )
            self.assertEqual("approved", decided["session"]["status"])
            self.assertEqual(3, decided["session"]["session_revision"])

            with self.assertRaisesRegex(ValueError, "terminally closed"):
                record_recommendation_action_result(
                    session_dir,
                    session_id=session_id,
                    expected_session_revision=3,
                    result={
                        "kind": "human_decision",
                        "decision": "rejected",
                    },
                    next_recommendation_projection=measured_recommendation,
                    next_information_gap_projection=measured_gaps,
                )

    def test_rejected_candidate_can_be_explicitly_stopped(self) -> None:
        context = load(MEASURED)
        context["benefit"]["after"] = context["benefit"]["before"]
        recommendation, gaps = projections(context)
        self.assertEqual("BENEFIT_NOT_DEMONSTRATED", recommendation["state"])
        self.assertEqual("stop_candidate", gaps["next_action"]["kind"])

        with tempfile.TemporaryDirectory() as directory:
            session_dir = Path(directory)
            started = start_recommendation_session(
                session_dir,
                recommendation_projection=recommendation,
                information_gap_projection=gaps,
            )
            self.assertEqual("candidate_rejected", started["session"]["status"])
            stopped = record_recommendation_action_result(
                session_dir,
                session_id=started["session"]["session_id"],
                expected_session_revision=1,
                result={
                    "kind": "stop_candidate",
                    "reason": "The bounded experiment did not demonstrate benefit.",
                },
                next_recommendation_projection=recommendation,
                next_information_gap_projection=gaps,
            )
            self.assertEqual("stopped", stopped["session"]["status"])

    def test_wrong_action_kind_fails_closed(self) -> None:
        context = load(INSUFFICIENT)
        recommendation, gaps = projections(context)
        with tempfile.TemporaryDirectory() as directory:
            session_dir = Path(directory)
            started = start_recommendation_session(
                session_dir,
                recommendation_projection=recommendation,
                information_gap_projection=gaps,
            )
            with self.assertRaisesRegex(ValueError, "result kind does not match"):
                record_recommendation_action_result(
                    session_dir,
                    session_id=started["session"]["session_id"],
                    expected_session_revision=1,
                    result={
                        "kind": "safe_experiment",
                        "gap_id": gaps["next_action"]["gap_id"],
                        "result_ref": "experiment.invalid",
                        "reported_outcome": "inconclusive",
                    },
                    next_recommendation_projection=recommendation,
                    next_information_gap_projection=gaps,
                )

    def test_hash_chain_tampering_is_detected(self) -> None:
        context = load(INSUFFICIENT)
        recommendation, gaps = projections(context)
        with tempfile.TemporaryDirectory() as directory:
            session_dir = Path(directory)
            started = start_recommendation_session(
                session_dir,
                recommendation_projection=recommendation,
                information_gap_projection=gaps,
            )
            session_id = started["session"]["session_id"]
            path = recommendation_session_path(session_dir, session_id)
            event = json.loads(path.read_text(encoding="utf-8").strip())
            event["data"]["snapshot"]["recommendation_projection"]["state"] = "READY_FOR_HUMAN_REVIEW"
            path.write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "event_hash mismatch"):
                verify_recommendation_session(session_dir, session_id)


if __name__ == "__main__":
    unittest.main()

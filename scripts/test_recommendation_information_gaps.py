#!/usr/bin/env python3

import copy
import json
import unittest
from pathlib import Path

from database_read_model_recommendation import project as project_recommendation
from recommendation_information_gaps import project as project_information_gaps

ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY = ROOT / "examples" / "topology" / "shop.yaml"
ADAPTER = ROOT / "examples" / "adapters" / "pgbot" / "postgresql.yaml"
PGBOT = ROOT / "examples" / "recommendations" / "database-read-model" / "pgbot-orders-findings.json"
INSUFFICIENT = ROOT / "examples" / "recommendations" / "database-read-model" / "insufficient-context.json"
MEASURED = ROOT / "examples" / "recommendations" / "database-read-model" / "measured-context.json"


def load(path):
    return json.loads(path.read_text())


def recommendation_projection(context):
    return project_recommendation(
        context=context,
        topology_path=TOPOLOGY,
        adapter_path=ADAPTER,
        pgbot_context_path=PGBOT,
    )


def information_gap_projection(context):
    return project_information_gaps(recommendation_projection(context))


class RecommendationInformationGapTest(unittest.TestCase):
    def test_business_semantics_is_next_when_slow_query_context_is_incomplete(self):
        result = information_gap_projection(load(INSUFFICIENT))
        self.assertEqual(result["recommendation_state"], "INSUFFICIENT_CONTEXT")
        self.assertEqual(result["status"], "INFORMATION_GAP")
        self.assertEqual(
            [gap["id"] for gap in result["gaps"]],
            [
                "information_gap.business_semantics.consistency_contract",
                "information_gap.maintenance.consistency_strategy",
                "information_gap.cost.maintenance_cost",
                "information_gap.verification.plan",
            ],
        )
        self.assertEqual([gap["rank"] for gap in result["gaps"]], [1, 2, 3, 4])
        self.assertEqual(result["next_action"]["kind"], "operator_question")
        self.assertEqual(
            result["next_action"]["gap_id"],
            "information_gap.business_semantics.consistency_contract",
        )
        self.assertEqual(result["next_action"]["execution_boundary"], "question_only")

    def test_stale_problem_evidence_recommends_existing_read_only_probe_first(self):
        context = load(MEASURED)
        context["evaluation_time"] = "2026-09-15T00:10:00Z"
        result = information_gap_projection(context)
        self.assertEqual(result["recommendation_state"], "NO_PROBLEM_EVIDENCE")
        self.assertEqual(result["status"], "EVIDENCE_REFRESH_REQUIRED")
        self.assertEqual(result["gaps"][0]["category"], "problem_evidence")
        self.assertEqual(result["next_action"]["kind"], "read_only_probe")
        self.assertEqual(
            result["next_action"]["probe_id"],
            "probe.database.measure_query_latency",
        )
        self.assertEqual(
            result["next_action"]["requested_observation"],
            "observation.database.query_latency",
        )
        self.assertEqual(
            result["next_action"]["execution_boundary"],
            "existing_read_only_probe",
        )

    def test_expected_benefit_recommends_bounded_experiment_not_architecture_change(self):
        context = load(MEASURED)
        context["benefit"]["basis"] = "expected"
        result = information_gap_projection(context)
        self.assertEqual(result["recommendation_state"], "EXPERIMENT_REQUIRED")
        self.assertEqual(result["status"], "EXPERIMENT_REQUIRED")
        self.assertEqual(result["next_action"]["kind"], "safe_experiment")
        self.assertEqual(
            result["next_action"]["execution_boundary"],
            "experiment_plan_only",
        )
        self.assertIn("Shadow-read", result["next_action"]["prompt"])

    def test_estimated_benefit_requests_measured_result(self):
        context = load(MEASURED)
        context["benefit"]["basis"] = "benchmark"
        result = information_gap_projection(context)
        self.assertEqual(result["recommendation_state"], "ESTIMATED_BENEFIT")
        self.assertEqual(result["next_action"]["kind"], "safe_experiment")
        self.assertEqual(
            result["next_action"]["gap_id"],
            "information_gap.benefit.measured_improvement",
        )
        self.assertIn("measured before/after", result["next_action"]["prompt"])

    def test_measured_full_context_ends_at_human_decision(self):
        result = information_gap_projection(load(MEASURED))
        self.assertEqual(result["recommendation_state"], "READY_FOR_HUMAN_REVIEW")
        self.assertEqual(result["status"], "HUMAN_REVIEW_READY")
        self.assertEqual(result["gaps"], [])
        self.assertEqual(result["next_action"]["kind"], "human_decision")
        self.assertEqual(
            result["next_action"]["execution_boundary"],
            "human_decision_required",
        )

    def test_failed_benefit_experiment_stops_candidate(self):
        context = load(MEASURED)
        context["benefit"]["after"] = context["benefit"]["before"]
        result = information_gap_projection(context)
        self.assertEqual(result["recommendation_state"], "BENEFIT_NOT_DEMONSTRATED")
        self.assertEqual(result["status"], "CANDIDATE_REJECTED")
        self.assertEqual(result["gaps"], [])
        self.assertEqual(result["next_action"]["kind"], "stop_candidate")

    def test_unknown_gap_semantics_fail_closed(self):
        projection = recommendation_projection(load(INSUFFICIENT))
        projection = copy.deepcopy(projection)
        projection["missing_assumptions"].append("future.unknown_context")
        with self.assertRaisesRegex(
            ValueError,
            "add explicit information-gap semantics first",
        ):
            project_information_gaps(projection)

    def test_information_gap_projection_does_not_mutate_causal_probe_ranking(self):
        result = information_gap_projection(load(INSUFFICIENT))
        self.assertNotIn("probe_ranking", result)
        self.assertTrue(
            any(
                "does not change causal ranking" in limitation
                for limitation in result["limitations"]
            )
        )


if __name__ == "__main__":
    unittest.main()

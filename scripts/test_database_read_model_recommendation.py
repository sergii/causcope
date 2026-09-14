#!/usr/bin/env python3

import copy
import json
import unittest
from pathlib import Path

from database_read_model_recommendation import project

ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY = ROOT / "examples" / "topology" / "shop.yaml"
ADAPTER = ROOT / "examples" / "adapters" / "pgbot" / "postgresql.yaml"
PGBOT = ROOT / "examples" / "recommendations" / "database-read-model" / "pgbot-orders-findings.json"
INSUFFICIENT = ROOT / "examples" / "recommendations" / "database-read-model" / "insufficient-context.json"
MEASURED = ROOT / "examples" / "recommendations" / "database-read-model" / "measured-context.json"


def load(path):
    return json.loads(path.read_text())


def projection(context):
    return project(
        context=context,
        topology_path=TOPOLOGY,
        adapter_path=ADAPTER,
        pgbot_context_path=PGBOT,
    )


class DatabaseReadModelRecommendationTest(unittest.TestCase):
    def test_slow_query_without_business_semantics_is_insufficient_context(self):
        result = projection(load(INSUFFICIENT))
        self.assertEqual(result["state"], "INSUFFICIENT_CONTEXT")
        self.assertEqual(
            result["causal_basis"]["observation"],
            "observation.database.query_latency",
        )
        self.assertIn("evidence_id", result["causal_basis"])
        self.assertEqual(
            result["causal_basis"]["source_uri"],
            "provider-instance:provider.pgbot.orders-prod",
        )
        self.assertEqual(
            result["missing_assumptions"],
            ["business_semantics", "cost", "maintenance", "verification"],
        )

    def test_measured_benefit_reaches_human_review_only_with_full_context(self):
        result = projection(load(MEASURED))
        self.assertEqual(result["state"], "READY_FOR_HUMAN_REVIEW")
        self.assertTrue(result["human_approval_required"])
        self.assertEqual(result["missing_assumptions"], [])
        self.assertEqual(result["benefit"]["basis"], "measured")
        self.assertEqual(result["benefit"]["improvement_percent"], 88.95)
        self.assertEqual(result["consistency"]["staleness_budget_ms"], 5000)
        self.assertEqual(result["consistency"]["update_strategy"], "transactional_outbox")

    def test_expected_benefit_still_requires_experiment(self):
        context = load(MEASURED)
        context["benefit"]["basis"] = "expected"
        result = projection(context)
        self.assertEqual(result["state"], "EXPERIMENT_REQUIRED")

    def test_planner_or_benchmark_gain_is_not_production_measurement(self):
        context = load(MEASURED)
        context["benefit"]["basis"] = "planner_experiment"
        result = projection(context)
        self.assertEqual(result["state"], "ESTIMATED_BENEFIT")
        self.assertTrue(
            any("not a measured production improvement" in item for item in result["limitations"])
        )

    def test_no_improvement_does_not_support_the_candidate(self):
        context = load(MEASURED)
        context["benefit"]["after"] = context["benefit"]["before"]
        result = projection(context)
        self.assertEqual(result["state"], "BENEFIT_NOT_DEMONSTRATED")

    def test_stale_pgbot_finding_is_not_problem_evidence(self):
        context = load(MEASURED)
        context["evaluation_time"] = "2026-09-15T00:10:00Z"
        result = projection(context)
        self.assertEqual(result["state"], "NO_PROBLEM_EVIDENCE")
        self.assertNotIn("evidence_id", result["causal_basis"])

    def test_wrong_provider_target_fails_closed(self):
        context = load(MEASURED)
        context["provider_instance"] = "provider.pgbot.payments-prod"
        with self.assertRaisesRegex(
            ValueError,
            "provider instance target does not match recommendation subject_resource",
        ):
            projection(context)


if __name__ == "__main__":
    unittest.main()

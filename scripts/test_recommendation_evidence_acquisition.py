#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from database_read_model_recommendation import project as project_recommendation
from recommendation_evidence_acquisition import acquire_and_reproject, build_pgbot_router
from recommendation_information_gaps import project as project_information_gaps

ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY = ROOT / "examples" / "topology" / "shop.yaml"
ADAPTER = ROOT / "examples" / "adapters" / "pgbot" / "postgresql.yaml"
OLD_PGBOT = ROOT / "examples" / "recommendations" / "database-read-model" / "pgbot-orders-findings.json"
FRESH_PGBOT = ROOT / "examples" / "recommendations" / "database-read-model" / "pgbot-orders-findings-fresh.json"
INSUFFICIENT = ROOT / "examples" / "recommendations" / "database-read-model" / "insufficient-context.json"

EVIDENCE_SCOPE = {
    "boundaries": ["boundary.application.database"],
    "attributes": {"service": "checkout-api", "dependency": "postgresql"},
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def stale_context(*, include_scope: bool = True) -> dict:
    context = load(INSUFFICIENT)
    context["evaluation_time"] = "2026-09-15T00:10:00Z"
    if include_scope:
        context["evidence_scope"] = copy.deepcopy(EVIDENCE_SCOPE)
    return context


def projection(context: dict, pgbot_path: Path) -> dict:
    return project_recommendation(
        context=context,
        topology_path=TOPOLOGY,
        adapter_path=ADAPTER,
        pgbot_context_path=pgbot_path,
    )


def router(context: dict, pgbot_path: Path):
    return build_pgbot_router(
        context=context,
        topology_path=TOPOLOGY,
        adapter_path=ADAPTER,
        pgbot_context_path=pgbot_path,
    )


class RecommendationEvidenceAcquisitionTest(unittest.TestCase):
    def test_fresh_exact_target_probe_advances_to_next_information_gap(self) -> None:
        context = stale_context()
        current = projection(context, OLD_PGBOT)
        self.assertEqual("NO_PROBLEM_EVIDENCE", current["state"])
        current_gaps = project_information_gaps(current)
        self.assertEqual("read_only_probe", current_gaps["next_action"]["kind"])
        self.assertEqual(EVIDENCE_SCOPE, current_gaps["next_action"]["scope"])

        bundle = acquire_and_reproject(
            context=context,
            current_projection=current,
            topology_path=TOPOLOGY,
            router=router(context, FRESH_PGBOT),
            acquisition_time="2026-09-15T00:10:00Z",
        )

        result = bundle["result"]
        self.assertEqual("NO_PROBLEM_EVIDENCE", result["previous_state"])
        self.assertEqual("INSUFFICIENT_CONTEXT", result["recommendation_state"])
        self.assertEqual("INFORMATION_GAP", result["information_gap_status"])
        self.assertTrue(result["progressed"])
        self.assertEqual("probe.database.measure_query_latency", result["probe_id"])
        self.assertEqual("observation.database.query_latency", result["requested_observation"])
        self.assertEqual("provider.pgbot.orders-prod", result["routing"]["instrument_id"])
        self.assertEqual("db.orders.prod", result["routing"]["target_resource"])
        self.assertEqual("operator_question", result["next_action"]["kind"])
        self.assertEqual("question_only", result["next_action"]["execution_boundary"])

        evidence = bundle["runtime_evidence"]
        matching = set(result["evidence"]["matching_instance_ids"])
        self.assertTrue(matching)
        instances = {item["id"]: item for item in evidence["instances"]}
        for evidence_id in matching:
            attributes = instances[evidence_id]["source"]["attributes"]
            self.assertEqual("query:orders-summary", attributes["pgbot.object"])
            self.assertEqual("db.orders.prod", attributes["routing.target_resource"])
            self.assertEqual("provider.pgbot.orders-prod", attributes["routing.instrument_id"])
            self.assertEqual(
                "provider.pgbot.orders-prod",
                instances[evidence_id]["labels"]["instrument"],
            )

        next_projection = bundle["recommendation_projection"]
        self.assertIn("evidence_id", next_projection["causal_basis"])
        self.assertEqual(
            "provider-instance:provider.pgbot.orders-prod",
            next_projection["causal_basis"]["source_uri"],
        )
        self.assertEqual(
            "information_gap.business_semantics.consistency_contract",
            bundle["information_gap_projection"]["next_action"]["gap_id"],
        )

    def test_stale_provider_report_does_not_fake_progress(self) -> None:
        context = stale_context()
        current = projection(context, OLD_PGBOT)
        bundle = acquire_and_reproject(
            context=context,
            current_projection=current,
            topology_path=TOPOLOGY,
            router=router(context, OLD_PGBOT),
            acquisition_time="2026-09-15T00:10:00Z",
        )
        self.assertFalse(bundle["result"]["progressed"])
        self.assertEqual("NO_PROBLEM_EVIDENCE", bundle["result"]["recommendation_state"])
        self.assertEqual("read_only_probe", bundle["result"]["next_action"]["kind"])
        self.assertNotIn("evidence_id", bundle["recommendation_projection"]["causal_basis"])

    def test_wrong_query_object_cannot_satisfy_refresh(self) -> None:
        context = stale_context()
        current = projection(context, OLD_PGBOT)
        wrong_query = load(FRESH_PGBOT)
        wrong_query["findings"][0]["object"] = "query:other-report"
        with tempfile.TemporaryDirectory(prefix="causcope-rec-acquisition-") as directory:
            path = Path(directory) / "wrong-query.json"
            path.write_text(json.dumps(wrong_query), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exact query"):
                acquire_and_reproject(
                    context=context,
                    current_projection=current,
                    topology_path=TOPOLOGY,
                    router=router(context, path),
                    acquisition_time="2026-09-15T00:10:00Z",
                )

    def test_missing_exact_scope_refuses_acquisition(self) -> None:
        context = stale_context(include_scope=False)
        current = projection(context, OLD_PGBOT)
        with self.assertRaisesRegex(ValueError, "no exact evidence scope"):
            acquire_and_reproject(
                context=context,
                current_projection=current,
                topology_path=TOPOLOGY,
                router=router(context, FRESH_PGBOT),
                acquisition_time="2026-09-15T00:10:00Z",
            )

    def test_non_probe_next_action_is_not_executed(self) -> None:
        context = stale_context()
        context["evaluation_time"] = "2026-09-15T00:02:00Z"
        current = projection(context, OLD_PGBOT)
        self.assertEqual("INSUFFICIENT_CONTEXT", current["state"])
        self.assertEqual("operator_question", project_information_gaps(current)["next_action"]["kind"])
        with self.assertRaisesRegex(ValueError, "requires current next_action kind read_only_probe"):
            acquire_and_reproject(
                context=context,
                current_projection=current,
                topology_path=TOPOLOGY,
                router=router(context, FRESH_PGBOT),
                acquisition_time="2026-09-15T00:10:00Z",
            )

    def test_provider_instance_mismatch_fails_before_execution(self) -> None:
        context = stale_context()
        current = projection(context, OLD_PGBOT)
        tampered_context = copy.deepcopy(context)
        tampered_projection = copy.deepcopy(current)
        tampered_context["provider_instance"] = "provider.pgbot.payments-prod"
        tampered_projection["provider_instance"] = "provider.pgbot.payments-prod"
        with self.assertRaisesRegex(ValueError, "selected recommendation evidence provider differs"):
            acquire_and_reproject(
                context=tampered_context,
                current_projection=tampered_projection,
                topology_path=TOPOLOGY,
                router=router(context, FRESH_PGBOT),
                acquisition_time="2026-09-15T00:10:00Z",
            )


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "causcope"


def recommendation_fixture() -> dict:
    return {
        "schema_version": "0.1",
        "kind": "architectural_recommendation_projection",
        "system_id": "shop-production",
        "revision": {
            "type": "git",
            "value": "recommendation-surface-r1",
            "repository": "https://github.com/sergii/causcope",
        },
        "incident_id": "INC-RECOMMENDATION-SURFACE-001",
        "recommendation_id": "recommendation.database.denormalize_read_model",
        "subject_resource": "db.orders.prod",
        "provider_instance": "provider.pgbot.orders-prod",
        "state": "INSUFFICIENT_CONTEXT",
        "human_approval_required": True,
        "causal_basis": {
            "observation": "observation.database.query_latency",
            "evidence_id": "evidence.query.orders-summary",
            "query_object": "query:orders-summary",
            "source_name": "pgbot",
            "source_uri": "provider-instance:provider.pgbot.orders-prod",
        },
        "problem": {
            "query_object": "query:orders-summary",
            "request_path": "GET /reports/orders-summary",
            "read_frequency_per_minute": 120,
            "query_contribution": "dominant",
        },
        "proposed_change": {
            "type": "materialized_projection",
            "description": "Precompute the orders summary for the dominant reporting path.",
        },
        "missing_assumptions": [
            "business_semantics",
            "maintenance",
            "cost",
            "verification",
        ],
        "limitations": [
            "PostgreSQL query-latency evidence does not by itself justify denormalization."
        ],
    }


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI), *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="causcope-recommendation-") as temporary:
        projection_path = Path(temporary) / "recommendation.json"
        projection_path.write_text(
            json.dumps(recommendation_fixture(), indent=2) + "\n",
            encoding="utf-8",
        )

        rendered = run("recommendation", "--projection", str(projection_path))
        assert "State: INSUFFICIENT_CONTEXT" in rendered.stdout
        assert "Decision status: INFORMATION_GAP" in rendered.stdout
        assert "Blocked by:" in rendered.stdout
        assert "information_gap.business_semantics.consistency_contract" in rendered.stdout
        assert "Kind: operator_question" in rendered.stdout
        assert "source of truth" in rendered.stdout
        assert "This surface does not execute probes" in rendered.stdout

        structured = run(
            "recommendation",
            "--projection",
            str(projection_path),
            "--json",
        )
        gaps = json.loads(structured.stdout)
        assert gaps["kind"] == "recommendation_information_gap_projection"
        assert gaps["recommendation_state"] == "INSUFFICIENT_CONTEXT"
        assert gaps["status"] == "INFORMATION_GAP"
        assert gaps["next_action"]["kind"] == "operator_question"
        assert gaps["next_action"]["gap_id"] == (
            "information_gap.business_semantics.consistency_contract"
        )

        stale = recommendation_fixture()
        stale["state"] = "NO_PROBLEM_EVIDENCE"
        stale["causal_basis"].pop("evidence_id")
        stale["causal_basis"].pop("source_name")
        stale["causal_basis"].pop("source_uri")
        stale_path = Path(temporary) / "stale.json"
        stale_path.write_text(json.dumps(stale, indent=2) + "\n", encoding="utf-8")

        stale_rendered = run("recommendation", "--projection", str(stale_path))
        assert "Decision status: EVIDENCE_REFRESH_REQUIRED" in stale_rendered.stdout
        assert "Kind: read_only_probe" in stale_rendered.stdout
        assert "Probe: probe.database.measure_query_latency" in stale_rendered.stdout
        assert "Target: db.orders.prod" in stale_rendered.stdout
        assert "does not execute the probe" in stale_rendered.stdout

    print("Causcope recommendation investigator CLI: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

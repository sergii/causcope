#!/usr/bin/env python3

from __future__ import annotations

import unittest
from pathlib import Path

from causal_projection import load_concepts, load_edges
from causal_ranking import rank_causes
from probe_ranking import rank_probes

ROOT = Path(__file__).resolve().parents[1]

POSTGRESQL_HEALTH_HYPOTHESES = {
    "hypothesis.database.lock_contention",
    "hypothesis.database.long_running_transaction",
    "hypothesis.database.autovacuum_pressure",
}

POSTGRESQL_HEALTH_PROBES = {
    "probe.database.inspect_lock_waits",
    "probe.database.inspect_long_running_transactions",
    "probe.database.inspect_vacuum_health",
}


class PostgreSQLHealthCausalRankingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.edges = load_edges(ROOT)
        cls.concepts = load_concepts(ROOT)

    def request_latency_ranking(
        self,
        *,
        observed: set[str] | None = None,
        absent: set[str] | None = None,
    ) -> dict:
        return rank_causes(
            "observation.http.request_latency",
            self.edges,
            self.concepts,
            observed=observed,
            absent=absent,
        )

    def test_postgresql_health_hypotheses_are_reachable_from_request_latency(self) -> None:
        ranking = self.request_latency_ranking()
        candidate_ids = {
            candidate["source"]["id"] for candidate in ranking["candidates"]
        }

        self.assertTrue(
            POSTGRESQL_HEALTH_HYPOTHESES.issubset(candidate_ids),
            f"missing PostgreSQL health candidates: "
            f"{sorted(POSTGRESQL_HEALTH_HYPOTHESES - candidate_ids)}",
        )

    def test_postgresql_health_probes_are_real_discriminating_questions(self) -> None:
        projection = rank_probes(self.request_latency_ranking(), self.concepts)
        probe_ids = {candidate["probe"]["id"] for candidate in projection["probes"]}

        self.assertTrue(
            POSTGRESQL_HEALTH_PROBES.issubset(probe_ids),
            f"missing PostgreSQL health discriminators: "
            f"{sorted(POSTGRESQL_HEALTH_PROBES - probe_ids)}",
        )
        for candidate in projection["probes"]:
            if candidate["probe"]["id"] in POSTGRESQL_HEALTH_PROBES:
                self.assertEqual("read_only", candidate["risk"])
                self.assertTrue(candidate["factors"]["discriminating_observations"])

    def test_resolving_one_health_question_leaves_other_health_questions_rankable(self) -> None:
        first = rank_probes(self.request_latency_ranking(), self.concepts)
        first_ids = {candidate["probe"]["id"] for candidate in first["probes"]}
        self.assertTrue(POSTGRESQL_HEALTH_PROBES.issubset(first_ids))

        resolved_probe = self.concepts["probe.database.inspect_long_running_transactions"]
        observed = set(resolved_probe["produces"])
        second = rank_probes(
            self.request_latency_ranking(observed=observed),
            self.concepts,
        )
        second_ids = {candidate["probe"]["id"] for candidate in second["probes"]}

        self.assertNotIn("probe.database.inspect_long_running_transactions", second_ids)
        self.assertIn("probe.database.inspect_lock_waits", second_ids)
        self.assertIn("probe.database.inspect_vacuum_health", second_ids)


if __name__ == "__main__":
    unittest.main()

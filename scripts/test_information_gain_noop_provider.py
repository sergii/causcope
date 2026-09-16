#!/usr/bin/env python3

from __future__ import annotations

import unittest

from information_gain_router import InformationGainInstrumentRouter

PROBE_ID = "probe.database.inspect_lock_waits"
TARGET_RESOURCE = "db.orders.prod"
PROVIDER_INSTANCE = "provider.postgresql-health.orders-prod"

PROBE_CANDIDATE = {
    "probe": {"id": PROBE_ID},
    "factors": {"top_candidate": "hypothesis.database.lock_contention"},
    "outcome_analysis": [
        {
            "observation": "observation.database.lock_wait_time",
            "observed_distinguishes_pairs": [
                [
                    "hypothesis.database.lock_contention",
                    "hypothesis.database.long_running_transaction",
                ]
            ],
            "absent_distinguishes_pairs": [
                [
                    "hypothesis.database.lock_contention",
                    "hypothesis.database.long_running_transaction",
                ]
            ],
        }
    ],
}


class FakeBaseRouter:
    def route(self, probe_id, scope, *, execution_requirement, target_resource):
        return {
            "probe": {"id": probe_id, "title": "Inspect database lock waits", "risk": "read_only"},
            "scope": scope,
            "selection": {"instrument": {"id": PROVIDER_INSTANCE}},
            "stop_reason": None,
            "candidates": [
                {
                    "instrument": {
                        "id": PROVIDER_INSTANCE,
                        "kind": "diagnostic_provider",
                        "execution_mode": "direct",
                        "provider_type": "provider.postgresql.health",
                        "target_resource": target_resource,
                    },
                    "eligible": True,
                    "reasons": ["safe exact-target direct provider"],
                }
            ],
        }


class PartialCoverageProvider:
    def capability_projection(self):
        return {
            "id": "provider.postgresql.health",
            "evidence_semantics": {"complete_snapshot": True},
            "probes": [
                {
                    "probe": {"id": PROBE_ID},
                    "mapped_observations": [
                        "observation.database.blocking_chain",
                        "observation.database.lock_wait_event",
                    ],
                }
            ],
        }


class InformationGainNoopProviderTest(unittest.TestCase):
    def test_safe_provider_is_not_selected_when_it_cannot_answer_any_remaining_discriminator(self) -> None:
        router = InformationGainInstrumentRouter(
            router=FakeBaseRouter(),
            provider_instance_bindings={PROVIDER_INSTANCE: PartialCoverageProvider()},
        )

        decision = router.route(
            PROBE_CANDIDATE,
            {"attributes": {"dependency": "postgresql"}},
            target_resource=TARGET_RESOURCE,
            execution_requirement="direct",
        )

        self.assertIsNone(decision["selection"])
        self.assertEqual("no_informative_provider", decision["stop_reason"])
        self.assertEqual(1, len(decision["provider_candidates"]))
        gain = decision["provider_candidates"][0]["information_gain_proxy"]
        self.assertEqual([], gain["discriminating_observations"])
        self.assertEqual([], gain["discriminated_candidate_pairs"])


if __name__ == "__main__":
    unittest.main()

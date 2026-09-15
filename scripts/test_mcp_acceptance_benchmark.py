#!/usr/bin/env python3

from __future__ import annotations

import unittest

from run_mcp_acceptance_benchmark import matching_route, public_failing_scope


class McpAcceptanceBenchmarkTest(unittest.TestCase):
    def test_public_failing_scope_is_derived_without_oracle(self) -> None:
        scenario = {
            "verification": [
                {
                    "method": "POST",
                    "path": "/orders",
                    "headers": {
                        "X-Client-Platform": "web",
                        "X-App-Version": "2026.09",
                    },
                    "expect_status": 201,
                },
                {
                    "method": "POST",
                    "path": "/orders",
                    "headers": {
                        "X-Client-Platform": "iOS",
                        "X-App-Version": "7.42.0",
                    },
                    "expect_status": 422,
                },
            ]
        }
        self.assertEqual(
            {
                "attributes": {
                    "method": "POST",
                    "path": "/orders",
                    "client_platform": "iOS",
                    "app_version": "7.42.0",
                }
            },
            public_failing_scope(scenario),
        )

    def test_agent_selects_only_exact_public_scope_with_mcp_execution(self) -> None:
        wanted = {
            "attributes": {
                "method": "POST",
                "path": "/orders",
                "client_platform": "iOS",
                "app_version": "7.42.0",
            }
        }
        executable = {
            "scope": wanted,
            "target": "observation.http.request_failure",
            "probe_id": "probe.http.compare_client_cohorts",
            "probe_rank": 2,
            "decision": {
                "selected_instrument": {"id": "provider.shop.structured_logs"}
            },
            "agent_action": {"mcp_execution_available": True},
        }
        wrong_scope = {
            **executable,
            "scope": {
                "attributes": {
                    "method": "POST",
                    "path": "/orders",
                    "client_platform": "web",
                    "app_version": "2026.09",
                }
            },
        }
        disabled = {
            **executable,
            "agent_action": {"mcp_execution_available": False},
        }
        routing = {"routes": [wrong_scope, disabled, executable]}
        self.assertEqual(executable, matching_route(routing, wanted))


if __name__ == "__main__":
    unittest.main()

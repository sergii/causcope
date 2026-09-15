#!/usr/bin/env python3

from __future__ import annotations

import unittest

from run_openai_mcp_acceptance_benchmark import public_failing_scope, validate_result


class OpenAIMcpAcceptanceBenchmarkTest(unittest.TestCase):
    def test_public_failing_scope_is_derived_from_public_verification(self) -> None:
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

    def test_schema_accepts_openai_backed_surface(self) -> None:
        result = {
            "schema_version": "0.1",
            "kind": "acceptance_benchmark_result",
            "benchmark_id": "benchmark.shop.mobile_bad_payload.openai_mcp",
            "surface": "openai_mcp_agent",
            "scenario_id": "scenario.shop.mobile_bad_payload",
            "incident_id": "incident.test.openai_mcp",
            "llm": {
                "enabled": True,
                "provider": "openai",
                "model": "gpt-5.6-luna",
                "credential_environment_removed": [
                    "ANTHROPIC_API_KEY",
                    "GEMINI_API_KEY",
                    "GOOGLE_API_KEY",
                    "OPENAI_API_KEY",
                ],
                "api_key_exposed_to_testbed_children": False,
                "response_ids": ["resp_1", "resp_2"],
                "usage": {
                    "response_count": 2,
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                },
            },
            "oracle_policy": {
                "loaded_after_investigation": True,
                "used_to_construct_diagnosis": False,
            },
            "expectations": {},
            "observed": {},
            "checks": [
                {
                    "id": "synthetic",
                    "passed": True,
                    "expected": True,
                    "actual": True,
                }
            ],
            "passed": True,
        }
        validate_result(result)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3

from __future__ import annotations

import json
import unittest

from openai_mcp_client import run_openai_mcp_client


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def create(self, payload):
        self.requests.append(payload)
        if not self.responses:
            raise AssertionError("unexpected OpenAI request")
        return self.responses.pop(0)


class OpenAIMcpClientTest(unittest.TestCase):
    def test_tool_driven_loop_uses_previous_response_id_and_finishes_explicitly(self) -> None:
        transport = FakeTransport(
            [
                {
                    "id": "resp_1",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_1",
                            "name": "mcp_list_resources",
                            "arguments": "{}",
                        },
                        {
                            "type": "function_call",
                            "call_id": "call_2",
                            "name": "mcp_list_tools",
                            "arguments": "{}",
                        },
                    ],
                    "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                },
                {
                    "id": "resp_2",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_3",
                            "name": "mcp_read_resource",
                            "arguments": json.dumps({"uri": "causcope://diagnosis/instrument-routing"}),
                        }
                    ],
                    "usage": {"input_tokens": 80, "output_tokens": 10, "total_tokens": 90},
                },
                {
                    "id": "resp_3",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_4",
                            "name": "mcp_call_tool",
                            "arguments": json.dumps(
                                {
                                    "name": "causcope.instrument.execute_ranked_routable",
                                    "arguments": {"evidenceRevision": 1},
                                }
                            ),
                        }
                    ],
                    "usage": {"input_tokens": 70, "output_tokens": 12, "total_tokens": 82},
                },
                {
                    "id": "resp_4",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_5",
                            "name": "finish_investigation",
                            "arguments": json.dumps({"reason": "No executable route remains"}),
                        }
                    ],
                    "usage": {"input_tokens": 50, "output_tokens": 8, "total_tokens": 58},
                },
            ]
        )
        dispatched = []

        def dispatch(name, arguments):
            dispatched.append((name, arguments))
            if name == "mcp_call_tool":
                return {
                    "ok": True,
                    "kind": "ranked_routable_instrument_execution_result",
                    "probe_id": "probe.http.compare_client_cohorts",
                    "evidence_revision": 2,
                }
            return {"ok": True, "kind": name}

        result = run_openai_mcp_client(
            transport=transport,
            dispatch=dispatch,
            public_prompt="Investigate the public incident through Causcope MCP.",
            model="test-model",
            max_turns=6,
        )

        self.assertEqual("model_finished", result["stop_reason"])
        self.assertTrue(result["finish_called"])
        self.assertEqual("No executable route remains", result["finish_reason"])
        self.assertEqual(4, result["usage"]["response_count"])
        self.assertEqual(300, result["usage"]["input_tokens"])
        self.assertEqual(50, result["usage"]["output_tokens"])
        self.assertEqual(350, result["usage"]["total_tokens"])
        self.assertEqual("resp_1", transport.requests[1]["previous_response_id"])
        self.assertEqual("resp_2", transport.requests[2]["previous_response_id"])
        self.assertEqual("resp_3", transport.requests[3]["previous_response_id"])
        self.assertEqual(
            ["mcp_list_resources", "mcp_list_tools", "mcp_read_resource", "mcp_call_tool"],
            [name for name, _arguments in dispatched],
        )

    def test_finish_must_be_called_alone(self) -> None:
        transport = FakeTransport(
            [
                {
                    "id": "resp_1",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_1",
                            "name": "finish_investigation",
                            "arguments": json.dumps({"reason": "done"}),
                        },
                        {
                            "type": "function_call",
                            "call_id": "call_2",
                            "name": "mcp_list_resources",
                            "arguments": "{}",
                        },
                    ],
                },
                {
                    "id": "resp_2",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_3",
                            "name": "finish_investigation",
                            "arguments": json.dumps({"reason": "done after inspection"}),
                        }
                    ],
                },
            ]
        )
        dispatched = []

        result = run_openai_mcp_client(
            transport=transport,
            dispatch=lambda name, arguments: dispatched.append((name, arguments)) or {"ok": True},
            public_prompt="Investigate.",
            model="test-model",
            max_turns=3,
        )

        self.assertTrue(result["finish_called"])
        self.assertEqual("done after inspection", result["finish_reason"])
        rejected = next(
            item
            for item in result["function_calls"]
            if item["name"] == "finish_investigation" and item["status"] == "rejected"
        )
        self.assertIsNotNone(rejected)
        self.assertEqual(["mcp_list_resources"], [name for name, _arguments in dispatched])

    def test_plain_text_without_finish_is_a_bounded_stop(self) -> None:
        transport = FakeTransport(
            [
                {
                    "id": "resp_1",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "I think the issue is clear."}],
                        }
                    ],
                }
            ]
        )
        result = run_openai_mcp_client(
            transport=transport,
            dispatch=lambda _name, _arguments: {"ok": True},
            public_prompt="Investigate.",
            model="test-model",
        )
        self.assertFalse(result["finish_called"])
        self.assertEqual("model_returned_without_finish", result["stop_reason"])
        self.assertEqual("I think the issue is clear.", result["final_text"])


if __name__ == "__main__":
    unittest.main()

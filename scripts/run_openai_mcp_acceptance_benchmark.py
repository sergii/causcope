#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SHOP_ROOT = ROOT / "testbed" / "shop"
if str(SHOP_ROOT) not in sys.path:
    sys.path.insert(0, str(SHOP_ROOT))

from causal_projection import load_concepts, load_edges
from diagnosis_http_api import DiagnosisSnapshotReader
from diagnosis_mcp_server import (
    CLIENT_CAPABILITIES_META_KEY,
    CURRENT_DIAGNOSIS_URI,
    MODERN_PROTOCOL_VERSION,
    PROTOCOL_VERSION_META_KEY,
)
from instrument_router import InstrumentRouter
from live_diagnosis import build_diagnosis_snapshot
from openai_mcp_client import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MAX_TURNS,
    DEFAULT_MODEL,
    OpenAIResponsesHTTPTransport,
    default_transport_from_env,
    run_openai_mcp_client,
)
from probe_executor_runtime import build_probe_execution_capabilities
from ranked_routable_mcp_tool import RankedRoutableInstrumentToolController
from ranked_routable_projection import build_ranked_routable_projection
from routing_mcp_server import RoutingDiagnosisMcpServer
from run_acceptance_benchmark import (
    AI_CREDENTIAL_ENV_KEYS,
    deterministic_env,
    load_json,
    run,
    score_summary,
)
from runtime_evidence import validate_runtime_references
from structured_log_evidence import build_runtime_evidence_from_logs, parse_structured_events
from causcope_bridge import collect_app_logs, summarize, utc_now, _timestamp
from routed_probe_provider import ShopRoutedProbeProvider

TESTBED = SHOP_ROOT / "testbed.py"
CAUSCOPE = ROOT / "bin" / "causcope"
SCENARIO_SLUG = "mobile-bad-payload"
SCENARIO_DIR = SHOP_ROOT / "scenarios" / SCENARIO_SLUG
RESULT_SCHEMA = ROOT / "schema" / "acceptance-benchmark-result.schema.json"
DEFAULT_WORKSPACE = ROOT / ".causcope-openai-mcp-benchmark"


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def modern_meta() -> dict[str, Any]:
    return {
        PROTOCOL_VERSION_META_KEY: MODERN_PROTOCOL_VERSION,
        CLIENT_CAPABILITIES_META_KEY: {},
    }


def public_failing_scope(scenario: dict[str, Any]) -> dict[str, Any]:
    failures = [
        check
        for check in scenario.get("verification", [])
        if isinstance(check, dict)
        and isinstance(check.get("expect_status"), int)
        and check["expect_status"] >= 400
    ]
    if len(failures) != 1:
        raise ValueError("OpenAI MCP benchmark requires exactly one public failing verification request")
    check = failures[0]
    headers = check.get("headers", {})
    attributes = {
        "method": str(check["method"]),
        "path": str(check["path"]),
    }
    if isinstance(headers, dict):
        if isinstance(headers.get("X-Client-Platform"), str):
            attributes["client_platform"] = headers["X-Client-Platform"]
        if isinstance(headers.get("X-App-Version"), str):
            attributes["app_version"] = headers["X-App-Version"]
    return {"attributes": attributes}


def build_initial_state(
    *,
    workspace: Path,
    incident_id: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]], str]:
    raw_logs = collect_app_logs()
    events = parse_structured_events(raw_logs)
    now = utc_now()
    evidence = build_runtime_evidence_from_logs(
        events,
        incident_id=incident_id,
        source_name="docker-compose:causcope-shop/app",
        collected_at=_timestamp(now),
        include_derived_findings=False,
    )
    concepts = load_concepts(ROOT)
    validate_runtime_references(evidence, concepts)
    edges = load_edges(ROOT)
    diagnosis = build_diagnosis_snapshot(
        evidence,
        concepts,
        edges,
        as_of=now,
        evidence_revision=1,
    )
    write_json(workspace / "runtime-evidence.json", evidence)
    write_json(workspace / "diagnosis.json", diagnosis)
    write_json(workspace / "initial-runtime-evidence.json", evidence)
    write_json(workspace / "initial-diagnosis.json", diagnosis)
    (workspace / "source-shop-app.log").write_text(raw_logs, encoding="utf-8")
    return events, concepts, edges, _timestamp(now)


def _mcp_result_or_error(response: dict[str, Any]) -> dict[str, Any]:
    error = response.get("error")
    if isinstance(error, dict):
        return {"ok": False, "error": error}
    result = response.get("result")
    if not isinstance(result, dict):
        return {"ok": False, "error": "MCP response is missing result"}
    return result


def build_mcp_bridge(
    *,
    server: RoutingDiagnosisMcpServer,
    completed_steps: list[dict[str, Any]],
):
    request_id = 0

    def request(method: str, params: dict[str, Any]) -> dict[str, Any]:
        nonlocal request_id
        request_id += 1
        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": {**params, "_meta": modern_meta()},
            }
        )
        if not isinstance(response, dict):
            return {"ok": False, "error": "MCP server returned a non-object response"}
        return _mcp_result_or_error(response)

    def dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "mcp_list_resources":
            result = request("resources/list", {})
            if result.get("ok") is False:
                return result
            resources = result.get("resources", [])
            return {"ok": True, "kind": "mcp_resource_list", "resources": resources}

        if name == "mcp_list_tools":
            result = request("tools/list", {})
            if result.get("ok") is False:
                return result
            tools = result.get("tools", [])
            return {"ok": True, "kind": "mcp_tool_list", "tools": tools}

        if name == "mcp_read_resource":
            uri = arguments.get("uri")
            if not isinstance(uri, str) or not uri:
                return {"ok": False, "error": "uri must be a non-empty string"}
            result = request("resources/read", {"uri": uri})
            if result.get("ok") is False:
                return result
            contents = result.get("contents", [])
            if len(contents) != 1 or not isinstance(contents[0], dict):
                return {"ok": False, "error": "MCP resource read returned an invalid content envelope"}
            text = contents[0].get("text")
            if not isinstance(text, str):
                return {"ok": False, "error": "MCP resource content is not JSON text"}
            try:
                document = json.loads(text)
            except json.JSONDecodeError as exc:
                return {"ok": False, "error": f"MCP resource contains invalid JSON: {exc.msg}"}
            return {
                "ok": True,
                "kind": "mcp_resource",
                "uri": uri,
                "document": document,
            }

        if name == "mcp_call_tool":
            tool_name = arguments.get("name")
            tool_arguments = arguments.get("arguments")
            if not isinstance(tool_name, str) or not tool_name:
                return {"ok": False, "error": "MCP tool name must be a non-empty string"}
            if not isinstance(tool_arguments, dict):
                return {"ok": False, "error": "MCP tool arguments must be an object"}
            result = request("tools/call", {"name": tool_name, "arguments": tool_arguments})
            if result.get("ok") is False:
                return result
            if result.get("isError") is True:
                content = result.get("content", [])
                message = None
                if content and isinstance(content[0], dict):
                    message = content[0].get("text")
                return {"ok": False, "error": message or "MCP tool returned an error"}
            structured = result.get("structuredContent")
            if not isinstance(structured, dict):
                return {"ok": False, "error": "MCP tool did not return structuredContent"}
            probe_id = structured.get("probe_id")
            revision = structured.get("evidence_revision")
            if isinstance(probe_id, str) and isinstance(revision, int):
                completed_steps.append(
                    {
                        "index": len(completed_steps) + 1,
                        "status": "completed",
                        "probe_id": probe_id,
                        "probe_rank": structured.get("probe_rank"),
                        "instrument_id": (structured.get("instrument") or {}).get("id"),
                        "previous_evidence_revision": structured.get("previous_evidence_revision"),
                        "evidence_revision": revision,
                        "added_instance_ids": structured.get("added_instance_ids", []),
                    }
                )
            return {"ok": True, **structured}

        return {"ok": False, "error": f"unsupported MCP bridge operation: {name}"}

    return dispatch


def read_current_diagnosis(server: RoutingDiagnosisMcpServer) -> dict[str, Any]:
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 999_999,
            "method": "resources/read",
            "params": {"uri": CURRENT_DIAGNOSIS_URI, "_meta": modern_meta()},
        }
    )
    if "error" in response:
        raise ValueError(f"final MCP diagnosis read failed: {response['error']}")
    contents = response.get("result", {}).get("contents", [])
    if len(contents) != 1 or not isinstance(contents[0].get("text"), str):
        raise ValueError("final MCP diagnosis has an invalid content envelope")
    document = json.loads(contents[0]["text"])
    if not isinstance(document, dict):
        raise ValueError("final MCP diagnosis must be an object")
    return document


def run_openai_agent(
    *,
    workspace: Path,
    incident_id: str,
    public_scope: dict[str, Any],
    public_summary: str,
    transport: OpenAIResponsesHTTPTransport,
    model: str,
    max_turns: int,
    max_output_tokens: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    events, concepts, edges, collected_at = build_initial_state(
        workspace=workspace,
        incident_id=incident_id,
    )
    snapshot_path = workspace / "diagnosis.json"
    evidence_path = workspace / "runtime-evidence.json"
    reader = DiagnosisSnapshotReader(snapshot_path)

    def router_provider() -> InstrumentRouter:
        provider = ShopRoutedProbeProvider(
            events=events,
            incident_id=incident_id,
            collected_at=collected_at,
            concepts=concepts,
            scope=public_scope,
        )
        return InstrumentRouter(
            concepts=concepts,
            host_capabilities=build_probe_execution_capabilities(concepts),
            providers=[provider],
        )

    controller = RankedRoutableInstrumentToolController(
        reader=reader,
        snapshot_path=snapshot_path,
        runtime_evidence_path=evidence_path,
        concepts=concepts,
        edges=edges,
        router_provider=router_provider,
        mutation_lock_dir=workspace / "openai-mcp-mutation-locks",
    )
    server = RoutingDiagnosisMcpServer(
        reader,
        instrument_router_provider=router_provider,
        probe_capability_provider=lambda: build_probe_execution_capabilities(concepts),
        routed_tools=controller,
        routing_projection_provider=lambda snapshot: build_ranked_routable_projection(
            snapshot,
            router_provider(),
        ),
    )

    completed_steps: list[dict[str, Any]] = []
    dispatch = build_mcp_bridge(server=server, completed_steps=completed_steps)
    public_prompt = (
        "Investigate this public incident only through the Causcope MCP bridge.\n\n"
        f"Public incident summary: {public_summary}\n"
        f"Public failing request scope: {json.dumps(public_scope, sort_keys=True)}\n\n"
        "Do not produce an independent diagnosis. Discover Causcope MCP state, request only server-authorized "
        "read-only diagnostic actions, re-read state after each mutation, and explicitly finish when bounded "
        "investigation should stop."
    )
    client_run = run_openai_mcp_client(
        transport=transport,
        dispatch=dispatch,
        public_prompt=public_prompt,
        model=model,
        max_turns=max_turns,
        max_output_tokens=max_output_tokens,
    )

    final_snapshot = read_current_diagnosis(server)
    summary = summarize(final_snapshot)
    summary["autonomous"] = {
        "stop_reason": client_run["stop_reason"],
        "steps": completed_steps,
        "final_evidence_revision": final_snapshot["evidence_revision"],
    }
    write_json(workspace / "openai-mcp-client-run.json", client_run)
    write_json(workspace / "diagnosis-summary.json", summary)
    return summary, client_run


def validate_result(result: dict[str, Any]) -> None:
    schema = load_json(RESULT_SCHEMA)
    errors = sorted(Draft202012Validator(schema).iter_errors(result), key=lambda item: list(item.path))
    if errors:
        raise ValueError(
            "OpenAI MCP acceptance result schema validation failed: "
            + "; ".join(error.message for error in errors)
        )


def run_benchmark(
    *,
    workspace: Path,
    model: str,
    max_turns: int,
    max_output_tokens: int,
    keep_testbed: bool,
    transport: OpenAIResponsesHTTPTransport | None = None,
) -> dict[str, Any]:
    scenario = load_json(SCENARIO_DIR / "scenario.json")
    summary_text = scenario["initial_report"]["summary"]
    public_scope = public_failing_scope(scenario)
    oracle_path = SCENARIO_DIR / scenario["oracle_file"]
    incident_id = "incident.benchmark.mobile_bad_payload.openai_mcp"
    child_env = deterministic_env()
    transport = transport or default_transport_from_env()

    if workspace.exists():
        shutil.rmtree(workspace)
    run([sys.executable, str(TESTBED), "down"], env=child_env)
    run([sys.executable, str(TESTBED), "up"], env=child_env)
    try:
        run(
            [
                str(CAUSCOPE),
                "investigate",
                summary_text,
                "--incident-id",
                incident_id,
                "--workspace",
                str(workspace),
                "--non-interactive",
                "--force",
            ],
            env=child_env,
        )
        run([sys.executable, str(TESTBED), "scenario", "start", SCENARIO_SLUG], env=child_env)
        run([sys.executable, str(TESTBED), "scenario", "verify", SCENARIO_SLUG], env=child_env)
        time.sleep(5)
        summary, client_run = run_openai_agent(
            workspace=workspace,
            incident_id=incident_id,
            public_scope=public_scope,
            public_summary=summary_text,
            transport=transport,
            model=model,
            max_turns=max_turns,
            max_output_tokens=max_output_tokens,
        )

        # Hidden ground truth is intentionally loaded only after the model-driven MCP loop has stopped.
        oracle = load_json(oracle_path)
        passed, checks, observed = score_summary(summary, oracle)
        call_records = client_run.get("function_calls", [])
        successful_bridge_calls = [
            item for item in call_records
            if isinstance(item, dict) and item.get("status") == "completed"
        ]
        mcp_tool_errors = [
            item for item in call_records
            if isinstance(item, dict)
            and item.get("name") == "mcp_call_tool"
            and item.get("status") != "completed"
        ]
        client_checks = [
            {
                "id": "openai_client_explicit_finish",
                "passed": client_run.get("finish_called") is True,
                "expected": True,
                "actual": client_run.get("finish_called"),
            },
            {
                "id": "openai_client_used_mcp_state",
                "passed": any(
                    item.get("name") in {"mcp_list_resources", "mcp_read_resource", "mcp_list_tools"}
                    for item in successful_bridge_calls
                ),
                "expected": True,
                "actual": [item.get("name") for item in successful_bridge_calls],
            },
            {
                "id": "openai_client_no_failed_mcp_mutation",
                "passed": not mcp_tool_errors,
                "expected": 0,
                "actual": len(mcp_tool_errors),
            },
        ]
        checks.extend(client_checks)
        passed = passed and all(check["passed"] for check in client_checks)
        observed.update(
            {
                "openai_stop_reason": client_run.get("stop_reason"),
                "openai_finish_reason": client_run.get("finish_reason"),
                "openai_function_calls": [
                    {
                        "turn": item.get("turn"),
                        "name": item.get("name"),
                        "status": item.get("status"),
                        "result_kind": item.get("result_kind"),
                    }
                    for item in call_records
                    if isinstance(item, dict)
                ],
                "mcp_tool_calls": [
                    step["probe_id"]
                    for step in summary.get("autonomous", {}).get("steps", [])
                    if isinstance(step, dict) and isinstance(step.get("probe_id"), str)
                ],
            }
        )
        result = {
            "schema_version": "0.1",
            "kind": "acceptance_benchmark_result",
            "benchmark_id": "benchmark.shop.mobile_bad_payload.openai_mcp",
            "surface": "openai_mcp_agent",
            "scenario_id": scenario["id"],
            "incident_id": incident_id,
            "llm": {
                "enabled": True,
                "provider": "openai",
                "model": model,
                "credential_environment_removed": sorted(AI_CREDENTIAL_ENV_KEYS),
                "api_key_exposed_to_testbed_children": False,
                "response_ids": client_run.get("response_ids", []),
                "usage": client_run.get("usage", {}),
            },
            "oracle_policy": {
                "loaded_after_investigation": True,
                "used_to_construct_diagnosis": False,
            },
            "expectations": oracle["expected_causcope"],
            "observed": observed,
            "checks": checks,
            "passed": passed,
        }
        validate_result(result)
        return result
    finally:
        try:
            run([sys.executable, str(TESTBED), "scenario", "stop", SCENARIO_SLUG], env=child_env)
        except ValueError:
            pass
        if not keep_testbed:
            try:
                run([sys.executable, str(TESTBED), "down"], env=child_env)
            except ValueError:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the blind OpenAI-backed MCP-agent Causcope acceptance benchmark. "
            "This command makes paid OpenAI API requests and is intentionally opt-in."
        )
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("CAUSCOPE_OPENAI_MODEL", DEFAULT_MODEL),
        help="OpenAI model ID; defaults to CAUSCOPE_OPENAI_MODEL or a cost-sensitive model",
    )
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--keep-testbed", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.max_turns <= 32:
        print("OpenAI MCP acceptance benchmark: --max-turns must be between 1 and 32", file=sys.stderr)
        return 2
    if not 128 <= args.max_output_tokens <= 8192:
        print(
            "OpenAI MCP acceptance benchmark: --max-output-tokens must be between 128 and 8192",
            file=sys.stderr,
        )
        return 2
    try:
        result = run_benchmark(
            workspace=args.workspace.expanduser().resolve(),
            model=args.model,
            max_turns=args.max_turns,
            max_output_tokens=args.max_output_tokens,
            keep_testbed=args.keep_testbed,
        )
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(f"OpenAI MCP acceptance benchmark: {error}", file=sys.stderr)
        return 2

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.result:
        result_path = args.result.expanduser().resolve()
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

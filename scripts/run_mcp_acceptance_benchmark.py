#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
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
from probe_executor_runtime import build_probe_execution_capabilities
from routed_instrument_mcp_tool import TOOL_NAME, RoutedInstrumentToolController
from routing_mcp_server import ROUTED_AGENT_PLAN_URI, RoutingDiagnosisMcpServer
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
DEFAULT_WORKSPACE = ROOT / ".causcope-mcp-benchmark"
TARGET = "observation.http.request_failure"


def write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def modern_meta() -> dict[str, Any]:
    return {
        PROTOCOL_VERSION_META_KEY: MODERN_PROTOCOL_VERSION,
        CLIENT_CAPABILITIES_META_KEY: {},
    }


def read_mcp_resource(server: RoutingDiagnosisMcpServer, uri: str, request_id: int) -> dict[str, Any]:
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "resources/read",
            "params": {"uri": uri, "_meta": modern_meta()},
        }
    )
    if "error" in response:
        raise ValueError(f"MCP resource read failed: {response['error']}")
    contents = response.get("result", {}).get("contents", [])
    if len(contents) != 1 or not isinstance(contents[0].get("text"), str):
        raise ValueError(f"MCP resource {uri} returned an invalid content envelope")
    document = json.loads(contents[0]["text"])
    if not isinstance(document, dict):
        raise ValueError(f"MCP resource {uri} must contain a JSON object")
    return document


def call_mcp_tool(
    server: RoutingDiagnosisMcpServer,
    arguments: dict[str, Any],
    request_id: int,
) -> dict[str, Any]:
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": TOOL_NAME,
                "arguments": arguments,
                "_meta": modern_meta(),
            },
        }
    )
    if "error" in response:
        raise ValueError(f"MCP tool protocol error: {response['error']}")
    result = response.get("result", {})
    if result.get("isError") is True:
        text = result.get("content", [{}])[0].get("text", "unknown MCP tool error")
        raise ValueError(f"MCP routed tool failed: {text}")
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        raise ValueError("MCP routed tool did not return structuredContent")
    return structured


def public_failing_scope(scenario: dict[str, Any]) -> dict[str, Any]:
    failures = [
        check
        for check in scenario.get("verification", [])
        if isinstance(check, dict)
        and isinstance(check.get("expect_status"), int)
        and check["expect_status"] >= 400
    ]
    if len(failures) != 1:
        raise ValueError("MCP benchmark requires exactly one public failing verification request")
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


def matching_route(plan: dict[str, Any], wanted_scope: dict[str, Any]) -> dict[str, Any] | None:
    wanted_attributes = wanted_scope["attributes"]
    matches = []
    for route in plan.get("routing", {}).get("routes", []):
        if route.get("target") != TARGET:
            continue
        attributes = (route.get("scope") or {}).get("attributes", {})
        if attributes != wanted_attributes:
            continue
        if route.get("agent_action", {}).get("mcp_execution_available") is not True:
            continue
        selection = route.get("decision", {}).get("selected_instrument")
        if not isinstance(selection, dict):
            continue
        matches.append(route)
    if len(matches) > 1:
        raise ValueError("MCP agent found multiple executable routes for the public failing scope")
    return matches[0] if matches else None


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


def run_mcp_agent(
    *,
    workspace: Path,
    incident_id: str,
    public_scope: dict[str, Any],
    max_steps: int,
) -> dict[str, Any]:
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

    controller = RoutedInstrumentToolController(
        reader=reader,
        snapshot_path=snapshot_path,
        runtime_evidence_path=evidence_path,
        concepts=concepts,
        edges=edges,
        router_provider=router_provider,
        mutation_lock_dir=workspace / "mcp-mutation-locks",
    )
    server = RoutingDiagnosisMcpServer(
        reader,
        instrument_router_provider=router_provider,
        probe_capability_provider=lambda: build_probe_execution_capabilities(concepts),
        routed_tools=controller,
    )

    steps: list[dict[str, Any]] = []
    request_id = 1
    stop_reason = "max_steps"
    for index in range(1, max_steps + 1):
        plan = read_mcp_resource(server, ROUTED_AGENT_PLAN_URI, request_id)
        request_id += 1
        route = matching_route(plan, public_scope)
        if route is None:
            stop_reason = "no_executable_route"
            break
        instrument = route["decision"]["selected_instrument"]
        arguments = {
            "incidentId": plan["incident_id"],
            "evidenceRevision": plan["evidence_revision"],
            "target": route["target"],
            "scope": route["scope"],
            "probeId": route["probe_id"],
            "instrumentId": instrument["id"],
        }
        execution = call_mcp_tool(server, arguments, request_id)
        request_id += 1
        steps.append(
            {
                "index": index,
                "status": "completed",
                "probe_id": route["probe_id"],
                "instrument_id": instrument["id"],
                "previous_evidence_revision": execution["previous_evidence_revision"],
                "evidence_revision": execution["evidence_revision"],
                "added_instance_ids": execution["added_instance_ids"],
            }
        )
    final_snapshot = read_mcp_resource(server, CURRENT_DIAGNOSIS_URI, request_id)
    summary = summarize(final_snapshot)
    summary["autonomous"] = {
        "stop_reason": stop_reason,
        "steps": steps,
        "final_evidence_revision": final_snapshot["evidence_revision"],
    }
    write_json(workspace / "mcp-agent-run.json", summary["autonomous"])
    write_json(workspace / "diagnosis-summary.json", summary)
    return summary


def validate_result(result: dict[str, Any]) -> None:
    schema = load_json(RESULT_SCHEMA)
    errors = sorted(Draft202012Validator(schema).iter_errors(result), key=lambda item: list(item.path))
    if errors:
        raise ValueError(
            "MCP acceptance result schema validation failed: "
            + "; ".join(error.message for error in errors)
        )


def run_benchmark(*, workspace: Path, max_steps: int, keep_testbed: bool) -> dict[str, Any]:
    scenario = load_json(SCENARIO_DIR / "scenario.json")
    summary_text = scenario["initial_report"]["summary"]
    public_scope = public_failing_scope(scenario)
    oracle_path = SCENARIO_DIR / scenario["oracle_file"]
    incident_id = "incident.benchmark.mobile_bad_payload.mcp"
    env = deterministic_env()

    if workspace.exists():
        shutil.rmtree(workspace)
    run([sys.executable, str(TESTBED), "down"], env=env)
    run([sys.executable, str(TESTBED), "up"], env=env)
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
            env=env,
        )
        run([sys.executable, str(TESTBED), "scenario", "start", SCENARIO_SLUG], env=env)
        run([sys.executable, str(TESTBED), "scenario", "verify", SCENARIO_SLUG], env=env)
        time.sleep(5)
        summary = run_mcp_agent(
            workspace=workspace,
            incident_id=incident_id,
            public_scope=public_scope,
            max_steps=max_steps,
        )

        # Hidden ground truth is intentionally unavailable until the MCP agent has stopped.
        oracle = load_json(oracle_path)
        passed, checks, observed = score_summary(summary, oracle)
        result = {
            "schema_version": "0.1",
            "kind": "acceptance_benchmark_result",
            "benchmark_id": "benchmark.shop.mobile_bad_payload.deterministic_mcp",
            "surface": "deterministic_mcp_agent",
            "scenario_id": scenario["id"],
            "incident_id": incident_id,
            "llm": {
                "enabled": False,
                "credential_environment_removed": sorted(AI_CREDENTIAL_ENV_KEYS),
            },
            "oracle_policy": {
                "loaded_after_investigation": True,
                "used_to_construct_diagnosis": False,
            },
            "expectations": oracle["expected_causcope"],
            "observed": {
                **observed,
                "mcp_tool_calls": [step["probe_id"] for step in summary["autonomous"]["steps"]],
            },
            "checks": checks,
            "passed": passed,
        }
        validate_result(result)
        return result
    finally:
        try:
            run([sys.executable, str(TESTBED), "scenario", "stop", SCENARIO_SLUG], env=env)
        except ValueError:
            pass
        if not keep_testbed:
            try:
                run([sys.executable, str(TESTBED), "down"], env=env)
            except ValueError:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the blind deterministic MCP-agent Causcope acceptance benchmark."
    )
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--max-steps", type=int, default=4)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--keep-testbed", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.max_steps <= 16:
        print("MCP acceptance benchmark: --max-steps must be between 1 and 16", file=sys.stderr)
        return 2
    try:
        result = run_benchmark(
            workspace=args.workspace.expanduser().resolve(),
            max_steps=args.max_steps,
            keep_testbed=args.keep_testbed,
        )
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(f"MCP acceptance benchmark: {error}", file=sys.stderr)
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

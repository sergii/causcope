#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any, Callable

from agent_plan_recovery import build_agent_plan_projection
from causal_projection import ROOT, load_concepts, load_edges
from diagnosis_http_api import DiagnosisSnapshotReader
from diagnosis_mcp_server import (
    DiagnosisMcpServer,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    McpProtocolError,
    serve_stdio,
)
from instrument_router import InstrumentRouter
from instrument_routing_projection import (
    build_instrument_routing_projection,
    validate_instrument_routing_projection,
)
from pgbot_adapter import load_adapter
from pgbot_autonomous_provider import PgbotAutonomousProbeProvider, file_context_supplier
from probe_executor_runtime import build_probe_execution_capabilities
from routed_agent_plan import build_routed_agent_plan
from routed_execution_set_mcp_tool import RoutedExecutionSetInvocationError
from routed_execution_set_status import build_execution_set_status
from routed_execution_sets import build_routed_execution_sets
from routed_instrument_mcp_tool import (
    RoutedInstrumentInvocationError,
    RoutedInstrumentToolController,
)

INSTRUMENT_ROUTING_URI = "causcope://diagnosis/instrument-routing"
ROUTED_AGENT_PLAN_URI = "causcope://diagnosis/routed-agent-plan"
EXECUTION_SET_STATUS_URI = "causcope://diagnosis/execution-set-status"

RouterProvider = Callable[[], InstrumentRouter]
RoutingProjectionProvider = Callable[[dict[str, Any]], dict[str, Any]]


class RoutingDiagnosisMcpServer(DiagnosisMcpServer):
    """MCP adapter that exposes routing and optionally exact routed direct execution."""

    def __init__(
        self,
        reader: DiagnosisSnapshotReader,
        *,
        instrument_router_provider: RouterProvider,
        probe_capability_provider: Callable[[], dict[str, Any]] | None = None,
        routed_tools: Any | None = None,
        routing_projection_provider: RoutingProjectionProvider | None = None,
        execution_set_state_dir: Path | None = None,
    ) -> None:
        super().__init__(
            reader,
            probe_capability_provider=probe_capability_provider,
        )
        self.instrument_router_provider = instrument_router_provider
        self.routed_tools = routed_tools
        self.routing_projection_provider = routing_projection_provider
        self.execution_set_state_dir = (
            execution_set_state_dir
            if execution_set_state_dir is not None
            else reader.snapshot_path.parent / "execution-sets"
        )

    def _capabilities(self) -> dict[str, Any]:
        capabilities = super()._capabilities()
        if self.routed_tools is not None:
            capabilities["tools"] = {}
        return capabilities

    def _instructions(self) -> str:
        instructions = (
            super()._instructions()
            + f" Read {INSTRUMENT_ROUTING_URI} to see which safe instrument, if any, can execute "
            "each current top-ranked canonical probe without changing semantic probe rank."
            + f" Read {ROUTED_AGENT_PLAN_URI} for the compatibility agent plan, routing projection, "
            "and any current bounded target execution sets in one validated envelope."
            + f" Read {EXECUTION_SET_STATUS_URI} for operator-facing lifecycle state of current and "
            "historical durable execution sets without reading raw journal JSONL."
        )
        if self.routed_tools is not None:
            instructions += (
                " Revision-bound routed tools are enabled. Execute only the exact route or execution set "
                "advertised by the current routed agent plan; stale incident revisions, probes, scopes, "
                "targets, instruments, or set identities fail closed."
            )
        else:
            instructions += " External-provider routes are read-only advisory in this process."
        return instructions

    def _resource_descriptors(self, *, modern: bool) -> list[dict[str, Any]]:
        resources = super()._resource_descriptors(modern=modern)
        additions = [
            {
                "uri": INSTRUMENT_ROUTING_URI,
                "name": "instrument_routing",
                "description": (
                    "Projection of instrument routing decisions for each current top-ranked canonical "
                    "probe. Routing filters by safety, availability, exact scope compatibility, and "
                    "execution mode; it never reranks hypotheses or probes."
                ),
                "mimeType": "application/json",
            },
            {
                "uri": ROUTED_AGENT_PLAN_URI,
                "name": "routed_agent_plan",
                "description": (
                    "Validated envelope containing the compatibility agent plan, current routing, and "
                    "first-class bounded execution sets for the same incident and evidence revision."
                ),
                "mimeType": "application/json",
            },
            {
                "uri": EXECUTION_SET_STATUS_URI,
                "name": "execution_set_status",
                "description": (
                    "Read-only operator projection of pending, in-progress, ready-to-commit, committed, "
                    "and stranded routed execution sets derived from the current plan and verified durable journals."
                ),
                "mimeType": "application/json",
            },
        ]
        if modern:
            additions[0]["title"] = "Causcope instrument routing"
            additions[1]["title"] = "Causcope routed agent plan"
            additions[2]["title"] = "Causcope execution-set status"
        return sorted(resources + additions, key=lambda resource: resource["uri"])

    def _router(self, uri: str) -> InstrumentRouter:
        try:
            return self.instrument_router_provider()
        except (OSError, ValueError) as exc:
            raise McpProtocolError(
                INTERNAL_ERROR,
                f"instrument router discovery failed: {exc}",
                data={"uri": uri},
            ) from exc

    def _routing_projection(
        self,
        snapshot: dict[str, Any],
        router: InstrumentRouter,
    ) -> dict[str, Any]:
        if self.routing_projection_provider is None:
            return build_instrument_routing_projection(
                snapshot,
                router,
                external_mcp_execution_enabled=self.routed_tools is not None,
            )
        projection = self.routing_projection_provider(snapshot)
        validate_instrument_routing_projection(projection)
        if projection.get("incident_id") != snapshot.get("incident_id"):
            raise ValueError("routing projection belongs to another incident")
        if projection.get("evidence_revision") != snapshot.get("evidence_revision"):
            raise ValueError("routing projection revision does not match diagnosis snapshot")
        return projection

    def _read_resource(self, uri: str, *, modern: bool) -> dict[str, Any]:
        if uri not in {
            INSTRUMENT_ROUTING_URI,
            ROUTED_AGENT_PLAN_URI,
            EXECUTION_SET_STATUS_URI,
        }:
            return super()._read_resource(uri, modern=modern)

        snapshot = self._read_snapshot(uri, modern=modern)
        router = self._router(uri)
        try:
            routing = self._routing_projection(snapshot, router)
            if uri == INSTRUMENT_ROUTING_URI:
                document = routing
            elif uri == EXECUTION_SET_STATUS_URI:
                execution_sets = build_routed_execution_sets(routing)
                document = build_execution_set_status(
                    execution_sets,
                    self.execution_set_state_dir,
                )
            else:
                base_plan = build_agent_plan_projection(
                    snapshot,
                    active_execution_enabled=False,
                    active_sessions=[],
                    recovery_issues=[],
                )
                document = build_routed_agent_plan(
                    snapshot,
                    base_plan,
                    router,
                    external_mcp_execution_enabled=self.routed_tools is not None,
                    routing_projection=routing,
                )
        except (OSError, ValueError) as exc:
            raise McpProtocolError(
                INTERNAL_ERROR,
                f"routing-aware projection failed: {exc}",
                data={"uri": uri},
            ) from exc

        payload = {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": self._json_text(document),
                }
            ]
        }
        if modern:
            return self._modern_result(payload, cacheable=True, ttl_ms=0, cache_scope="private")
        return payload

    def _tools_list(self, message: dict[str, Any], *, modern: bool) -> dict[str, Any]:
        if self.routed_tools is None:
            return super()._tools_list(message, modern=modern)
        params = self._request_params(message)
        if params.get("cursor") is not None:
            raise McpProtocolError(INVALID_PARAMS, "this tool list does not use pagination")
        payload = {"tools": self.routed_tools.tool_descriptors()}
        if modern:
            return self._modern_result(payload, cacheable=True, ttl_ms=60_000, cache_scope="public")
        return payload

    def _tools_call(self, message: dict[str, Any], *, modern: bool) -> dict[str, Any]:
        if self.routed_tools is None:
            return super()._tools_call(message, modern=modern)
        params = self._request_params(message)
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise McpProtocolError(INVALID_PARAMS, "tools/call requires a non-empty name")
        if name not in self.routed_tools.tool_names():
            raise McpProtocolError(INVALID_PARAMS, "Tool not found", data={"name": name})
        try:
            result = self.routed_tools.call(name, params.get("arguments"))
        except (RoutedInstrumentInvocationError, RoutedExecutionSetInvocationError) as exc:
            return self._tool_result(None, modern=modern, error_message=str(exc))
        return self._tool_result(result, modern=modern)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Expose current Causcope diagnosis, instrument routing, routed agent plan, execution-set "
            "lifecycle status, and optionally revision-bound direct provider execution over MCP stdio."
        )
    )
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--pgbot-adapter", type=Path)
    parser.add_argument("--pgbot-report", type=Path)
    parser.add_argument(
        "--enable-routed-provider-tools",
        action="store_true",
        help="Opt in to revision-bound execution of the exact selected direct diagnostic provider",
    )
    parser.add_argument(
        "--runtime-evidence",
        type=Path,
        help="Runtime evidence JSON/YAML source of truth; required with routed provider tools",
    )
    parser.add_argument(
        "--mutation-lock-dir",
        type=Path,
        default=Path("/tmp/causcope-routed-mutations"),
        help="Directory for cross-process routed instrument mutation claims",
    )
    parser.add_argument(
        "--execution-set-state-dir",
        type=Path,
        help=(
            "Directory containing durable execution-set journals; defaults to "
            "<snapshot-dir>/execution-sets"
        ),
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(root: Path = ROOT) -> int:
    parser = build_parser()
    args = parser.parse_args()
    if (args.pgbot_adapter is None) != (args.pgbot_report is None):
        parser.error("--pgbot-adapter and --pgbot-report must be provided together")
    if args.enable_routed_provider_tools and args.runtime_evidence is None:
        parser.error("--runtime-evidence is required with --enable-routed-provider-tools")
    if args.enable_routed_provider_tools and args.pgbot_adapter is None:
        parser.error("a configured direct provider is required with --enable-routed-provider-tools")

    try:
        reader = DiagnosisSnapshotReader(
            args.snapshot,
            schema_path=root / "schema" / "diagnosis-snapshot.schema.json",
        )
        concepts = load_concepts(root)
        edges = load_edges(root)

        def router_provider() -> InstrumentRouter:
            providers = []
            if args.pgbot_adapter is not None:
                providers.append(
                    PgbotAutonomousProbeProvider(
                        adapter=load_adapter(args.pgbot_adapter),
                        concepts=concepts,
                        context_supplier=file_context_supplier(args.pgbot_report),
                    )
                )
            return InstrumentRouter(
                concepts=concepts,
                host_capabilities=build_probe_execution_capabilities(concepts),
                providers=providers,
            )

        routed_tools = None
        if args.enable_routed_provider_tools:
            routed_tools = RoutedInstrumentToolController(
                reader=reader,
                snapshot_path=args.snapshot,
                runtime_evidence_path=args.runtime_evidence,
                concepts=concepts,
                edges=edges,
                router_provider=router_provider,
                mutation_lock_dir=args.mutation_lock_dir,
            )

        server = RoutingDiagnosisMcpServer(
            reader,
            instrument_router_provider=router_provider,
            probe_capability_provider=lambda: build_probe_execution_capabilities(concepts),
            routed_tools=routed_tools,
            execution_set_state_dir=args.execution_set_state_dir,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return serve_stdio(server, verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any, Callable

from agent_plan_recovery import build_agent_plan_projection
from causal_projection import ROOT, load_concepts
from diagnosis_http_api import DiagnosisSnapshotReader
from diagnosis_mcp_server import (
    AGENT_PLAN_URI,
    DiagnosisMcpServer,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    LEGACY_RESOURCE_NOT_FOUND,
    McpProtocolError,
    serve_stdio,
)
from instrument_router import InstrumentRouter
from instrument_routing_projection import build_instrument_routing_projection
from pgbot_adapter import load_adapter
from pgbot_autonomous_provider import PgbotAutonomousProbeProvider, file_context_supplier
from probe_executor_runtime import build_probe_execution_capabilities
from routed_agent_plan import build_routed_agent_plan

INSTRUMENT_ROUTING_URI = "causcope://diagnosis/instrument-routing"
ROUTED_AGENT_PLAN_URI = "causcope://diagnosis/routed-agent-plan"

RouterProvider = Callable[[], InstrumentRouter]


class RoutingDiagnosisMcpServer(DiagnosisMcpServer):
    """Read-only MCP adapter that composes diagnosis semantics with instrument routing."""

    def __init__(
        self,
        reader: DiagnosisSnapshotReader,
        *,
        instrument_router_provider: RouterProvider,
        probe_capability_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            reader,
            probe_capability_provider=probe_capability_provider,
        )
        self.instrument_router_provider = instrument_router_provider

    def _instructions(self) -> str:
        return (
            super()._instructions()
            + f" Read {INSTRUMENT_ROUTING_URI} to see which safe instrument, if any, can execute "
            "each current top-ranked canonical probe without changing semantic probe rank."
            + f" Read {ROUTED_AGENT_PLAN_URI} for the compatibility agent plan and routing projection "
            "in one validated envelope. External-provider routes are advisory in this read-only MCP "
            "adapter; only host probe tools exposed by the base server are executable over MCP."
        )

    def _resource_descriptors(self, *, modern: bool) -> list[dict[str, Any]]:
        resources = super()._resource_descriptors(modern=modern)
        additions = [
            {
                "uri": INSTRUMENT_ROUTING_URI,
                "name": "instrument_routing",
                "description": (
                    "Read-only projection of instrument routing decisions for each current top-ranked "
                    "canonical probe. Routing filters by safety, availability, exact scope compatibility, "
                    "and execution mode; it never reranks hypotheses or probes."
                ),
                "mimeType": "application/json",
            },
            {
                "uri": ROUTED_AGENT_PLAN_URI,
                "name": "routed_agent_plan",
                "description": (
                    "Validated envelope containing the existing compatibility agent plan plus the current "
                    "instrument-routing projection for the same incident and evidence revision."
                ),
                "mimeType": "application/json",
            },
        ]
        if modern:
            additions[0]["title"] = "Causcope instrument routing"
            additions[1]["title"] = "Causcope routed agent plan"
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

    def _read_resource(self, uri: str, *, modern: bool) -> dict[str, Any]:
        if uri not in {INSTRUMENT_ROUTING_URI, ROUTED_AGENT_PLAN_URI}:
            return super()._read_resource(uri, modern=modern)

        snapshot = self._read_snapshot(uri, modern=modern)
        router = self._router(uri)
        try:
            if uri == INSTRUMENT_ROUTING_URI:
                document = build_instrument_routing_projection(snapshot, router)
            else:
                base_plan = build_agent_plan_projection(
                    snapshot,
                    active_execution_enabled=False,
                    active_sessions=[],
                    recovery_issues=[],
                )
                document = build_routed_agent_plan(snapshot, base_plan, router)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Expose current Causcope diagnosis plus read-only instrument routing and a routed agent plan "
            "over MCP stdio."
        )
    )
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--pgbot-adapter", type=Path)
    parser.add_argument("--pgbot-report", type=Path)
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(root: Path = ROOT) -> int:
    parser = build_parser()
    args = parser.parse_args()
    if (args.pgbot_adapter is None) != (args.pgbot_report is None):
        parser.error("--pgbot-adapter and --pgbot-report must be provided together")

    try:
        reader = DiagnosisSnapshotReader(
            args.snapshot,
            schema_path=root / "schema" / "diagnosis-snapshot.schema.json",
        )
        concepts = load_concepts(root)

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

        server = RoutingDiagnosisMcpServer(
            reader,
            instrument_router_provider=router_provider,
            probe_capability_provider=lambda: build_probe_execution_capabilities(concepts),
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return serve_stdio(server, verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())

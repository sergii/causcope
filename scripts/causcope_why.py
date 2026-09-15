#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from causal_projection import ROOT, load_concepts, load_edges
from causcope_cli import (
    DEFAULT_WORKSPACE,
    default_incident_id,
    initial_context,
    initial_session,
    load_state,
    persist_state,
)
from diagnosis_http_api import DiagnosisSnapshotReader
from information_gain_router import InformationGainInstrumentRouter
from instrument_router import InstrumentRouter
from instrument_routing_projection import build_instrument_routing_projection
from probe_executor_runtime import build_probe_execution_capabilities
from provider_bindings import load_provider_instance_bindings
from rails_pool_vertical_slice import build_summary, load_document, render
from resource_topology import load_resource_topology
from routed_execution_set_mcp_tool import (
    TOOL_NAME as EXECUTE_SET_TOOL,
    RoutedExecutionSetToolController,
)
from routed_execution_sets import build_routed_execution_sets
from runtime_target_resolution import build_runtime_target_resolution

WORKSPACE_DIAGNOSIS = "diagnosis.json"
WORKSPACE_RUNTIME_EVIDENCE = "runtime-evidence.json"
WORKSPACE_RUNTIME_RELATIONSHIPS = "runtime-relationships.json"
WORKSPACE_RESOURCE_TOPOLOGY = "resource-topology.yaml"
WORKSPACE_PROVIDER_BINDINGS = "provider-bindings.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="causcope why",
        description="Explain the current Causcope investigation without introducing a second reasoning path.",
    )
    parser.add_argument("problem", nargs="?", help="User-visible problem statement")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=DEFAULT_WORKSPACE,
        help="Investigation workspace (default: .causcope)",
    )
    parser.add_argument("--static", type=Path, help="Concrete System Facts document")
    parser.add_argument("--runtime", type=Path, help="Concrete Runtime Facts document")
    parser.add_argument("--pool", type=Path, help="Resource-pool runtime evidence document")
    parser.add_argument("--json", action="store_true", help="Print the selected canonical projection as JSON")
    parser.add_argument(
        "--require-confirmed",
        action="store_true",
        help="Fail closed unless the selected diagnostic projection is causally verified or compatibility-confirmed",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=4,
        metavar="N",
        help="Maximum autonomous read-only evidence acquisitions per invocation (default: 4, max: 16)",
    )
    parser.add_argument(
        "--acquire",
        action="store_true",
        help=(
            "Explicitly execute exactly one current ready target-aware read-only execution set, "
            "atomically append its evidence, and recompute diagnosis"
        ),
    )
    parser.add_argument(
        "--observe",
        type=Path,
        metavar="RAILS_ROOT",
        help=(
            "Create/resume the Investigation, run one bounded local observation session for RAILS_ROOT, "
            "then render the resulting canonical diagnosis. Place the application command after `--`."
        ),
    )
    return parser


def diagnostic_paths(args: argparse.Namespace) -> tuple[Path, Path, Path] | None:
    supplied = [args.static is not None, args.runtime is not None, args.pool is not None]
    if any(supplied) and not all(supplied):
        raise ValueError("--static, --runtime, and --pool must be supplied together")
    if all(supplied):
        return args.static, args.runtime, args.pool
    return None


def _scope_attributes(scope: dict[str, Any] | None) -> str:
    if not scope:
        return "global"
    attributes = scope.get("attributes", {})
    if not attributes:
        return "global"
    return ", ".join(f"{key}={attributes[key]}" for key in sorted(attributes))


def workspace_problem(args: argparse.Namespace, snapshot: dict[str, Any]) -> str:
    if args.problem:
        return args.problem
    incident = snapshot.get("incident_id")
    if isinstance(incident, str) and incident:
        return f"investigation {incident}"
    return "current investigation"


def load_workspace_diagnosis(workspace: Path) -> dict[str, Any] | None:
    path = workspace / WORKSPACE_DIAGNOSIS
    if not path.exists():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("kind") != "diagnosis_snapshot":
        raise ValueError(f"workspace diagnosis is not a diagnosis_snapshot: {path}")
    return document


def workspace_route_context(
    snapshot: dict[str, Any],
    workspace: Path,
    *,
    external_execution_enabled: bool = False,
    information_gain: bool = False,
) -> tuple[
    dict[str, Any],
    dict[str, Any] | None,
    InstrumentRouter | None,
    InformationGainInstrumentRouter | None,
]:
    concepts = load_concepts(ROOT)
    edges = load_edges(ROOT)
    topology_path = workspace / WORKSPACE_RESOURCE_TOPOLOGY
    relationships_path = workspace / WORKSPACE_RUNTIME_RELATIONSHIPS
    provider_bindings_path = workspace / WORKSPACE_PROVIDER_BINDINGS
    topology = load_resource_topology(topology_path) if topology_path.exists() else None
    runtime_relationships = (
        json.loads(relationships_path.read_text(encoding="utf-8"))
        if relationships_path.exists()
        else None
    )
    target_resolution = None
    if runtime_relationships is not None:
        target_resolution = build_runtime_target_resolution(snapshot, runtime_relationships)

    capabilities = build_probe_execution_capabilities(
        concepts,
        topology=topology,
        runtime_relationships=runtime_relationships,
        external_execution_enabled=external_execution_enabled,
    )
    router = InstrumentRouter(capabilities)
    information_gain_router = None
    if information_gain:
        provider_bindings = (
            load_provider_instance_bindings(provider_bindings_path, workspace=workspace)
            if provider_bindings_path.exists()
            else {}
        )
        information_gain_router = InformationGainInstrumentRouter(router, provider_bindings)

    routing = build_instrument_routing_projection(
        snapshot,
        router,
        target_resolution=target_resolution,
        information_gain_router=information_gain_router,
    )
    return routing, target_resolution, router, information_gain_router


def render_workspace_diagnosis(
    problem: str,
    snapshot: dict[str, Any],
    routing: dict[str, Any],
) -> str:
    lines = [
        "Causcope investigation",
        f"  problem: {problem}",
        f"  incident: {snapshot.get('incident_id', '<unknown>')}",
        f"  evidence revision: {snapshot.get('evidence_revision', '<unknown>')}",
    ]
    for partition in snapshot.get("partitions", []):
        lines.append(f"  scope: {_scope_attributes(partition.get('scope'))}")
        for diagnosis in partition.get("diagnoses", []):
            lines.append(f"    target: {diagnosis.get('target', '<unknown>')}")
            ranking = diagnosis.get("ranking", {})
            candidates = ranking.get("candidates", []) if isinstance(ranking, dict) else []
            if candidates:
                source = candidates[0].get("source", {})
                lines.append(f"      leading hypothesis: {source.get('id', '<unknown>')}")
            probe_ranking = diagnosis.get("probe_ranking", {})
            probes = probe_ranking.get("probes", []) if isinstance(probe_ranking, dict) else []
            if probes:
                probe = probes[0].get("probe", {})
                lines.append(f"      next probe: {probe.get('id', '<unknown>')}")

    ready = [
        route
        for route in routing.get("routes", [])
        if route.get("decision", {}).get("state") == "ready"
    ]
    if ready:
        lines.append("  ready evidence routes:")
        for route in ready:
            selected = route.get("decision", {}).get("selected_instrument", {})
            lines.append(
                "    - "
                f"{route.get('probe_id', '<unknown>')} -> "
                f"{route.get('target_resource', '<unknown>')} via {selected.get('id', '<unknown>')}"
            )
    return "\n".join(lines) + "\n"


def render_acquisition(result: dict[str, Any]) -> str:
    lines = [
        "Evidence acquisition",
        f"  execution set: {result.get('execution_set_id', '<unknown>')}",
        f"  probe: {result.get('probe_id', '<unknown>')}",
        "  evidence revision: "
        f"{result.get('previous_evidence_revision', '<unknown>')} -> "
        f"{result.get('evidence_revision', '<unknown>')}",
    ]
    for member in result.get("member_results", []):
        lines.append(
            "  target: "
            f"{member.get('target_resource', '<unknown>')} via {member.get('instrument_id', '<unknown>')}"
        )
    return "\n".join(lines) + "\n"


def acquire_workspace_evidence(
    snapshot: dict[str, Any],
    workspace: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    runtime_evidence_path = workspace / WORKSPACE_RUNTIME_EVIDENCE
    if not runtime_evidence_path.exists():
        raise ValueError(f"evidence acquisition requires {runtime_evidence_path}")

    routing, _resolution, _router, information_gain_router = workspace_route_context(
        snapshot,
        workspace,
        external_execution_enabled=True,
        information_gain=True,
    )
    if information_gain_router is None:
        raise ValueError(
            "evidence acquisition requires exact target resolution and at least one configured direct provider binding"
        )

    execution_sets = build_routed_execution_sets(routing)
    ready = [item for item in execution_sets["sets"] if item.get("state") == "ready"]
    if len(ready) != 1:
        raise ValueError(
            "evidence acquisition requires exactly one current ready execution set; "
            f"found {len(ready)}"
        )
    execution_set = ready[0]
    arguments = execution_set.get("arguments")
    if not isinstance(arguments, dict):
        raise ValueError("ready execution set did not expose MCP execution arguments")

    diagnosis_path = workspace / WORKSPACE_DIAGNOSIS
    concepts = load_concepts(ROOT)
    edges = load_edges(ROOT)

    def current_routing(current_snapshot: dict[str, Any]) -> dict[str, Any]:
        return workspace_route_context(
            current_snapshot,
            workspace,
            external_execution_enabled=True,
            information_gain=True,
        )[0]

    def current_information_gain_router() -> InformationGainInstrumentRouter:
        current_snapshot = load_workspace_diagnosis(workspace)
        if current_snapshot is None:
            raise ValueError("current diagnosis snapshot disappeared during acquisition")
        router = workspace_route_context(
            current_snapshot,
            workspace,
            external_execution_enabled=True,
            information_gain=True,
        )[3]
        if router is None:
            raise ValueError("current workspace no longer has an executable information-gain provider route")
        return router

    controller = RoutedExecutionSetToolController(
        reader=DiagnosisSnapshotReader(diagnosis_path),
        snapshot_path=diagnosis_path,
        runtime_evidence_path=runtime_evidence_path,
        concepts=concepts,
        edges=edges,
        routing_projection_provider=current_routing,
        information_gain_router_provider=current_information_gain_router,
        mutation_lock_dir=workspace / "locks",
    )
    result = controller.call(EXECUTE_SET_TOOL, arguments)

    next_snapshot = load_workspace_diagnosis(workspace)
    if next_snapshot is None:
        raise ValueError("evidence acquisition committed without a diagnosis snapshot")
    next_routing, next_resolution, _next_router, _next_information_gain_router = workspace_route_context(
        next_snapshot,
        workspace,
        information_gain=True,
    )
    return result, next_snapshot, next_routing, next_resolution


def scoping_projection(args: argparse.Namespace) -> dict[str, Any]:
    problem = args.problem or "current investigation"
    workspace = args.workspace
    state = load_state(workspace)
    if state is None:
        state = {
            "schema_version": "0.1",
            "incident_id": default_incident_id(problem),
            "context": initial_context(problem),
            "session": initial_session(),
        }
        persist_state(workspace, state)
    return state


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.workspace = args.workspace.expanduser().resolve()
    try:
        paths = diagnostic_paths(args)
        if paths is not None:
            static_path, runtime_path, pool_path = paths
            summary = build_summary(
                args.problem or "checkout is slow",
                load_document(static_path),
                load_document(runtime_path),
                load_document(pool_path),
            )
            if args.require_confirmed and summary.get("status") != "confirmed":
                raise ValueError("diagnostic projection did not reach CAUSAL_DIAGNOSIS_CONFIRMED")
            if args.json:
                print(json.dumps(summary, indent=2, sort_keys=True))
            else:
                print(render(summary), end="")
            return 0

        snapshot = load_workspace_diagnosis(args.workspace)
        if snapshot is not None:
            problem = workspace_problem(args, snapshot)
            if args.acquire:
                acquisition, snapshot, routing, target_resolution = acquire_workspace_evidence(
                    snapshot, args.workspace
                )
            else:
                routing, target_resolution, _router, _information_gain_router = workspace_route_context(
                    snapshot, args.workspace
                )
                acquisition = None
            if args.json:
                document: dict[str, Any] = {
                    "kind": "causcope_why",
                    "problem": problem,
                    "status": "diagnosis_available",
                    "diagnosis": snapshot,
                    "routing": routing,
                }
                if target_resolution is not None:
                    document["target_resolution"] = target_resolution
                if acquisition is not None:
                    document["acquisition"] = acquisition
                print(json.dumps(document, indent=2, sort_keys=True))
            else:
                if acquisition is not None:
                    print(render_acquisition(acquisition))
                print(render_workspace_diagnosis(problem, snapshot, routing), end="")
            return 0

        state = scoping_projection(args)
        if args.json:
            print(json.dumps(state, indent=2, sort_keys=True))
        else:
            context = state["context"]
            print("Causcope investigation")
            print(f"  problem: {context.get('problem', args.problem or 'current investigation')}")
            print(f"  incident: {state['incident_id']}")
            print(f"  next question: {state['session'].get('next_question', '<unknown>')}")
        return 0
    except (ValueError, FileNotFoundError, OSError) as error:
        print(f"causcope: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

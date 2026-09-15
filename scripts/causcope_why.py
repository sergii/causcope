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
        help="Fail closed unless an attached diagnostic projection reaches CAUSAL_DIAGNOSIS_CONFIRMED",
    )
    parser.add_argument(
        "--acquire",
        action="store_true",
        help=(
            "Explicitly execute exactly one current ready target-aware read-only execution set, "
            "atomically append its evidence, and recompute diagnosis"
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


def render_scoping(problem: str, projection: dict[str, Any]) -> str:
    action = projection.get("next_action")
    lines = [
        "Causcope investigation",
        "",
        "Problem",
        f"  {problem}",
        "",
        "Status",
    ]
    if action:
        lines.extend(
            [
                "  NEEDS_SCOPE",
                "",
                "Next question",
                f"  {action['question']}",
                "",
                "Why now",
                f"  {action['reason']}",
            ]
        )
    else:
        lines.extend(
            [
                "  SCOPING_COMPLETE",
                "",
                "Diagnosis",
                "  No diagnostic evidence bundle is available in this workspace yet.",
                "  Continue with evidence acquisition; `causcope why` will consume diagnosis.json automatically when it appears.",
            ]
        )
    return "\n".join(lines) + "\n"


def scoping_projection(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    context_path = args.workspace / "incident-context.yaml"
    if context_path.exists():
        context, _session, projection = load_state(args.workspace)
        problem = args.problem or context["summary"]
        return problem, projection

    if not args.problem:
        raise FileNotFoundError(
            f"no investigation exists in {args.workspace}; provide a problem statement to start one"
        )

    incident_id = default_incident_id(args.problem)
    context = initial_context(args.problem, incident_id)
    session = initial_session(incident_id)
    projection = persist_state(args.workspace, context, session)
    return args.problem, projection


def _load_json_object(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return document


def load_workspace_diagnosis(workspace: Path) -> dict[str, Any] | None:
    path = workspace / WORKSPACE_DIAGNOSIS
    if not path.exists():
        return None
    document = _load_json_object(path)
    if document.get("kind") != "diagnosis_snapshot":
        raise ValueError(f"{path} is not a diagnosis_snapshot")
    incident_id = document.get("incident_id")
    if not isinstance(incident_id, str) or not incident_id:
        raise ValueError(f"{path} does not contain a valid incident_id")
    return document


def workspace_problem(args: argparse.Namespace, snapshot: dict[str, Any]) -> str:
    if args.problem:
        return args.problem
    context_path = args.workspace / "incident-context.yaml"
    if context_path.exists():
        context, _session, _projection = load_state(args.workspace)
        if context["incident_id"] != snapshot["incident_id"]:
            raise ValueError(
                "workspace diagnosis belongs to another investigation: "
                f"{snapshot['incident_id']} != {context['incident_id']}"
            )
        return context["summary"]
    return f"investigation {snapshot['incident_id']}"


def workspace_route_context(
    snapshot: dict[str, Any],
    workspace: Path,
    *,
    external_execution_enabled: bool = False,
    information_gain: bool = False,
) -> tuple[
    dict[str, Any],
    dict[str, Any] | None,
    InstrumentRouter,
    InformationGainInstrumentRouter | None,
]:
    concepts = load_concepts(ROOT)
    runtime_evidence_path = workspace / WORKSPACE_RUNTIME_EVIDENCE
    relationships_path = workspace / WORKSPACE_RUNTIME_RELATIONSHIPS
    topology_path = workspace / WORKSPACE_RESOURCE_TOPOLOGY
    provider_bindings_path = workspace / WORKSPACE_PROVIDER_BINDINGS

    topology = load_resource_topology(topology_path) if topology_path.exists() else None
    if provider_bindings_path.exists() and topology is None:
        raise ValueError(
            f"{provider_bindings_path} requires {topology_path}; provider instances cannot be bound without topology"
        )

    target_resolution: dict[str, Any] | None = None
    if runtime_evidence_path.exists() and relationships_path.exists() and topology is not None:
        target_resolution = build_runtime_target_resolution(
            snapshot,
            _load_json_object(runtime_evidence_path),
            _load_json_object(relationships_path),
            topology,
        )

    provider_instance_bindings = (
        load_provider_instance_bindings(
            provider_bindings_path,
            topology=topology,
            concepts=concepts,
            incident_id=snapshot["incident_id"],
        )
        if provider_bindings_path.exists() and topology is not None
        else {}
    )

    router = InstrumentRouter(
        concepts=concepts,
        host_capabilities=build_probe_execution_capabilities(concepts),
        providers=[],
        resource_topology=topology,
        provider_instance_bindings=provider_instance_bindings,
    )
    information_gain_router = (
        InformationGainInstrumentRouter(
            router=router,
            provider_instance_bindings=provider_instance_bindings,
        )
        if information_gain and target_resolution is not None and provider_instance_bindings
        else None
    )
    routing = build_instrument_routing_projection(
        snapshot,
        router,
        external_mcp_execution_enabled=external_execution_enabled,
        target_resolution=target_resolution,
        information_gain_router=information_gain_router,
    )
    return routing, target_resolution, router, information_gain_router


def _top_candidate(diagnosis: dict[str, Any]) -> dict[str, Any] | None:
    ranking = diagnosis.get("ranking")
    candidates = ranking.get("candidates", []) if isinstance(ranking, dict) else []
    if not isinstance(candidates, list) or not candidates:
        return None
    candidate = candidates[0]
    return candidate if isinstance(candidate, dict) else None


def _top_probe(diagnosis: dict[str, Any]) -> dict[str, Any] | None:
    ranking = diagnosis.get("probe_ranking")
    probes = ranking.get("probes", []) if isinstance(ranking, dict) else []
    if not isinstance(probes, list) or not probes:
        return None
    probe = probes[0]
    return probe if isinstance(probe, dict) else None


def _candidate_evidence(candidate: dict[str, Any]) -> tuple[list[str], list[str]]:
    factors = candidate.get("factors", {})
    supporting: set[str] = set()
    contradicting: set[str] = set()
    if isinstance(factors, dict):
        for item in factors.get("matched_path_observations", []):
            if isinstance(item, str):
                supporting.add(item)
        predictions = factors.get("prediction_matches", {})
        if isinstance(predictions, dict):
            for values in predictions.values():
                if isinstance(values, list):
                    supporting.update(item for item in values if isinstance(item, str))
        for item in factors.get("conflicting_observations", []):
            if isinstance(item, str):
                contradicting.add(item)
    return sorted(supporting), sorted(contradicting)


def _route_index(routing: dict[str, Any]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for route in routing.get("routes", []):
        target = route.get("target")
        probe_id = route.get("probe_id")
        if isinstance(target, str) and isinstance(probe_id, str):
            index.setdefault((target, probe_id), []).append(route)
    return index


def render_workspace_diagnosis(
    problem: str,
    snapshot: dict[str, Any],
    routing: dict[str, Any],
) -> str:
    lines = [
        "Causcope investigation",
        "",
        "Problem",
        f"  {problem}",
        "",
        "Status",
        f"  DIAGNOSIS_AVAILABLE (evidence revision {snapshot['evidence_revision']})",
    ]
    routes = _route_index(routing)
    diagnosis_count = 0

    for partition in snapshot.get("partitions", []):
        scope = partition.get("scope")
        for diagnosis in partition.get("diagnoses", []):
            diagnosis_count += 1
            target = diagnosis.get("target", "<unknown>")
            candidate = _top_candidate(diagnosis)
            probe = _top_probe(diagnosis)
            lines.extend(["", f"Diagnosis {diagnosis_count}", f"  target: {target}"])
            if scope:
                lines.append("  scope: " + json.dumps(scope, sort_keys=True))

            if candidate is None:
                lines.append("  leading hypothesis: not established")
            else:
                hypothesis = candidate.get("source", {}).get("id", "<unknown>")
                lines.append(f"  leading hypothesis: {hypothesis}")
                supporting, contradicting = _candidate_evidence(candidate)
                lines.append("  supported by:")
                if supporting:
                    lines.extend(f"    + {item}" for item in supporting)
                else:
                    lines.append("    + no explicit supporting observation beyond the ranked causal path")
                lines.append("  contradicted by:")
                if contradicting:
                    lines.extend(f"    - {item}" for item in contradicting)
                else:
                    lines.append("    - none currently known")

            if probe is None:
                reason = diagnosis.get("probe_ranking", {}).get("not_found_reason")
                lines.append(f"  next probe: none ({reason or 'not required'})")
                continue

            probe_id = probe.get("probe", {}).get("id", "<unknown>")
            lines.append(f"  next probe: {probe_id}")
            matching_routes = routes.get((str(target), str(probe_id)), [])
            if not matching_routes:
                lines.append("  instrument: unresolved")
                continue
            for route in matching_routes:
                target_resource = route.get("target_resource")
                if isinstance(target_resource, str) and target_resource:
                    lines.append(f"  operational target: {target_resource}")
                selected = route.get("decision", {}).get("selected_instrument")
                if isinstance(selected, dict):
                    lines.append(f"  instrument: {selected.get('id', '<unknown>')}")
                    lines.append(f"  action: {route.get('agent_action', {}).get('kind', 'unknown')}")
                else:
                    stop_reason = route.get("decision", {}).get("stop_reason") or "no_safe_available_instrument"
                    lines.append(f"  instrument: not selected ({stop_reason})")

    if diagnosis_count == 0:
        lines.extend(
            [
                "",
                "Diagnosis",
                "  No ranked diagnosis is currently available from active evidence.",
            ]
        )

    unranked = sorted(
        {
            item
            for partition in snapshot.get("partitions", [])
            for item in partition.get("unranked_observations", [])
            if isinstance(item, str)
        }
    )
    if unranked:
        lines.extend(["", "Unranked observations"])
        lines.extend(f"  ? {item}" for item in unranked)

    return "\n".join(lines) + "\n"


def acquire_workspace_evidence(
    snapshot: dict[str, Any],
    workspace: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    runtime_evidence_path = workspace / WORKSPACE_RUNTIME_EVIDENCE
    if not runtime_evidence_path.exists():
        raise ValueError(f"--acquire requires {runtime_evidence_path}")

    routing, _resolution, _router, information_gain_router = workspace_route_context(
        snapshot,
        workspace,
        external_execution_enabled=True,
        information_gain=True,
    )
    if information_gain_router is None:
        raise ValueError(
            "--acquire requires exact target resolution and at least one configured direct provider binding"
        )

    execution_sets = build_routed_execution_sets(routing)
    ready = [item for item in execution_sets["sets"] if item["state"] == "ready"]
    if len(ready) != 1:
        blocked = [
            f"{item['id']}: {item['reason']}"
            for item in execution_sets["sets"]
            if item["state"] != "ready"
        ]
        detail = "; ".join(blocked) if blocked else "no ready execution set"
        raise ValueError(
            f"--acquire requires exactly one ready execution set, found {len(ready)}: {detail}"
        )

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
    result = controller.call(EXECUTE_SET_TOOL, ready[0]["arguments"])

    next_snapshot = load_workspace_diagnosis(workspace)
    if next_snapshot is None:
        raise ValueError("evidence acquisition committed without a diagnosis snapshot")
    next_routing, next_resolution, _next_router, _next_information_gain_router = workspace_route_context(
        next_snapshot,
        workspace,
        information_gain=True,
    )
    return result, next_snapshot, next_routing, next_resolution


def render_acquisition(result: dict[str, Any]) -> str:
    lines = [
        "Evidence acquisition",
        f"  execution set: {result['execution_set_id']}",
        f"  probe: {result['probe_id']}",
        (
            "  evidence revision: "
            f"{result['previous_evidence_revision']} -> {result['evidence_revision']}"
        ),
    ]
    for member in result["member_results"]:
        lines.append(
            f"  target: {member['target_resource']} via {member['instrument_id']}"
        )
    lines.append("  added evidence: " + ", ".join(result["added_instance_ids"]))
    return "\n".join(lines) + "\n"


def command(args: argparse.Namespace) -> int:
    paths = diagnostic_paths(args)
    if paths is not None:
        if args.acquire:
            raise ValueError("--acquire cannot be combined with --static/--runtime/--pool")
        static_path, runtime_path, pool_path = paths
        problem = args.problem or "request is slow"
        summary = build_summary(
            problem,
            load_document(static_path),
            load_document(runtime_path),
            load_document(pool_path),
        )
        if args.require_confirmed and summary["status"] != "confirmed":
            raise ValueError(f"diagnosis not confirmed: {summary['epistemic_state']}")
        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True))
        else:
            print(render(summary), end="")
        return 0

    snapshot = load_workspace_diagnosis(args.workspace)
    if snapshot is not None:
        if args.require_confirmed:
            raise ValueError(
                "--require-confirmed currently applies only to the Rails D3.1 concrete proof; "
                "workspace diagnosis is ordinal and does not claim causal confirmation"
            )
        problem = workspace_problem(args, snapshot)
        if args.acquire:
            acquisition, snapshot, routing, target_resolution = acquire_workspace_evidence(
                snapshot,
                args.workspace,
            )
        else:
            routing, target_resolution, _router, _information_gain_router = workspace_route_context(
                snapshot,
                args.workspace,
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

    if args.acquire:
        raise ValueError("--acquire requires an existing diagnosis snapshot")
    if args.require_confirmed:
        raise ValueError("--require-confirmed requires --static, --runtime, and --pool")

    problem, projection = scoping_projection(args)
    if args.json:
        print(
            json.dumps(
                {
                    "kind": "causcope_why",
                    "problem": problem,
                    "status": "needs_scope" if projection.get("next_action") else "scoping_complete",
                    "scoping": projection,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(render_scoping(problem, projection), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return command(args)
    except (ValueError, FileNotFoundError, OSError, json.JSONDecodeError) as error:
        print(f"causcope: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

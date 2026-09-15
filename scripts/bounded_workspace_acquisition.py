#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
from typing import Any

import causcope_why
from causal_projection import ROOT, load_concepts, load_edges
from diagnosis_http_api import DiagnosisSnapshotReader
from execution_set_selection import select_ready_execution_set
from information_gain_router import InformationGainInstrumentRouter
from routed_execution_set_mcp_tool import (
    TOOL_NAME as EXECUTE_SET_TOOL,
    RoutedExecutionSetToolController,
)
from routed_execution_sets import build_routed_execution_sets


def acquire_best_workspace_evidence(
    snapshot: dict[str, Any],
    workspace: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    """Execute one bounded autonomous acquisition selected from current ready sets.

    Selection is advisory only until the existing revision-bound execution-set
    controller re-derives the current routing contract and authorizes the exact
    mutation. This function does not bypass provider routing, exact target
    resolution, journaling, atomic evidence commit, or reranking.
    """

    runtime_evidence_path = workspace / causcope_why.WORKSPACE_RUNTIME_EVIDENCE
    if not runtime_evidence_path.exists():
        raise ValueError(f"evidence acquisition requires {runtime_evidence_path}")

    routing, _resolution, _router, information_gain_router = causcope_why.workspace_route_context(
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
    selection = select_ready_execution_set(snapshot, execution_sets)
    if selection["state"] != "selected":
        best = [
            item["execution_set_id"]
            for item in selection["candidates"]
            if item.get("best") is True
        ]
        detail = ", ".join(best) if best else "none"
        raise ValueError(
            "evidence acquisition has no unique semantically preferred read-only execution set: "
            f"{selection['reason']}; best candidates: {detail}"
        )

    selected_id = selection["selected_execution_set_id"]
    selected = next(
        (
            item
            for item in execution_sets["sets"]
            if item.get("id") == selected_id and item.get("state") == "ready"
        ),
        None,
    )
    if selected is None or not isinstance(selected.get("arguments"), dict):
        raise ValueError("selected execution set disappeared from the current ready projection")

    diagnosis_path = workspace / causcope_why.WORKSPACE_DIAGNOSIS
    concepts = load_concepts(ROOT)
    edges = load_edges(ROOT)

    def current_routing(current_snapshot: dict[str, Any]) -> dict[str, Any]:
        return causcope_why.workspace_route_context(
            current_snapshot,
            workspace,
            external_execution_enabled=True,
            information_gain=True,
        )[0]

    def current_information_gain_router() -> InformationGainInstrumentRouter:
        current_snapshot = causcope_why.load_workspace_diagnosis(workspace)
        if current_snapshot is None:
            raise ValueError("current diagnosis snapshot disappeared during acquisition")
        router = causcope_why.workspace_route_context(
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
    result = controller.call(EXECUTE_SET_TOOL, selected["arguments"])

    next_snapshot = causcope_why.load_workspace_diagnosis(workspace)
    if next_snapshot is None:
        raise ValueError("evidence acquisition committed without a diagnosis snapshot")
    next_routing, next_resolution, _next_router, _next_information_gain_router = (
        causcope_why.workspace_route_context(
            next_snapshot,
            workspace,
            information_gain=True,
        )
    )
    return result, next_snapshot, next_routing, next_resolution

#!/usr/bin/env python3

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

import causcope_why
from bounded_workspace_acquisition import acquire_best_workspace_evidence
from causal_verification import build_causal_verification_projection
from causal_verification_source import load_causal_verification_source
from execution_set_selection import select_ready_execution_set
from routed_execution_sets import build_routed_execution_sets

SelectionProvider = Callable[[dict[str, Any], Path], dict[str, Any]]
AcquisitionExecutor = Callable[
    [dict[str, Any], Path],
    tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None],
]
VerificationProvider = Callable[[dict[str, Any], Path], bool]


def workspace_acquisition_selection(
    snapshot: dict[str, Any],
    workspace: Path,
) -> dict[str, Any]:
    """Project whether one current read-only execution set may run autonomously."""

    evidence_path = workspace / causcope_why.WORKSPACE_RUNTIME_EVIDENCE
    if not evidence_path.exists():
        return {
            "state": "none",
            "selected_execution_set_id": None,
            "reason": "runtime_evidence_missing",
            "candidates": [],
        }

    routing, _resolution, _router, information_gain_router = causcope_why.workspace_route_context(
        snapshot,
        workspace,
        external_execution_enabled=True,
        information_gain=True,
    )
    if information_gain_router is None:
        return {
            "state": "none",
            "selected_execution_set_id": None,
            "reason": "no_executable_provider_route",
            "candidates": [],
        }

    return select_ready_execution_set(snapshot, build_routed_execution_sets(routing))


def workspace_causally_verified(snapshot: dict[str, Any], workspace: Path) -> bool:
    evidence_path = workspace / causcope_why.WORKSPACE_RUNTIME_EVIDENCE
    if not evidence_path.exists():
        return False
    projection = build_causal_verification_projection(
        snapshot,
        load_causal_verification_source(evidence_path),
    )
    return any(
        isinstance(claim, dict) and claim.get("status") == "verified"
        for claim in projection.get("claims", [])
    )


def _terminal_state(selection: dict[str, Any]) -> tuple[str, str] | None:
    state = selection.get("state")
    reason = str(selection.get("reason") or "unknown")
    if state == "none":
        return "blocked", reason
    if state == "ambiguous":
        return "ambiguous", reason
    if state != "selected":
        raise ValueError(f"unknown workspace acquisition selection state: {state}")
    return None


def _step_record(
    index: int,
    selection: dict[str, Any],
    result: dict[str, Any],
    *,
    previous_revision: int,
    evidence_revision: int,
) -> dict[str, Any]:
    selected_id = selection.get("selected_execution_set_id")
    result_id = result.get("execution_set_id")
    if result_id is not None and result_id != selected_id:
        raise ValueError(
            "bounded acquisition executed a different set than the current semantic selection: "
            f"selected={selected_id} executed={result_id}"
        )
    return {
        "index": index,
        "execution_set_id": selected_id,
        "probe_id": result.get("probe_id"),
        "previous_evidence_revision": previous_revision,
        "evidence_revision": evidence_revision,
        "added_instance_ids": sorted(result.get("added_instance_ids", [])),
    }


def run_workspace_investigation(
    snapshot: dict[str, Any],
    workspace: Path,
    *,
    max_steps: int = 4,
    selection_provider: SelectionProvider = workspace_acquisition_selection,
    acquisition_executor: AcquisitionExecutor = acquire_best_workspace_evidence,
    verification_provider: VerificationProvider = workspace_causally_verified,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    """Continue one canonical workspace through several bounded read-only questions.

    Every mutation still goes through the existing revision-bound execution-set
    controller. This loop only decides whether another already-authorized bounded
    question may be attempted after the previous atomic commit and rerank.
    """

    if max_steps < 1 or max_steps > 16:
        raise ValueError("max_steps must be between 1 and 16")
    if snapshot.get("kind") != "diagnosis_snapshot":
        raise ValueError("workspace autonomous investigation requires a diagnosis_snapshot")

    current = copy.deepcopy(snapshot)
    incident_id = current.get("incident_id")
    initial_revision = int(current.get("evidence_revision", 0))
    routing: dict[str, Any] | None = None
    resolution: dict[str, Any] | None = None
    steps: list[dict[str, Any]] = []
    stop_reason: str | None = None
    stop_detail: str | None = None

    for index in range(1, max_steps + 1):
        if verification_provider(current, workspace):
            stop_reason = "verified"
            stop_detail = "canonical_causal_verification_established"
            break

        selection = selection_provider(current, workspace)
        terminal = _terminal_state(selection)
        if terminal is not None:
            stop_reason, stop_detail = terminal
            break

        previous_revision = int(current.get("evidence_revision", 0))
        result, next_snapshot, routing, resolution = acquisition_executor(current, workspace)
        if next_snapshot.get("incident_id") != incident_id:
            raise ValueError("bounded acquisition switched investigation incident")
        next_revision = int(next_snapshot.get("evidence_revision", 0))
        if next_revision != previous_revision + 1:
            raise ValueError(
                "bounded acquisition did not advance evidence revision by exactly one: "
                f"{previous_revision} -> {next_revision}"
            )
        if result.get("previous_evidence_revision") != previous_revision:
            raise ValueError("bounded acquisition result reports a stale previous evidence revision")
        if result.get("evidence_revision") != next_revision:
            raise ValueError("bounded acquisition result disagrees with committed evidence revision")

        steps.append(
            _step_record(
                index,
                selection,
                result,
                previous_revision=previous_revision,
                evidence_revision=next_revision,
            )
        )
        current = next_snapshot

    if stop_reason is None:
        # The budget is a mutation budget, not a reasoning budget. After the last
        # allowed commit, inspect the freshly reranked state once more without
        # executing anything so a naturally terminal state is not mislabeled.
        if verification_provider(current, workspace):
            stop_reason = "verified"
            stop_detail = "canonical_causal_verification_established"
        else:
            selection = selection_provider(current, workspace)
            terminal = _terminal_state(selection)
            if terminal is not None:
                stop_reason, stop_detail = terminal
            else:
                stop_reason = "budget_exhausted"
                stop_detail = "max_steps_reached"

    report = {
        "schema_version": "0.1",
        "kind": "workspace_autonomous_investigation",
        "incident_id": incident_id,
        "max_steps": max_steps,
        "initial_evidence_revision": initial_revision,
        "final_evidence_revision": int(current.get("evidence_revision", 0)),
        "stop_reason": stop_reason,
        "stop_detail": stop_detail,
        "steps": steps,
    }
    return report, current, routing, resolution

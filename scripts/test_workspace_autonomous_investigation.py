#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

from workspace_autonomous_investigation import run_workspace_investigation


def snapshot(revision: int) -> dict:
    return {
        "kind": "diagnosis_snapshot",
        "incident_id": "incident.workspace-loop",
        "evidence_revision": revision,
        "partitions": [],
    }


def selected(execution_set_id: str) -> dict:
    return {
        "state": "selected",
        "selected_execution_set_id": execution_set_id,
        "reason": "unique_best_semantic_probe_priority",
        "candidates": [],
    }


def main() -> int:
    workspace = Path("/tmp/causcope-workspace-loop-contract")

    selections = iter(
        [
            selected("execution-set.first"),
            selected("execution-set.second"),
            {
                "state": "none",
                "selected_execution_set_id": None,
                "reason": "no_read_only_ready_execution_set",
                "candidates": [],
            },
        ]
    )
    acquired: list[str] = []

    def selection_provider(_snapshot: dict, _workspace: Path) -> dict:
        return next(selections)

    def acquisition_executor(current: dict, _workspace: Path):
        revision = current["evidence_revision"]
        execution_set_id = f"execution-set.{'first' if revision == 7 else 'second'}"
        acquired.append(execution_set_id)
        next_snapshot = snapshot(revision + 1)
        result = {
            "kind": "routed_execution_set_result",
            "execution_set_id": execution_set_id,
            "probe_id": f"probe.step.{revision - 6}",
            "previous_evidence_revision": revision,
            "evidence_revision": revision + 1,
            "added_instance_ids": [f"evidence.step.{revision - 6}"],
        }
        return result, next_snapshot, {"kind": "instrument_routing_projection"}, None

    report, final_snapshot, _routing, _resolution = run_workspace_investigation(
        snapshot(7),
        workspace,
        max_steps=4,
        selection_provider=selection_provider,
        acquisition_executor=acquisition_executor,
        verification_provider=lambda _snapshot, _workspace: False,
    )
    assert acquired == ["execution-set.first", "execution-set.second"]
    assert final_snapshot["evidence_revision"] == 9
    assert report["kind"] == "workspace_autonomous_investigation"
    assert report["initial_evidence_revision"] == 7
    assert report["final_evidence_revision"] == 9
    assert report["stop_reason"] == "blocked"
    assert report["stop_detail"] == "no_read_only_ready_execution_set"
    assert [step["execution_set_id"] for step in report["steps"]] == acquired
    assert [step["evidence_revision"] for step in report["steps"]] == [8, 9]

    calls = 0

    def must_not_acquire(_snapshot: dict, _workspace: Path):
        nonlocal calls
        calls += 1
        raise AssertionError("ambiguous or verified investigation must not acquire evidence")

    ambiguous_report, ambiguous_snapshot, _routing, _resolution = run_workspace_investigation(
        snapshot(3),
        workspace,
        selection_provider=lambda _snapshot, _workspace: {
            "state": "ambiguous",
            "selected_execution_set_id": None,
            "reason": "semantic_priority_tie",
            "candidates": [
                {"execution_set_id": "execution-set.a", "best": True},
                {"execution_set_id": "execution-set.b", "best": True},
            ],
        },
        acquisition_executor=must_not_acquire,
        verification_provider=lambda _snapshot, _workspace: False,
    )
    assert ambiguous_report["stop_reason"] == "ambiguous"
    assert ambiguous_report["stop_detail"] == "semantic_priority_tie"
    assert ambiguous_report["steps"] == []
    assert ambiguous_snapshot["evidence_revision"] == 3
    assert calls == 0

    verified_report, verified_snapshot, _routing, _resolution = run_workspace_investigation(
        snapshot(5),
        workspace,
        selection_provider=lambda _snapshot, _workspace: selected("execution-set.unused"),
        acquisition_executor=must_not_acquire,
        verification_provider=lambda _snapshot, _workspace: True,
    )
    assert verified_report["stop_reason"] == "verified"
    assert verified_report["stop_detail"] == "canonical_causal_verification_established"
    assert verified_report["steps"] == []
    assert verified_snapshot["evidence_revision"] == 5
    assert calls == 0

    budget_calls = 0

    def budget_acquire(current: dict, _workspace: Path):
        nonlocal budget_calls
        budget_calls += 1
        revision = current["evidence_revision"]
        next_snapshot = snapshot(revision + 1)
        result = {
            "kind": "routed_execution_set_result",
            "execution_set_id": f"execution-set.budget.{budget_calls}",
            "probe_id": f"probe.budget.{budget_calls}",
            "previous_evidence_revision": revision,
            "evidence_revision": revision + 1,
            "added_instance_ids": [f"evidence.budget.{budget_calls}"],
        }
        return result, next_snapshot, {"kind": "instrument_routing_projection"}, None

    budget_report, budget_snapshot, _routing, _resolution = run_workspace_investigation(
        snapshot(10),
        workspace,
        max_steps=2,
        selection_provider=lambda _snapshot, _workspace: selected(
            f"execution-set.budget.{_snapshot['evidence_revision']}"
        ),
        acquisition_executor=budget_acquire,
        verification_provider=lambda _snapshot, _workspace: False,
    )
    assert budget_calls == 2
    assert budget_snapshot["evidence_revision"] == 12
    assert budget_report["stop_reason"] == "budget_exhausted"
    assert budget_report["stop_detail"] == "max_steps_reached"
    assert len(budget_report["steps"]) == 2

    try:
        run_workspace_investigation(
            snapshot(20),
            workspace,
            max_steps=1,
            selection_provider=lambda _snapshot, _workspace: selected("execution-set.stale"),
            acquisition_executor=lambda current, _workspace: (
                {
                    "kind": "routed_execution_set_result",
                    "execution_set_id": "execution-set.stale",
                    "probe_id": "probe.stale",
                    "previous_evidence_revision": 20,
                    "evidence_revision": 20,
                    "added_instance_ids": [],
                },
                current,
                {"kind": "instrument_routing_projection"},
                None,
            ),
            verification_provider=lambda _snapshot, _workspace: False,
        )
    except ValueError as error:
        assert "did not advance evidence revision" in str(error)
    else:
        raise AssertionError("workspace loop must fail closed when an acquisition makes no revision progress")

    print("Bounded workspace autonomous investigation loop: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

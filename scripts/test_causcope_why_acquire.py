#!/usr/bin/env python3

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

import causcope_why
from execution_set_selection import select_ready_execution_set
from test_causcope_why import run, write_json
from test_multi_target_execution_set import MultiTargetExecutionSetTest

ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY = ROOT / "examples" / "topology" / "shop.yaml"
PGBOT_ADAPTER = ROOT / "examples" / "adapters" / "pgbot" / "postgresql.yaml"
PGBOT_REPORT = ROOT / "examples" / "telemetry" / "pgbot" / "postgresql-findings.json"


def prepare_workspace(workspace: Path) -> None:
    fixture = MultiTargetExecutionSetTest()
    snapshot = fixture.snapshot()
    evidence = fixture.runtime_evidence()
    relationships = fixture.relationships()
    relationships["relationships"] = [
        item
        for item in relationships["relationships"]
        if item["object_resource"] == "pool:active_record.primary"
    ]

    write_json(workspace / "diagnosis.json", snapshot)
    write_json(workspace / "runtime-evidence.json", evidence)
    write_json(workspace / "runtime-relationships.json", relationships)
    (workspace / "resource-topology.yaml").write_text(
        TOPOLOGY.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (workspace / "pgbot-postgresql.yaml").write_text(
        PGBOT_ADAPTER.read_text(encoding="utf-8"), encoding="utf-8"
    )

    report = json.loads(PGBOT_REPORT.read_text(encoding="utf-8"))
    report["server"]["database"] = "orders"
    report["collected_at"] = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    write_json(workspace / "pgbot-orders.json", report)

    bindings = {
        "schema_version": "0.1",
        "kind": "provider_bindings",
        "bindings": [
            {
                "provider_instance": "provider.pgbot.orders-prod",
                "driver": "pgbot_file",
                "adapter": "pgbot-postgresql.yaml",
                "context": "pgbot-orders.json",
            }
        ],
    }
    (workspace / "provider-bindings.yaml").write_text(
        yaml.safe_dump(bindings, sort_keys=False), encoding="utf-8"
    )


def assert_ready_route_before_acquisition(workspace: Path) -> None:
    snapshot = causcope_why.load_workspace_diagnosis(workspace)
    assert snapshot is not None
    assert snapshot["evidence_revision"] == 7
    routing, _resolution, _router, _information_gain_router = causcope_why.workspace_route_context(
        snapshot,
        workspace,
    )
    route = routing["routes"][0]
    assert route["target_resource"] == "db.orders.prod"
    assert route["decision"]["selected_instrument"]["id"] == "provider.pgbot.orders-prod"
    assert route["agent_action"]["mcp_execution_available"] is False


def _probe_candidate(
    probe_id: str,
    *,
    top_two_sided: int,
    top_contrast: int,
    top_discriminated: int,
    two_sided_pairs: int,
    contrast_components: int,
    discriminated_pairs: int,
    hypotheses_tested: int,
) -> dict:
    return {
        "rank": 1,
        "probe": {"id": probe_id},
        "risk": "read_only",
        "hypotheses_tested": [f"hypothesis.{probe_id}.{index}" for index in range(hypotheses_tested)],
        "factors": {
            "top_candidate_two_sided_alternatives": [
                f"hypothesis.alt.{index}" for index in range(top_two_sided)
            ],
            "top_candidate_contrast_components": top_contrast,
            "top_candidate_discriminated_alternatives": [
                f"hypothesis.discriminated.{index}" for index in range(top_discriminated)
            ],
            "two_sided_candidate_pairs": [
                [f"hypothesis.left.{index}", f"hypothesis.right.{index}"]
                for index in range(two_sided_pairs)
            ],
            "contrast_components": contrast_components,
            "discriminated_candidate_pairs": [
                [f"hypothesis.pair-left.{index}", f"hypothesis.pair-right.{index}"]
                for index in range(discriminated_pairs)
            ],
        },
    }


def _selection_fixture(
    left_candidate: dict,
    right_candidate: dict,
) -> tuple[dict, dict]:
    left_scope = {"attributes": {"cohort": "checkout"}}
    right_scope = {"attributes": {"cohort": "billing"}}
    snapshot = {
        "kind": "diagnosis_snapshot",
        "incident_id": "incident.multi-ready",
        "evidence_revision": 4,
        "partitions": [
            {
                "scope": left_scope,
                "diagnoses": [
                    {
                        "target": "observation.http.request_latency",
                        "probe_ranking": {"found": True, "probes": [left_candidate]},
                    }
                ],
            },
            {
                "scope": right_scope,
                "diagnoses": [
                    {
                        "target": "observation.payment.failure_rate",
                        "probe_ranking": {"found": True, "probes": [right_candidate]},
                    }
                ],
            },
        ],
    }
    execution_sets = {
        "kind": "routed_execution_sets",
        "incident_id": "incident.multi-ready",
        "evidence_revision": 4,
        "sets": [
            {
                "id": "execution-set.billing",
                "scope": right_scope,
                "diagnosis_target": "observation.payment.failure_rate",
                "probe_id": right_candidate["probe"]["id"],
                "state": "ready",
                "arguments": {"executionSetId": "execution-set.billing"},
            },
            {
                "id": "execution-set.checkout",
                "scope": left_scope,
                "diagnosis_target": "observation.http.request_latency",
                "probe_id": left_candidate["probe"]["id"],
                "state": "ready",
                "arguments": {"executionSetId": "execution-set.checkout"},
            },
            {
                "id": "execution-set.blocked",
                "scope": left_scope,
                "diagnosis_target": "observation.http.request_latency",
                "probe_id": "probe.blocked",
                "state": "blocked",
                "arguments": None,
            },
        ],
    }
    return snapshot, execution_sets


def assert_bounded_multi_set_selection() -> None:
    stronger = _probe_candidate(
        "probe.checkout.strong",
        top_two_sided=2,
        top_contrast=6,
        top_discriminated=2,
        two_sided_pairs=3,
        contrast_components=9,
        discriminated_pairs=4,
        hypotheses_tested=2,
    )
    weaker = _probe_candidate(
        "probe.billing.weaker",
        top_two_sided=1,
        top_contrast=8,
        top_discriminated=3,
        two_sided_pairs=4,
        contrast_components=12,
        discriminated_pairs=5,
        hypotheses_tested=3,
    )
    snapshot, execution_sets = _selection_fixture(stronger, weaker)
    selection = select_ready_execution_set(snapshot, execution_sets)
    assert selection["state"] == "selected"
    assert selection["selected_execution_set_id"] == "execution-set.checkout"
    assert selection["reason"] == "unique_best_semantic_probe_priority"
    assert len(selection["candidates"]) == 2

    tied_left = _probe_candidate(
        "probe.checkout.tie-a",
        top_two_sided=1,
        top_contrast=4,
        top_discriminated=2,
        two_sided_pairs=2,
        contrast_components=6,
        discriminated_pairs=3,
        hypotheses_tested=2,
    )
    tied_right = _probe_candidate(
        "probe.billing.tie-z",
        top_two_sided=1,
        top_contrast=4,
        top_discriminated=2,
        two_sided_pairs=2,
        contrast_components=6,
        discriminated_pairs=3,
        hypotheses_tested=2,
    )
    snapshot, execution_sets = _selection_fixture(tied_left, tied_right)
    ambiguous = select_ready_execution_set(snapshot, execution_sets)
    assert ambiguous["state"] == "ambiguous"
    assert ambiguous["selected_execution_set_id"] is None
    assert ambiguous["reason"] == "semantic_priority_tie"
    assert {
        item["execution_set_id"] for item in ambiguous["candidates"] if item["best"]
    } == {"execution-set.checkout", "execution-set.billing"}


def main() -> int:
    help_result = run("why", "--help")
    assert "--acquire" not in help_result.stdout
    assert_bounded_multi_set_selection()

    with tempfile.TemporaryDirectory(prefix="causcope-why-acquire-") as temporary:
        workspace = Path(temporary) / ".causcope"
        workspace.mkdir(parents=True)
        prepare_workspace(workspace)
        assert_ready_route_before_acquisition(workspace)

        acquired = run(
            "why",
            "database requests are slow",
            "--workspace",
            str(workspace),
            "--json",
        )
        document = json.loads(acquired.stdout)
        result = document["acquisition"]
        assert result["kind"] == "routed_execution_set_result"
        assert result["previous_evidence_revision"] == 7
        assert result["evidence_revision"] == 8
        assert result["probe_id"] == "probe.database.measure_query_latency"
        assert result["rerank_count"] == 1
        assert len(result["member_results"]) == 1
        member = result["member_results"][0]
        assert member["target_resource"] == "db.orders.prod"
        assert member["instrument_id"] == "provider.pgbot.orders-prod"
        assert result["added_instance_ids"]
        assert document["diagnosis"]["evidence_revision"] == 8

        committed_evidence = json.loads(
            (workspace / "runtime-evidence.json").read_text(encoding="utf-8")
        )
        assert committed_evidence["incident_id"] == result["incident_id"]
        added = [
            instance
            for instance in committed_evidence["instances"]
            if instance["id"] in set(result["added_instance_ids"])
        ]
        assert added
        assert all(
            instance["source"]["attributes"]["routing.target_resource"] == "db.orders.prod"
            for instance in added
        )
        assert all(
            instance["scope"]["attributes"]["target_resource"] == "db.orders.prod"
            for instance in added
        )

        journal_files = list((workspace / "execution-sets").glob("*.journal.jsonl"))
        assert len(journal_files) == 1
        journal = journal_files[0].read_text(encoding="utf-8")
        assert "member_succeeded" in journal
        assert "set_committed" in journal

        human_workspace = Path(temporary) / "human" / ".causcope"
        human_workspace.mkdir(parents=True)
        prepare_workspace(human_workspace)
        human = run(
            "why",
            "database requests are slow",
            "--workspace",
            str(human_workspace),
        )
        assert "Evidence acquisition" in human.stdout
        assert "evidence revision: 7 -> 8" in human.stdout
        assert "target: db.orders.prod via provider.pgbot.orders-prod" in human.stdout
        assert "Causcope investigation" in human.stdout

    print("Causcope why implicit acquisition: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
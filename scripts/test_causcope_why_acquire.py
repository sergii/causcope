#!/usr/bin/env python3

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

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


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="causcope-why-acquire-") as temporary:
        workspace = Path(temporary) / ".causcope"
        workspace.mkdir(parents=True)
        prepare_workspace(workspace)

        before = run(
            "why",
            "database requests are slow",
            "--workspace",
            str(workspace),
            "--json",
        )
        before_document = json.loads(before.stdout)
        before_route = before_document["routing"]["routes"][0]
        assert before_document["diagnosis"]["evidence_revision"] == 7
        assert before_route["target_resource"] == "db.orders.prod"
        assert before_route["decision"]["selected_instrument"]["id"] == "provider.pgbot.orders-prod"
        assert before_route["agent_action"]["mcp_execution_available"] is False

        acquired = run(
            "why",
            "database requests are slow",
            "--workspace",
            str(workspace),
            "--acquire",
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
            "--acquire",
        )
        assert "Evidence acquisition" in human.stdout
        assert "evidence revision: 7 -> 8" in human.stdout
        assert "target: db.orders.prod via provider.pgbot.orders-prod" in human.stdout
        assert "Causcope investigation" in human.stdout

    print("Causcope why explicit acquisition: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

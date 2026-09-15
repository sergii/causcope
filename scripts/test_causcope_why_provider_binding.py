#!/usr/bin/env python3

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import yaml

from test_causcope_why import run, target_aware_documents, write_json

ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY = ROOT / "examples" / "topology" / "shop.yaml"
PGBOT_ADAPTER = ROOT / "examples" / "adapters" / "pgbot" / "postgresql.yaml"
PGBOT_REPORT = ROOT / "examples" / "telemetry" / "pgbot" / "postgresql-findings.json"


def write_binding(workspace: Path) -> None:
    (workspace / "pgbot-postgresql.yaml").write_text(
        PGBOT_ADAPTER.read_text(encoding="utf-8"), encoding="utf-8"
    )
    report = json.loads(PGBOT_REPORT.read_text(encoding="utf-8"))
    report["server"]["database"] = "orders"
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


def prepare_bound_workspace(workspace: Path) -> None:
    run("why", "database requests are slow", "--workspace", str(workspace))
    context = yaml.safe_load(
        (workspace / "incident-context.yaml").read_text(encoding="utf-8")
    )
    snapshot, evidence, relationships = target_aware_documents(context["incident_id"])
    write_json(workspace / "diagnosis.json", snapshot)
    write_json(workspace / "runtime-evidence.json", evidence)
    write_json(workspace / "runtime-relationships.json", relationships)
    (workspace / "resource-topology.yaml").write_text(
        TOPOLOGY.read_text(encoding="utf-8"), encoding="utf-8"
    )
    write_binding(workspace)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="causcope-why-provider-") as temporary:
        root = Path(temporary)

        human_workspace = root / "human" / ".causcope"
        prepare_bound_workspace(human_workspace)
        human = run("why", "--workspace", str(human_workspace))
        assert "Evidence acquisition" in human.stdout
        assert "target: db.orders.prod via provider.pgbot.orders-prod" in human.stdout

        machine_workspace = root / "machine" / ".causcope"
        prepare_bound_workspace(machine_workspace)
        machine = run("why", "--workspace", str(machine_workspace), "--json")
        document = json.loads(machine.stdout)
        acquisition = document["acquisition"]
        assert acquisition["previous_evidence_revision"] == 7
        assert acquisition["evidence_revision"] == 8
        assert acquisition["probe_id"] == "probe.database.measure_query_latency"
        member = acquisition["member_results"][0]
        assert member["instrument_id"] == "provider.pgbot.orders-prod"
        assert member["target_resource"] == "db.orders.prod"

        mismatch_workspace = root / "mismatch" / ".causcope"
        prepare_bound_workspace(mismatch_workspace)
        wrong_report = json.loads(PGBOT_REPORT.read_text(encoding="utf-8"))
        write_json(mismatch_workspace / "pgbot-orders.json", wrong_report)
        mismatch = run("why", "--workspace", str(mismatch_workspace), check=False)
        assert mismatch.returncode == 2
        assert "database identity mismatch" in mismatch.stderr
        assert "orders" in mismatch.stderr
        assert "app_production" in mismatch.stderr
        assert json.loads(
            (mismatch_workspace / "diagnosis.json").read_text(encoding="utf-8")
        )["evidence_revision"] == 7

    print("Causcope why provider binding implicit acquisition: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="causcope-why-provider-") as temporary:
        workspace = Path(temporary) / ".causcope"
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

        human = run("why", "--workspace", str(workspace))
        assert "operational target: db.orders.prod" in human.stdout
        assert "instrument: provider.pgbot.orders-prod" in human.stdout
        assert "action: use_external_instrument" in human.stdout

        machine = run("why", "--workspace", str(workspace), "--json")
        document = json.loads(machine.stdout)
        route = document["routing"]["routes"][0]
        instrument = route["decision"]["selected_instrument"]
        assert instrument["id"] == "provider.pgbot.orders-prod"
        assert instrument["kind"] == "diagnostic_provider"
        assert instrument["target_resource"] == "db.orders.prod"
        assert instrument["runner"] == "runner.shop.prod"
        assert route["agent_action"]["kind"] == "use_external_instrument"
        assert route["agent_action"]["mcp_execution_available"] is False

        wrong_report = json.loads(PGBOT_REPORT.read_text(encoding="utf-8"))
        write_json(workspace / "pgbot-orders.json", wrong_report)
        mismatch = run("why", "--workspace", str(workspace), check=False)
        assert mismatch.returncode == 2
        assert "database identity mismatch" in mismatch.stderr
        assert "orders" in mismatch.stderr
        assert "app_production" in mismatch.stderr

    print("Causcope why provider binding: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

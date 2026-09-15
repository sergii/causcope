#!/usr/bin/env python3

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from test_causcope_why import run, write_json
from test_causcope_why_acquire import prepare_workspace

ROOT = Path(__file__).resolve().parents[1]
PGBOT_REPORT = ROOT / "examples" / "telemetry" / "pgbot" / "postgresql-findings.json"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="causcope-why-provider-") as temporary:
        root = Path(temporary)

        human_workspace = root / "human" / ".causcope"
        human_workspace.mkdir(parents=True)
        prepare_workspace(human_workspace)
        human = run("why", "--workspace", str(human_workspace))
        assert "Evidence acquisition" in human.stdout
        assert "target: db.orders.prod via provider.pgbot.orders-prod" in human.stdout

        machine_workspace = root / "machine" / ".causcope"
        machine_workspace.mkdir(parents=True)
        prepare_workspace(machine_workspace)
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
        mismatch_workspace.mkdir(parents=True)
        prepare_workspace(mismatch_workspace)
        wrong_report = json.loads(PGBOT_REPORT.read_text(encoding="utf-8"))
        wrong_report["collected_at"] = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        )
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

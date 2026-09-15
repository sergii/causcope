#!/usr/bin/env python3

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from diagnosis_http_api import DiagnosisSnapshotReader
from routing_mcp_server import CAUSAL_VERIFICATION_URI, RoutingDiagnosisMcpServer
from test_rails_pool_evidence_import import pool_document, run, seed, write_json
from test_runtime_incident_seed import FIXTURE


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="causcope-causal-verification-surfaces-") as temporary:
        root = Path(temporary)
        app = root / "verified-app"
        shutil.copytree(FIXTURE, app)
        workspace, static, incident_id = seed(app)
        pool_path = root / "verified-pool.json"
        write_json(pool_path, pool_document(static, incident_id))
        run(
            "runtime", "import-pool",
            "--workspace", str(workspace),
            "--pool-evidence", str(pool_path),
        )

        text = run("why", "checkout is slow", "--workspace", str(workspace), "--require-confirmed")
        assert "Causal verification" in text.stdout
        assert "VERIFIED: hypothesis.database.connection_pool_exhaustion" in text.stdout
        assert "target: db.causcope.prod" in text.stdout
        assert "intervention: resource_capacity_release on pool:active_record.primary" in text.stdout
        assert "canonical evidence: 5 instances" in text.stdout
        assert "predicted recovery: observed" in text.stdout
        assert "CAUSAL_DIAGNOSIS_CONFIRMED" not in text.stdout

        rendered_json = run(
            "why", "checkout is slow", "--workspace", str(workspace),
            "--require-confirmed", "--json",
        )
        document = json.loads(rendered_json.stdout)
        assert document["kind"] == "causcope_why"
        assert document["status"] == "diagnosis_available"
        assert document["diagnosis"]["evidence_revision"] == 2
        verification = document["causal_verification"]
        assert verification["kind"] == "causal_verification_projection"
        assert verification["evidence_revision"] == 2
        assert verification["claims"][0]["status"] == "verified"
        assert verification["claims"][0]["hypothesis"] == "hypothesis.database.connection_pool_exhaustion"

        mcp = RoutingDiagnosisMcpServer(
            DiagnosisSnapshotReader(workspace / "diagnosis.json"),
            instrument_router_provider=lambda: None,
        )
        mcp_payload = mcp._read_resource(CAUSAL_VERIFICATION_URI, modern=False)
        mcp_verification = json.loads(mcp_payload["contents"][0]["text"])
        assert mcp_verification == verification
        assert mcp_verification["claims"][0]["status"] == "verified"

        incomplete_app = root / "incomplete-app"
        shutil.copytree(FIXTURE, incomplete_app)
        incomplete_workspace, incomplete_static, incomplete_incident = seed(incomplete_app)
        incomplete = pool_document(incomplete_static, incomplete_incident)
        incomplete["assertions"]["recovery_request_latency_returned_to_baseline"] = False
        incomplete_path = root / "incomplete-pool.json"
        write_json(incomplete_path, incomplete)
        run(
            "runtime", "import-pool",
            "--workspace", str(incomplete_workspace),
            "--pool-evidence", str(incomplete_path),
        )
        rejected = run(
            "why", "checkout is slow", "--workspace", str(incomplete_workspace),
            "--require-confirmed", check=False,
        )
        assert rejected.returncode == 2
        assert "not verified by canonical intervention evidence" in rejected.stderr

    print("Canonical causal verification why/MCP surfaces: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

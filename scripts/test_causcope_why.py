#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from causal_projection import load_concepts, load_edges
from live_diagnosis import build_diagnosis_snapshot
from test_rails_pool_vertical_slice import fixtures

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "causcope"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI), *args],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def workspace_diagnosis(incident_id: str) -> dict:
    evidence = {
        "schema_version": "0.1",
        "kind": "runtime_evidence",
        "incident_id": incident_id,
        "instances": [
            {
                "id": "evidence.test.tcp_retransmissions",
                "observation": "observation.network.tcp_retransmissions",
                "state": "observed",
                "observed_at": "2026-09-15T14:00:00Z",
                "expires_at": "2026-09-15T15:00:00Z",
                "confidence": "high",
                "source": {"type": "metric", "name": "test.tcp.retransmissions"},
            }
        ],
    }
    return build_diagnosis_snapshot(
        evidence,
        load_concepts(ROOT),
        load_edges(ROOT),
        as_of=datetime(2026, 9, 15, 14, 30, tzinfo=timezone.utc),
        evidence_revision=1,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="causcope-why-") as temporary:
        root = Path(temporary)
        workspace = root / ".causcope"

        started = run(
            "why",
            "checkout is slow",
            "--workspace",
            str(workspace),
        )
        assert "Causcope investigation" in started.stdout
        assert "checkout is slow" in started.stdout
        assert "NEEDS_SCOPE" in started.stdout
        assert "Who is affected and how broadly?" in started.stdout
        assert (workspace / "incident-context.yaml").exists()
        assert (workspace / "investigation-session.yaml").exists()
        assert (workspace / "scoping-projection.json").exists()

        resumed = run("why", "--workspace", str(workspace), "--json")
        resumed_document = json.loads(resumed.stdout)
        assert resumed_document["kind"] == "causcope_why"
        assert resumed_document["problem"] == "checkout is slow"
        assert resumed_document["status"] == "needs_scope"
        assert resumed_document["scoping"]["next_action"]["dimension"] == "investigation.blast_radius"

        context = yaml.safe_load((workspace / "incident-context.yaml").read_text(encoding="utf-8"))
        snapshot = workspace_diagnosis(context["incident_id"])
        write_json(workspace / "diagnosis.json", snapshot)

        workspace_result = run("why", "--workspace", str(workspace))
        assert "DIAGNOSIS_AVAILABLE (evidence revision 1)" in workspace_result.stdout
        assert "target: observation.network.tcp_retransmissions" in workspace_result.stdout
        assert "leading hypothesis: hypothesis.network.packet_loss" in workspace_result.stdout
        assert "next probe: probe.network.inspect_tcp_integrity_errors" in workspace_result.stdout
        assert "instrument: executor.linux.proc_net_snmp.tcp_inerrs" in workspace_result.stdout
        assert "action: begin_host_probe_session" in workspace_result.stdout

        workspace_json = run("why", "--workspace", str(workspace), "--json")
        workspace_document = json.loads(workspace_json.stdout)
        assert workspace_document["status"] == "diagnosis_available"
        assert workspace_document["diagnosis"]["kind"] == "diagnosis_snapshot"
        assert workspace_document["routing"]["kind"] == "instrument_routing_projection"
        routes = workspace_document["routing"]["routes"]
        route = next(
            item
            for item in routes
            if item["target"] == "observation.network.tcp_retransmissions"
            and item["probe_id"] == "probe.network.inspect_tcp_integrity_errors"
        )
        assert route["decision"]["selected_instrument"]["id"] == "executor.linux.proc_net_snmp.tcp_inerrs"
        assert route["agent_action"]["kind"] == "begin_host_probe_session"

        mismatched_workspace = root / "mismatched-workspace"
        run("why", "another problem", "--workspace", str(mismatched_workspace))
        write_json(mismatched_workspace / "diagnosis.json", snapshot)
        mismatch = run("why", "--workspace", str(mismatched_workspace), check=False)
        assert mismatch.returncode == 2
        assert "workspace diagnosis belongs to another investigation" in mismatch.stderr

        (workspace / "diagnosis.json").unlink()

        static, runtime, pool = fixtures()
        static_path = root / "static.json"
        runtime_path = root / "runtime.json"
        pool_path = root / "pool.json"
        write_json(static_path, static)
        write_json(runtime_path, runtime)
        write_json(pool_path, pool)

        diagnosed = run(
            "why",
            "checkout is slow",
            "--static",
            str(static_path),
            "--runtime",
            str(runtime_path),
            "--pool",
            str(pool_path),
            "--require-confirmed",
        )
        assert "Causcope diagnosis" in diagnosed.stdout
        assert "CONFIRMED (CAUSAL_DIAGNOSIS_CONFIRMED)" in diagnosed.stdout
        assert "application-side database connection pool exhaustion" in diagnosed.stdout
        assert "code:CheckoutController#create()" in diagnosed.stdout
        assert "pool:active_record.primary" in diagnosed.stdout
        assert "not established by this bounded slice" in diagnosed.stdout

        diagnosed_json = run(
            "why",
            "checkout is slow",
            "--static",
            str(static_path),
            "--runtime",
            str(runtime_path),
            "--pool",
            str(pool_path),
            "--json",
            "--require-confirmed",
        )
        diagnosis = json.loads(diagnosed_json.stdout)
        assert diagnosis["status"] == "confirmed"
        assert diagnosis["epistemic_state"] == "CAUSAL_DIAGNOSIS_CONFIRMED"
        assert diagnosis["root_cause"] == "application-side database connection pool exhaustion"

        incomplete_pool = copy.deepcopy(pool)
        incomplete_pool["assertions"]["database_still_accepts_direct_connections"] = False
        incomplete_pool_path = root / "pool-incomplete.json"
        write_json(incomplete_pool_path, incomplete_pool)
        not_confirmed = run(
            "why",
            "checkout is slow",
            "--static",
            str(static_path),
            "--runtime",
            str(runtime_path),
            "--pool",
            str(incomplete_pool_path),
            "--require-confirmed",
            check=False,
        )
        assert not_confirmed.returncode == 2
        assert "diagnosis not confirmed: CHECKOUT_WAIT_OBSERVED" in not_confirmed.stderr

        require_without_artifacts = run(
            "why",
            "checkout is slow",
            "--workspace",
            str(root / "another-workspace"),
            "--require-confirmed",
            check=False,
        )
        assert require_without_artifacts.returncode == 2
        assert "--require-confirmed requires --static, --runtime, and --pool" in require_without_artifacts.stderr

        partial = run(
            "why",
            "checkout is slow",
            "--static",
            str(static_path),
            check=False,
        )
        assert partial.returncode == 2
        assert "--static, --runtime, and --pool must be supplied together" in partial.stderr

    print("Causcope why front door: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

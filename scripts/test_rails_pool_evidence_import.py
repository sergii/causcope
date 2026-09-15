#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

from test_runtime_incident_seed import FIXTURE, bootstrap, runtime_document

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "causcope"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(CLI), *args], cwd=ROOT, check=False, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise AssertionError(
            "command failed: " + " ".join([str(CLI), *args])
            + f"\nexit={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def pool_document(static: dict, incident_id: str) -> dict:
    return {
        "schema_version": "0.1",
        "kind": "resource_pool_runtime_evidence",
        "system_id": static["system_id"],
        "revision": static["revision"],
        "incident_id": incident_id,
        "observed_at": "2026-09-15T15:00:00.500000Z",
        "pool": {
            "id": "pool:active_record.primary",
            "technology": "active_record",
            "configured_capacity": 1,
            "observed_capacity": 1,
            "busy": 1,
            "utilization": 1.0,
        },
        "request": {
            "code_symbol": "code:PoolController#work()",
            "trace_id": "a" * 32,
            "span_id": "b" * 16,
            "checkout_wait_ms": 260.0,
            "request_latency_ms": 500.0,
            "dependency_latency_ms": 8.0,
            "dependency_backend_id": "backend-request",
        },
        "dependency_control": {
            "dependency_id": "database:primary",
            "reachable": True,
            "total_latency_ms": 9.0,
            "query_latency_ms": 7.0,
            "backend_id": "backend-control",
        },
        "baseline": {
            "checkout_wait_ms": 2.0,
            "request_latency_ms": 230.0,
            "dependency_latency_ms": 7.0,
        },
        "recovery": {
            "checkout_wait_ms": 2.0,
            "request_latency_ms": 235.0,
            "dependency_latency_ms": 7.0,
        },
        "assertions": {
            "application_pool_was_at_capacity": True,
            "pool_checkout_wait_increased": True,
            "request_latency_increased": True,
            "query_latency_stayed_near_baseline": True,
            "database_still_accepts_direct_connections": True,
            "checkout_wait_explains_request_delta": True,
            "recovery_checkout_wait_returned_to_baseline": True,
            "recovery_request_latency_returned_to_baseline": True,
        },
        "source": {
            "type": "probe",
            "name": "rails-active-record-d3-1-test",
            "uri": "test:rails-pool-evidence",
        },
    }


def seed(app: Path) -> tuple[Path, dict, str]:
    bootstrap(app)
    workspace = app / ".causcope"
    run("why", "checkout is slow", "--workspace", str(workspace))
    context = yaml.safe_load((workspace / "incident-context.yaml").read_text(encoding="utf-8"))
    incident_id = context["incident_id"]
    static = json.loads((workspace / "concrete-system-facts.json").read_text(encoding="utf-8"))
    runtime_path = workspace / "runtime" / f"{incident_id}.json"
    write_json(runtime_path, runtime_document(static, incident_id))
    seeded = run(
        "runtime", "seed", str(app),
        "--request-latency-threshold-ms", "200",
        "--pool-wait-threshold-ms", "50",
        "--json",
    )
    assert json.loads(seeded.stdout)["evidence_revision"] == 1
    return workspace, static, incident_id


def leading_hypothesis(snapshot: dict) -> str:
    diagnosis = next(
        item
        for partition in snapshot["partitions"]
        for item in partition["diagnoses"]
        if item["target"] == "observation.http.request_latency"
    )
    return diagnosis["ranking"]["candidates"][0]["source"]["id"]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="causcope-rails-pool-import-") as temporary:
        root = Path(temporary)
        app = root / "rails-app"
        shutil.copytree(FIXTURE, app)
        workspace, static, incident_id = seed(app)
        pool_path = root / "pool-proof.json"
        write_json(pool_path, pool_document(static, incident_id))

        imported = run(
            "runtime", "import-pool",
            "--workspace", str(workspace),
            "--pool-evidence", str(pool_path),
            "--json",
        )
        result = json.loads(imported.stdout)
        assert result["kind"] == "rails_pool_evidence_import_result"
        assert result["previous_evidence_revision"] == 1
        assert result["evidence_revision"] == 2
        assert result["target_resource"] == "db.causcope.prod"
        assert result["projected_observations"] == [
            "observation.database.connection_pool_utilization",
            "observation.database.query_latency",
        ]

        evidence = json.loads((workspace / "runtime-evidence.json").read_text(encoding="utf-8"))
        observations = {(item["observation"], item["state"]) for item in evidence["instances"]}
        assert ("observation.database.connection_pool_utilization", "observed") in observations
        assert ("observation.database.query_latency", "absent") in observations
        query = next(item for item in evidence["instances"] if item["observation"] == "observation.database.query_latency")
        assert query["source"]["attributes"]["causcope.target_resource"] == "db.causcope.prod"
        assert query["labels"]["independent_database_control"] == "reachable"

        diagnosis = json.loads((workspace / "diagnosis.json").read_text(encoding="utf-8"))
        assert diagnosis["evidence_revision"] == 2
        assert leading_hypothesis(diagnosis) == "hypothesis.database.connection_pool_exhaustion"

        why = json.loads(run("why", "--workspace", str(workspace), "--json").stdout)
        assert why["status"] == "diagnosis_available"
        assert why["diagnosis"]["evidence_revision"] == 2
        request_diagnosis = next(
            item
            for partition in why["diagnosis"]["partitions"]
            for item in partition["diagnoses"]
            if item["target"] == "observation.http.request_latency"
        )
        assert request_diagnosis["ranking"]["candidates"][0]["source"]["id"] == (
            "hypothesis.database.connection_pool_exhaustion"
        )

        before_evidence = (workspace / "runtime-evidence.json").read_text(encoding="utf-8")
        before_diagnosis = (workspace / "diagnosis.json").read_text(encoding="utf-8")
        duplicate = run(
            "runtime", "import-pool",
            "--workspace", str(workspace),
            "--pool-evidence", str(pool_path),
            check=False,
        )
        assert duplicate.returncode == 2
        assert "produced no new canonical evidence" in duplicate.stderr
        assert (workspace / "runtime-evidence.json").read_text(encoding="utf-8") == before_evidence
        assert (workspace / "diagnosis.json").read_text(encoding="utf-8") == before_diagnosis

        mismatch_app = root / "mismatch-app"
        shutil.copytree(FIXTURE, mismatch_app)
        mismatch_workspace, mismatch_static, mismatch_incident = seed(mismatch_app)
        wrong = pool_document(mismatch_static, mismatch_incident)
        wrong["request"]["trace_id"] = "c" * 32
        wrong_path = root / "wrong-pool-proof.json"
        write_json(wrong_path, wrong)
        failed = run(
            "runtime", "import-pool",
            "--workspace", str(mismatch_workspace),
            "--pool-evidence", str(wrong_path),
            check=False,
        )
        assert failed.returncode == 2
        assert "bind to exactly one current canonical pool-wait instance" in failed.stderr
        assert json.loads((mismatch_workspace / "diagnosis.json").read_text())["evidence_revision"] == 1

    print("Rails D3.1 canonical evidence import: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

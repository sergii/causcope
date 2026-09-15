#!/usr/bin/env python3

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "causcope"
FIXTURE = ROOT / "lab" / "rails-connection-pool"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(CLI), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            "command failed: "
            + " ".join([str(CLI), *args])
            + f"\nexit={result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def runtime_document(static: dict, incident_id: str, *, wait_ms: float = 260.0) -> dict:
    trace_id = "a" * 32
    span_id = "b" * 16
    execution_id = "execution.opentelemetry.0123456789abcdef"
    interaction_id = "pool_interaction.opentelemetry.fedcba9876543210"
    return {
        "schema_version": "0.1",
        "kind": "concrete_runtime_facts",
        "system_id": static["system_id"],
        "revision": static["revision"],
        "incident_id": incident_id,
        "executions": [
            {
                "id": execution_id,
                "code_symbol": "code:PoolController#work()",
                "start_time": "2026-09-15T15:00:00Z",
                "end_time": "2026-09-15T15:00:00.500000Z",
                "duration_ms": 500.0,
                "trace_id": trace_id,
                "span_id": span_id,
                "source": {
                    "type": "trace",
                    "name": "opentelemetry",
                    "uri": "otlp:http:portable-runtime",
                },
            }
        ],
        "overlaps": [],
        "pool_interactions": [
            {
                "id": interaction_id,
                "execution_id": execution_id,
                "code_symbol": "code:PoolController#work()",
                "pool_id": "pool:active_record.primary",
                "technology": "active_record",
                "config_name": "primary",
                "trace_id": trace_id,
                "span_id": span_id,
                "event_index": 0,
                "observed_at": "2026-09-15T15:00:00.260000Z",
                "checkout_wait_ms": wait_ms,
                "observed_size": 1,
                "observed_busy": 1,
                "observed_waiting": 1,
                "source": {
                    "type": "trace",
                    "name": "opentelemetry",
                    "uri": "otlp:http:portable-runtime",
                },
            }
        ],
        "limitations": [
            "Test fixture contains one explicitly bound Rails request and one exact pool checkout interaction."
        ],
    }


def bootstrap(app: Path) -> None:
    run(
        "bootstrap",
        str(app),
        "--system-id",
        "incident-seed-fixture",
        "--revision",
        "revision-incident-seed-123",
        "--repository",
        "https://github.com/sergii/causcope",
        "--env-file",
        "deployment.yml",
        "--database",
        "causcope",
        "--database-url-env",
        "CAUSCOPE_INCIDENT_SEED_DATABASE_URL",
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="causcope-runtime-seed-") as temporary:
        root = Path(temporary)
        app = root / "rails-app"
        shutil.copytree(FIXTURE, app)
        bootstrap(app)
        workspace = app / ".causcope"

        run("why", "checkout is slow", "--workspace", str(workspace))
        context = yaml.safe_load((workspace / "incident-context.yaml").read_text(encoding="utf-8"))
        incident_id = context["incident_id"]

        receiver = run("runtime", "start", str(app), "--dry-run")
        assert f"Investigation: {incident_id}" in receiver.stdout
        assert f"--incident-id {incident_id}" in receiver.stdout
        expected_runtime_path = workspace / "runtime" / f"{incident_id}.json"
        assert str(expected_runtime_path) in receiver.stdout

        static = json.loads((workspace / "concrete-system-facts.json").read_text(encoding="utf-8"))
        write_json(expected_runtime_path, runtime_document(static, incident_id))

        seeded = run(
            "runtime",
            "seed",
            str(app),
            "--request-latency-threshold-ms",
            "200",
            "--pool-wait-threshold-ms",
            "50",
            "--json",
        )
        seed = json.loads(seeded.stdout)
        assert seed["kind"] == "incident_seed_result"
        assert seed["incident_id"] == incident_id
        assert seed["evidence_revision"] == 1
        assert seed["request_duration_ms"] == 500.0
        assert seed["pool_wait_ms"] == 260.0
        assert seed["runtime_resource"] == "pool:active_record.primary"
        assert seed["target_resource"] == "db.causcope.prod"
        assert seed["leading_hypothesis"] == "hypothesis.database.connection_pool_exhaustion"
        assert seed["selected_execution"] == "execution.opentelemetry.0123456789abcdef"
        assert seed["selected_pool_interaction"] == "pool_interaction.opentelemetry.fedcba9876543210"

        evidence = json.loads((workspace / "runtime-evidence.json").read_text(encoding="utf-8"))
        observations = {item["observation"]: item for item in evidence["instances"]}
        assert set(observations) == {
            "observation.http.request_latency",
            "observation.database.connection_pool_wait_time",
        }
        request = observations["observation.http.request_latency"]
        pool_wait = observations["observation.database.connection_pool_wait_time"]
        assert request["measurement"]["comparison"] == "above_baseline"
        assert pool_wait["measurement"]["value"] == 260.0
        assert pool_wait["measurement"]["baseline"] == 50.0
        assert pool_wait["source"]["attributes"]["otel.trace_id"] == "a" * 32
        assert pool_wait["source"]["attributes"]["causcope.target_resource"] == "db.causcope.prod"

        relationships = json.loads(
            (workspace / "runtime-relationships.json").read_text(encoding="utf-8")
        )
        assert len(relationships["relationships"]) == 1
        assert relationships["relationships"][0]["object_resource"] == "pool:active_record.primary"

        diagnosis = json.loads((workspace / "diagnosis.json").read_text(encoding="utf-8"))
        assert diagnosis["evidence_revision"] == 1
        pool_diagnosis = next(
            item
            for partition in diagnosis["partitions"]
            for item in partition["diagnoses"]
            if item["target"] == "observation.database.connection_pool_wait_time"
        )
        assert pool_diagnosis["ranking"]["candidates"][0]["source"]["id"] == (
            "hypothesis.database.connection_pool_exhaustion"
        )

        why = run("why", "--workspace", str(workspace), "--json")
        why_document = json.loads(why.stdout)
        assert why_document["status"] == "diagnosis_available"
        resolution = next(
            item
            for item in why_document["target_resolution"]["resolutions"]
            if item["diagnosis_target"] == "observation.database.connection_pool_wait_time"
        )
        assert resolution["status"] == "resolved"
        assert resolution["target_bindings"][0]["target_resource"] == "db.causcope.prod"

        overwrite = run(
            "runtime",
            "seed",
            str(app),
            "--request-latency-threshold-ms",
            "200",
            "--pool-wait-threshold-ms",
            "50",
            check=False,
        )
        assert overwrite.returncode == 2
        assert "refusing to overwrite existing incident seed artifacts" in overwrite.stderr

        forced = run(
            "runtime",
            "seed",
            str(app),
            "--request-latency-threshold-ms",
            "200",
            "--pool-wait-threshold-ms",
            "50",
            "--force",
            "--json",
        )
        assert json.loads(forced.stdout)["evidence_revision"] == 1

        low_wait_app = root / "low-wait-app"
        shutil.copytree(FIXTURE, low_wait_app)
        bootstrap(low_wait_app)
        low_workspace = low_wait_app / ".causcope"
        run("why", "checkout is slow", "--workspace", str(low_workspace))
        low_context = yaml.safe_load(
            (low_workspace / "incident-context.yaml").read_text(encoding="utf-8")
        )
        low_incident_id = low_context["incident_id"]
        low_static = json.loads(
            (low_workspace / "concrete-system-facts.json").read_text(encoding="utf-8")
        )
        low_runtime = low_workspace / "runtime" / f"{low_incident_id}.json"
        write_json(low_runtime, runtime_document(low_static, low_incident_id, wait_ms=2.0))
        no_seed = run(
            "runtime",
            "seed",
            str(low_wait_app),
            "--request-latency-threshold-ms",
            "200",
            "--pool-wait-threshold-ms",
            "50",
            check=False,
        )
        assert no_seed.returncode == 2
        assert "no request execution satisfied both explicit objectives" in no_seed.stderr
        assert not (low_workspace / "runtime-evidence.json").exists()
        assert not (low_workspace / "diagnosis.json").exists()

        mismatch_app = root / "mismatch-app"
        shutil.copytree(FIXTURE, mismatch_app)
        bootstrap(mismatch_app)
        mismatch_workspace = mismatch_app / ".causcope"
        run("why", "checkout is slow", "--workspace", str(mismatch_workspace))
        mismatch_static = json.loads(
            (mismatch_workspace / "concrete-system-facts.json").read_text(encoding="utf-8")
        )
        mismatch_runtime = mismatch_workspace / "runtime" / "wrong.json"
        write_json(mismatch_runtime, runtime_document(mismatch_static, "incident.other"))
        mismatch = run(
            "runtime",
            "seed",
            str(mismatch_app),
            "--runtime-facts",
            str(mismatch_runtime),
            "--request-latency-threshold-ms",
            "200",
            "--pool-wait-threshold-ms",
            "50",
            check=False,
        )
        assert mismatch.returncode == 2
        assert "expected current investigation" in mismatch.stderr
        assert not (mismatch_workspace / "runtime-evidence.json").exists()

    print("Causcope observed Rails incident bootstrap: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

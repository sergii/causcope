#!/usr/bin/env python3

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

from test_runtime_incident_seed import FIXTURE, bootstrap, run
from test_workspace_objectives import configure_objectives


def write_emitter(path: Path) -> None:
    path.write_text(
        '''import json
import os
import urllib.request


def attr(key, value, kind="stringValue"):
    return {"key": key, "value": {kind: value}}

endpoint = os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"]
system_id = os.environ["CAUSCOPE_SYSTEM_ID"]
revision = os.environ["CAUSCOPE_REVISION"]
start = 1_760_000_000_000_000_000
checkout = start + 260_000_000
end = start + 500_000_000
payload = {
    "resourceSpans": [
        {
            "resource": {
                "attributes": [
                    attr("service.name", system_id),
                    attr("causcope.system_id", system_id),
                    attr("causcope.revision", revision),
                ]
            },
            "scopeSpans": [
                {
                    "scope": {"name": "causcope.observe.test"},
                    "spans": [
                        {
                            "traceId": "c" * 32,
                            "spanId": "d" * 16,
                            "name": "GET /work",
                            "startTimeUnixNano": str(start),
                            "endTimeUnixNano": str(end),
                            "attributes": [
                                attr("causcope.code_symbol", "code:PoolController#work()"),
                            ],
                            "events": [
                                {
                                    "timeUnixNano": str(checkout),
                                    "name": "causcope.pool.checkout",
                                    "attributes": [
                                        attr("causcope.pool_id", "pool:active_record.primary"),
                                        attr("causcope.pool.technology", "active_record"),
                                        attr("causcope.pool.config_name", "primary"),
                                        attr("causcope.pool.checkout_wait_ms", 260.0, "doubleValue"),
                                        attr("causcope.pool.checkout_size", "1", "intValue"),
                                        attr("causcope.pool.checkout_busy", "1", "intValue"),
                                        attr("causcope.pool.checkout_waiting", "1", "intValue"),
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ]
}
request = urllib.request.Request(
    endpoint,
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=5) as response:
    assert response.status == 200
''',
        encoding="utf-8",
    )


def prepare(app: Path) -> tuple[Path, str]:
    bootstrap(app)
    run("rails", "install", str(app), "--no-gemfile")
    configure_objectives(app)
    workspace = app / ".causcope"
    run("why", "checkout is slow", "--workspace", str(workspace))
    context = yaml.safe_load((workspace / "incident-context.yaml").read_text(encoding="utf-8"))
    return workspace, context["incident_id"]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="causcope-runtime-observe-") as temporary:
        root = Path(temporary)

        app = root / "rails-app"
        shutil.copytree(FIXTURE, app)
        workspace, incident_id = prepare(app)
        emitter = app / "emit_observation.py"
        write_emitter(emitter)

        observed = run(
            "runtime",
            "observe",
            str(app),
            "--port",
            "4329",
            "--json",
            "--",
            sys.executable,
            str(emitter),
        )
        result = json.loads(observed.stdout)
        assert result["kind"] == "bounded_observation_session_result"
        assert result["incident_id"] == incident_id
        assert result["application_exit_code"] == 0
        assert result["seed"]["evidence_revision"] == 1
        assert result["seed"]["request_duration_ms"] == 500.0
        assert result["seed"]["pool_wait_ms"] == 260.0
        assert result["seed"]["target_resource"] == "db.causcope.prod"
        assert result["seed"]["leading_hypothesis"] == (
            "hypothesis.database.connection_pool_exhaustion"
        )
        assert result["seed"]["next_probe"] == "probe.database.measure_query_latency"
        assert Path(result["runtime_snapshot"]).is_file()
        assert (workspace / "runtime-evidence.json").is_file()
        assert (workspace / "runtime-relationships.json").is_file()
        assert (workspace / "diagnosis.json").is_file()

        why = run("why", "--workspace", str(workspace), "--json")
        why_document = json.loads(why.stdout)
        assert why_document["status"] == "diagnosis_available"

        missing_app = root / "missing-objectives"
        shutil.copytree(FIXTURE, missing_app)
        bootstrap(missing_app)
        run("rails", "install", str(missing_app), "--no-gemfile")
        missing_workspace = missing_app / ".causcope"
        run("why", "checkout is slow", "--workspace", str(missing_workspace))
        marker = missing_app / "should-not-run"
        missing = run(
            "runtime",
            "observe",
            str(missing_app),
            "--port",
            "4330",
            "--",
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
            check=False,
        )
        assert missing.returncode == 2
        assert "objectives" in missing.stderr
        assert not marker.exists()
        assert not (missing_workspace / "diagnosis.json").exists()

        failed_app = root / "failed-command"
        shutil.copytree(FIXTURE, failed_app)
        failed_workspace, _failed_incident = prepare(failed_app)
        failed = run(
            "runtime",
            "observe",
            str(failed_app),
            "--port",
            "4331",
            "--",
            sys.executable,
            "-c",
            "import sys; sys.exit(3)",
            check=False,
        )
        assert failed.returncode == 2
        assert "bounded application command exited non-zero" in failed.stderr
        assert not (failed_workspace / "diagnosis.json").exists()

    print("Causcope bounded runtime observation session: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

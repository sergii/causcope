#!/usr/bin/env python3

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import yaml

from test_runtime_incident_seed import FIXTURE, bootstrap, run, runtime_document, write_json


def configure_objectives(app: Path) -> dict:
    result = run(
        "objectives",
        "set",
        str(app),
        "--request-latency-ms",
        "200",
        "--pool-wait-ms",
        "50",
        "--json",
    )
    return json.loads(result.stdout)


def prepare_runtime(app: Path) -> tuple[Path, str]:
    workspace = app / ".causcope"
    run("why", "checkout is slow", "--workspace", str(workspace))
    context = yaml.safe_load((workspace / "incident-context.yaml").read_text(encoding="utf-8"))
    incident_id = context["incident_id"]
    static = json.loads((workspace / "concrete-system-facts.json").read_text(encoding="utf-8"))
    runtime_path = workspace / "runtime" / f"{incident_id}.json"
    write_json(runtime_path, runtime_document(static, incident_id))
    return workspace, incident_id


def main() -> int:
    help_result = run("runtime", "seed", "--help")
    assert "--request-latency-threshold-ms" in help_result.stdout
    assert "--pool-wait-threshold-ms" in help_result.stdout

    with tempfile.TemporaryDirectory(prefix="causcope-objectives-") as temporary:
        root = Path(temporary)

        app = root / "rails-app"
        shutil.copytree(FIXTURE, app)
        bootstrap(app)
        objectives = configure_objectives(app)
        assert objectives["kind"] == "workspace_objectives"
        assert [item["observation"] for item in objectives["objectives"]] == [
            "observation.http.request_latency",
            "observation.database.connection_pool_wait_time",
        ]
        assert all(item["source"]["type"] == "user_declared" for item in objectives["objectives"])

        shown = run("objectives", "show", str(app), "--json")
        assert json.loads(shown.stdout) == objectives

        workspace, incident_id = prepare_runtime(app)
        seeded = run("runtime", "seed", str(app), "--json")
        seed = json.loads(seeded.stdout)
        assert seed["incident_id"] == incident_id
        assert seed["request_latency_threshold_ms"] == 200.0
        assert seed["pool_wait_threshold_ms"] == 50.0
        assert seed["leading_hypothesis"] == "hypothesis.database.connection_pool_exhaustion"
        assert seed["next_probe"] == "probe.database.measure_query_latency"
        assert (workspace / "diagnosis.json").exists()

        missing_app = root / "missing-objectives"
        shutil.copytree(FIXTURE, missing_app)
        bootstrap(missing_app)
        prepare_runtime(missing_app)
        missing = run("runtime", "seed", str(missing_app), "--json", check=False)
        assert missing.returncode == 2
        assert "missing incident bootstrap objectives" in missing.stderr
        assert "causcope objectives set" in missing.stderr

        partial_app = root / "partial-override"
        shutil.copytree(FIXTURE, partial_app)
        bootstrap(partial_app)
        configure_objectives(partial_app)
        prepare_runtime(partial_app)
        partial = run(
            "runtime",
            "seed",
            str(partial_app),
            "--request-latency-threshold-ms",
            "600",
            "--json",
            check=False,
        )
        assert partial.returncode == 2
        assert "request > 600 ms" in partial.stderr
        assert "pool wait > 50 ms" in partial.stderr

        invalid = run(
            "objectives",
            "set",
            str(root),
            "--request-latency-ms",
            "0",
            "--pool-wait-ms",
            "50",
            check=False,
        )
        assert invalid.returncode == 2
        assert "request latency objective must be positive" in invalid.stderr

    print("Causcope workspace objectives: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

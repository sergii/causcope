#!/usr/bin/env python3

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from test_runtime_incident_seed import FIXTURE, bootstrap, run
from test_runtime_observe import write_emitter
from test_workspace_objectives import configure_objectives


def prepare(app: Path) -> Path:
    bootstrap(app)
    run("rails", "install", str(app), "--no-gemfile")
    configure_objectives(app)
    emitter = app / "emit_observation.py"
    write_emitter(emitter)
    return emitter


def main() -> int:
    help_result = run("why", "--help")
    assert "--observe RAILS_ROOT" in help_result.stdout

    with tempfile.TemporaryDirectory(prefix="causcope-why-observe-") as temporary:
        root = Path(temporary)

        app = root / "rails-app"
        shutil.copytree(FIXTURE, app)
        emitter = prepare(app)

        result = run(
            "why",
            "checkout is slow",
            "--observe",
            str(app),
            "--json",
            "--",
            sys.executable,
            str(emitter),
        )
        document = json.loads(result.stdout)
        workspace = app / ".causcope"
        assert document["kind"] == "causcope_why"
        assert document["problem"] == "checkout is slow"
        assert document["status"] == "diagnosis_available"
        assert document["diagnosis"]["evidence_revision"] == 1
        assert "acquisition" not in document
        assert (workspace / "incident-context.yaml").is_file()
        assert (workspace / "runtime-evidence.json").is_file()
        assert (workspace / "runtime-relationships.json").is_file()
        assert (workspace / "diagnosis.json").is_file()

        resolution = next(
            item
            for item in document["target_resolution"]["resolutions"]
            if item["diagnosis_target"] == "observation.http.request_latency"
        )
        assert resolution["status"] == "resolved"
        assert resolution["probe_id"] == "probe.database.measure_query_latency"
        assert resolution["target_bindings"][0]["target_resource"] == "db.causcope.prod"

        marker = app / "must-not-run-again"
        second = run(
            "why",
            "checkout is slow",
            "--observe",
            str(app),
            "--",
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
            check=False,
        )
        assert second.returncode == 2
        assert "already has diagnosis.json" in second.stderr
        assert not marker.exists()

        conflict = run(
            "why",
            "checkout is slow",
            "--observe",
            str(app),
            "--acquire",
            "--",
            sys.executable,
            "-c",
            "print('must not run')",
            check=False,
        )
        assert conflict.returncode == 2
        assert "cannot be combined with --acquire" in conflict.stderr

        missing_app = root / "missing-objectives"
        shutil.copytree(FIXTURE, missing_app)
        bootstrap(missing_app)
        run("rails", "install", str(missing_app), "--no-gemfile")
        missing_marker = missing_app / "must-not-run"
        missing = run(
            "why",
            "checkout is slow",
            "--observe",
            str(missing_app),
            "--",
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(missing_marker)!r}).write_text('ran')",
            check=False,
        )
        assert missing.returncode == 2
        assert "objectives" in missing.stderr
        assert not missing_marker.exists()
        assert (missing_app / ".causcope" / "incident-context.yaml").is_file()
        assert not (missing_app / ".causcope" / "diagnosis.json").exists()

    print("Causcope why bounded observation composition: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

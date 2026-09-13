#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from scoping_projection import load_incident_context

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "causcope_cli.py"
SESSION_SCHEMA = ROOT / "schema" / "investigation-session.schema.json"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="causcope-cli-") as temporary:
        workspace = Path(temporary) / ".causcope"

        started = run(
            "investigate",
            "Checkout sometimes fails",
            "--incident-id",
            "incident.test.checkout",
            "--workspace",
            str(workspace),
            "--non-interactive",
        )
        assert "Started incident.test.checkout" in started.stdout
        assert "Who is affected and how broadly?" in started.stdout

        context_path = workspace / "incident-context.yaml"
        session_path = workspace / "investigation-session.yaml"
        projection_path = workspace / "scoping-projection.json"
        assert context_path.exists()
        assert session_path.exists()
        assert projection_path.exists()

        initial_projection = json.loads(projection_path.read_text(encoding="utf-8"))
        assert initial_projection["next_action"]["dimension"] == "investigation.blast_radius"
        assert initial_projection["completeness"] == 0.0

        blast = run(
            "answer",
            "blast_radius",
            "unit=users",
            "affected=8",
            "total=100",
            "--workspace",
            str(workspace),
        )
        assert "Recorded blast_radius" in blast.stdout
        assert "Where does the failure occur?" in blast.stdout

        where = run(
            "answer",
            "where",
            "environment=production",
            "region=eu-central",
            "--workspace",
            str(workspace),
        )
        assert "Recorded where" in where.stdout
        assert "When did the problem begin" in where.stdout

        status = run("status", "--workspace", str(workspace), "--json")
        status_projection = json.loads(status.stdout)
        assert status_projection["known_count"] == 2
        assert status_projection["next_action"]["dimension"] == "investigation.when"

        context = load_incident_context(context_path)
        assert context["impact"]["populations"][0]["affected"] == 8
        assert context["impact"]["populations"][0]["total"] == 100
        assert context["scope"]["environments"] == ["production"]
        assert context["scope"]["regions"] == ["eu-central"]
        assert "who" not in context["unknowns"]
        assert "where" not in context["unknowns"]

        session = yaml.safe_load(session_path.read_text(encoding="utf-8"))
        schema = json.loads(SESSION_SCHEMA.read_text(encoding="utf-8"))
        errors = sorted(Draft202012Validator(schema).iter_errors(session), key=lambda item: list(item.path))
        assert not errors, "; ".join(error.message for error in errors)
        assert session["context_revision"] == 2
        assert [event["type"] for event in session["events"]] == [
            "question",
            "answer",
            "question",
            "answer",
        ]

        report = run("report", "--workspace", str(workspace))
        assert "# Incident report: incident.test.checkout" in report.stdout
        assert "Checkout sometimes fails" in report.stdout
        assert "Scoping completeness: 20.0%" in report.stdout
        assert "## Next recommended action" in report.stdout
        assert "When did the problem begin" in report.stdout

    print("Causcope investigator CLI: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

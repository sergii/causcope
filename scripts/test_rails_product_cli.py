#!/usr/bin/env python3

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "lab" / "rails-connection-pool"
CLI = ROOT / "bin" / "causcope"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI), *args],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def prepare_app(path: Path) -> Path:
    shutil.copytree(FIXTURE, path)
    fixture_initializer = path / "config" / "initializers" / "opentelemetry.rb"
    fixture_initializer.unlink()
    gemfile = path / "Gemfile"
    gemfile.write_text(
        "\n".join(
            line
            for line in gemfile.read_text(encoding="utf-8").splitlines()
            if "opentelemetry-sdk" not in line and "opentelemetry-exporter-otlp" not in line
        )
        + "\n",
        encoding="utf-8",
    )
    return gemfile


def scan_app(app: Path, *, system_id: str, revision: str) -> None:
    result = run(
        "scan",
        str(app),
        "--provider",
        "rails",
        "--environment",
        "production",
        "--env-file",
        "deployment.yml",
        "--system-id",
        system_id,
        "--revision",
        revision,
    )
    assert "Provider: rails" in result.stdout


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="causcope-rails-product-") as temporary:
        temporary_root = Path(temporary)

        conflict_app = temporary_root / "atomic-conflict-app"
        conflict_gemfile = prepare_app(conflict_app)
        scan_app(conflict_app, system_id="atomic-conflict", revision="revision-atomic")
        conflicting_initializer = conflict_app / "config" / "initializers" / "causcope.rb"
        conflicting_initializer.write_text("# user-owned initializer\n", encoding="utf-8")
        gemfile_before_conflict = conflict_gemfile.read_text(encoding="utf-8")
        conflict_result = run("rails", "install", str(conflict_app), check=False)
        assert conflict_result.returncode == 2
        assert "refusing to overwrite existing file" in conflict_result.stderr
        assert not (conflict_app / "lib" / "causcope" / "runtime.rb").exists()
        assert conflict_gemfile.read_text(encoding="utf-8") == gemfile_before_conflict
        assert conflicting_initializer.read_text(encoding="utf-8") == "# user-owned initializer\n"

        app = temporary_root / "app"
        gemfile = prepare_app(app)
        scan_app(app, system_id="product-cli-fixture", revision="revision-product-123")

        facts_path = app / ".causcope" / "concrete-system-facts.json"
        facts = json.loads(facts_path.read_text(encoding="utf-8"))
        assert facts["system_id"] == "product-cli-fixture"
        assert facts["revision"]["value"] == "revision-product-123"

        install = run("rails", "install", str(app))
        assert "System: product-cli-fixture" in install.stdout
        runtime = app / "lib" / "causcope" / "runtime.rb"
        initializer = app / "config" / "initializers" / "causcope.rb"
        assert runtime.is_file()
        assert initializer.is_file()
        assert "causcope rails install" in initializer.read_text(encoding="utf-8")

        installed_gemfile = gemfile.read_text(encoding="utf-8")
        assert installed_gemfile.count('gem "opentelemetry-sdk"') == 1
        assert installed_gemfile.count('gem "opentelemetry-exporter-otlp"') == 1

        syntax = subprocess.run(
            ["ruby", "-c", str(runtime)],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "Syntax OK" in syntax.stdout

        second_install = run("rails", "install", str(app))
        assert "Unchanged:" in second_install.stdout
        second_gemfile = gemfile.read_text(encoding="utf-8")
        assert second_gemfile == installed_gemfile

        env_probe = run(
            "rails",
            "run",
            str(app),
            "--revision",
            "revision-product-123",
            "--otel-endpoint",
            "http://127.0.0.1:9999/v1/traces",
            "--",
            "ruby",
            "-e",
            "puts [ENV.fetch('CAUSCOPE_SYSTEM_ID'), ENV.fetch('CAUSCOPE_REVISION'), ENV.fetch('CAUSCOPE_STATIC_FACTS'), ENV.fetch('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT')].join('|')",
        )
        values = env_probe.stdout.strip().split("|")
        assert values[0] == "product-cli-fixture"
        assert values[1] == "revision-product-123"
        assert Path(values[2]) == facts_path.resolve()
        assert values[3] == "http://127.0.0.1:9999/v1/traces"

        mismatch = run(
            "rails",
            "run",
            str(app),
            "--revision",
            "revision-different",
            "--",
            "ruby",
            "-e",
            "abort 'must not execute'",
            check=False,
        )
        assert mismatch.returncode == 2
        assert "does not match scanned concrete facts" in mismatch.stderr
        assert "must not execute" not in mismatch.stderr

        initializer.write_text("# user-owned initializer\n", encoding="utf-8")
        conflict = run("rails", "install", str(app), check=False)
        assert conflict.returncode == 2
        assert "refusing to overwrite existing file" in conflict.stderr
        forced = run("rails", "install", str(app), "--force")
        assert "Replaced:" in forced.stdout

        dry_run = run(
            "runtime",
            "start",
            str(app),
            "--incident-id",
            "INC PRODUCT/1",
            "--port",
            "54321",
            "--dry-run",
        )
        assert "System: product-cli-fixture" in dry_run.stdout
        assert "Revision: revision-product-123" in dry_run.stdout
        assert "http://127.0.0.1:54321/v1/traces" in dry_run.stdout
        assert "INC-PRODUCT-1.json" in dry_run.stdout
        assert "otlp_concrete_receiver.py" in dry_run.stdout
        assert "--incident-id 'INC PRODUCT/1'" in dry_run.stdout

        missing = temporary_root / "missing-facts-app"
        shutil.copytree(FIXTURE, missing)
        result = run("rails", "install", str(missing), check=False)
        assert result.returncode == 2
        assert "run `causcope scan <rails-root>` first" in result.stderr

    print("Rails product CLI lifecycle: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

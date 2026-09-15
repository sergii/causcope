#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

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
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
        )
        diagnosis = json.loads(diagnosed_json.stdout)
        assert diagnosis["status"] == "confirmed"
        assert diagnosis["epistemic_state"] == "CAUSAL_DIAGNOSIS_CONFIRMED"
        assert diagnosis["root_cause"] == "application-side database connection pool exhaustion"

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

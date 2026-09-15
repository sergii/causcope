#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from test_rails_pool_vertical_slice import fixtures

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "causcope"


def write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI), *args],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="causcope-why-workspace-golden-") as temporary:
        workspace = Path(temporary) / ".causcope"
        static, runtime, pool = fixtures()

        write_json(workspace / "concrete-system-facts.json", static)
        write_json(workspace / "concrete-runtime-facts.json", runtime)
        write_json(workspace / "resource-pool-runtime-evidence.json", pool)

        diagnosed = run(
            "why",
            "checkout is slow",
            "--workspace",
            str(workspace),
            "--require-confirmed",
        )
        assert "CONFIRMED (CAUSAL_DIAGNOSIS_CONFIRMED)" in diagnosed.stdout
        assert "application-side database connection pool exhaustion" in diagnosed.stdout
        assert "code:CheckoutController#create()" in diagnosed.stdout
        assert "pool:active_record.primary" in diagnosed.stdout
        assert "PostgreSQL-wide connection admission exhaustion" in diagnosed.stdout
        assert "not established by this bounded slice" in diagnosed.stdout

        diagnosed_json = run(
            "why",
            "checkout is slow",
            "--workspace",
            str(workspace),
            "--require-confirmed",
            "--json",
        )
        document = json.loads(diagnosed_json.stdout)
        assert document["status"] == "confirmed"
        assert document["epistemic_state"] == "CAUSAL_DIAGNOSIS_CONFIRMED"
        assert document["root_cause"] == "application-side database connection pool exhaustion"

        incomplete = Path(temporary) / "incomplete" / ".causcope"
        write_json(incomplete / "concrete-system-facts.json", static)
        result = run(
            "why",
            "checkout is slow",
            "--workspace",
            str(incomplete),
            "--require-confirmed",
            check=False,
        )
        assert result.returncode == 2
        assert "complete Rails D3.1 proof" in result.stderr

    print("Causcope why workspace golden proof: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
    with tempfile.TemporaryDirectory(prefix="causcope-why-workspace-compatibility-") as temporary:
        workspace = Path(temporary) / ".causcope"
        static, runtime, pool = fixtures()
        static_path = workspace / "concrete-system-facts.json"
        runtime_path = workspace / "concrete-runtime-facts.json"
        pool_path = workspace / "resource-pool-runtime-evidence.json"

        write_json(static_path, static)
        write_json(runtime_path, runtime)
        write_json(pool_path, pool)

        # Retaining old proof artifacts must not silently make the compatibility
        # X-Ray a product authority. Compatibility requires explicit paths.
        implicit = run(
            "why",
            "checkout is slow",
            "--workspace",
            str(workspace),
            "--require-confirmed",
            check=False,
        )
        assert implicit.returncode == 2
        assert "requires --static, --runtime, and --pool" in implicit.stderr
        assert "CAUSAL_DIAGNOSIS_CONFIRMED" not in implicit.stdout

        explicit = run(
            "why",
            "checkout is slow",
            "--workspace",
            str(workspace),
            "--static",
            str(static_path),
            "--runtime",
            str(runtime_path),
            "--pool",
            str(pool_path),
            "--require-confirmed",
        )
        assert "CONFIRMED (CAUSAL_DIAGNOSIS_CONFIRMED)" in explicit.stdout
        assert "application-side database connection pool exhaustion" in explicit.stdout

        explicit_json = run(
            "why",
            "checkout is slow",
            "--static",
            str(static_path),
            "--runtime",
            str(runtime_path),
            "--pool",
            str(pool_path),
            "--require-confirmed",
            "--json",
        )
        document = json.loads(explicit_json.stdout)
        assert document["status"] == "confirmed"
        assert document["epistemic_state"] == "CAUSAL_DIAGNOSIS_CONFIRMED"

    print("Causcope explicit compatibility proof boundary: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

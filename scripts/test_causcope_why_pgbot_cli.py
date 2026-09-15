#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import yaml

from test_causcope_why_acquire import prepare_workspace

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "causcope"
SECRET_DSN = "postgresql://causcope:test-secret@127.0.0.1:5432/orders"
DATABASE_URL_ENV = "CAUSCOPE_TEST_ORDERS_DATABASE_URL"


def run_with_env(
    workspace: Path,
    *args: str,
    env: dict[str, str],
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI), *args, "--workspace", str(workspace)],
        cwd=ROOT,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def write_fake_pgbot(directory: Path, marker: Path) -> Path:
    executable = directory / "pgbot"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

marker = pathlib.Path(os.environ["CAUSCOPE_TEST_PGBOT_MARKER"])
marker.parent.mkdir(parents=True, exist_ok=True)
with marker.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"argv": sys.argv[1:]}) + "\\n")

if sys.argv[1:] != ["inspect", "--json"]:
    sys.exit(64)

expected = os.environ["CAUSCOPE_TEST_EXPECTED_DATABASE_URL"]
if os.environ.get("DATABASE_URL") != expected:
    print("DATABASE_URL mismatch", file=sys.stderr)
    sys.exit(3)

# The parent environment may contain this legacy variable. Causcope must not
# pass it through to pgbot when it supplies the explicit DATABASE_URL binding.
if "PGBOT_DATABASE_URL" in os.environ:
    print("unexpected PGBOT_DATABASE_URL", file=sys.stderr)
    sys.exit(3)

report = {
    "schema_version": "1.2.0",
    "collected_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    "fingerprint": "fake-live-pgbot",
    "server": {
        "database": os.environ.get("CAUSCOPE_TEST_REPORTED_DATABASE", "orders")
    },
    "findings": [
        {
            "id": "query_slowdown",
            "object": "query:live-test",
            "severity": "warn",
            "detail": "Live fake pgbot observed query slowdown.",
            "confidence": 0.99
        }
    ]
}
print(json.dumps(report))
# pgbot report exit codes 0/1/2 are valid diagnostic states. Use 2 to prove
# Causcope accepts a report-bearing non-zero diagnostic exit code.
sys.exit(2)
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def configure_cli_binding(workspace: Path) -> None:
    bindings_path = workspace / "provider-bindings.yaml"
    document = yaml.safe_load(bindings_path.read_text(encoding="utf-8"))
    binding = document["bindings"][0]
    binding.pop("context", None)
    binding["driver"] = "pgbot_cli"
    binding["database_url_env"] = DATABASE_URL_ENV
    binding["timeout_seconds"] = 10
    bindings_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def base_env(fake_bin: Path, marker: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    env[DATABASE_URL_ENV] = SECRET_DSN
    env["CAUSCOPE_TEST_EXPECTED_DATABASE_URL"] = SECRET_DSN
    env["CAUSCOPE_TEST_PGBOT_MARKER"] = str(marker)
    # Prove the supplier deliberately removes this variable in the child.
    env["PGBOT_DATABASE_URL"] = "must-not-reach-child"
    return env


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="causcope-why-pgbot-cli-") as temporary:
        root = Path(temporary)
        fake_bin = root / "bin"
        fake_bin.mkdir()
        marker = root / "pgbot-invocations.jsonl"
        write_fake_pgbot(fake_bin, marker)

        workspace = root / "happy" / ".causcope"
        workspace.mkdir(parents=True)
        prepare_workspace(workspace)
        configure_cli_binding(workspace)
        env = base_env(fake_bin, marker)

        # Discovery must be non-invasive. Plain `why` may verify that the
        # executable and env binding exist, but it must not query PostgreSQL.
        before = run_with_env(
            workspace,
            "why",
            "database requests are slow",
            "--json",
            env=env,
        )
        before_document = json.loads(before.stdout)
        route = before_document["routing"]["routes"][0]
        assert route["decision"]["selected_instrument"]["id"] == "provider.pgbot.orders-prod"
        assert not marker.exists(), "plain why unexpectedly executed pgbot"

        acquired = run_with_env(
            workspace,
            "why",
            "database requests are slow",
            "--acquire",
            "--json",
            env=env,
        )
        document = json.loads(acquired.stdout)
        result = document["acquisition"]
        assert result["previous_evidence_revision"] == 7
        assert result["evidence_revision"] == 8
        assert result["rerank_count"] == 1
        assert result["member_results"][0]["target_resource"] == "db.orders.prod"
        assert result["member_results"][0]["instrument_id"] == "provider.pgbot.orders-prod"

        invocations = [json.loads(line) for line in marker.read_text(encoding="utf-8").splitlines()]
        assert invocations == [{"argv": ["inspect", "--json"]}]
        assert SECRET_DSN not in acquired.stdout
        assert SECRET_DSN not in acquired.stderr

        committed = json.loads((workspace / "runtime-evidence.json").read_text(encoding="utf-8"))
        added = [
            instance
            for instance in committed["instances"]
            if instance["id"] in set(result["added_instance_ids"])
        ]
        assert len(added) == 1
        assert added[0]["source"]["attributes"]["routing.target_resource"] == "db.orders.prod"
        assert added[0]["source"]["attributes"]["routing.instrument_id"] == "provider.pgbot.orders-prod"

        # TOCTOU safety: live identity is checked on the actual acquisition
        # read, not only when the binding is loaded during routing.
        mismatch_workspace = root / "mismatch" / ".causcope"
        mismatch_workspace.mkdir(parents=True)
        prepare_workspace(mismatch_workspace)
        configure_cli_binding(mismatch_workspace)
        mismatch_marker = root / "pgbot-mismatch-invocations.jsonl"
        mismatch_env = base_env(fake_bin, mismatch_marker)
        mismatch_env["CAUSCOPE_TEST_REPORTED_DATABASE"] = "payments"

        routed = run_with_env(
            mismatch_workspace,
            "why",
            "database requests are slow",
            "--json",
            env=mismatch_env,
        )
        routed_document = json.loads(routed.stdout)
        routed_route = routed_document["routing"]["routes"][0]
        assert routed_route["decision"]["selected_instrument"]["id"] == "provider.pgbot.orders-prod"
        assert not mismatch_marker.exists(), "plain why unexpectedly queried live pgbot"

        mismatch = run_with_env(
            mismatch_workspace,
            "why",
            "database requests are slow",
            "--acquire",
            "--json",
            env=mismatch_env,
            check=False,
        )
        assert mismatch.returncode == 2
        assert "database identity mismatch" in mismatch.stderr
        assert "orders" in mismatch.stderr
        assert "payments" in mismatch.stderr
        assert SECRET_DSN not in mismatch.stderr
        assert json.loads(
            (mismatch_workspace / "diagnosis.json").read_text(encoding="utf-8")
        )["evidence_revision"] == 7
        assert len(mismatch_marker.read_text(encoding="utf-8").splitlines()) == 1

    print("Causcope why live pgbot CLI acquisition: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

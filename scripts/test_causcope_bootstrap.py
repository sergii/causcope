#!/usr/bin/env python3

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

from provider_bindings import load_provider_bindings_document
from resource_topology import load_resource_topology

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "causcope"
FIXTURE = ROOT / "lab" / "rails-connection-pool"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI), *args],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def bootstrap(app: Path, *extra: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(
        "bootstrap",
        str(app),
        "--system-id",
        "bootstrap-rails-fixture",
        "--revision",
        "revision-bootstrap-123",
        "--repository",
        "https://github.com/sergii/causcope",
        "--env-file",
        "deployment.yml",
        "--database",
        "causcope",
        "--database-url-env",
        "CAUSCOPE_BOOTSTRAP_DATABASE_URL",
        *extra,
        check=check,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="causcope-bootstrap-") as temporary:
        temporary_root = Path(temporary)
        app = temporary_root / "rails-app"
        shutil.copytree(FIXTURE, app)

        result = bootstrap(app, "--json")
        document = json.loads(result.stdout)
        workspace = app / ".causcope"
        assert document["kind"] == "bootstrap_result"
        assert document["workspace"] == str(workspace.resolve())
        assert document["system_id"] == "bootstrap-rails-fixture"
        assert document["revision"] == "revision-bootstrap-123"
        assert document["pool"] == "pool:active_record.primary"
        assert document["pool_config"] == "primary"
        assert document["database"] == "causcope"
        assert document["database_url_env"] == "CAUSCOPE_BOOTSTRAP_DATABASE_URL"
        assert document["runtime_evidence_created"] is False
        assert document["diagnosis_created"] is False

        expected = {
            "concrete-system-facts.json",
            "resource-topology.yaml",
            "pgbot-postgresql.yaml",
            "provider-bindings.yaml",
        }
        assert {path.name for path in workspace.iterdir()} == expected

        topology = load_resource_topology(workspace / "resource-topology.yaml")
        assert topology.resolve_runtime_resource("pool:active_record.primary") == "db.causcope.prod"
        provider = topology.provider_instance("provider.pgbot.causcope-prod")
        assert provider["target"] == "db.causcope.prod"
        database = topology.resource("db.causcope.prod")
        assert database["attributes"]["database"] == "causcope"
        assert database["environment"] == "production"

        bindings = load_provider_bindings_document(workspace / "provider-bindings.yaml")
        assert bindings["bindings"] == [
            {
                "provider_instance": "provider.pgbot.causcope-prod",
                "driver": "pgbot_cli",
                "adapter": "pgbot-postgresql.yaml",
                "database_url_env": "CAUSCOPE_BOOTSTRAP_DATABASE_URL",
                "timeout_seconds": 30,
            }
        ]
        adapter = yaml.safe_load((workspace / "pgbot-postgresql.yaml").read_text(encoding="utf-8"))
        assert adapter["scope"]["attributes"]["service"] == "bootstrap-rails-fixture"
        assert adapter["scope"]["attributes"]["dependency"] == "postgresql"

        rendered_workspace = "\n".join(
            path.read_text(encoding="utf-8") for path in sorted(workspace.iterdir())
        )
        assert "postgresql://" not in rendered_workspace
        assert "CAUSCOPE_BOOTSTRAP_DATABASE_URL" in rendered_workspace

        conflict = bootstrap(app, check=False)
        assert conflict.returncode == 2
        assert "refusing to overwrite existing bootstrap artifacts" in conflict.stderr

        forced = bootstrap(app, "--force", "--json")
        assert json.loads(forced.stdout)["provider_instance"] == "provider.pgbot.causcope-prod"

        multi = temporary_root / "multi-db-app"
        shutil.copytree(FIXTURE, multi)
        ambiguous = bootstrap(multi, "--environment", "multi_database", check=False)
        assert ambiguous.returncode == 2
        assert "multiple PostgreSQL ActiveRecord pools" in ambiguous.stderr
        assert "primary" in ambiguous.stderr
        assert "replica" in ambiguous.stderr

        selected = bootstrap(
            multi,
            "--environment",
            "multi_database",
            "--pool-config",
            "replica",
            "--workspace",
            ".causcope-replica",
            "--json",
        )
        selected_document = json.loads(selected.stdout)
        assert selected_document["pool"] == "pool:active_record.replica"
        replica_topology = load_resource_topology(multi / ".causcope-replica" / "resource-topology.yaml")
        assert replica_topology.resolve_runtime_resource("pool:active_record.replica") == "db.causcope.multi_database"

    print("Causcope Rails/PostgreSQL bootstrap: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

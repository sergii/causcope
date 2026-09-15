#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCAN = ROOT / "scripts" / "causcope_scan.py"
PGBOT_ADAPTER = ROOT / "examples" / "adapters" / "pgbot" / "postgresql.yaml"


def slug(value: str, fallback: str) -> str:
    rendered = re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-")
    return rendered or fallback


def environment_slug(value: str) -> str:
    if value == "production":
        return "prod"
    if value == "development":
        return "dev"
    if value == "staging":
        return "staging"
    return slug(value, "env")


def workspace_path(root: Path, configured: Path | None) -> Path:
    if configured is None:
        return (root / ".causcope").resolve()
    if configured.is_absolute():
        return configured.resolve()
    return (root / configured).resolve()


def output_paths(workspace: Path) -> dict[str, Path]:
    return {
        "facts": workspace / "concrete-system-facts.json",
        "topology": workspace / "resource-topology.yaml",
        "adapter": workspace / "pgbot-postgresql.yaml",
        "bindings": workspace / "provider-bindings.yaml",
    }


def preflight(paths: dict[str, Path], *, force: bool) -> None:
    conflicts = sorted(str(path) for path in paths.values() if path.exists())
    if conflicts and not force:
        raise ValueError(
            "refusing to overwrite existing bootstrap artifacts; pass --force to replace: "
            + ", ".join(conflicts)
        )


def run_scan(args: argparse.Namespace, root: Path, facts_path: Path) -> None:
    command = [sys.executable, str(SCAN), str(root), "--provider", "rails", "--environment", args.environment, "--output", str(facts_path)]
    if args.system_id:
        command.extend(["--system-id", args.system_id])
    if args.revision:
        command.extend(["--revision", args.revision])
    if args.repository:
        command.extend(["--repository", args.repository])
    if args.database_config:
        command.extend(["--database-config", str(args.database_config)])
    if args.env_file:
        command.extend(["--env-file", str(args.env_file)])
    for item in args.env:
        command.extend(["--env", item])
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise ValueError(completed.stderr.strip() or completed.stdout.strip() or "Rails scan failed")


def load_facts(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("kind") != "concrete_system_facts":
        raise ValueError("bootstrap scan did not produce concrete_system_facts")
    return document


def select_postgres_pool(document: dict[str, Any], configured: str | None) -> dict[str, Any]:
    pools = [entity for entity in document.get("entities", []) if entity.get("kind") == "resource_pool" and entity.get("attributes", {}).get("technology") == "active_record" and entity.get("attributes", {}).get("adapter") == "postgresql"]
    if configured is not None:
        matching = [pool for pool in pools if pool.get("attributes", {}).get("config_name") == configured]
        if len(matching) != 1:
            available = ", ".join(sorted(str(pool.get("attributes", {}).get("config_name", "<unknown>")) for pool in pools)) or "none"
            raise ValueError(f"PostgreSQL ActiveRecord pool {configured!r} not found; available: {available}")
        return matching[0]
    if len(pools) == 1:
        return pools[0]
    if not pools:
        raise ValueError("Rails scan found no PostgreSQL ActiveRecord pool to bootstrap")
    available = ", ".join(sorted(str(pool.get("attributes", {}).get("config_name", "<unknown>")) for pool in pools))
    raise ValueError("Rails scan found multiple PostgreSQL ActiveRecord pools; pass --pool-config explicitly. Available: " + available)


def build_topology(document: dict[str, Any], pool: dict[str, Any], *, database: str, environment: str, network_domain: str) -> tuple[dict[str, Any], str]:
    env_slug = environment_slug(environment)
    system_slug = slug(document["system_id"], "rails-app")
    database_slug = slug(database, "database")
    service_id = f"service.{system_slug}.{env_slug}"
    database_id = f"db.{database_slug}.{env_slug}"
    runner_id = f"runner.local.{env_slug}"
    provider_instance = f"provider.pgbot.{database_slug}-{env_slug}"
    rails_provider_instance = f"provider.rails_pool.{system_slug}-{env_slug}"
    topology = {
        "schema_version": "0.1",
        "kind": "resource_topology",
        "resources": [
            {"id": service_id, "kind": "application_service", "environment": environment, "network_domain": network_domain, "attributes": {"service": document["system_id"], "framework": "rails"}},
            {"id": database_id, "kind": "postgresql_database", "environment": environment, "network_domain": network_domain, "attributes": {"database": database, "dependency": "postgresql"}},
        ],
        "relationships": [{"from": service_id, "relation": "depends_on", "to": database_id}],
        "runtime_bindings": [{"runtime_resource": pool["id"], "target_resource": database_id}],
        "runners": [{"id": runner_id, "kind": "edge_runner", "capabilities": ["outbound_postgresql", "local_file_read"], "network_domains": [network_domain], "available": True}],
        "provider_types": [
            {"id": "provider_type.pgbot.postgresql", "instrument": "pgbot", "provider_id": "provider.pgbot.postgresql", "runner_capabilities": ["outbound_postgresql"]},
            {"id": "provider_type.rails.active_record_pool", "instrument": "rails_runtime_evidence", "provider_id": "provider.rails.active_record_pool", "runner_capabilities": ["local_file_read"]},
        ],
        "provider_instances": [
            {"id": provider_instance, "provider_type": "provider_type.pgbot.postgresql", "target": database_id, "runner": runner_id},
            {"id": rails_provider_instance, "provider_type": "provider_type.rails.active_record_pool", "target": database_id, "runner": runner_id},
        ],
    }
    return topology, provider_instance


def build_adapter(system_id: str) -> dict[str, Any]:
    adapter = yaml.safe_load(PGBOT_ADAPTER.read_text(encoding="utf-8"))
    if not isinstance(adapter, dict):
        raise ValueError("canonical pgbot adapter is invalid")
    adapter.setdefault("scope", {}).setdefault("attributes", {})["service"] = system_id
    adapter["scope"]["attributes"]["dependency"] = "postgresql"
    return adapter


def build_bindings(provider_instance: str, *, rails_provider_instance: str | None = None, database_url_env: str, timeout_seconds: int) -> dict[str, Any]:
    bindings = [{"provider_instance": provider_instance, "driver": "pgbot_cli", "adapter": "pgbot-postgresql.yaml", "database_url_env": database_url_env, "timeout_seconds": timeout_seconds}]
    if rails_provider_instance is not None:
        bindings.append({
            "provider_instance": rails_provider_instance,
            "driver": "rails_pool_file",
            "pool_evidence": "resource-pool-runtime-evidence.json",
            "runtime_evidence": "runtime-evidence.json",
            "diagnosis": "diagnosis.json",
        })
    return {"schema_version": "0.1", "kind": "provider_bindings", "bindings": bindings}


def write_yaml(path: Path, document: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="causcope bootstrap", description="Bootstrap a bounded local Rails/PostgreSQL Causcope workspace without inventing runtime evidence.")
    parser.add_argument("path", type=Path, help="Rails repository root")
    parser.add_argument("--workspace", type=Path, help="Workspace path; defaults to PATH/.causcope")
    parser.add_argument("--environment", default="production")
    parser.add_argument("--system-id")
    parser.add_argument("--revision")
    parser.add_argument("--repository")
    parser.add_argument("--database-config", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--pool-config", help="ActiveRecord database config_name. Required when multiple PostgreSQL pools are present.")
    parser.add_argument("--database", required=True, help="Expected PostgreSQL database identity")
    parser.add_argument("--database-url-env", default="DATABASE_URL", help="Environment variable that will hold the read-only PostgreSQL DSN")
    parser.add_argument("--network-domain", help="Logical network domain; defaults to local.<environment>")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = args.path.expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Rails repository does not exist: {root}")
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", args.database_url_env):
            raise ValueError("--database-url-env must be an uppercase environment variable name")
        if not 1 <= args.timeout_seconds <= 300:
            raise ValueError("--timeout-seconds must be between 1 and 300")
        workspace = workspace_path(root, args.workspace)
        paths = output_paths(workspace)
        preflight(paths, force=args.force)
        workspace.mkdir(parents=True, exist_ok=True)
        run_scan(args, root, paths["facts"])
        facts = load_facts(paths["facts"])
        pool = select_postgres_pool(facts, args.pool_config)
        env_slug = environment_slug(args.environment)
        network_domain = args.network_domain or f"local.{env_slug}"
        topology, provider_instance = build_topology(facts, pool, database=args.database, environment=args.environment, network_domain=network_domain)
        rails_provider_instance = next(item["id"] for item in topology["provider_instances"] if item["provider_type"] == "provider_type.rails.active_record_pool")
        adapter = build_adapter(facts["system_id"])
        bindings = build_bindings(provider_instance, rails_provider_instance=rails_provider_instance, database_url_env=args.database_url_env, timeout_seconds=args.timeout_seconds)
        write_yaml(paths["topology"], topology)
        write_yaml(paths["adapter"], adapter)
        write_yaml(paths["bindings"], bindings)
        result = {
            "kind": "bootstrap_result", "workspace": str(workspace), "system_id": facts["system_id"],
            "revision": facts["revision"]["value"], "environment": args.environment, "pool": pool["id"],
            "pool_config": pool.get("attributes", {}).get("config_name"), "database": args.database,
            "provider_instance": provider_instance, "rails_provider_instance": rails_provider_instance,
            "database_url_env": args.database_url_env, "artifacts": {name: str(path) for name, path in paths.items()},
            "runtime_evidence_created": False, "diagnosis_created": False,
        }
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(f"Bootstrapped Causcope workspace: {workspace}")
            print(f"System: {facts['system_id']} @ {facts['revision']['value']}")
            print(f"PostgreSQL target: {args.database} via {pool['id']}")
            print(f"Providers: {provider_instance} (pgbot_cli), {rails_provider_instance} (Rails pool evidence)")
            print(f"Secret boundary: ${args.database_url_env}")
            print("Runtime evidence: not created (requires observation)")
            print("Diagnosis: not created (requires evidence)")
            print("Next: run `causcope rails install <rails-root>` if runtime instrumentation is not installed")
            print("Then start an investigation with `causcope why \"<problem>\"`")
        return 0
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"causcope bootstrap: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

import yaml

from concrete_system_facts import load_schema, validate_schema, validate_semantics


CODE_SYMBOL = "code:Handler#do_GET()"
SERVICE_ID = "service:database-connection-pool-app"
POOL_ID = "pool:application_database"
POOL_CONFIG_NAME = "application_database"
DEPENDENCY_ID = "dependency:postgresql"


def load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a YAML object")
    return payload


def find_handler_method(tree: ast.AST) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "Handler":
            continue
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "do_GET":
                return item
    raise ValueError("Handler.do_GET was not found in the application source")


def parse_env_default(tree: ast.AST, name: str, env_name: str) -> int:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        value = node.value
        if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Name) or value.func.id != "int":
            continue
        if len(value.args) != 1:
            continue
        getter = value.args[0]
        if not isinstance(getter, ast.Call) or len(getter.args) < 2:
            continue
        func = getter.func
        if not isinstance(func, ast.Attribute) or func.attr != "get":
            continue
        owner = func.value
        if not (
            isinstance(owner, ast.Attribute)
            and owner.attr == "environ"
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "os"
        ):
            continue
        key, default = getter.args[:2]
        if not isinstance(key, ast.Constant) or key.value != env_name:
            continue
        if not isinstance(default, ast.Constant):
            continue
        return int(default.value)
    raise ValueError(f"{name} must be sourced from os.environ.get({env_name!r}, <default>)")


def find_connection_pool(tree: ast.AST) -> tuple[int, float]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id != "ConnectionPool":
            continue
        keywords = {item.arg: item.value for item in node.keywords if item.arg}
        min_size = keywords.get("min_size")
        max_size = keywords.get("max_size")
        timeout = keywords.get("timeout")
        if not (
            isinstance(min_size, ast.Name)
            and min_size.id == "POOL_SIZE"
            and isinstance(max_size, ast.Name)
            and max_size.id == "POOL_SIZE"
        ):
            raise ValueError("ConnectionPool min_size and max_size must both bind to POOL_SIZE")
        if not isinstance(timeout, ast.Constant) or not isinstance(timeout.value, (int, float)):
            raise ValueError("ConnectionPool timeout must be a literal numeric value in this bounded extractor")
        return node.lineno, float(timeout.value)
    raise ValueError("ConnectionPool(...) declaration was not found")


def method_uses_pool(method: ast.FunctionDef) -> bool:
    for node in ast.walk(method):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "connection"
            and isinstance(func.value, ast.Name)
            and func.value.id == "pool"
        ):
            return True
    return False


def compose_pool_capacity(compose: dict[str, Any]) -> tuple[int, str]:
    services = compose.get("services")
    if not isinstance(services, dict):
        raise ValueError("compose document must contain services")
    app = services.get("app")
    db = services.get("db")
    if not isinstance(app, dict) or not isinstance(db, dict):
        raise ValueError("compose document must contain app and db services")

    environment = app.get("environment")
    if not isinstance(environment, dict) or "POOL_SIZE" not in environment:
        raise ValueError("app service must declare POOL_SIZE")
    capacity = int(environment["POOL_SIZE"])
    if capacity < 1:
        raise ValueError("POOL_SIZE must be positive")

    dependencies = app.get("depends_on", {})
    if isinstance(dependencies, dict):
        depends_on_db = "db" in dependencies
    elif isinstance(dependencies, list):
        depends_on_db = "db" in dependencies
    else:
        depends_on_db = False
    if not depends_on_db:
        raise ValueError("app service must depend on db in this bounded extractor")

    image = str(db.get("image", ""))
    if not image.startswith("postgres:"):
        raise ValueError("db service must use a PostgreSQL image")
    return capacity, image


def build_document(
    *,
    app_path: Path,
    compose_path: Path,
    system_id: str,
    revision_value: str,
    repository: str,
) -> dict[str, Any]:
    source = app_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(app_path))
    method = find_handler_method(tree)
    pool_default = parse_env_default(tree, "POOL_SIZE", "POOL_SIZE")
    pool_line, pool_timeout = find_connection_pool(tree)
    if not method_uses_pool(method):
        raise ValueError("Handler.do_GET does not acquire a connection from pool")

    compose = load_yaml(compose_path)
    configured_capacity, database_image = compose_pool_capacity(compose)

    revision = {
        "type": "git",
        "value": revision_value,
        "repository": repository,
    }
    source_ref = str(app_path)
    compose_ref = str(compose_path)

    document = {
        "schema_version": "0.1",
        "kind": "concrete_system_facts",
        "system_id": system_id,
        "revision": revision,
        "entities": [
            {
                "id": SERVICE_ID,
                "kind": "service",
                "label": "database-connection-pool-app",
                "certainty": "direct",
                "provenance": {
                    "source_type": "declared_config",
                    "name": "docker_compose",
                    "reference": compose_ref,
                },
                "attributes": {
                    "runtime": "python",
                },
            },
            {
                "id": CODE_SYMBOL,
                "kind": "code_symbol",
                "label": "Handler#do_GET()",
                "certainty": "direct",
                "provenance": {
                    "source_type": "static_analysis",
                    "name": "python_ast",
                    "reference": source_ref,
                },
                "source_location": {
                    "path": source_ref,
                    "start_line": method.lineno,
                    "end_line": method.end_lineno or method.lineno,
                },
            },
            {
                "id": POOL_ID,
                "kind": "resource_pool",
                "label": "application database connection pool",
                "certainty": "inferred",
                "provenance": {
                    "source_type": "generated",
                    "name": "python_connection_pool_concrete_facts",
                    "reference": f"{source_ref} + {compose_ref}",
                    "rule": "python.connection_pool.compose_capacity.v0",
                },
                "source_location": {
                    "path": source_ref,
                    "start_line": pool_line,
                },
                "attributes": {
                    "technology": "psycopg_pool",
                    "config_name": POOL_CONFIG_NAME,
                    "configured_capacity": configured_capacity,
                    "source_default_capacity": pool_default,
                    "checkout_timeout_seconds": pool_timeout,
                },
            },
            {
                "id": DEPENDENCY_ID,
                "kind": "external_dependency",
                "label": "PostgreSQL",
                "certainty": "direct",
                "provenance": {
                    "source_type": "declared_config",
                    "name": "docker_compose",
                    "reference": compose_ref,
                },
                "attributes": {
                    "dbms": "postgresql",
                    "image": database_image,
                },
            },
        ],
        "facts": [
            {
                "id": "fact.connection_pool.service_contains_handler",
                "subject": SERVICE_ID,
                "relation": "contains",
                "object": CODE_SYMBOL,
                "certainty": "inferred",
                "provenance": {
                    "source_type": "generated",
                    "name": "python_connection_pool_concrete_facts",
                    "reference": f"{source_ref} + {compose_ref}",
                    "rule": "python.http_handler_service_binding.v0",
                },
            },
            {
                "id": "fact.connection_pool.handler_depends_on_pool",
                "subject": CODE_SYMBOL,
                "relation": "depends_on",
                "object": POOL_ID,
                "certainty": "direct",
                "provenance": {
                    "source_type": "static_analysis",
                    "name": "python_ast",
                    "reference": source_ref,
                },
            },
            {
                "id": "fact.connection_pool.pool_depends_on_postgresql",
                "subject": POOL_ID,
                "relation": "depends_on",
                "object": DEPENDENCY_ID,
                "certainty": "inferred",
                "provenance": {
                    "source_type": "generated",
                    "name": "python_connection_pool_concrete_facts",
                    "reference": compose_ref,
                    "rule": "docker_compose.service_dependency.v0",
                },
            },
        ],
        "limitations": [
            "The extractor intentionally supports only the bounded Python/psycopg_pool fixture shape used by the D3.1 concrete proof.",
            "The provider-local config_name is an exact stable identity for this one declared psycopg_pool instance; it is not a Rails database-role concept.",
            "A configured pool capacity proves a revision-bound deployment fact, not that the pool was saturated at runtime.",
            "Runtime execution and saturation require independent trace and probe evidence.",
        ],
    }
    validate_schema(document, load_schema())
    validate_semantics(document)
    return document


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract revision-bound Python connection-pool facts from source and Docker Compose config."
    )
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--compose", required=True, type=Path)
    parser.add_argument("--system-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        document = build_document(
            app_path=args.app,
            compose_path=args.compose,
            system_id=args.system_id,
            revision_value=args.revision,
            repository=args.repository,
        )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise SystemExit(str(exc)) from exc

    rendered = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

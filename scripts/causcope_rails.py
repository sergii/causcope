#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SOURCE = ROOT / "integrations" / "rails" / "causcope_runtime.rb"
DEFAULT_FACTS = Path(".causcope/concrete-system-facts.json")
RUNTIME_TARGET = Path("lib/causcope/runtime.rb")
INITIALIZER_TARGET = Path("config/initializers/causcope.rb")
DEFAULT_OTLP_ENDPOINT = "http://127.0.0.1:4318/v1/traces"

INITIALIZER = '''# frozen_string_literal: true

# Installed by `causcope rails install`.
require Rails.root.join("lib/causcope/runtime").to_s
'''

GEMS = (
    ("opentelemetry-sdk", 'gem "opentelemetry-sdk", ">= 1.6", "< 2"'),
    ("opentelemetry-exporter-otlp", 'gem "opentelemetry-exporter-otlp", ">= 0.29", "< 1"'),
)


def ensure_rails_root(root: Path) -> None:
    required = [root / "Gemfile", root / "config" / "application.rb"]
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    if missing:
        raise ValueError("not a supported Rails repository; missing " + ", ".join(missing))


def facts_path(root: Path, configured: Path | None) -> Path:
    if configured is None:
        return (root / DEFAULT_FACTS).resolve()
    if configured.is_absolute():
        return configured.resolve()
    return (root / configured).resolve()


def load_facts(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(
            f"concrete system facts not found at {path}; run `causcope scan <rails-root>` first"
        ) from error
    except json.JSONDecodeError as error:
        raise ValueError(f"concrete system facts are not valid JSON: {path}") from error

    if not isinstance(document, dict) or document.get("kind") != "concrete_system_facts":
        raise ValueError(f"{path} is not a concrete_system_facts document")
    if not isinstance(document.get("system_id"), str) or not document["system_id"]:
        raise ValueError("concrete system facts do not contain a system_id")
    revision = document.get("revision")
    if (
        not isinstance(revision, dict)
        or not isinstance(revision.get("value"), str)
        or not revision["value"]
    ):
        raise ValueError("concrete system facts do not contain a revision value")
    return document


def managed_file_action(path: Path, content: str, *, force: bool) -> str:
    if not path.exists():
        return "created"
    current = path.read_text(encoding="utf-8")
    if current == content:
        return "unchanged"
    if not force:
        raise ValueError(f"refusing to overwrite existing file: {path}; pass --force to replace it")
    return "replaced"


def write_managed_file(path: Path, content: str, action: str) -> None:
    if action == "unchanged":
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def gem_declared(gemfile: str, name: str) -> bool:
    pattern = rf"(?m)^\s*gem\s+[\"']{re.escape(name)}[\"'](?:\s|,|$)"
    return re.search(pattern, gemfile) is not None


def prepare_runtime_gems(gemfile_path: Path) -> tuple[str, list[str]]:
    content = gemfile_path.read_text(encoding="utf-8")
    missing_names = [name for name, _line in GEMS if not gem_declared(content, name)]
    if not missing_names:
        return content, []

    missing_lines = [line for name, line in GEMS if name in missing_names]
    separator = "\n" if content.endswith("\n") else "\n\n"
    block = "# Causcope runtime instrumentation\n" + "\n".join(missing_lines) + "\n"
    return content + separator + block, missing_names


def run_command(command: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value or None


def current_git_revision(root: Path) -> str | None:
    git = shutil.which("git")
    if not git:
        return None
    return run_command([git, "rev-parse", "HEAD"], root)


def bind_identity_env(env: dict[str, str], name: str, value: str) -> None:
    existing = env.get(name)
    if existing and existing != value:
        raise ValueError(f"{name}={existing!r} conflicts with pinned value {value!r}")
    env[name] = value


def install(args: argparse.Namespace) -> int:
    root = args.path.expanduser().resolve()
    ensure_rails_root(root)
    static_path = facts_path(root, args.static_facts)
    document = load_facts(static_path)

    runtime_content = RUNTIME_SOURCE.read_text(encoding="utf-8")
    runtime_path = root / RUNTIME_TARGET
    initializer_path = root / INITIALIZER_TARGET

    # Preflight every managed file before mutating the target repository so a conflict
    # cannot leave a half-installed integration behind.
    runtime_action = managed_file_action(runtime_path, runtime_content, force=args.force)
    initializer_action = managed_file_action(initializer_path, INITIALIZER, force=args.force)

    gemfile_path = root / "Gemfile"
    gemfile_content = gemfile_path.read_text(encoding="utf-8")
    added_gems: list[str] = []
    if not args.no_gemfile:
        gemfile_content, added_gems = prepare_runtime_gems(gemfile_path)

    write_managed_file(runtime_path, runtime_content, runtime_action)
    write_managed_file(initializer_path, INITIALIZER, initializer_action)
    if not args.no_gemfile and added_gems:
        gemfile_path.write_text(gemfile_content, encoding="utf-8")

    pool_count = sum(
        1
        for entity in document.get("entities", [])
        if entity.get("kind") == "resource_pool"
        and entity.get("attributes", {}).get("technology") == "active_record"
    )
    print(f"Rails root: {root}")
    print(f"System: {document['system_id']}")
    print(f"Scanned revision: {document['revision']['value']}")
    print(f"ActiveRecord pools: {pool_count}")
    print(f"{runtime_action.capitalize()}: {runtime_path}")
    print(f"{initializer_action.capitalize()}: {initializer_path}")
    if args.no_gemfile:
        print("Gemfile: unchanged (--no-gemfile)")
    elif added_gems:
        print("Gemfile: added " + ", ".join(added_gems))
        print("Next: run bundle install in the Rails application")
    else:
        print("Gemfile: OpenTelemetry runtime dependencies already declared")
    print("Next: start the receiver with `causcope runtime start <rails-root> --incident-id <id>`")
    print("Then launch Rails with `causcope rails run <rails-root> -- <command>`")
    return 0


def run_rails(args: argparse.Namespace) -> int:
    root = args.path.expanduser().resolve()
    ensure_rails_root(root)
    static_path = facts_path(root, args.static_facts)
    document = load_facts(static_path)

    if not (root / INITIALIZER_TARGET).is_file() or not (root / RUNTIME_TARGET).is_file():
        raise ValueError(
            "portable Rails runtime is not installed; run `causcope rails install <rails-root>` first"
        )

    actual_revision = args.revision or current_git_revision(root)
    if not actual_revision:
        raise ValueError("could not determine current revision; pass --revision explicitly")
    expected_revision = document["revision"]["value"]
    if actual_revision != expected_revision:
        raise ValueError(
            "current application revision does not match scanned concrete facts: "
            f"expected {expected_revision!r}, got {actual_revision!r}; rescan before starting runtime instrumentation"
        )

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("missing application command after `--`")

    env = dict(os.environ)
    bind_identity_env(env, "CAUSCOPE_SYSTEM_ID", document["system_id"])
    bind_identity_env(env, "CAUSCOPE_REVISION", expected_revision)
    env["CAUSCOPE_STATIC_FACTS"] = str(static_path)
    if args.otel_endpoint:
        env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = args.otel_endpoint
    else:
        env.setdefault("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", DEFAULT_OTLP_ENDPOINT)
    if args.sync_export:
        env["CAUSCOPE_OTEL_SYNC"] = "1"

    print(
        f"Starting revision {expected_revision} for system {document['system_id']} with Causcope runtime binding",
        file=sys.stderr,
    )
    completed = subprocess.run(command, cwd=root, env=env, check=False)
    return completed.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="causcope rails",
        description="Install and launch the portable Causcope Rails runtime integration.",
    )
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    install_parser = subparsers.add_parser(
        "install", help="Install the portable runtime into a scanned Rails repository"
    )
    install_parser.add_argument("path", type=Path)
    install_parser.add_argument("--static-facts", type=Path)
    install_parser.add_argument(
        "--force", action="store_true", help="Replace conflicting generated runtime files"
    )
    install_parser.add_argument(
        "--no-gemfile", action="store_true", help="Do not add OpenTelemetry dependencies to Gemfile"
    )
    install_parser.set_defaults(handler=install)

    run_parser = subparsers.add_parser(
        "run", help="Launch a Rails process only when its revision matches the scanned contract"
    )
    run_parser.add_argument("path", type=Path)
    run_parser.add_argument("--static-facts", type=Path)
    run_parser.add_argument("--revision", help="Explicit running revision; defaults to git HEAD")
    run_parser.add_argument(
        "--otel-endpoint",
        help=f"Override OTLP traces endpoint; defaults to existing env or {DEFAULT_OTLP_ENDPOINT}",
    )
    run_parser.add_argument(
        "--sync-export",
        action="store_true",
        help="Use synchronous span export for deterministic local tests",
    )
    run_parser.add_argument("command", nargs="+", help="Application command; place it after `--`")
    run_parser.set_defaults(handler=run_rails)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return args.handler(args)
    except (ValueError, OSError) as error:
        print(f"causcope rails: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

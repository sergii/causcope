#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RECEIVER = ROOT / "scripts" / "otlp_concrete_receiver.py"
DEFAULT_FACTS = Path(".causcope/concrete-system-facts.json")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4318


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
            f"concrete system facts not found at {path}; run `causcope scan <application-root>` first"
        ) from error
    except json.JSONDecodeError as error:
        raise ValueError(f"concrete system facts are not valid JSON: {path}") from error

    if not isinstance(document, dict) or document.get("kind") != "concrete_system_facts":
        raise ValueError(f"{path} is not a concrete_system_facts document")
    return document


def snapshot_path(root: Path, incident_id: str, configured: Path | None, disabled: bool) -> Path | None:
    if disabled:
        return None
    if configured is not None:
        return configured.resolve() if configured.is_absolute() else (root / configured).resolve()
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", incident_id).strip("-") or "incident"
    return (root / ".causcope" / "runtime" / f"{safe}.json").resolve()


def resolve_incident_id(args: argparse.Namespace, root: Path) -> str:
    if args.incident_id:
        return args.incident_id
    from runtime_incident_seed import load_workspace_incident_id, workspace_path

    workspace = workspace_path(root, args.workspace)
    return load_workspace_incident_id(workspace)


def build_start_command(args: argparse.Namespace) -> tuple[list[str], Path, Path | None, dict[str, Any], str]:
    root = args.path.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"application root does not exist: {root}")
    static_path = facts_path(root, args.static_facts)
    document = load_facts(static_path)
    incident_id = resolve_incident_id(args, root)
    snapshot = snapshot_path(root, incident_id, args.snapshot, args.no_snapshot)

    command = [
        sys.executable,
        str(RECEIVER),
        "--static-facts",
        str(static_path),
        "--incident-id",
        incident_id,
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--source-uri",
        args.source_uri,
    ]
    if snapshot is not None:
        command.extend(["--snapshot", str(snapshot)])
    if args.verbose:
        command.append("--verbose")
    return command, root, snapshot, document, incident_id


def start(args: argparse.Namespace) -> int:
    command, root, snapshot, document, incident_id = build_start_command(args)
    if snapshot is not None:
        snapshot.parent.mkdir(parents=True, exist_ok=True)

    print(f"Investigation: {incident_id}")
    print(f"System: {document.get('system_id', '<unknown>')}")
    print(f"Revision: {document.get('revision', {}).get('value', '<unknown>')}")
    print(f"OTLP endpoint: http://{args.host}:{args.port}/v1/traces")
    if snapshot is not None:
        print(f"Runtime snapshot: {snapshot}")
    else:
        print("Runtime snapshot: disabled")

    if args.dry_run:
        print("Command: " + shlex.join(command))
        return 0

    completed = subprocess.run(command, cwd=ROOT, check=False)
    return completed.returncode


def seed_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("path", type=Path, nargs="?", default=Path("."))
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--runtime-facts", type=Path)
    parser.add_argument("--request-latency-threshold-ms", type=float)
    parser.add_argument("--pool-wait-threshold-ms", type=float)
    parser.add_argument("--code-symbol")
    parser.add_argument("--trace-id")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def enrich_seed_arguments(arguments: list[str]) -> list[str]:
    from runtime_incident_seed import workspace_path
    from workspace_objectives import (
        DEFAULT_FILENAME,
        POOL_WAIT_OBSERVATION,
        REQUEST_LATENCY_OBSERVATION,
        load_workspace_objectives,
        objective_threshold_ms,
    )

    if "-h" in arguments or "--help" in arguments:
        return arguments

    parsed = seed_argument_parser().parse_args(arguments)
    if (
        parsed.request_latency_threshold_ms is not None
        and parsed.pool_wait_threshold_ms is not None
    ):
        return arguments

    root = parsed.path.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"application root does not exist: {root}")
    workspace = workspace_path(root, parsed.workspace)
    objectives_path = workspace / DEFAULT_FILENAME
    try:
        objectives = load_workspace_objectives(objectives_path)
    except ValueError as error:
        missing = []
        if parsed.request_latency_threshold_ms is None:
            missing.append("--request-latency-threshold-ms")
        if parsed.pool_wait_threshold_ms is None:
            missing.append("--pool-wait-threshold-ms")
        raise ValueError(
            "missing incident bootstrap objectives "
            + ", ".join(missing)
            + f"; configure {objectives_path} with `causcope objectives set {root}` or pass explicit CLI overrides"
        ) from error

    enriched = list(arguments)
    if parsed.request_latency_threshold_ms is None:
        enriched.extend(
            [
                "--request-latency-threshold-ms",
                str(objective_threshold_ms(objectives, REQUEST_LATENCY_OBSERVATION)),
            ]
        )
    if parsed.pool_wait_threshold_ms is None:
        enriched.extend(
            [
                "--pool-wait-threshold-ms",
                str(objective_threshold_ms(objectives, POOL_WAIT_OBSERVATION)),
            ]
        )
    return enriched


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="causcope runtime",
        description="Run concrete Causcope runtime ingestion against a pinned static contract.",
    )
    subparsers = parser.add_subparsers(dest="command_name", required=True)
    start_parser = subparsers.add_parser("start", help="Start an OTLP receiver for one investigation and scanned revision")
    start_parser.add_argument("path", type=Path, nargs="?", default=Path("."))
    start_parser.add_argument(
        "--incident-id",
        help="Investigation identity; defaults to WORKSPACE/incident-context.yaml",
    )
    start_parser.add_argument(
        "--workspace",
        type=Path,
        help="Causcope workspace used to resolve the current investigation; defaults to PATH/.causcope",
    )
    start_parser.add_argument("--static-facts", type=Path)
    start_parser.add_argument("--host", default=DEFAULT_HOST)
    start_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    start_parser.add_argument("--snapshot", type=Path)
    start_parser.add_argument("--no-snapshot", action="store_true")
    start_parser.add_argument("--source-uri", default="otlp:http:portable-runtime")
    start_parser.add_argument("--verbose", action="store_true")
    start_parser.add_argument("--dry-run", action="store_true", help="Validate configuration and print the receiver command without starting it")
    start_parser.set_defaults(handler=start)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "observe":
        from runtime_observe import main as observe_main

        return observe_main(arguments[1:])
    if arguments and arguments[0] == "seed":
        from runtime_incident_seed import main as seed_main

        try:
            return seed_main(enrich_seed_arguments(arguments[1:]))
        except (ValueError, OSError) as error:
            print(f"causcope runtime seed: {error}", file=sys.stderr)
            return 2

    try:
        args = build_parser().parse_args(arguments)
        if not 0 <= args.port <= 65535:
            raise ValueError("--port must be between 0 and 65535")
        return args.handler(args)
    except (ValueError, OSError) as error:
        print(f"causcope runtime: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

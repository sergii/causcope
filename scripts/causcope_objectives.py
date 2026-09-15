#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from workspace_objectives import (
    DEFAULT_FILENAME,
    build_workspace_objectives,
    load_workspace_objectives,
    write_workspace_objectives,
)


def workspace_path(root: Path, configured: Path | None) -> Path:
    if configured is None:
        return (root / ".causcope").resolve()
    return configured.resolve() if configured.is_absolute() else (root / configured).resolve()


def set_objectives(args: argparse.Namespace) -> int:
    root = args.path.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"application root does not exist: {root}")
    workspace = workspace_path(root, args.workspace)
    document = build_workspace_objectives(
        request_latency_ms=args.request_latency_ms,
        pool_wait_ms=args.pool_wait_ms,
    )
    path = workspace / DEFAULT_FILENAME
    write_workspace_objectives(path, document)
    if args.json:
        print(json.dumps(document, indent=2, sort_keys=True))
    else:
        print(f"Workspace objectives: {path}")
        print(f"Request latency objective: {args.request_latency_ms:.3f} ms")
        print(f"Pool-wait objective: {args.pool_wait_ms:.3f} ms")
    return 0


def show_objectives(args: argparse.Namespace) -> int:
    root = args.path.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"application root does not exist: {root}")
    workspace = workspace_path(root, args.workspace)
    path = workspace / DEFAULT_FILENAME
    document = load_workspace_objectives(path)
    if args.json:
        print(json.dumps(document, indent=2, sort_keys=True))
    else:
        print(yaml.safe_dump(document, sort_keys=False).rstrip())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="causcope objectives",
        description="Manage explicit workspace objectives used by bounded incident bootstrap.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    set_parser = subparsers.add_parser("set", help="Write the bounded Rails incident objectives")
    set_parser.add_argument("path", type=Path, nargs="?", default=Path("."))
    set_parser.add_argument("--workspace", type=Path)
    set_parser.add_argument("--request-latency-ms", type=float, required=True)
    set_parser.add_argument("--pool-wait-ms", type=float, required=True)
    set_parser.add_argument("--json", action="store_true")
    set_parser.set_defaults(handler=set_objectives)

    show_parser = subparsers.add_parser("show", help="Show and validate current workspace objectives")
    show_parser.add_argument("path", type=Path, nargs="?", default=Path("."))
    show_parser.add_argument("--workspace", type=Path)
    show_parser.add_argument("--json", action="store_true")
    show_parser.set_defaults(handler=show_objectives)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return args.handler(args)
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"causcope objectives: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

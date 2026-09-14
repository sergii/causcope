#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAILS_SCANNER = ROOT / "scripts" / "rails_repository_scan.rb"
DEFAULT_OUTPUT = Path(".causcope/concrete-system-facts.json")


def run_command(command: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value or None


def detect_provider(root: Path) -> str:
    if (root / "Gemfile").is_file() and (root / "config" / "application.rb").is_file():
        return "rails"
    raise ValueError("could not detect a supported application provider")


def git_revision(root: Path) -> str | None:
    if not shutil.which("git"):
        return None
    return run_command(["git", "rev-parse", "HEAD"], root)


def git_repository(root: Path) -> str | None:
    if not shutil.which("git"):
        return None
    return run_command(["git", "config", "--get", "remote.origin.url"], root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="causcope scan",
        description="Discover revision-bound concrete system facts from an application repository.",
    )
    parser.add_argument("path", type=Path, help="Application repository root")
    parser.add_argument("--provider", choices=["auto", "rails"], default="auto")
    parser.add_argument("--environment", default="production", help="Rails environment to inspect")
    parser.add_argument(
        "--database-config",
        type=Path,
        help="Rails database config path relative to the repository; defaults to database.yml, .sample, then .example",
    )
    parser.add_argument("--env-file", type=Path, help="YAML file containing environment values")
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Environment value used only for bounded config rendering",
    )
    parser.add_argument("--system-id", help="Stable concrete system identifier; defaults to directory name")
    parser.add_argument("--revision", help="Revision identity; defaults to git HEAD")
    parser.add_argument("--repository", help="Repository URI; defaults to git remote.origin.url")
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON path; defaults to PATH/.causcope/concrete-system-facts.json",
    )
    parser.add_argument("--json", action="store_true", help="Print the emitted document to stdout")
    return parser


def scan_rails(
    args: argparse.Namespace,
    root: Path,
    output: Path,
    revision: str,
    repository: str | None,
) -> None:
    ruby = shutil.which("ruby")
    if not ruby:
        raise ValueError("Rails scanning requires Ruby on PATH")

    command = [
        ruby,
        str(RAILS_SCANNER),
        "--root",
        str(root),
        "--environment",
        args.environment,
        "--system-id",
        args.system_id or root.name,
        "--revision",
        revision,
        "--output",
        str(output),
    ]
    if repository:
        command.extend(["--repository", repository])
    if args.database_config:
        command.extend(["--database-config", str(args.database_config)])
    if args.env_file:
        env_file = args.env_file if args.env_file.is_absolute() else root / args.env_file
        command.extend(["--env-file", str(env_file)])
    for item in args.env:
        if "=" not in item or item.startswith("="):
            raise ValueError(f"--env expects KEY=VALUE, got {item!r}")
        command.extend(["--env", item])

    try:
        subprocess.run(command, cwd=ROOT, check=True)
    except subprocess.CalledProcessError as error:
        raise ValueError(f"Rails provider failed with exit status {error.returncode}") from error


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = args.path.expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"application repository does not exist: {root}")

        provider = detect_provider(root) if args.provider == "auto" else args.provider
        revision = args.revision or git_revision(root)
        if not revision:
            raise ValueError("could not determine revision; pass --revision explicitly")
        repository = args.repository or git_repository(root)

        output = args.output or (root / DEFAULT_OUTPUT)
        if not output.is_absolute():
            output = (Path.cwd() / output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

        if provider == "rails":
            scan_rails(args, root, output, revision, repository)
        else:
            raise ValueError(f"unsupported provider: {provider}")

        document = json.loads(output.read_text(encoding="utf-8"))
        code_paths = sum(
            1 for item in document.get("entities", []) if item.get("kind") == "code_symbol"
        )
        pools = sum(
            1 for item in document.get("entities", []) if item.get("kind") == "resource_pool"
        )
        print(f"Scanned {root}")
        print(f"Provider: {provider}")
        print(f"Revision: {revision}")
        print(f"Resource pools: {pools}")
        print(f"Explicit code paths: {code_paths}")
        print(f"Wrote {output}")
        if args.json:
            print(json.dumps(document, indent=2, sort_keys=True))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"causcope scan: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

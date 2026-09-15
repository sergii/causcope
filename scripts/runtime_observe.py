#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "causcope"
RECEIVER = ROOT / "scripts" / "otlp_concrete_receiver.py"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4318


def _workspace_path(root: Path, configured: Path | None) -> Path:
    from runtime_incident_seed import workspace_path

    return workspace_path(root, configured)


def _facts_path(root: Path, configured: Path | None) -> Path:
    if configured is None:
        return (root / ".causcope" / "concrete-system-facts.json").resolve()
    return configured.resolve() if configured.is_absolute() else (root / configured).resolve()


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"{label} not found at {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(document, dict):
        raise ValueError(f"{label} must contain a JSON object: {path}")
    return document


def _load_incident_id(workspace: Path) -> str:
    from runtime_incident_seed import load_workspace_incident_id

    return load_workspace_incident_id(workspace)


def _snapshot_path(workspace: Path, incident_id: str) -> Path:
    from runtime_incident_seed import default_runtime_snapshot_path

    return default_runtime_snapshot_path(workspace, incident_id)


def _preflight_objectives(workspace: Path) -> None:
    from workspace_objectives import (
        DEFAULT_FILENAME,
        POOL_WAIT_OBSERVATION,
        REQUEST_LATENCY_OBSERVATION,
        load_workspace_objectives,
        objective_threshold_ms,
    )

    document = load_workspace_objectives(workspace / DEFAULT_FILENAME)
    objective_threshold_ms(document, REQUEST_LATENCY_OBSERVATION)
    objective_threshold_ms(document, POOL_WAIT_OBSERVATION)


def _receiver_command(
    *,
    static_facts: Path,
    incident_id: str,
    snapshot: Path,
    host: str,
    port: int,
    source_uri: str,
    verbose: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(RECEIVER),
        "--static-facts",
        str(static_facts),
        "--incident-id",
        incident_id,
        "--host",
        host,
        "--port",
        str(port),
        "--snapshot",
        str(snapshot),
        "--source-uri",
        source_uri,
    ]
    if verbose:
        command.append("--verbose")
    return command


def _wait_for_receiver(process: subprocess.Popen[str], host: str, port: int) -> None:
    health_url = f"http://{host}:{port}/health"
    deadline = time.monotonic() + 5.0
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        code = process.poll()
        if code is not None:
            stderr = process.stderr.read().strip() if process.stderr is not None else ""
            detail = stderr or f"receiver exited with status {code}"
            raise ValueError(f"OTLP receiver failed before becoming ready: {detail}")
        try:
            with urllib.request.urlopen(health_url, timeout=0.25) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError) as error:
            last_error = error
        time.sleep(0.05)
    raise ValueError(f"OTLP receiver did not become ready at {health_url}: {last_error}")


def _stop_receiver(process: subprocess.Popen[str]) -> str:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    if process.stderr is None:
        return ""
    return process.stderr.read().strip()


def _rails_command(
    *,
    root: Path,
    revision: str,
    endpoint: str,
    application_command: list[str],
) -> list[str]:
    return [
        str(CLI),
        "rails",
        "run",
        str(root),
        "--revision",
        revision,
        "--otel-endpoint",
        endpoint,
        "--sync-export",
        "--",
        *application_command,
    ]


def _seed_command(
    *,
    root: Path,
    workspace: Path,
    snapshot: Path,
    force: bool,
    code_symbol: str | None,
    trace_id: str | None,
) -> list[str]:
    command = [
        str(CLI),
        "runtime",
        "seed",
        str(root),
        "--workspace",
        str(workspace),
        "--runtime-facts",
        str(snapshot),
        "--json",
    ]
    if force:
        command.append("--force")
    if code_symbol:
        command.extend(["--code-symbol", code_symbol])
    if trace_id:
        command.extend(["--trace-id", trace_id])
    return command


def observe(args: argparse.Namespace) -> dict[str, Any]:
    root = args.path.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"application root does not exist: {root}")
    if not 1 <= args.port <= 65535:
        raise ValueError("--port must be between 1 and 65535 for a bounded observation session")

    workspace = _workspace_path(root, args.workspace)
    incident_id = _load_incident_id(workspace)
    _preflight_objectives(workspace)

    static_path = _facts_path(root, args.static_facts)
    static = _load_json_object(static_path, "concrete system facts")
    if static.get("kind") != "concrete_system_facts":
        raise ValueError(f"{static_path} is not a concrete_system_facts document")
    revision = static.get("revision", {}).get("value")
    if not isinstance(revision, str) or not revision:
        raise ValueError("concrete system facts do not contain a revision value")

    application_command = list(args.application_command)
    if application_command and application_command[0] == "--":
        application_command = application_command[1:]
    if not application_command:
        raise ValueError("missing bounded application command after `--`")

    snapshot = _snapshot_path(workspace, incident_id)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    endpoint = f"http://{args.host}:{args.port}/v1/traces"
    receiver_command = _receiver_command(
        static_facts=static_path,
        incident_id=incident_id,
        snapshot=snapshot,
        host=args.host,
        port=args.port,
        source_uri=args.source_uri,
        verbose=args.verbose_receiver,
    )
    receiver = subprocess.Popen(
        receiver_command,
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    receiver_stderr = ""
    try:
        _wait_for_receiver(receiver, args.host, args.port)
        app = subprocess.run(
            _rails_command(
                root=root,
                revision=revision,
                endpoint=endpoint,
                application_command=application_command,
            ),
            cwd=ROOT,
            check=False,
        )
        if app.returncode != 0:
            raise ValueError(
                "bounded application command exited non-zero; observation was not seeded: "
                f"exit={app.returncode}"
            )
    finally:
        receiver_stderr = _stop_receiver(receiver)

    if not snapshot.is_file():
        suffix = f"; receiver: {receiver_stderr}" if receiver_stderr else ""
        raise ValueError(
            "bounded application command completed but no explicitly bound runtime facts were captured"
            + suffix
        )

    seed = subprocess.run(
        _seed_command(
            root=root,
            workspace=workspace,
            snapshot=snapshot,
            force=args.force_seed,
            code_symbol=args.code_symbol,
            trace_id=args.trace_id,
        ),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if seed.returncode != 0:
        detail = seed.stderr.strip() or seed.stdout.strip() or "incident seed failed"
        raise ValueError(f"observation captured runtime facts but could not seed revision 1: {detail}")

    try:
        seed_document = json.loads(seed.stdout)
    except json.JSONDecodeError as error:
        raise ValueError("runtime seed did not return valid JSON") from error

    return {
        "schema_version": "0.1",
        "kind": "bounded_observation_session_result",
        "incident_id": incident_id,
        "system_id": static.get("system_id"),
        "revision": revision,
        "otlp_endpoint": endpoint,
        "runtime_snapshot": str(snapshot),
        "application_exit_code": 0,
        "seed": seed_document,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="causcope runtime observe",
        description=(
            "Run one bounded instrumented application command, collect exact OTLP runtime facts, "
            "then seed Investigation revision 1 from workspace objectives."
        ),
    )
    parser.add_argument("path", type=Path, nargs="?", default=Path("."))
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--static-facts", type=Path)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--source-uri", default="otlp:http:bounded-observation")
    parser.add_argument("--code-symbol")
    parser.add_argument("--trace-id")
    parser.add_argument("--force-seed", action="store_true")
    parser.add_argument("--verbose-receiver", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "application_command",
        nargs=argparse.REMAINDER,
        help="Bounded application command; place it after `--` and make it exit on its own.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = observe(args)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            seed = result["seed"]
            print(f"Investigation: {result['incident_id']}")
            print(f"Runtime snapshot: {result['runtime_snapshot']}")
            print(f"Evidence revision: {seed['evidence_revision']}")
            print(f"Exact target: {seed['target_resource']}")
            print(f"Leading hypothesis: {seed['leading_hypothesis']}")
            print(f"Next probe: {seed['next_probe']}")
        return 0
    except (OSError, ValueError) as error:
        print(f"causcope runtime observe: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

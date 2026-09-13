from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
COMPOSE_FILE = ROOT / "compose.yaml"
SCENARIOS_DIR = ROOT / "scenarios"
CAUSCOPE_BRIDGE = ROOT / "causcope_bridge.py"
DEFAULT_PORT = 18080


def compose(*args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        cwd=ROOT,
        env=env,
        check=True,
        text=True,
        capture_output=False,
    )


def base_url() -> str:
    return f"http://127.0.0.1:{int(os.environ.get('SHOP_PORT', str(DEFAULT_PORT)))}"


def http_request(
    method: str,
    path: str,
    *,
    payload: object | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, str]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"Accept": "application/json"}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        f"{base_url()}{path}",
        data=body,
        method=method,
        headers=request_headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def wait_for_health(timeout_seconds: float = 30) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            status, _ = http_request("GET", "/health")
            if status == 200:
                return
        except OSError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"shop did not become healthy at {base_url()}")


def scenario_directories() -> list[Path]:
    if not SCENARIOS_DIR.exists():
        return []
    return sorted(path for path in SCENARIOS_DIR.iterdir() if path.is_dir())


def load_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"expected object in {path}")
    return document


def load_scenario(slug: str) -> tuple[Path, dict[str, Any]]:
    path = SCENARIOS_DIR / slug / "scenario.json"
    if not path.exists():
        available = ", ".join(directory.name for directory in scenario_directories())
        raise ValueError(f"unknown scenario {slug!r}; available: {available}")
    return path.parent, load_json(path)


def cmd_up(_: argparse.Namespace) -> int:
    compose("up", "-d", "--build", "app")
    wait_for_health()
    print(f"Causcope Shop is ready at {base_url()}")
    return 0


def cmd_down(_: argparse.Namespace) -> int:
    compose("--profile", "scenarios", "down", "-v", "--remove-orphans")
    print("Causcope Shop stopped and testbed data removed")
    return 0


def cmd_smoke(_: argparse.Namespace) -> int:
    wait_for_health()
    status, body = http_request("GET", "/products")
    if status != 200 or len(json.loads(body)) < 3:
        raise RuntimeError(f"products smoke check failed: status={status} body={body}")

    status, body = http_request(
        "POST",
        "/orders",
        payload={"items": [{"product_id": 1, "quantity": 1}]},
        headers={"X-Client-Platform": "smoke", "X-App-Version": "testbed"},
    )
    if status != 201:
        raise RuntimeError(f"create-order smoke check failed: status={status} body={body}")
    order = json.loads(body)
    order_id = int(order["id"])

    status, body = http_request("POST", f"/orders/{order_id}/pay")
    if status != 200:
        raise RuntimeError(f"pay-order smoke check failed: status={status} body={body}")

    status, body = http_request("GET", f"/orders/{order_id}")
    if status != 200 or json.loads(body).get("status") != "paid":
        raise RuntimeError(f"order read-back failed: status={status} body={body}")

    print(f"happy-path smoke test passed: order={order_id}")
    return 0


def cmd_causcope(args: argparse.Namespace) -> int:
    command = [sys.executable, str(CAUSCOPE_BRIDGE), "--workspace", str(args.workspace)]
    if args.incident_id:
        command.extend(["--incident-id", args.incident_id])
    if args.since:
        command.extend(["--since", args.since])
    if args.json:
        command.append("--json")
    return subprocess.run(command, cwd=REPO_ROOT, check=True).returncode


def cmd_scenario_list(_: argparse.Namespace) -> int:
    for directory in scenario_directories():
        scenario = load_json(directory / "scenario.json")
        print(f"{directory.name:24} {scenario['title']}")
    return 0


def cmd_scenario_report(args: argparse.Namespace) -> int:
    _, scenario = load_scenario(args.slug)
    report = scenario["initial_report"]
    print(f"Scenario: {scenario['title']}")
    print(f"Incident report: {report['summary']}")
    for detail in report.get("details", []):
        print(f"- {detail}")
    print("\nKnown working controls:")
    for control in scenario.get("working_controls", []):
        print(f"- {control}")
    print("\nOracle remains hidden. Use `scenario reveal` only after the investigation.")
    return 0


def cmd_scenario_start(args: argparse.Namespace) -> int:
    _, scenario = load_scenario(args.slug)
    wait_for_health()
    activation = scenario["activation"]
    service = activation["service"]
    extra_env: dict[str, str] = {}
    duration_env = activation.get("duration_env")
    if duration_env:
        duration = args.duration or activation.get("default_duration_seconds")
        if duration:
            extra_env[duration_env] = str(duration)
    compose(
        "--profile",
        "scenarios",
        "up",
        "-d",
        "--force-recreate",
        service,
        extra_env=extra_env,
    )
    startup_wait = float(activation.get("startup_wait_seconds", 0.5))
    time.sleep(startup_wait)
    print(f"started {args.slug}: {scenario['initial_report']['summary']}")
    return 0


def cmd_scenario_stop(args: argparse.Namespace) -> int:
    _, scenario = load_scenario(args.slug)
    service = scenario["activation"]["service"]
    compose("--profile", "scenarios", "stop", service)
    compose("--profile", "scenarios", "rm", "-f", service)
    print(f"stopped {args.slug}")
    return 0


def cmd_scenario_verify(args: argparse.Namespace) -> int:
    _, scenario = load_scenario(args.slug)
    wait_for_health()
    failures: list[str] = []
    for check in scenario.get("verification", []):
        status, body = http_request(
            check["method"],
            check["path"],
            payload=check.get("json"),
            headers=check.get("headers"),
        )
        expected = int(check["expect_status"])
        if status == expected:
            print(f"ok: {check['name']} -> {status}")
        else:
            failures.append(
                f"{check['name']}: expected {expected}, got {status}; body={body}"
            )
    if failures:
        raise RuntimeError("scenario verification failed: " + " | ".join(failures))
    return 0


def cmd_scenario_reveal(args: argparse.Namespace) -> int:
    directory, scenario = load_scenario(args.slug)
    oracle_path = directory / scenario["oracle_file"]
    oracle = load_json(oracle_path)
    print(json.dumps(oracle, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Causcope Shop integration testbed."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    up = subparsers.add_parser("up", help="Build and start the happy-path shop")
    up.set_defaults(func=cmd_up)

    down = subparsers.add_parser("down", help="Stop the testbed and remove its data")
    down.set_defaults(func=cmd_down)

    smoke = subparsers.add_parser("smoke", help="Verify the happy path")
    smoke.set_defaults(func=cmd_smoke)

    causcope = subparsers.add_parser(
        "causcope",
        help="Collect shop logs read-only and run the Causcope evidence/diagnosis pipeline",
    )
    causcope.add_argument("--workspace", type=Path, default=REPO_ROOT / ".causcope")
    causcope.add_argument("--incident-id")
    causcope.add_argument("--since")
    causcope.add_argument("--json", action="store_true")
    causcope.set_defaults(func=cmd_causcope)

    scenario = subparsers.add_parser("scenario", help="Manage failure scenarios")
    scenario_subparsers = scenario.add_subparsers(dest="scenario_command", required=True)

    list_parser = scenario_subparsers.add_parser("list", help="List available scenarios")
    list_parser.set_defaults(func=cmd_scenario_list)

    report = scenario_subparsers.add_parser("report", help="Show only the public incident report")
    report.add_argument("slug")
    report.set_defaults(func=cmd_scenario_report)

    start = scenario_subparsers.add_parser("start", help="Activate a scenario")
    start.add_argument("slug")
    start.add_argument("--duration", type=int, help="Override duration for temporary scenarios")
    start.set_defaults(func=cmd_scenario_start)

    stop = scenario_subparsers.add_parser("stop", help="Stop a scenario helper")
    stop.add_argument("slug")
    stop.set_defaults(func=cmd_scenario_stop)

    verify = scenario_subparsers.add_parser("verify", help="Verify the scenario's observable surface")
    verify.add_argument("slug")
    verify.set_defaults(func=cmd_scenario_verify)

    reveal = scenario_subparsers.add_parser("reveal", help="Reveal the scenario oracle")
    reveal.add_argument("slug")
    reveal.set_defaults(func=cmd_scenario_reveal)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

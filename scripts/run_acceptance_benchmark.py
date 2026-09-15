#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TESTBED = ROOT / "testbed" / "shop" / "testbed.py"
CAUSCOPE = ROOT / "bin" / "causcope"
SCENARIOS = ROOT / "testbed" / "shop" / "scenarios"
DEFAULT_SCENARIO = "sqlite-write-lock"
DEFAULT_WORKSPACE = ROOT / ".causcope-benchmark"
AI_CREDENTIAL_ENV_KEYS = {
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
}


def load_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return document


def deterministic_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in AI_CREDENTIAL_ENV_KEYS:
        env.pop(key, None)
    return env


def run(
    command: list[str],
    *,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=capture,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        if completed.stdout:
            print(completed.stdout, file=sys.stderr)
        if completed.stderr:
            print(completed.stderr, file=sys.stderr)
        raise ValueError(
            f"command failed with exit {completed.returncode}: {' '.join(command)}"
        )
    return completed


def scope_matches(scope: Any, expected: dict[str, Any]) -> bool:
    if not isinstance(scope, dict):
        return False
    attributes = scope.get("attributes")
    if not isinstance(attributes, dict):
        return False
    return all(attributes.get(key) == value for key, value in expected.items())


def score_summary(
    summary: dict[str, Any],
    oracle: dict[str, Any],
) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
    expected = oracle.get("expected_causcope")
    if not isinstance(expected, dict):
        raise ValueError("oracle does not define expected_causcope benchmark expectations")

    target = expected["target"]
    scope_contains = expected.get("scope_contains", {})
    diagnoses = summary.get("diagnoses", [])
    if not isinstance(diagnoses, list):
        diagnoses = []

    matching = [
        item
        for item in diagnoses
        if isinstance(item, dict)
        and item.get("target") == target
        and scope_matches(item.get("scope"), scope_contains)
    ]
    selected = matching[0] if len(matching) == 1 else None

    autonomous = summary.get("autonomous", {})
    if not isinstance(autonomous, dict):
        autonomous = {}
    steps = autonomous.get("steps", [])
    if not isinstance(steps, list):
        steps = []
    completed_probes = sorted(
        {
            step.get("probe_id")
            for step in steps
            if isinstance(step, dict)
            and step.get("status") == "completed"
            and isinstance(step.get("probe_id"), str)
        }
    )
    final_revision = autonomous.get("final_evidence_revision")

    checks = [
        {
            "id": "single_expected_diagnosis_scope",
            "passed": len(matching) == 1,
            "expected": 1,
            "actual": len(matching),
        },
        {
            "id": "top_hypothesis",
            "passed": selected is not None
            and selected.get("top_hypothesis") == expected["top_hypothesis"],
            "expected": expected["top_hypothesis"],
            "actual": selected.get("top_hypothesis") if selected else None,
        },
        {
            "id": "minimum_evidence_revision",
            "passed": isinstance(final_revision, int)
            and final_revision >= expected["minimum_evidence_revision"],
            "expected": f">={expected['minimum_evidence_revision']}",
            "actual": final_revision,
        },
        {
            "id": "required_completed_probes",
            "passed": all(
                probe_id in completed_probes
                for probe_id in expected.get("required_completed_probes", [])
            ),
            "expected": expected.get("required_completed_probes", []),
            "actual": completed_probes,
        },
    ]

    observed = {
        "target": selected.get("target") if selected else None,
        "scope": selected.get("scope") if selected else None,
        "top_hypothesis": selected.get("top_hypothesis") if selected else None,
        "next_probe": selected.get("next_probe") if selected else None,
        "completed_probes": completed_probes,
        "final_evidence_revision": final_revision,
        "stop_reason": autonomous.get("stop_reason"),
    }
    return all(check["passed"] for check in checks), checks, observed


def build_result(
    *,
    scenario: dict[str, Any],
    oracle: dict[str, Any],
    summary: dict[str, Any],
    incident_id: str,
) -> dict[str, Any]:
    passed, checks, observed = score_summary(summary, oracle)
    return {
        "schema_version": "0.1",
        "kind": "acceptance_benchmark_result",
        "benchmark_id": f"benchmark.shop.{scenario['slug']}.deterministic",
        "surface": "deterministic_shop_autonomous",
        "scenario_id": scenario["id"],
        "incident_id": incident_id,
        "llm": {
            "enabled": False,
            "credential_environment_removed": sorted(AI_CREDENTIAL_ENV_KEYS),
        },
        "oracle_policy": {
            "loaded_after_investigation": True,
            "used_to_construct_diagnosis": False,
        },
        "expectations": oracle["expected_causcope"],
        "observed": observed,
        "checks": checks,
        "passed": passed,
    }


def run_benchmark(
    *,
    slug: str,
    workspace: Path,
    max_steps: int,
    keep_testbed: bool,
) -> dict[str, Any]:
    scenario_dir = SCENARIOS / slug
    scenario_path = scenario_dir / "scenario.json"
    if not scenario_path.is_file():
        raise ValueError(f"unknown benchmark scenario: {slug}")

    # Public scenario context may be read before the investigation. The oracle may not.
    scenario = load_json(scenario_path)
    summary_text = scenario.get("initial_report", {}).get("summary")
    if not isinstance(summary_text, str) or not summary_text:
        raise ValueError(f"scenario {slug} has no public initial report summary")

    oracle_path = scenario_dir / scenario["oracle_file"]
    incident_id = f"incident.benchmark.{slug.replace('-', '_')}"
    env = deterministic_env()

    if workspace.exists():
        shutil.rmtree(workspace)

    run([sys.executable, str(TESTBED), "down"], env=env)
    run([sys.executable, str(TESTBED), "up"], env=env)

    try:
        run(
            [
                str(CAUSCOPE),
                "investigate",
                summary_text,
                "--incident-id",
                incident_id,
                "--workspace",
                str(workspace),
                "--non-interactive",
                "--force",
            ],
            env=env,
        )
        run(
            [
                sys.executable,
                str(TESTBED),
                "scenario",
                "start",
                slug,
                "--duration",
                "20",
            ],
            env=env,
        )
        run(
            [sys.executable, str(TESTBED), "scenario", "verify", slug],
            env=env,
        )
        completed = run(
            [
                sys.executable,
                str(TESTBED),
                "causcope",
                "--autonomous",
                "--max-steps",
                str(max_steps),
                "--workspace",
                str(workspace),
                "--json",
            ],
            capture=True,
            env=env,
        )
        summary = json.loads(completed.stdout)
        if not isinstance(summary, dict):
            raise ValueError("Causcope benchmark summary must be a JSON object")

        # Hidden ground truth is intentionally unavailable until Causcope has finished.
        oracle = load_json(oracle_path)
        return build_result(
            scenario=scenario,
            oracle=oracle,
            summary=summary,
            incident_id=incident_id,
        )
    finally:
        try:
            run([sys.executable, str(TESTBED), "scenario", "stop", slug], env=env)
        except ValueError:
            pass
        if not keep_testbed:
            try:
                run([sys.executable, str(TESTBED), "down"], env=env)
            except ValueError:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the canonical blind deterministic Causcope acceptance benchmark, "
            "then score the finished Investigation against hidden oracle ground truth."
        )
    )
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--max-steps", type=int, default=4)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--keep-testbed", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.max_steps <= 16:
        print("acceptance benchmark: --max-steps must be between 1 and 16", file=sys.stderr)
        return 2
    try:
        result = run_benchmark(
            slug=args.scenario,
            workspace=args.workspace.expanduser().resolve(),
            max_steps=args.max_steps,
            keep_testbed=args.keep_testbed,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"acceptance benchmark: {error}", file=sys.stderr)
        return 2

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.result:
        result_path = args.result.expanduser().resolve()
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

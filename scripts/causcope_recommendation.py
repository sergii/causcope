#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from recommendation_information_gaps import load_json, project


def render(recommendation: dict[str, Any], gaps: dict[str, Any]) -> str:
    lines = [
        f"Recommendation: {gaps['recommendation_id']}",
        f"Subject: {gaps['subject_resource']}",
        f"State: {gaps['recommendation_state']}",
        f"Decision status: {gaps['status']}",
    ]

    problem = recommendation.get("problem")
    if isinstance(problem, dict):
        query_object = problem.get("query_object")
        request_path = problem.get("request_path")
        if isinstance(query_object, str) and query_object:
            lines.append(f"Problem query: {query_object}")
        if isinstance(request_path, str) and request_path:
            lines.append(f"Affected path: {request_path}")

    blockers = gaps.get("gaps", [])
    if blockers:
        lines.extend(["", "Blocked by:"])
        for blocker in blockers:
            lines.append(
                f"  {blocker['rank']}. {blocker['id']} - {blocker['why_now']}"
            )

    action = gaps["next_action"]
    lines.extend(
        [
            "",
            "Next best action:",
            f"  Kind: {action['kind']}",
            f"  {action['prompt']}",
            f"  Why: {action['reason']}",
            f"  Execution boundary: {action['execution_boundary']}",
        ]
    )
    if "probe_id" in action:
        lines.append(f"  Probe: {action['probe_id']}")
        lines.append(f"  Target: {gaps['subject_resource']}")
        lines.append(
            "  Handoff: use the existing safe target-aware instrument routing path; this command does not execute the probe."
        )
    if "requested_observation" in action:
        lines.append(f"  Requested observation: {action['requested_observation']}")

    lines.extend(
        [
            "",
            "Authority:",
            "  This surface does not execute probes, experiments, or architecture changes.",
            "  Architectural changes still require explicit human approval.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="causcope recommendation",
        description="Show recommendation maturity, information gaps, and the next bounded action.",
    )
    parser.add_argument(
        "--projection",
        type=Path,
        required=True,
        help="Architectural recommendation projection JSON file",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the strict recommendation information-gap projection as JSON",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        recommendation = load_json(args.projection)
        gaps = project(recommendation)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(gaps, indent=2, sort_keys=True))
    else:
        print(render(recommendation, gaps), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from causcope_cli import (
    DEFAULT_WORKSPACE,
    default_incident_id,
    initial_context,
    initial_session,
    load_state,
    persist_state,
)
from rails_pool_vertical_slice import build_summary, load_document, render


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="causcope why",
        description="Explain the current Causcope investigation without introducing a second reasoning path.",
    )
    parser.add_argument("problem", nargs="?", help="User-visible problem statement")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=DEFAULT_WORKSPACE,
        help="Investigation workspace (default: .causcope)",
    )
    parser.add_argument("--static", type=Path, help="Concrete System Facts document")
    parser.add_argument("--runtime", type=Path, help="Concrete Runtime Facts document")
    parser.add_argument("--pool", type=Path, help="Resource-pool runtime evidence document")
    parser.add_argument("--json", action="store_true", help="Print the selected canonical projection as JSON")
    parser.add_argument(
        "--require-confirmed",
        action="store_true",
        help="Fail closed unless an attached diagnostic projection reaches CAUSAL_DIAGNOSIS_CONFIRMED",
    )
    return parser


def diagnostic_paths(args: argparse.Namespace) -> tuple[Path, Path, Path] | None:
    supplied = [args.static is not None, args.runtime is not None, args.pool is not None]
    if any(supplied) and not all(supplied):
        raise ValueError("--static, --runtime, and --pool must be supplied together")
    if all(supplied):
        return args.static, args.runtime, args.pool
    return None


def render_scoping(problem: str, projection: dict) -> str:
    action = projection.get("next_action")
    lines = [
        "Causcope investigation",
        "",
        "Problem",
        f"  {problem}",
        "",
        "Status",
    ]
    if action:
        lines.extend(
            [
                "  NEEDS_SCOPE",
                "",
                "Next question",
                f"  {action['question']}",
                "",
                "Why now",
                f"  {action['reason']}",
            ]
        )
    else:
        lines.extend(
            [
                "  SCOPING_COMPLETE",
                "",
                "Diagnosis",
                "  No diagnostic evidence bundle is attached to this front door yet.",
                "  Continue with evidence acquisition or provide canonical diagnostic artifacts.",
            ]
        )
    return "\n".join(lines) + "\n"


def scoping_projection(args: argparse.Namespace) -> tuple[str, dict]:
    context_path = args.workspace / "incident-context.yaml"
    if context_path.exists():
        context, _session, projection = load_state(args.workspace)
        problem = args.problem or context["summary"]
        return problem, projection

    if not args.problem:
        raise FileNotFoundError(
            f"no investigation exists in {args.workspace}; provide a problem statement to start one"
        )

    incident_id = default_incident_id(args.problem)
    context = initial_context(args.problem, incident_id)
    session = initial_session(incident_id)
    projection = persist_state(args.workspace, context, session)
    return args.problem, projection


def command(args: argparse.Namespace) -> int:
    paths = diagnostic_paths(args)
    if paths is not None:
        static_path, runtime_path, pool_path = paths
        problem = args.problem or "request is slow"
        summary = build_summary(
            problem,
            load_document(static_path),
            load_document(runtime_path),
            load_document(pool_path),
        )
        if args.require_confirmed and summary["status"] != "confirmed":
            raise ValueError(f"diagnosis not confirmed: {summary['epistemic_state']}")
        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True))
        else:
            print(render(summary), end="")
        return 0

    if args.require_confirmed:
        raise ValueError("--require-confirmed requires --static, --runtime, and --pool")

    problem, projection = scoping_projection(args)
    if args.json:
        print(
            json.dumps(
                {
                    "kind": "causcope_why",
                    "problem": problem,
                    "status": "needs_scope" if projection.get("next_action") else "scoping_complete",
                    "scoping": projection,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(render_scoping(problem, projection), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return command(args)
    except (ValueError, FileNotFoundError, OSError, json.JSONDecodeError) as error:
        print(f"causcope: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

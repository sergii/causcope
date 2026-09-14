#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from concrete_system_facts import (
    load_document,
    load_schema,
    opposing_access_orders,
    validate_schema,
    validate_semantics,
)
from otel_concrete_runtime_facts import load_json, validate_runtime_document


def matching_overlaps(
    precondition: dict[str, Any], runtime: dict[str, Any]
) -> list[dict[str, Any]]:
    expected = {
        precondition["left"]["code_path"],
        precondition["right"]["code_path"],
    }
    matches: list[dict[str, Any]] = []
    for overlap in runtime["overlaps"]:
        observed = {overlap["left_code_symbol"], overlap["right_code_symbol"]}
        if observed == expected:
            matches.append(overlap)
    return matches


def project(static: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    validate_schema(static, load_schema())
    validate_semantics(static)
    validate_runtime_document(runtime)

    if runtime["system_id"] != static["system_id"]:
        raise ValueError("runtime and static facts belong to different concrete systems")
    if runtime["revision"] != static["revision"]:
        raise ValueError("runtime and static facts belong to different revisions")

    structural = opposing_access_orders(static)
    matched: list[dict[str, Any]] = []
    for precondition in structural:
        overlaps = matching_overlaps(precondition, runtime)
        matched.append(
            {
                "precondition": precondition,
                "matching_overlaps": overlaps,
            }
        )

    has_structural = bool(structural)
    has_runtime_overlap = any(item["matching_overlaps"] for item in matched)

    if has_structural and has_runtime_overlap:
        risk_state = "RISK_DETECTED"
    elif has_structural:
        risk_state = "PRECONDITIONS_PRESENT"
    else:
        risk_state = "UNKNOWN"

    return {
        "schema_version": "0.1",
        "kind": "d2_2_xray_projection",
        "catalog_code": "D2.2",
        "hypothesis": "hypothesis.database.deadlock",
        "system_id": static["system_id"],
        "revision": static["revision"],
        "incident_id": runtime["incident_id"],
        "structural_preconditions": {
            "state": "present" if has_structural else "unknown",
            "matches": structural,
        },
        "runtime_concurrency": {
            "state": "observed" if has_runtime_overlap else "unknown",
            "matches": [item for item in matched if item["matching_overlaps"]],
        },
        "deadlock_event": {
            "state": "unknown",
            "reason": (
                "Static access order plus overlapping code-path execution does not prove a "
                "PostgreSQL wait-for cycle or deadlock detector event."
            ),
        },
        "risk_state": risk_state,
        "next_evidence_needed": [
            "PostgreSQL lock waits/blockers for the affected scope",
            "deadlock detector evidence such as SQLSTATE 40P01 or a deadlock counter/event",
            "transaction/resource identity sufficient to connect runtime database evidence to these concrete paths",
        ],
        "limitations": [
            "RISK_DETECTED means a known D2.2 structural precondition executed concurrently; it is not an observed deadlock.",
            "No matching overlap in the supplied trace sample is treated as unknown, not proof that the paths never overlap.",
            "Static accesses_before facts remain source-derived preconditions and are not proof of exact PostgreSQL lock acquisition order.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Derive a D2.2 predictive X-Ray projection from concrete static and runtime facts."
    )
    parser.add_argument("--static-facts", required=True, type=Path)
    parser.add_argument("--runtime-facts", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        static = load_document(args.static_facts)
        runtime = load_json(args.runtime_facts)
        output = project(static, runtime)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    rendered = json.dumps(output, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

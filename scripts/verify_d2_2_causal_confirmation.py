#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from concrete_system_facts import load_document as load_static_document
from d2_2_causal_confirmation import project
from otel_concrete_runtime_facts import load_json


def expect_failure(label: str, fn, expected_fragment: str) -> None:
    try:
        fn()
    except ValueError as exc:
        if expected_fragment not in str(exc):
            raise SystemExit(f"{label} failed for the wrong reason: {exc}") from exc
    else:
        raise SystemExit(f"{label} must fail closed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify exact D2.2 causal-confirmation invariants.")
    parser.add_argument("--static-facts", required=True, type=Path)
    parser.add_argument("--runtime-facts", required=True, type=Path)
    parser.add_argument("--database-projection", required=True, type=Path)
    parser.add_argument("--correlation-evidence", required=True, type=Path)
    parser.add_argument("--confirmation", required=True, type=Path)
    args = parser.parse_args()

    static = load_static_document(args.static_facts)
    runtime = load_json(args.runtime_facts)
    database_projection = load_json(args.database_projection)
    correlation = load_json(args.correlation_evidence)
    saved = load_json(args.confirmation)

    recomputed = project(static, runtime, database_projection, correlation)
    if recomputed != saved:
        raise SystemExit("saved causal confirmation differs from deterministic recomputation")
    if saved["epistemic_state"] != "CAUSAL_DIAGNOSIS_CONFIRMED":
        raise SystemExit("exact correlated wait-for cycle must reach CAUSAL_DIAGNOSIS_CONFIRMED")
    if saved["causal_diagnosis"]["state"] != "confirmed":
        raise SystemExit("causal diagnosis must be confirmed")
    if len(saved["binding"]["participants"]) != 2 or len(saved["binding"]["wait_edges"]) < 2:
        raise SystemExit("confirmation must preserve both exact participants and both wait directions")

    bad_span = copy.deepcopy(correlation)
    bad_span["participants"][0]["span_id"] = "ffffffffffffffff"
    expect_failure(
        "tampered span binding",
        lambda: project(static, runtime, database_projection, bad_span),
        "span_id does not match exact OTel execution",
    )

    bad_cycle = copy.deepcopy(correlation)
    first_pid = bad_cycle["participants"][0]["backend_pid"]
    bad_cycle["wait_edges"][0]["blocker_backend_pid"] = first_pid
    expect_failure(
        "broken wait-for cycle",
        lambda: project(static, runtime, database_projection, bad_cycle),
        "wait edge escapes the exact correlated participant set",
    )

    bad_incident = copy.deepcopy(correlation)
    bad_incident["incident_id"] = "INC-OTHER"
    expect_failure(
        "cross-incident correlation",
        lambda: project(static, runtime, database_projection, bad_incident),
        "different incident",
    )

    print(
        json.dumps(
            {
                "status": "ok",
                "epistemic_state": saved["epistemic_state"],
                "participants": len(saved["binding"]["participants"]),
                "wait_edges": len(saved["binding"]["wait_edges"]),
                "tampered_span": "rejected",
                "broken_cycle": "rejected",
                "cross_incident": "rejected",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

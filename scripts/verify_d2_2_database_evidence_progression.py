#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from d2_2_database_evidence_projection import load_json, project
from runtime_evidence import load_runtime_evidence, parse_timestamp

AS_OF = "2026-09-14T12:01:04Z"
SCOPE_ATTRIBUTES = [
    ("service", "checkout-api"),
    ("dependency", "postgresql"),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify D2.2 progression from concrete risk to DB contention and deadlock event evidence."
    )
    parser.add_argument("--xray", required=True, type=Path)
    parser.add_argument("--pgbot-evidence", required=True, type=Path)
    parser.add_argument("--deadlock-evidence", required=True, type=Path)
    parser.add_argument("--contention-projection", required=True, type=Path)
    parser.add_argument("--event-projection", required=True, type=Path)
    args = parser.parse_args()

    xray = load_json(args.xray)
    pgbot = load_runtime_evidence(args.pgbot_evidence)
    deadlock = load_runtime_evidence(args.deadlock_evidence)
    contention_projection = load_json(args.contention_projection)
    event_projection = load_json(args.event_projection)
    as_of = parse_timestamp(AS_OF, "fixture as_of")

    recomputed_contention = project(
        xray,
        [(str(args.pgbot_evidence), pgbot)],
        as_of=as_of,
        scope_attributes=SCOPE_ATTRIBUTES,
    )
    if recomputed_contention != contention_projection:
        raise SystemExit("contention projection differs from deterministic recomputation")

    if contention_projection["epistemic_state"] != "CONTENTION_OBSERVED":
        raise SystemExit("pgBot lock evidence must advance D2.2 to CONTENTION_OBSERVED")
    if contention_projection["database_contention"]["state"] != "observed":
        raise SystemExit("canonical database lock-wait observation must be observed")
    if contention_projection["deadlock_event"]["state"] != "unknown":
        raise SystemExit("lock contention must not be promoted to a deadlock event")
    if contention_projection["causal_diagnosis"]["state"] != "unconfirmed":
        raise SystemExit("lock contention must not confirm concrete causal linkage")
    if contention_projection["runtime_concurrency"]["state"] != "observed":
        raise SystemExit("database progression must preserve concrete runtime overlap")

    recomputed_event = project(
        xray,
        [
            (str(args.pgbot_evidence), pgbot),
            (str(args.deadlock_evidence), deadlock),
        ],
        as_of=as_of,
        scope_attributes=SCOPE_ATTRIBUTES,
    )
    if recomputed_event != event_projection:
        raise SystemExit("event projection differs from deterministic recomputation")

    if event_projection["epistemic_state"] != "EVENT_OBSERVED":
        raise SystemExit("canonical deadlock error must advance D2.2 to EVENT_OBSERVED")
    if event_projection["database_contention"]["state"] != "observed":
        raise SystemExit("event projection must preserve lock contention evidence")
    if event_projection["deadlock_event"]["state"] != "observed":
        raise SystemExit("canonical SQLSTATE 40P01 evidence must be observed as a deadlock event")
    if event_projection["causal_diagnosis"]["state"] != "unconfirmed":
        raise SystemExit("deadlock event without concrete DB linkage must remain causally unconfirmed")

    mismatched = copy.deepcopy(pgbot)
    mismatched["incident_id"] = "INC-OTHER"
    try:
        project(
            xray,
            [("mismatched", mismatched)],
            as_of=as_of,
            scope_attributes=SCOPE_ATTRIBUTES,
        )
    except ValueError as exc:
        if "incident mismatch" not in str(exc):
            raise SystemExit(f"incident mismatch failed for the wrong reason: {exc}") from exc
    else:
        raise SystemExit("cross-incident database evidence must fail closed")

    print(
        json.dumps(
            {
                "status": "ok",
                "base_state": xray["risk_state"],
                "contention_state": contention_projection["epistemic_state"],
                "event_state": event_projection["epistemic_state"],
                "causal_diagnosis": event_projection["causal_diagnosis"]["state"],
                "incident_mismatch": "rejected",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from concrete_system_facts import load_document
from d2_2_xray_projection import project
from otel_concrete_runtime_facts import build_document, load_json, validate_runtime_document

EXPECTED_SYMBOLS = {
    "code:CheckoutService#call()",
    "code:SettlementJob#perform()",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify revision-bound OTel execution facts and D2.2 predictive runtime projection."
    )
    parser.add_argument("--static-facts", required=True, type=Path)
    parser.add_argument("--runtime-facts", required=True, type=Path)
    parser.add_argument("--projection", required=True, type=Path)
    parser.add_argument("--otlp", required=True, type=Path)
    args = parser.parse_args()

    static = load_document(args.static_facts)
    runtime = load_json(args.runtime_facts)
    projection = load_json(args.projection)
    payload = load_json(args.otlp)

    validate_runtime_document(runtime)

    if runtime["system_id"] != static["system_id"]:
        raise SystemExit("runtime system_id is not bound to the static concrete system")
    if runtime["revision"] != static["revision"]:
        raise SystemExit("runtime revision is not bound to the static concrete-system revision")

    symbols = {execution["code_symbol"] for execution in runtime["executions"]}
    if symbols != EXPECTED_SYMBOLS:
        raise SystemExit(f"unexpected concrete executions: {sorted(symbols)}")
    if len(runtime["executions"]) != 2:
        raise SystemExit("fixture must produce exactly two concrete executions")
    if len(runtime["overlaps"]) != 1:
        raise SystemExit("fixture must produce exactly one cross-symbol overlap")

    overlap = runtime["overlaps"][0]
    overlap_symbols = {overlap["left_code_symbol"], overlap["right_code_symbol"]}
    if overlap_symbols != EXPECTED_SYMBOLS:
        raise SystemExit("runtime overlap does not connect the D2.2 concrete code paths")
    if abs(overlap["overlap_ms"] - 260.0) > 0.000001:
        raise SystemExit(f"expected 260ms runtime overlap, got {overlap['overlap_ms']}")

    recomputed = project(static, runtime)
    if recomputed != projection:
        raise SystemExit("saved D2.2 projection differs from deterministic recomputation")

    if projection["catalog_code"] != "D2.2":
        raise SystemExit("projection lost the D2.2 catalog identity")
    if projection["hypothesis"] != "hypothesis.database.deadlock":
        raise SystemExit("projection lost the canonical deadlock hypothesis")
    if projection["structural_preconditions"]["state"] != "present":
        raise SystemExit("D2.2 structural precondition must be present")
    if projection["runtime_concurrency"]["state"] != "observed":
        raise SystemExit("concrete code-path overlap must be observed")
    if projection["risk_state"] != "RISK_DETECTED":
        raise SystemExit("static precondition plus runtime overlap must derive RISK_DETECTED")
    if projection["deadlock_event"]["state"] != "unknown":
        raise SystemExit("runtime overlap must not be promoted to an observed deadlock")

    bad_payload = copy.deepcopy(payload)
    bad_payload["resourceSpans"][0]["resource"]["attributes"][2]["value"][
        "stringValue"
    ] = "different-revision"
    try:
        build_document(
            static,
            bad_payload,
            incident_id=runtime["incident_id"],
            source_uri="negative-revision-test",
        )
    except ValueError as exc:
        if "revision mismatch" not in str(exc):
            raise SystemExit(f"revision mismatch failed for the wrong reason: {exc}") from exc
    else:
        raise SystemExit("revision mismatch must fail closed")

    print(
        json.dumps(
            {
                "status": "ok",
                "executions": len(runtime["executions"]),
                "overlaps": len(runtime["overlaps"]),
                "overlap_ms": overlap["overlap_ms"],
                "risk_state": projection["risk_state"],
                "deadlock_event": projection["deadlock_event"]["state"],
                "revision_mismatch": "rejected",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import secrets
import time
from pathlib import Path
from typing import Any

import psycopg


def string_attribute(key: str, value: str) -> dict[str, Any]:
    return {"key": key, "value": {"stringValue": value}}


def build_live_trace(
    dsn: str,
    *,
    sleep_ms: int,
    service: str,
    dependency: str,
    boundary: str,
) -> dict[str, Any]:
    if sleep_ms <= 0:
        raise ValueError("sleep_ms must be positive")

    start_ns = time.time_ns()
    with psycopg.connect(dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_sleep(%s)", (sleep_ms / 1000.0,))
    end_ns = time.time_ns()

    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        string_attribute("service.name", service),
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "causcope.live-postgresql-lab"},
                        "spans": [
                            {
                                "traceId": secrets.token_hex(16),
                                "spanId": secrets.token_hex(8),
                                "name": "SELECT pg_sleep",
                                "kind": "SPAN_KIND_CLIENT",
                                "startTimeUnixNano": str(start_ns),
                                "endTimeUnixNano": str(end_ns),
                                "status": {"code": "STATUS_CODE_OK"},
                                "attributes": [
                                    string_attribute("db.system", "postgresql"),
                                    string_attribute("peer.service", dependency),
                                    string_attribute("causcope.boundary", boundary),
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute a real PostgreSQL query and emit an OTLP/HTTP JSON trace payload."
    )
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sleep-ms", type=int, default=180)
    parser.add_argument("--service", default="checkout-api")
    parser.add_argument("--dependency", default="postgresql")
    parser.add_argument(
        "--boundary",
        default="boundary.application.external_dependency",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = build_live_trace(
        args.dsn,
        sleep_ms=args.sleep_ms,
        service=args.service,
        dependency=args.dependency,
        boundary=args.boundary,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

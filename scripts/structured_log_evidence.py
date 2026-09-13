#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from causal_projection import ROOT, load_concepts
from runtime_evidence import validate_runtime_references

REQUEST_FAILURE = "observation.http.request_failure"
CLIENT_COHORT_SKEW = "observation.http.client_cohort_failure_skew"
DATABASE_LOCK_WAIT = "observation.database.lock_wait_event"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_object_from_line(line: str) -> dict[str, Any] | None:
    start = line.find("{")
    if start < 0:
        return None
    try:
        value = json.loads(line[start:])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def parse_structured_events(text: str) -> list[dict[str, Any]]:
    return [event for line in text.splitlines() if (event := _json_object_from_line(line)) is not None]


def _safe_timestamp(event: dict[str, Any], fallback: str) -> str:
    value = event.get("observed_at")
    return value if isinstance(value, str) and value else fallback


def _instance_id(prefix: str, parts: Iterable[str]) -> str:
    canonical = "\x1f".join(parts)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    return f"evidence.{prefix}.{digest}"


def _request_scope(method: str, path: str, platform: str, version: str) -> dict[str, Any]:
    return {
        "attributes": {
            "method": method,
            "path": path,
            "client_platform": platform,
            "app_version": version,
        }
    }


def _source(source_name: str) -> dict[str, Any]:
    return {
        "type": "log",
        "name": source_name,
        "attributes": {"format": "json_lines"},
    }


def build_runtime_evidence_from_logs(
    events: list[dict[str, Any]],
    *,
    incident_id: str,
    source_name: str = "structured-application-log",
    collected_at: str | None = None,
    cohort_skew_threshold_pct: float = 50.0,
) -> dict[str, Any]:
    if not incident_id:
        raise ValueError("incident_id must not be empty")
    fallback_time = collected_at or utc_now()
    source = _source(source_name)
    instances: list[dict[str, Any]] = []

    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = defaultdict(
        lambda: {"total": 0, "failures": 0, "latest": fallback_time}
    )
    lock_events: list[dict[str, Any]] = []

    for event in events:
        event_type = event.get("event")
        if event_type == "http_request":
            method = str(event.get("method", "unknown"))
            path = str(event.get("path", "unknown"))
            platform = str(event.get("client_platform", "unknown"))
            version = str(event.get("app_version", "unknown"))
            try:
                status = int(event.get("status", 0))
            except (TypeError, ValueError):
                continue
            bucket = grouped[(method, path, platform, version)]
            bucket["total"] += 1
            if status >= 400:
                bucket["failures"] += 1
            bucket["latest"] = _safe_timestamp(event, fallback_time)
        elif event_type == "sqlite_operational_error":
            error = str(event.get("error", ""))
            if "locked" in error.lower():
                lock_events.append(event)

    for (method, path, platform, version), bucket in sorted(grouped.items()):
        total = int(bucket["total"])
        failures = int(bucket["failures"])
        failure_pct = round((failures / total) * 100.0, 3) if total else 0.0
        state = "observed" if failures > 0 else "absent"
        instances.append(
            {
                "id": _instance_id(
                    "http_request_failure",
                    [incident_id, method, path, platform, version],
                ),
                "observation": REQUEST_FAILURE,
                "state": state,
                "observed_at": str(bucket["latest"]),
                "confidence": "high",
                "source": source,
                "scope": _request_scope(method, path, platform, version),
                "measurement": {
                    "value": failure_pct,
                    "baseline": 0.0,
                    "delta": failure_pct,
                    "unit": "percent",
                    "comparison": "above_baseline" if failures > 0 else "equal",
                },
                "labels": {
                    "requests_total": str(total),
                    "requests_failed": str(failures),
                },
                "note": "HTTP failure outcome is evidence, not a causal conclusion.",
            }
        )

    by_route: dict[tuple[str, str], list[tuple[tuple[str, str], dict[str, Any]]]] = defaultdict(list)
    for (method, path, platform, version), bucket in grouped.items():
        by_route[(method, path)].append(((platform, version), bucket))

    for (method, path), cohorts in sorted(by_route.items()):
        usable = [item for item in cohorts if int(item[1]["total"]) > 0]
        if len(usable) < 2:
            continue

        def failure_pct(item: tuple[tuple[str, str], dict[str, Any]]) -> float:
            bucket = item[1]
            return (int(bucket["failures"]) / int(bucket["total"])) * 100.0

        highest = max(usable, key=lambda item: (failure_pct(item), item[0]))
        lowest = min(usable, key=lambda item: (failure_pct(item), item[0]))
        high_pct = failure_pct(highest)
        low_pct = failure_pct(lowest)
        delta = round(high_pct - low_pct, 3)
        if highest[0] == lowest[0] or delta < cohort_skew_threshold_pct:
            continue

        high_platform, high_version = highest[0]
        low_platform, low_version = lowest[0]
        latest = max(str(item[1]["latest"]) for item in usable)
        instances.append(
            {
                "id": _instance_id(
                    "http_client_cohort_failure_skew",
                    [incident_id, method, path, high_platform, high_version, low_platform, low_version],
                ),
                "observation": CLIENT_COHORT_SKEW,
                "state": "observed",
                "observed_at": latest,
                "confidence": "high",
                "source": source,
                "scope": {"attributes": {"method": method, "path": path}},
                "measurement": {
                    "value": round(high_pct, 3),
                    "baseline": round(low_pct, 3),
                    "delta": delta,
                    "unit": "percentage_points",
                    "comparison": "above_baseline",
                },
                "labels": {
                    "failing_cohort": f"{high_platform}@{high_version}",
                    "working_cohort": f"{low_platform}@{low_version}",
                },
                "note": "Cohort skew is a discriminator; it does not by itself prove the client is causal.",
            }
        )

    if lock_events:
        latest_event = max(lock_events, key=lambda event: _safe_timestamp(event, fallback_time))
        instances.append(
            {
                "id": _instance_id("database_lock_wait", [incident_id, "sqlite"]),
                "observation": DATABASE_LOCK_WAIT,
                "state": "observed",
                "observed_at": _safe_timestamp(latest_event, fallback_time),
                "confidence": "high",
                "source": source,
                "scope": {"attributes": {"database_engine": "sqlite"}},
                "measurement": {
                    "value": len(lock_events),
                    "unit": "events",
                    "comparison": "present",
                },
                "labels": {"error": "database is locked"},
                "note": "SQLite operational-error logs report lock acquisition failure; provenance is preserved as log evidence.",
            }
        )

    if not instances:
        raise ValueError("structured log input did not contain any supported diagnostic events")

    return {
        "schema_version": "0.1",
        "kind": "runtime_evidence",
        "incident_id": incident_id,
        "description": "Runtime evidence derived from structured application logs by read-only aggregation.",
        "instances": sorted(instances, key=lambda item: item["id"]),
    }


def validate_document(document: dict[str, Any]) -> None:
    concepts = load_concepts(ROOT)
    validate_runtime_references(document, concepts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert structured application logs into Causcope runtime evidence.")
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--input", type=Path, required=True, help="Text log file containing JSON events")
    parser.add_argument("--output", type=Path, help="Write runtime evidence JSON to this path")
    parser.add_argument("--source-name", default="structured-application-log")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    text = args.input.read_text(encoding="utf-8")
    document = build_runtime_evidence_from_logs(
        parse_structured_events(text),
        incident_id=args.incident_id,
        source_name=args.source_name,
    )
    validate_document(document)
    encoded = json.dumps(document, indent=2 if args.pretty or args.output else None, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

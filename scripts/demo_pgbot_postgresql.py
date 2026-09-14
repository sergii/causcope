#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from causal_projection import load_concepts, load_edges
from live_diagnosis import build_diagnosis_snapshot
from opentelemetry_trace_adapter import (
    build_runtime_evidence as build_trace_evidence,
)
from opentelemetry_trace_adapter import load_adapter as load_trace_adapter
from opentelemetry_trace_adapter import load_payload
from pgbot_adapter import build_runtime_evidence as build_pgbot_evidence
from pgbot_adapter import load_adapter as load_pgbot_adapter
from pgbot_adapter import load_context as load_pgbot_context
from runtime_evidence_composition import compose_runtime_evidence

ROOT = Path(__file__).resolve().parents[1]
INCIDENT_ID = "incident.checkout.postgresql"


def main() -> int:
    concepts = load_concepts(ROOT)
    edges = load_edges(ROOT)

    pgbot_adapter = load_pgbot_adapter(
        ROOT / "examples" / "adapters" / "pgbot" / "postgresql.yaml"
    )
    pgbot_context = load_pgbot_context(
        ROOT / "examples" / "telemetry" / "pgbot" / "postgresql-findings.json"
    )
    trace_adapter = load_trace_adapter(
        ROOT
        / "examples"
        / "adapters"
        / "opentelemetry"
        / "postgresql-dependency.yaml"
    )
    trace_payload = load_payload(
        ROOT
        / "examples"
        / "telemetry"
        / "opentelemetry"
        / "postgresql-query-trace.json"
    )

    pgbot_evidence = build_pgbot_evidence(
        pgbot_adapter,
        pgbot_context,
        concepts,
        incident_id=INCIDENT_ID,
        source_uri="pgbot://app-production",
    )
    trace_evidence = build_trace_evidence(
        trace_adapter,
        trace_payload,
        concepts,
        incident_id=INCIDENT_ID,
        source_uri="otlp://checkout-api",
    )
    composed = compose_runtime_evidence(
        [pgbot_evidence, trace_evidence],
        concepts,
    )
    snapshot = build_diagnosis_snapshot(
        composed,
        concepts,
        edges,
        as_of=datetime(2026, 9, 14, 0, 31, tzinfo=timezone.utc),
        evidence_revision=1,
    )

    output = {
        "incident_id": INCIDENT_ID,
        "pgbot": [
            {
                "finding": instance["labels"]["source_finding"],
                "observation": instance["observation"],
            }
            for instance in pgbot_evidence["instances"]
        ],
        "otel": [
            {
                "source": instance["source"]["name"],
                "observation": instance["observation"],
            }
            for instance in trace_evidence["instances"]
        ],
        "composed_source_types": sorted(
            {instance["source"]["type"] for instance in composed["instances"]}
        ),
        "partition": {
            "scope": snapshot["partitions"][0]["scope"],
            "observed": snapshot["partitions"][0]["observed"],
        },
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

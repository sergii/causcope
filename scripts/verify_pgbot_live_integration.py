#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from causal_projection import ROOT, load_concepts, load_edges
from live_diagnosis import build_diagnosis_snapshot
from opentelemetry_trace_adapter import (
    build_runtime_evidence as build_trace_evidence,
)
from opentelemetry_trace_adapter import load_adapter as load_trace_adapter
from opentelemetry_trace_adapter import load_payload as load_trace_payload
from pgbot_adapter import build_runtime_evidence as build_pgbot_evidence
from pgbot_adapter import load_adapter as load_pgbot_adapter
from pgbot_adapter import load_context as load_pgbot_context
from runtime_evidence_composition import compose_runtime_evidence

PGBOT_ADAPTER = ROOT / "examples" / "adapters" / "pgbot" / "postgresql.yaml"
TRACE_ADAPTER = (
    ROOT / "examples" / "adapters" / "opentelemetry" / "postgresql-dependency.yaml"
)
INCIDENT_ID = "incident.live.postgresql"
EXPECTED_SCOPE = {
    "boundaries": ["boundary.application.external_dependency"],
    "attributes": {
        "dependency": "postgresql",
        "service": "checkout-api",
    },
}


def active_finding_ids(context: dict) -> set[str]:
    return {
        finding["id"]
        for finding in context["findings"]
        if isinstance(finding, dict)
        and isinstance(finding.get("id"), str)
        and finding.get("suppressed") is not True
    }


def verify(pgbot_report: Path, trace_payload: Path) -> dict:
    concepts = load_concepts(ROOT)
    edges = load_edges(ROOT)
    pgbot_adapter = load_pgbot_adapter(PGBOT_ADAPTER)
    trace_adapter = load_trace_adapter(TRACE_ADAPTER)
    pgbot_context = load_pgbot_context(pgbot_report)
    trace_context = load_trace_payload(trace_payload)

    source_findings = active_finding_ids(pgbot_context)
    if "wait_lock_contention" not in source_findings:
        raise ValueError(
            "live pgbot report did not contain active wait_lock_contention finding"
        )

    pgbot_evidence = build_pgbot_evidence(
        pgbot_adapter,
        pgbot_context,
        concepts,
        incident_id=INCIDENT_ID,
        source_uri="pgbot://live-postgresql-lab",
    )
    trace_evidence = build_trace_evidence(
        trace_adapter,
        trace_context,
        concepts,
        incident_id=INCIDENT_ID,
        source_uri="otlp://live-postgresql-lab",
    )
    composed = compose_runtime_evidence(
        [pgbot_evidence, trace_evidence],
        concepts,
    )

    scopes = {
        json.dumps(instance.get("scope"), sort_keys=True)
        for instance in composed["instances"]
    }
    if scopes != {json.dumps(EXPECTED_SCOPE, sort_keys=True)}:
        raise ValueError(f"live evidence did not compose into expected scope: {scopes}")

    observations = {
        instance["observation"]
        for instance in composed["instances"]
        if instance["state"] == "observed"
    }
    required_observations = {
        "observation.database.lock_wait_time",
        "observation.database.query_latency",
    }
    missing = sorted(required_observations - observations)
    if missing:
        raise ValueError("live evidence is missing observations: " + ", ".join(missing))

    provenance_types = {
        instance["source"]["type"]
        for instance in composed["instances"]
    }
    if not {"other", "trace"}.issubset(provenance_types):
        raise ValueError(
            "live composition did not preserve both pgbot and trace provenance"
        )

    snapshot = build_diagnosis_snapshot(
        composed,
        concepts,
        edges,
        as_of=datetime.now(timezone.utc),
        evidence_revision=1,
    )
    if len(snapshot["partitions"]) != 1:
        raise ValueError(
            f"expected one live diagnosis partition, got {len(snapshot['partitions'])}"
        )
    partition = snapshot["partitions"][0]
    if partition["scope"] != EXPECTED_SCOPE:
        raise ValueError(f"unexpected live diagnosis scope: {partition['scope']}")

    return {
        "kind": "pgbot_live_integration_summary",
        "incident_id": INCIDENT_ID,
        "pgbot_schema_version": pgbot_context["schema_version"],
        "pgbot_findings": sorted(source_findings),
        "canonical_observations": sorted(observations),
        "provenance_types": sorted(provenance_types),
        "scope": partition["scope"],
        "diagnosis_targets": sorted(
            item["target"] for item in partition.get("diagnoses", [])
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify live pgbot and PostgreSQL trace evidence composition."
    )
    parser.add_argument("--pgbot-report", required=True, type=Path)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        summary = verify(args.pgbot_report, args.trace)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(summary, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

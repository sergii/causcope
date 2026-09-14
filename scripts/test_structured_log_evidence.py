#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import datetime, timezone

from jsonschema import Draft202012Validator

from causal_projection import ROOT, load_concepts, load_edges
from live_diagnosis import build_diagnosis_snapshot
from runtime_evidence import SCHEMA_PATH, validate_runtime_references
from structured_log_evidence import (
    CLIENT_COHORT_SKEW,
    DATABASE_LOCK_WAIT,
    REQUEST_FAILURE,
    build_runtime_evidence_from_logs,
    parse_structured_events,
)


def main() -> int:
    log_text = """
noise before json
{"event":"http_request","observed_at":"2026-09-14T00:00:01Z","method":"POST","path":"/orders","status":201,"client_platform":"web","app_version":"1.0","duration_ms":8.2}
{"event":"http_request","observed_at":"2026-09-14T00:00:02Z","method":"POST","path":"/orders","status":201,"client_platform":"web","app_version":"1.0","duration_ms":7.8}
{"event":"http_request","observed_at":"2026-09-14T00:00:03Z","method":"POST","path":"/orders","status":422,"client_platform":"ios","app_version":"7.42.0","duration_ms":2.1}
{"event":"http_request","observed_at":"2026-09-14T00:00:04Z","method":"POST","path":"/orders","status":422,"client_platform":"ios","app_version":"7.42.0","duration_ms":2.0}
{"event":"sqlite_operational_error","observed_at":"2026-09-14T00:00:05Z","error":"database is locked","db_path":"/data/shop.db"}
"""
    events = parse_structured_events(log_text)
    assert len(events) == 5

    evidence = build_runtime_evidence_from_logs(
        events,
        incident_id="incident.test.structured-logs",
        source_name="test-log",
        collected_at="2026-09-14T00:00:06Z",
    )

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(evidence), key=lambda error: list(error.path))
    assert not errors, "; ".join(error.message for error in errors)

    concepts = load_concepts(ROOT)
    validate_runtime_references(evidence, concepts)

    by_observation: dict[str, list[dict]] = {}
    for instance in evidence["instances"]:
        by_observation.setdefault(instance["observation"], []).append(instance)

    request_instances = by_observation[REQUEST_FAILURE]
    assert len(request_instances) == 2
    request_states = {
        instance["scope"]["attributes"]["client_platform"]: instance["state"]
        for instance in request_instances
    }
    assert request_states == {"ios": "observed", "web": "absent"}

    skew = by_observation[CLIENT_COHORT_SKEW]
    assert len(skew) == 1
    assert skew[0]["measurement"]["delta"] == 100.0
    assert skew[0]["labels"]["failing_cohort"] == "ios@7.42.0"
    assert skew[0]["labels"]["working_cohort"] == "web@1.0"

    lock_wait = by_observation[DATABASE_LOCK_WAIT]
    assert len(lock_wait) == 1
    assert lock_wait[0]["state"] == "observed"

    passive = build_runtime_evidence_from_logs(
        events,
        incident_id="incident.test.passive-logs",
        source_name="test-log",
        collected_at="2026-09-14T00:00:06Z",
        include_derived_findings=False,
    )
    validate_runtime_references(passive, concepts)
    assert {item["observation"] for item in passive["instances"]} == {REQUEST_FAILURE}
    assert len(passive["instances"]) == 2

    snapshot = build_diagnosis_snapshot(
        evidence,
        concepts,
        load_edges(ROOT),
        as_of=datetime(2026, 9, 14, 0, 0, 10, tzinfo=timezone.utc),
        evidence_revision=1,
    )

    diagnoses = [
        diagnosis
        for partition in snapshot["partitions"]
        for diagnosis in partition["diagnoses"]
    ]
    by_target = {diagnosis["target"]: diagnosis for diagnosis in diagnoses}

    cohort_ranking = by_target[CLIENT_COHORT_SKEW]["ranking"]
    assert cohort_ranking["candidates"][0]["source"]["id"] == "hypothesis.client.payload_contract_mismatch"

    lock_ranking = by_target[DATABASE_LOCK_WAIT]["ranking"]
    assert lock_ranking["candidates"][0]["source"]["id"] == "hypothesis.database.lock_contention"

    request_rankings = [diagnosis for diagnosis in diagnoses if diagnosis["target"] == REQUEST_FAILURE]
    failing_request_ranking = next(
        diagnosis
        for diagnosis in request_rankings
        if diagnosis["ranking"]["query"]["observed"] == [REQUEST_FAILURE]
    )
    candidate_ids = {
        candidate["source"]["id"]
        for candidate in failing_request_ranking["ranking"]["candidates"]
    }
    assert "hypothesis.database.lock_contention" in candidate_ids
    assert "hypothesis.client.payload_contract_mismatch" in candidate_ids
    assert failing_request_ranking["probe_ranking"]["found"] is True
    assert failing_request_ranking["probe_ranking"]["probes"]

    print("Structured log evidence adapter: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

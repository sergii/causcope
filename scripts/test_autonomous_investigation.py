#!/usr/bin/env python3

from __future__ import annotations

import sys
from datetime import datetime, timezone

from autonomous_investigation import run_autonomous_read_only_loop
from causal_projection import ROOT, load_concepts, load_edges
from live_diagnosis import build_diagnosis_snapshot, normalize_scope, scope_key
from structured_log_evidence import REQUEST_FAILURE, build_runtime_evidence_from_logs, parse_structured_events

SHOP_ROOT = ROOT / "testbed" / "shop"
if str(SHOP_ROOT) not in sys.path:
    sys.path.insert(0, str(SHOP_ROOT))

from read_only_probe_adapter import (  # noqa: E402
    CLIENT_COHORT_SKEW,
    COMPARE_CLIENT_COHORTS,
    DATABASE_LOCK_ERROR,
    INSPECT_LOCK_ERRORS,
    ShopStructuredLogProbeAdapter,
)

NOW = datetime(2026, 9, 14, 0, 10, 0, tzinfo=timezone.utc)


def clock() -> datetime:
    return NOW


def passive_evidence(log_text: str, incident_id: str) -> tuple[list[dict], dict]:
    events = parse_structured_events(log_text)
    evidence = build_runtime_evidence_from_logs(
        events,
        incident_id=incident_id,
        source_name="autonomous-loop-test",
        collected_at="2026-09-14T00:09:59Z",
        include_derived_findings=False,
    )
    return events, evidence


def diagnosis_for(snapshot: dict, *, target: str, scope: dict | None, concepts: dict) -> dict:
    wanted = scope_key(normalize_scope(scope, concepts))
    matches = [
        diagnosis
        for partition in snapshot["partitions"]
        if scope_key(partition.get("scope")) == wanted
        for diagnosis in partition["diagnoses"]
        if diagnosis["target"] == target
    ]
    assert len(matches) == 1, (target, scope, matches)
    return matches[0]


def top_hypothesis(diagnosis: dict) -> str:
    return diagnosis["ranking"]["candidates"][0]["source"]["id"]


def observed_scope(evidence: dict) -> dict:
    matches = [
        item
        for item in evidence["instances"]
        if item["observation"] == REQUEST_FAILURE and item["state"] == "observed"
    ]
    assert len(matches) == 1
    return matches[0]["scope"]


def run_case(log_text: str, incident_id: str) -> tuple[dict, dict, dict, dict]:
    concepts = load_concepts(ROOT)
    edges = load_edges(ROOT)
    events, evidence = passive_evidence(log_text, incident_id)
    initial = build_diagnosis_snapshot(
        evidence,
        concepts,
        edges,
        as_of=NOW,
        evidence_revision=1,
    )
    adapter = ShopStructuredLogProbeAdapter(
        events=events,
        incident_id=incident_id,
        collected_at="2026-09-14T00:09:59Z",
    )
    final_evidence, final_snapshot, report = run_autonomous_read_only_loop(
        evidence=evidence,
        snapshot=initial,
        concepts=concepts,
        edges=edges,
        supported_probe_ids=adapter.supported_probe_ids,
        execute_probe=adapter.execute,
        max_steps=4,
        clock=clock,
    )
    return final_evidence, final_snapshot, report, concepts


def test_mobile_cohort_converges_to_client_mismatch() -> None:
    log_text = """
{"event":"http_request","observed_at":"2026-09-14T00:09:01Z","method":"POST","path":"/orders","status":201,"client_platform":"web","app_version":"2026.09"}
{"event":"http_request","observed_at":"2026-09-14T00:09:02Z","method":"POST","path":"/orders","status":201,"client_platform":"web","app_version":"2026.09"}
{"event":"http_request","observed_at":"2026-09-14T00:09:03Z","method":"POST","path":"/orders","status":422,"client_platform":"iOS","app_version":"7.42.0"}
{"event":"http_request","observed_at":"2026-09-14T00:09:04Z","method":"POST","path":"/orders","status":422,"client_platform":"iOS","app_version":"7.42.0"}
"""
    evidence, snapshot, report, concepts = run_case(log_text, "incident.test.autonomous-mobile")
    scope = observed_scope(evidence)
    diagnosis = diagnosis_for(snapshot, target=REQUEST_FAILURE, scope=scope, concepts=concepts)

    assert top_hypothesis(diagnosis) == "hypothesis.client.payload_contract_mismatch"
    by_observation = {item["observation"]: item for item in evidence["instances"] if item["scope"] == scope}
    assert by_observation[CLIENT_COHORT_SKEW]["state"] == "observed"
    assert by_observation[CLIENT_COHORT_SKEW]["labels"]["failing_cohort"] == "iOS@7.42.0"
    assert by_observation[DATABASE_LOCK_ERROR]["state"] == "absent"

    completed = {step["probe_id"] for step in report["steps"] if step["status"] == "completed"}
    assert {COMPARE_CLIENT_COHORTS, INSPECT_LOCK_ERRORS}.issubset(completed)
    assert report["final_evidence_revision"] == 3
    assert report["stop_reason"] in {"repeated_recommendation", "no_executable_recommendation"}


def test_sqlite_lock_converges_after_insufficient_cohort_probe() -> None:
    log_text = """
{"event":"sqlite_operational_error","observed_at":"2026-09-14T00:09:03Z","error":"database is locked","db_path":"/data/shop.db","method":"POST","path":"/orders","client_platform":"web","app_version":"2026.09","request_id":"lock-request"}
{"event":"http_request","observed_at":"2026-09-14T00:09:04Z","method":"POST","path":"/orders","status":503,"client_platform":"web","app_version":"2026.09","request_id":"lock-request"}
"""
    evidence, snapshot, report, concepts = run_case(log_text, "incident.test.autonomous-lock")
    scope = observed_scope(evidence)
    diagnosis = diagnosis_for(snapshot, target=REQUEST_FAILURE, scope=scope, concepts=concepts)

    assert top_hypothesis(diagnosis) == "hypothesis.database.lock_contention"
    lock_evidence = [
        item
        for item in evidence["instances"]
        if item["observation"] == DATABASE_LOCK_ERROR and item.get("scope") == scope
    ]
    assert len(lock_evidence) == 1
    assert lock_evidence[0]["state"] == "observed"
    assert lock_evidence[0]["source"]["type"] == "probe"

    completed = [step for step in report["steps"] if step["status"] == "completed"]
    assert any(step["probe_id"] == INSPECT_LOCK_ERRORS for step in completed)
    insufficient = [step for step in report["steps"] if step["status"] == "insufficient_evidence"]
    assert any(step["probe_id"] == COMPARE_CLIENT_COHORTS for step in insufficient)
    assert report["final_evidence_revision"] == 2
    assert all(step["evidence_revision"] == 1 for step in insufficient)


def main() -> int:
    test_mobile_cohort_converges_to_client_mismatch()
    test_sqlite_lock_converges_after_insufficient_cohort_probe()
    print("Autonomous read-only investigation loop: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

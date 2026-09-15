#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from run_acceptance_benchmark import (  # noqa: E402
    AI_CREDENTIAL_ENV_KEYS,
    build_result,
    deterministic_env,
    score_summary,
)


def main() -> int:
    oracle = {
        "expected_causcope": {
            "target": "observation.http.request_failure",
            "scope_contains": {
                "method": "POST",
                "path": "/orders",
                "client_platform": "web",
            },
            "top_hypothesis": "hypothesis.database.lock_contention",
            "required_completed_probes": [
                "probe.database.inspect_lock_error_events"
            ],
            "minimum_evidence_revision": 2,
        }
    }
    summary = {
        "diagnoses": [
            {
                "target": "observation.http.request_failure",
                "scope": {
                    "attributes": {
                        "method": "POST",
                        "path": "/orders",
                        "client_platform": "web",
                        "app_version": "2026.09",
                    }
                },
                "top_hypothesis": "hypothesis.database.lock_contention",
                "next_probe": None,
            }
        ],
        "autonomous": {
            "stop_reason": "no_eligible_probe",
            "final_evidence_revision": 2,
            "steps": [
                {
                    "probe_id": "probe.http.compare_client_cohorts",
                    "status": "insufficient_evidence",
                },
                {
                    "probe_id": "probe.database.inspect_lock_error_events",
                    "status": "completed",
                },
            ],
        },
    }

    passed, checks, observed = score_summary(summary, oracle)
    assert passed
    assert all(check["passed"] for check in checks)
    assert observed["top_hypothesis"] == "hypothesis.database.lock_contention"
    assert observed["completed_probes"] == [
        "probe.database.inspect_lock_error_events"
    ]

    wrong_summary = json.loads(json.dumps(summary))
    wrong_summary["diagnoses"][0]["top_hypothesis"] = "hypothesis.client.payload_contract_mismatch"
    wrong_passed, wrong_checks, _ = score_summary(wrong_summary, oracle)
    assert not wrong_passed
    assert not next(check for check in wrong_checks if check["id"] == "top_hypothesis")["passed"]

    original = {key: os.environ.get(key) for key in AI_CREDENTIAL_ENV_KEYS}
    try:
        for key in AI_CREDENTIAL_ENV_KEYS:
            os.environ[key] = "benchmark-must-not-see-this"
        env = deterministic_env()
        assert all(key not in env for key in AI_CREDENTIAL_ENV_KEYS)
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    scenario = {"slug": "sqlite-write-lock", "id": "scenario.shop.sqlite_write_lock"}
    result = build_result(
        scenario=scenario,
        oracle=oracle,
        summary=summary,
        incident_id="incident.benchmark.sqlite_write_lock",
    )
    schema = json.loads(
        (ROOT / "schema" / "acceptance-benchmark-result.schema.json").read_text(
            encoding="utf-8"
        )
    )
    errors = list(Draft202012Validator(schema).iter_errors(result))
    assert not errors, "; ".join(error.message for error in errors)
    assert result["passed"] is True
    assert result["llm"]["enabled"] is False
    assert result["oracle_policy"] == {
        "loaded_after_investigation": True,
        "used_to_construct_diagnosis": False,
    }

    print("acceptance benchmark scoring: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

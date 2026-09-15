#!/usr/bin/env python3

from __future__ import annotations

import copy

from rails_pool_vertical_slice import build_summary, render


def fixtures():
    revision = {"type": "git", "value": "abc123", "repository": "https://example.test/app"}
    static = {
        "kind": "concrete_system_facts",
        "system_id": "shop",
        "revision": revision,
        "entities": [
            {
                "id": "pool:active_record.primary",
                "kind": "resource_pool",
                "attributes": {"technology": "active_record", "configured_capacity": 1},
            },
            {"id": "code:CheckoutController#create()", "kind": "code_symbol", "attributes": {}},
            {
                "id": "dependency:postgresql",
                "kind": "external_dependency",
                "attributes": {"dbms": "postgresql"},
            },
        ],
        "facts": [
            {
                "subject": "code:CheckoutController#create()",
                "relation": "depends_on",
                "object": "pool:active_record.primary",
            },
            {
                "subject": "pool:active_record.primary",
                "relation": "depends_on",
                "object": "dependency:postgresql",
            },
        ],
    }
    runtime = {
        "kind": "concrete_runtime_facts",
        "system_id": "shop",
        "revision": revision,
        "incident_id": "incident.checkout.slow",
        "executions": [
            {
                "id": "execution:checkout",
                "code_symbol": "code:CheckoutController#create()",
                "trace_id": "1" * 32,
                "span_id": "2" * 16,
            }
        ],
        "pool_interactions": [
            {
                "id": "interaction:checkout-primary",
                "execution_id": "execution:checkout",
                "code_symbol": "code:CheckoutController#create()",
                "pool_id": "pool:active_record.primary",
                "technology": "active_record",
                "config_name": "primary",
                "trace_id": "1" * 32,
                "span_id": "2" * 16,
            }
        ],
    }
    pool = {
        "kind": "resource_pool_runtime_evidence",
        "system_id": "shop",
        "revision": revision,
        "incident_id": "incident.checkout.slow",
        "pool": {
            "id": "pool:active_record.primary",
            "technology": "active_record",
            "configured_capacity": 1,
            "observed_capacity": 1,
            "busy": 1,
            "utilization": 1.0,
        },
        "request": {
            "code_symbol": "code:CheckoutController#create()",
            "trace_id": "1" * 32,
            "span_id": "2" * 16,
            "checkout_wait_ms": 451.2,
            "request_latency_ms": 480.0,
            "dependency_latency_ms": 8.0,
            "dependency_backend_id": "101",
        },
        "dependency_control": {
            "dependency_id": "dependency:postgresql",
            "reachable": True,
            "total_latency_ms": 4.0,
            "query_latency_ms": 1.0,
            "backend_id": "202",
        },
        "baseline": {
            "checkout_wait_ms": 0.2,
            "request_latency_ms": 20.0,
            "dependency_latency_ms": 7.0,
        },
        "recovery": {
            "checkout_wait_ms": 0.3,
            "request_latency_ms": 21.0,
            "dependency_latency_ms": 7.5,
        },
        "assertions": {
            "application_pool_was_at_capacity": True,
            "pool_checkout_wait_increased": True,
            "request_latency_increased": True,
            "query_latency_stayed_near_baseline": True,
            "database_still_accepts_direct_connections": True,
            "checkout_wait_explains_request_delta": True,
            "recovery_checkout_wait_returned_to_baseline": True,
            "recovery_request_latency_returned_to_baseline": True,
        },
    }
    return static, runtime, pool


def main() -> int:
    static, runtime, pool = fixtures()
    summary = build_summary("checkout is slow", static, runtime, pool)
    assert summary["status"] == "confirmed"
    assert summary["epistemic_state"] == "CAUSAL_DIAGNOSIS_CONFIRMED"
    assert summary["root_cause"] == "application-side database connection pool exhaustion"
    assert summary["resource_pool"] == "pool:active_record.primary"
    assert summary["technology"] == "active_record"
    assert summary["blast_radius"] == "not established by this bounded slice"
    assert "slow SQL execution as the primary explanation" in summary["rejected_nearby_explanations"]
    assert "PostgreSQL-wide connection admission exhaustion" in summary["rejected_nearby_explanations"]

    human = render(summary)
    assert "Problem\n  checkout is slow" in human
    assert "Root cause\n  application-side database connection pool exhaustion" in human
    assert "451.2 ms" in human
    assert "not established by this bounded slice" in human

    incomplete = copy.deepcopy(pool)
    incomplete["assertions"]["database_still_accepts_direct_connections"] = False
    incomplete_summary = build_summary("checkout is slow", static, runtime, incomplete)
    assert incomplete_summary["status"] == "not_confirmed"
    assert incomplete_summary["epistemic_state"] == "CHECKOUT_WAIT_OBSERVED"
    assert incomplete_summary["root_cause"] is None
    assert "PostgreSQL-wide connection admission exhaustion" not in incomplete_summary["rejected_nearby_explanations"]

    print("Rails pool golden vertical slice projection: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

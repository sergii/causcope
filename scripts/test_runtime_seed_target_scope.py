#!/usr/bin/env python3

from __future__ import annotations

from runtime_incident_seed import build_initial_evidence


def main() -> int:
    execution = {
        "id": "execution.test",
        "trace_id": "a" * 32,
        "span_id": "b" * 16,
        "code_symbol": "code:PoolController#work()",
        "duration_ms": 900.0,
        "end_time": "2026-09-15T21:00:00Z",
        "source": {"uri": "otlp:test"},
    }
    interaction = {
        "id": "pool-interaction.test",
        "pool_id": "pool:active_record.primary",
        "checkout_wait_ms": 700.0,
        "observed_at": "2026-09-15T21:00:00Z",
    }
    target = "db.causcope.prod"
    evidence = build_initial_evidence(
        incident_id="incident.test",
        system_id="rails-connection-pool-app",
        revision="revision-test",
        execution=execution,
        interaction=interaction,
        request_threshold_ms=200.0,
        pool_wait_threshold_ms=50.0,
        target_resource=target,
    )
    assert len(evidence["instances"]) == 2
    for instance in evidence["instances"]:
        assert instance["scope"]["attributes"]["target_resource"] == target
        assert instance["source"]["attributes"]["causcope.target_resource"] == target
        assert instance["labels"]["target_resource"] == target
    print("runtime seed exact target scope: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

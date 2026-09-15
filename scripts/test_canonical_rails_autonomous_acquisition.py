#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

from causcope_bootstrap import build_bindings, build_topology

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    document = {"system_id": "rails-connection-pool-app"}
    pool = {"id": "pool:active_record.primary"}
    topology, pgbot_instance = build_topology(
        document,
        pool,
        database="causcope",
        environment="production",
        network_domain="local.prod",
    )

    assert pgbot_instance == "provider.pgbot.causcope-prod"
    provider_types = {item["id"]: item for item in topology["provider_types"]}
    assert provider_types["provider_type.rails.active_record_pool"] == {
        "id": "provider_type.rails.active_record_pool",
        "instrument": "rails_runtime_evidence",
        "provider_id": "provider.rails.active_record_pool",
        "runner_capabilities": ["local_file_read"],
    }

    rails_instances = [
        item
        for item in topology["provider_instances"]
        if item["provider_type"] == "provider_type.rails.active_record_pool"
    ]
    assert rails_instances == [
        {
            "id": "provider.rails_pool.rails-connection-pool-app-prod",
            "provider_type": "provider_type.rails.active_record_pool",
            "target": "db.causcope.prod",
            "runner": "runner.local.prod",
        }
    ]
    runner = topology["runners"][0]
    assert "local_file_read" in runner["capabilities"]

    bindings = build_bindings(
        pgbot_instance,
        rails_provider_instance=rails_instances[0]["id"],
        database_url_env="DATABASE_URL",
        timeout_seconds=30,
    )
    rails_binding = next(
        item for item in bindings["bindings"] if item["driver"] == "rails_pool_file"
    )
    assert rails_binding == {
        "provider_instance": "provider.rails_pool.rails-connection-pool-app-prod",
        "driver": "rails_pool_file",
        "pool_evidence": "resource-pool-runtime-evidence.json",
        "runtime_evidence": "runtime-evidence.json",
        "diagnosis": "diagnosis.json",
    }

    demo = (ROOT / "scripts" / "demo_canonical_rails_pool.sh").read_text(encoding="utf-8")
    assert "runtime import-pool" not in demo
    assert "--acquire" in demo
    assert "--require-confirmed" in demo
    acquire_position = demo.index("--acquire")
    confirmed_position = demo.index("--require-confirmed")
    assert abs(acquire_position - confirmed_position) < 300

    print("canonical Rails autonomous acquisition contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

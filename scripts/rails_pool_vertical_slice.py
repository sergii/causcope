#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from xray_engine import project

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "xray" / "profiles" / "d3-1-concrete-connection-pool.yaml"
CONFIRMED = "CAUSAL_DIAGNOSIS_CONFIRMED"


def load_document(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    document = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    if not isinstance(document, dict):
        raise ValueError(f"expected object in {path}")
    return document


def last_bindings(projection: dict[str, Any]) -> dict[str, Any]:
    for stage in reversed(projection["stages"]):
        bindings = stage.get("bindings") or []
        if stage["state"] == "reached" and bindings:
            return bindings[0]
    return {}


def build_summary(
    problem: str,
    static: dict[str, Any],
    runtime: dict[str, Any],
    pool: dict[str, Any],
) -> dict[str, Any]:
    profile = load_document(PROFILE)
    xray = project(profile, {"static": static, "runtime": runtime, "pool": pool})
    bindings = last_bindings(xray)
    assertions = pool["assertions"]
    confirmed = xray["epistemic_state"] == CONFIRMED

    rejected: list[str] = []
    if assertions.get("query_latency_stayed_near_baseline"):
        rejected.append("slow SQL execution as the primary explanation")
    if assertions.get("database_still_accepts_direct_connections"):
        rejected.append("PostgreSQL-wide connection admission exhaustion")

    evidence = [
        f"exact request {pool['request']['code_symbol']} used {pool['pool']['id']}",
        f"application pool was at capacity ({pool['pool']['busy']}/{pool['pool']['observed_capacity']} busy)",
        f"checkout wait was {pool['request']['checkout_wait_ms']:.1f} ms during the affected request",
    ]
    if assertions.get("query_latency_stayed_near_baseline"):
        evidence.append("database query latency stayed near baseline")
    if assertions.get("database_still_accepts_direct_connections"):
        evidence.append("an independent PostgreSQL connection remained reachable")
    if assertions.get("recovery_checkout_wait_returned_to_baseline") and assertions.get(
        "recovery_request_latency_returned_to_baseline"
    ):
        evidence.append("checkout wait and request latency recovered after the pool slot was released")

    return {
        "problem": problem,
        "status": "confirmed" if confirmed else "not_confirmed",
        "epistemic_state": xray["epistemic_state"],
        "root_cause": (
            "application-side database connection pool exhaustion" if confirmed else None
        ),
        "hypothesis": xray["hypothesis"],
        "catalog_code": xray["catalog_code"],
        "system_id": xray["system_id"],
        "revision": xray["revision"],
        "incident_id": xray["incident_id"],
        "code_symbol": bindings.get("code_symbol", pool["request"]["code_symbol"]),
        "resource_pool": bindings.get("pool_id", pool["pool"]["id"]),
        "technology": bindings.get("pool_technology", pool["pool"]["technology"]),
        "evidence": evidence,
        "rejected_nearby_explanations": rejected,
        "blast_radius": "not established by this bounded slice",
        "verification": (
            "pool checkout wait and request latency returned to baseline after capacity was released"
            if confirmed
            else "causal verification is incomplete"
        ),
        "xray": xray,
    }


def render(summary: dict[str, Any]) -> str:
    lines = [
        "Causcope diagnosis",
        "",
        "Problem",
        f"  {summary['problem']}",
        "",
        "Status",
        f"  {summary['status'].upper()} ({summary['epistemic_state']})",
        "",
        "Root cause",
        f"  {summary['root_cause'] or 'Not established'}",
        f"  {summary['catalog_code']} / {summary['hypothesis']}",
        "",
        "Concrete scope",
        f"  system: {summary['system_id']}",
        f"  code: {summary['code_symbol']}",
        f"  pool: {summary['resource_pool']} ({summary['technology']})",
        "",
        "Evidence",
    ]
    lines.extend(f"  + {item}" for item in summary["evidence"])
    lines.extend(["", "Rejected nearby explanations"])
    if summary["rejected_nearby_explanations"]:
        lines.extend(f"  - {item}" for item in summary["rejected_nearby_explanations"])
    else:
        lines.append("  - none established")
    lines.extend(
        [
            "",
            "Blast radius",
            f"  {summary['blast_radius']}",
            "",
            "Verification",
            f"  {summary['verification']}",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render the Rails/ActiveRecord connection-pool golden vertical slice."
    )
    parser.add_argument("--static", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--pool", required=True, type=Path)
    parser.add_argument("--problem", default="request is slow")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-confirmed", action="store_true")
    args = parser.parse_args()

    try:
        summary = build_summary(
            args.problem,
            load_document(args.static),
            load_document(args.runtime),
            load_document(args.pool),
        )
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SystemExit(str(exc)) from exc

    if args.require_confirmed and summary["status"] != "confirmed":
        raise SystemExit(f"diagnosis not confirmed: {summary['epistemic_state']}")

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(render(summary), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

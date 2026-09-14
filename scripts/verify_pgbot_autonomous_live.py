#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
from datetime import timedelta
from pathlib import Path

from autonomous_investigation import run_autonomous_read_only_loop
from causal_projection import ROOT, load_concepts, load_edges
from instrument_router import InstrumentRouter
from live_diagnosis import build_diagnosis_snapshot, normalize_scope, scope_key
from pgbot_adapter import load_adapter, load_context
from pgbot_autonomous_provider import (
    PGBOT_PROVIDER_ID,
    PgbotAutonomousProbeProvider,
    file_context_supplier,
)
from probe_executor_runtime import build_probe_execution_capabilities
from runtime_evidence import format_timestamp, parse_timestamp

DEFAULT_ADAPTER = ROOT / "examples" / "adapters" / "pgbot" / "postgresql.yaml"
TARGET = "observation.http.request_failure"
LOCK_OBSERVATION = "observation.database.lock_wait_time"
LOCK_PROBE = "probe.database.inspect_lock_waits"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the autonomous Causcope loop over a real pgbot PostgreSQL report."
    )
    parser.add_argument("--pgbot-report", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--incident-id", default="incident.ci.pgbot-live-autonomous")
    parser.add_argument("--pretty", action="store_true")
    return parser


def diagnosis_for(snapshot: dict, *, target: str, scope: dict, concepts: dict) -> dict:
    wanted = scope_key(normalize_scope(scope, concepts))
    matches = [
        diagnosis
        for partition in snapshot["partitions"]
        if scope_key(partition.get("scope")) == wanted
        for diagnosis in partition["diagnoses"]
        if diagnosis["target"] == target
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one diagnosis for {target}, got {len(matches)}")
    return matches[0]


def main() -> int:
    args = build_parser().parse_args()
    concepts = load_concepts(ROOT)
    edges = load_edges(ROOT)
    adapter = load_adapter(args.adapter)
    context = load_context(args.pgbot_report)
    collected_at = parse_timestamp(context["collected_at"], "pgbot.collected_at")
    as_of = collected_at + timedelta(seconds=1)

    provider = PgbotAutonomousProbeProvider(
        adapter=adapter,
        concepts=concepts,
        incident_id=args.incident_id,
        context_supplier=file_context_supplier(args.pgbot_report),
        source_uri="pgbot://live-postgresql-ci",
    )
    scope = copy.deepcopy(provider.adapter_scope)
    router = InstrumentRouter(
        concepts=concepts,
        host_capabilities=build_probe_execution_capabilities(concepts),
        providers=[provider],
    )
    route = router.route(LOCK_PROBE, scope, execution_requirement="direct")
    selection = route["selection"]
    if selection is None:
        raise RuntimeError(f"instrument router did not select a live lock instrument: {route}")
    if selection["instrument"]["id"] != PGBOT_PROVIDER_ID:
        raise RuntimeError(
            f"expected router to select {PGBOT_PROVIDER_ID}, got {selection['instrument']['id']}"
        )

    initial_evidence = {
        "schema_version": "0.1",
        "kind": "runtime_evidence",
        "incident_id": args.incident_id,
        "description": "Synthetic incident symptom only; diagnostic evidence must come from the real pgbot report.",
        "instances": [
            {
                "id": "evidence.ci.request-failure",
                "observation": TARGET,
                "state": "observed",
                "observed_at": format_timestamp(collected_at),
                "confidence": "high",
                "source": {"type": "manual", "name": "ci-incident-symptom"},
                "scope": scope,
            }
        ],
    }
    initial_snapshot = build_diagnosis_snapshot(
        initial_evidence,
        concepts,
        edges,
        as_of=as_of,
        evidence_revision=1,
    )

    def clock():
        return as_of

    final_evidence, final_snapshot, report = run_autonomous_read_only_loop(
        evidence=initial_evidence,
        snapshot=initial_snapshot,
        concepts=concepts,
        edges=edges,
        supported_probe_ids=router.autonomous_probe_ids,
        execute_probe=router.execute,
        max_steps=4,
        clock=clock,
    )

    completed = [step for step in report["steps"] if step["status"] == "completed"]
    if not any(step["probe_id"] == LOCK_PROBE for step in completed):
        raise RuntimeError(f"autonomous loop did not complete {LOCK_PROBE}: {report}")

    lock_instances = [
        instance
        for instance in final_evidence["instances"]
        if instance["observation"] == LOCK_OBSERVATION
        and instance.get("labels", {}).get("provider") == PGBOT_PROVIDER_ID
    ]
    if len(lock_instances) != 1:
        raise RuntimeError(
            f"expected one pgbot autonomous {LOCK_OBSERVATION} instance, got {len(lock_instances)}"
        )
    lock_instance = lock_instances[0]
    if lock_instance["source"]["type"] != "probe" or lock_instance["source"]["name"] != LOCK_PROBE:
        raise RuntimeError("live pgbot evidence did not preserve canonical probe provenance")
    if lock_instance["labels"].get("source_finding") != "wait_lock_contention":
        raise RuntimeError("live pgbot evidence lost wait_lock_contention source identity")
    if lock_instance["labels"].get("instrument") != PGBOT_PROVIDER_ID:
        raise RuntimeError("live pgbot evidence did not preserve router instrument identity")
    routing_attributes = lock_instance["source"].get("attributes", {})
    if routing_attributes.get("routing.instrument_id") != PGBOT_PROVIDER_ID:
        raise RuntimeError("live pgbot evidence lost instrument routing provenance")

    diagnosis = diagnosis_for(
        final_snapshot,
        target=TARGET,
        scope=scope,
        concepts=concepts,
    )
    top = diagnosis["ranking"]["candidates"][0]["source"]["id"]
    if top != "hypothesis.database.lock_contention":
        raise RuntimeError(f"expected database lock contention to rank first, got {top}")

    output = {
        "incident_id": args.incident_id,
        "initial_target": TARGET,
        "provider": PGBOT_PROVIDER_ID,
        "selected_instrument": selection["instrument"],
        "route_selection_policy": route["selection_policy"],
        "completed_probes": [step["probe_id"] for step in completed],
        "source_finding": lock_instance["labels"]["source_finding"],
        "new_observation": lock_instance["observation"],
        "final_top_hypothesis": top,
        "initial_evidence_revision": report["initial_evidence_revision"],
        "final_evidence_revision": report["final_evidence_revision"],
        "stop_reason": report["stop_reason"],
        "scope": scope,
    }
    print(json.dumps(output, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

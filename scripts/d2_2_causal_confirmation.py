#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import jsonschema

from concrete_system_facts import load_document as load_static_document
from otel_concrete_runtime_facts import load_json, validate_runtime_document

ROOT = Path(__file__).resolve().parents[1]
CORRELATION_SCHEMA = ROOT / "schema" / "concrete-database-deadlock-evidence.schema.json"


def validate_correlation(document: dict[str, Any]) -> None:
    schema = load_json(CORRELATION_SCHEMA)
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        rendered = []
        for error in errors:
            path = ".".join(str(part) for part in error.path) or "<root>"
            rendered.append(f"{path}: {error.message}")
        raise ValueError("concrete database correlation validation failed:\n" + "\n".join(rendered))


def require_same_identity(
    static: dict[str, Any],
    runtime: dict[str, Any],
    database_projection: dict[str, Any],
    correlation: dict[str, Any],
) -> None:
    expected_system = static["system_id"]
    expected_revision = static["revision"]
    expected_incident = runtime["incident_id"]
    for label, document in (
        ("runtime", runtime),
        ("database projection", database_projection),
        ("database correlation", correlation),
    ):
        if document.get("system_id") != expected_system:
            raise ValueError(f"{label} belongs to a different concrete system")
        if document.get("revision") != expected_revision:
            raise ValueError(f"{label} belongs to a different concrete-system revision")
        if document.get("incident_id") != expected_incident:
            raise ValueError(f"{label} belongs to a different incident")


def runtime_bindings(runtime: dict[str, Any], correlation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    executions = {execution["id"]: execution for execution in runtime["executions"]}
    result: dict[str, dict[str, Any]] = {}
    for participant in correlation["participants"]:
        execution = executions.get(participant["execution_id"])
        if execution is None:
            raise ValueError(f"database participant references unknown concrete execution: {participant['execution_id']}")
        for field in ("trace_id", "span_id", "code_symbol"):
            if participant[field] != execution[field]:
                raise ValueError(
                    f"database participant {field} does not match exact OTel execution {execution['id']}"
                )
        if participant["code_symbol"] in result:
            raise ValueError(f"duplicate correlated participant for code symbol: {participant['code_symbol']}")
        result[participant["code_symbol"]] = participant
    return result


def matching_precondition(
    static: dict[str, Any],
    database_projection: dict[str, Any],
    participants: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    facts = {fact["id"]: fact for fact in static["facts"]}
    participant_symbols = set(participants)
    matches = database_projection["structural_preconditions"]["matches"]
    candidates = []
    for precondition in matches:
        symbols = {precondition["left"]["code_path"], precondition["right"]["code_path"]}
        if symbols == participant_symbols:
            candidates.append(precondition)
    if len(candidates) != 1:
        raise ValueError(f"expected exactly one structural precondition for correlated code paths, got {len(candidates)}")

    precondition = candidates[0]
    for side in ("left", "right"):
        binding = precondition[side]
        participant = participants[binding["code_path"]]
        if participant["transaction"] != binding["transaction"]:
            raise ValueError("database participant transaction does not match static concrete transaction")
        fact = facts.get(binding["fact"])
        if fact is None:
            raise ValueError(f"static precondition references unknown fact: {binding['fact']}")
        expected_order = [fact["subject"], fact["object"]]
        if participant["resource_order"] != expected_order:
            raise ValueError("database participant resource order does not match revision-pinned static precondition")
    return precondition


def verify_wait_cycle(
    correlation: dict[str, Any], participants: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    by_pid = {participant["backend_pid"]: participant for participant in participants.values()}
    if len(by_pid) != 2:
        raise ValueError("causal confirmation requires exactly two distinct PostgreSQL backends")
    pids = set(by_pid)
    directed_pairs: set[tuple[int, int]] = set()
    for edge in correlation["wait_edges"]:
        waiter_pid = edge["waiter_backend_pid"]
        blocker_pid = edge["blocker_backend_pid"]
        if waiter_pid not in pids or blocker_pid not in pids or waiter_pid == blocker_pid:
            raise ValueError("wait edge escapes the exact correlated participant set")
        waiter = by_pid[waiter_pid]
        blocker = by_pid[blocker_pid]
        if edge["waiter_execution_id"] != waiter["execution_id"]:
            raise ValueError("wait edge waiter execution does not match correlated backend")
        if edge["blocker_execution_id"] != blocker["execution_id"]:
            raise ValueError("wait edge blocker execution does not match correlated backend")
        if edge["waiting_on_resource"] != waiter["resource_order"][1]:
            raise ValueError("wait edge resource does not match the participant's second ordered resource")
        directed_pairs.add((waiter_pid, blocker_pid))

    left, right = sorted(pids)
    expected = {(left, right), (right, left)}
    if not expected.issubset(directed_pairs):
        raise ValueError("correlated PostgreSQL evidence does not contain a mutual two-backend wait-for cycle")
    return sorted(correlation["wait_edges"], key=lambda item: (item["waiter_backend_pid"], item["blocker_backend_pid"]))


def verify_deadlock_event(correlation: dict[str, Any], participants: dict[str, dict[str, Any]]) -> dict[str, Any]:
    event = correlation["deadlock_event"]
    if event["state"] != "observed" or event["sqlstate"] != "40P01":
        raise ValueError("causal confirmation requires an observed PostgreSQL SQLSTATE 40P01 event")
    victim = None
    for participant in participants.values():
        if participant["backend_pid"] == event["victim_backend_pid"]:
            victim = participant
            break
    if victim is None:
        raise ValueError("deadlock victim is not one of the correlated PostgreSQL participants")
    if victim["execution_id"] != event["victim_execution_id"]:
        raise ValueError("deadlock victim execution does not match correlated backend identity")
    if victim["outcome"] != "deadlock_aborted" or victim.get("sqlstate") != "40P01":
        raise ValueError("deadlock victim outcome does not preserve PostgreSQL 40P01")
    return victim


def project(
    static: dict[str, Any],
    runtime: dict[str, Any],
    database_projection: dict[str, Any],
    correlation: dict[str, Any],
) -> dict[str, Any]:
    validate_runtime_document(runtime)
    validate_correlation(correlation)
    if database_projection.get("kind") != "d2_2_database_evidence_projection":
        raise ValueError("database projection must be a d2_2_database_evidence_projection")
    if database_projection.get("catalog_code") != "D2.2":
        raise ValueError("database projection must describe D2.2")
    if database_projection.get("deadlock_event", {}).get("state") != "observed":
        raise ValueError("causal confirmation requires canonical deadlock-event evidence")
    if database_projection.get("epistemic_state") != "EVENT_OBSERVED":
        raise ValueError("causal confirmation requires the EVENT_OBSERVED database stage")

    require_same_identity(static, runtime, database_projection, correlation)
    participants = runtime_bindings(runtime, correlation)
    precondition = matching_precondition(static, database_projection, participants)
    wait_edges = verify_wait_cycle(correlation, participants)
    victim = verify_deadlock_event(correlation, participants)

    ordered_participants = sorted(participants.values(), key=lambda item: item["code_symbol"])
    return {
        "schema_version": "0.1",
        "kind": "d2_2_causal_confirmation",
        "catalog_code": "D2.2",
        "hypothesis": "hypothesis.database.deadlock",
        "system_id": static["system_id"],
        "revision": static["revision"],
        "incident_id": runtime["incident_id"],
        "epistemic_state": "CAUSAL_DIAGNOSIS_CONFIRMED",
        "causal_diagnosis": {
            "state": "confirmed",
            "mechanism": "postgresql_mutual_wait_for_cycle",
            "reason": (
                "The exact revision-bound OTel executions matching the D2.2 static precondition were "
                "correlated to two PostgreSQL backends that mutually blocked each other, and PostgreSQL "
                "aborted one of those exact participants with SQLSTATE 40P01."
            ),
        },
        "binding": {
            "structural_precondition": precondition,
            "participants": ordered_participants,
            "wait_edges": wait_edges,
            "victim_execution_id": victim["execution_id"],
        },
        "evidence_progression": [
            "PRECONDITIONS_PRESENT",
            "RISK_DETECTED",
            "CONTENTION_OBSERVED",
            "EVENT_OBSERVED",
            "CAUSAL_DIAGNOSIS_CONFIRMED",
        ],
        "limitations": [
            "Confirmation is scoped to this incident, concrete revision, exact correlated OTel executions, and observed PostgreSQL wait-for cycle.",
            "The Rails resource-order facts remain deterministic static inferences; causal confirmation proves the exact executions formed the database deadlock cycle, not every internal PostgreSQL lock mode or lock object.",
            "Production use requires a trustworthy trace/span-to-database-session correlation channel equivalent to the explicit application_name binding used by the live proof.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Confirm D2.2 causal diagnosis only when a PostgreSQL wait-for cycle is exactly correlated to the concrete OTel executions and static precondition.")
    parser.add_argument("--static-facts", required=True, type=Path)
    parser.add_argument("--runtime-facts", required=True, type=Path)
    parser.add_argument("--database-projection", required=True, type=Path)
    parser.add_argument("--correlation-evidence", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        static = load_static_document(args.static_facts)
        runtime = load_json(args.runtime_facts)
        database_projection = load_json(args.database_projection)
        correlation = load_json(args.correlation_evidence)
        output = project(static, runtime, database_projection, correlation)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    rendered = json.dumps(output, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

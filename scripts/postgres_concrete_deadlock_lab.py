#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema
import psycopg
from psycopg import errors, sql

from causal_projection import load_concepts
from concrete_system_facts import load_document as load_static_document
from d2_2_xray_projection import project as project_xray
from otel_concrete_runtime_facts import load_json, validate_runtime_document
from runtime_evidence import validate_runtime_references

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "concrete-database-deadlock-evidence.schema.json"
RESOURCE_RE = re.compile(r"^db:public\.([A-Za-z_][A-Za-z0-9_]*)$")
APPLICATION_NAME_RE = re.compile(r"^cs:([0-9a-fA-F]+):([0-9a-fA-F]+)$")
DATABASE_BOUNDARY = "boundary.application.database"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def resource_table(resource_id: str) -> str:
    match = RESOURCE_RE.fullmatch(resource_id)
    if match is None:
        raise ValueError(f"unsupported concrete database resource id: {resource_id}")
    return match.group(1)


def load_schema() -> dict[str, Any]:
    return load_json(SCHEMA_PATH)


def validate_correlation_document(document: dict[str, Any]) -> None:
    validator = jsonschema.Draft202012Validator(
        load_schema(),
        format_checker=jsonschema.FormatChecker(),
    )
    errors_found = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors_found:
        rendered = []
        for error in errors_found:
            path = ".".join(str(part) for part in error.path) or "<root>"
            rendered.append(f"{path}: {error.message}")
        raise ValueError("concrete database evidence validation failed:\n" + "\n".join(rendered))


def matching_pair(static: dict[str, Any], runtime: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    xray = project_xray(static, runtime)
    matches = xray["runtime_concurrency"]["matches"]
    if len(matches) != 1:
        raise ValueError(f"live lab requires exactly one runtime-matched D2.2 precondition, got {len(matches)}")
    item = matches[0]
    overlaps = item["matching_overlaps"]
    if len(overlaps) != 1:
        raise ValueError(f"live lab requires exactly one matching overlap, got {len(overlaps)}")
    return item["precondition"], overlaps[0]


def execution_for_symbol(runtime: dict[str, Any], overlap: dict[str, Any], symbol: str) -> dict[str, Any]:
    executions = {item["id"]: item for item in runtime["executions"]}
    if overlap["left_code_symbol"] == symbol:
        execution_id = overlap["left_execution"]
    elif overlap["right_code_symbol"] == symbol:
        execution_id = overlap["right_execution"]
    else:
        raise ValueError(f"runtime overlap does not contain concrete code symbol: {symbol}")
    return executions[execution_id]


def participant_specs(static: dict[str, Any], runtime: dict[str, Any]) -> list[dict[str, Any]]:
    precondition, overlap = matching_pair(static, runtime)
    facts = {fact["id"]: fact for fact in static["facts"]}
    specs: list[dict[str, Any]] = []
    for side in ("left", "right"):
        binding = precondition[side]
        fact = facts[binding["fact"]]
        execution = execution_for_symbol(runtime, overlap, binding["code_path"])
        resources = [fact["subject"], fact["object"]]
        for resource in resources:
            resource_table(resource)
        specs.append(
            {
                "code_symbol": binding["code_path"],
                "transaction": binding["transaction"],
                "resource_order": resources,
                "execution": execution,
            }
        )
    return specs


def application_name(execution: dict[str, Any]) -> str:
    value = f"cs:{execution['trace_id']}:{execution['span_id']}"
    if len(value) > 63:
        raise ValueError("correlation application_name exceeds PostgreSQL's practical 63-byte limit")
    return value


def parse_application_name(value: str) -> tuple[str, str]:
    match = APPLICATION_NAME_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"unexpected correlation application_name: {value}")
    return match.group(1), match.group(2)


def setup_database(dsn: str, resources: list[str]) -> str:
    tables = sorted({resource_table(resource) for resource in resources})
    with psycopg.connect(dsn, autocommit=True) as conn:
        version = str(conn.execute("SHOW server_version").fetchone()[0])
        for table in reversed(tables):
            conn.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(table)))
        for table in tables:
            conn.execute(
                sql.SQL("CREATE TABLE {} (id integer PRIMARY KEY, value integer NOT NULL)").format(
                    sql.Identifier(table)
                )
            )
            conn.execute(
                sql.SQL("INSERT INTO {} (id, value) VALUES (1, 0)").format(sql.Identifier(table))
            )
    return version


def update_resource(conn: psycopg.Connection[Any], resource_id: str) -> None:
    table = resource_table(resource_id)
    conn.execute(
        sql.SQL("UPDATE {} SET value = value + 1 WHERE id = 1").format(sql.Identifier(table))
    )


def monitor_cycle(
    dsn: str,
    pids: list[int],
    participants_by_pid: dict[int, dict[str, Any]],
    *,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    with psycopg.connect(dsn, autocommit=True) as conn:
        while time.monotonic() < deadline:
            rows = conn.execute(
                """
                SELECT pid, application_name, wait_event_type, wait_event,
                       pg_blocking_pids(pid), query
                  FROM pg_stat_activity
                 WHERE pid IN (%s, %s)
                """,
                (pids[0], pids[1]),
            ).fetchall()
            by_pid = {int(row[0]): row for row in rows}
            if len(by_pid) == 2:
                left, right = pids
                left_blockers = {int(value) for value in by_pid[left][4]}
                right_blockers = {int(value) for value in by_pid[right][4]}
                if right in left_blockers and left in right_blockers:
                    edges: list[dict[str, Any]] = []
                    for waiter_pid, blocker_pid in ((left, right), (right, left)):
                        row = by_pid[waiter_pid]
                        participant = participants_by_pid[waiter_pid]
                        blocker = participants_by_pid[blocker_pid]
                        observed_trace_id, observed_span_id = parse_application_name(str(row[1]))
                        execution = participant["execution"]
                        if observed_trace_id != execution["trace_id"] or observed_span_id != execution["span_id"]:
                            raise ValueError("PostgreSQL application_name correlation does not match OTel execution")
                        edges.append(
                            {
                                "waiter_backend_pid": waiter_pid,
                                "blocker_backend_pid": blocker_pid,
                                "waiter_execution_id": execution["id"],
                                "blocker_execution_id": blocker["execution"]["id"],
                                "wait_event_type": str(row[2] or "unknown"),
                                "wait_event": str(row[3] or "unknown"),
                                "waiting_on_resource": participant["resource_order"][1],
                            }
                        )
                    return edges
            time.sleep(0.05)
    raise ValueError("failed to observe mutual PostgreSQL blocking before deadlock resolution")


def run_deadlock(dsn: str, specs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    release_second_write = threading.Barrier(3)
    pids_ready = threading.Event()
    lock = threading.Lock()
    participants_by_pid: dict[int, dict[str, Any]] = {}
    outcomes: dict[int, dict[str, Any]] = {}

    def worker(spec: dict[str, Any]) -> None:
        execution = spec["execution"]
        app_name = application_name(execution)
        pid: int | None = None
        conn = psycopg.connect(dsn, application_name=app_name)
        try:
            conn.execute("SET deadlock_timeout = '4s'")
            pid = int(conn.execute("SELECT pg_backend_pid()").fetchone()[0])
            update_resource(conn, spec["resource_order"][0])
            with lock:
                participants_by_pid[pid] = {**spec, "application_name": app_name, "backend_pid": pid}
                if len(participants_by_pid) == 2:
                    pids_ready.set()
            release_second_write.wait(timeout=5)
            update_resource(conn, spec["resource_order"][1])
            conn.commit()
            outcome = {"outcome": "committed", "sqlstate": None}
        except errors.DeadlockDetected as exc:
            conn.rollback()
            outcome = {"outcome": "deadlock_aborted", "sqlstate": exc.sqlstate}
        except Exception:
            conn.rollback()
            raise
        finally:
            if pid is not None:
                with lock:
                    outcomes[pid] = outcome
            conn.close()

    threads = [threading.Thread(target=worker, args=(spec,), daemon=True) for spec in specs]
    for thread in threads:
        thread.start()

    if not pids_ready.wait(timeout=5):
        raise ValueError("database participants did not acquire their first resources in time")

    with lock:
        pids = sorted(participants_by_pid)
    if len(pids) != 2:
        raise ValueError("expected exactly two database participants")

    release_second_write.wait(timeout=5)
    wait_edges = monitor_cycle(dsn, pids, participants_by_pid, timeout_seconds=3.0)

    for thread in threads:
        thread.join(timeout=10)
    if any(thread.is_alive() for thread in threads):
        raise ValueError("deadlock participant did not finish after PostgreSQL deadlock detection")

    with lock:
        if set(outcomes) != set(pids):
            raise ValueError("missing database participant outcome")
        participants = []
        for pid in pids:
            item = participants_by_pid[pid]
            execution = item["execution"]
            outcome = outcomes[pid]
            participants.append(
                {
                    "backend_pid": pid,
                    "application_name": item["application_name"],
                    "execution_id": execution["id"],
                    "trace_id": execution["trace_id"],
                    "span_id": execution["span_id"],
                    "code_symbol": item["code_symbol"],
                    "transaction": item["transaction"],
                    "resource_order": item["resource_order"],
                    "outcome": outcome["outcome"],
                    "sqlstate": outcome["sqlstate"],
                }
            )
    return participants, wait_edges


def stable_evidence_id(prefix: str, incident_id: str, execution_ids: list[str]) -> str:
    digest = hashlib.sha256(
        "\0".join([prefix, incident_id, *sorted(execution_ids)]).encode("utf-8")
    ).hexdigest()[:12]
    return f"evidence.postgresql.{prefix}.{digest}"


def build_runtime_evidence(correlation: dict[str, Any]) -> dict[str, Any]:
    execution_ids = [participant["execution_id"] for participant in correlation["participants"]]
    observed_at = correlation["observed_at"]
    incident_id = correlation["incident_id"]
    scope = {
        "boundaries": [DATABASE_BOUNDARY],
        "attributes": {"service": "checkout-api", "dependency": "postgresql"},
    }
    common_labels = {
        "correlated_executions": ",".join(sorted(execution_ids)),
        "correlation_kind": "concrete_postgresql_deadlock_cycle",
    }
    document = {
        "schema_version": "0.1",
        "kind": "runtime_evidence",
        "incident_id": incident_id,
        "description": "Canonical observations derived from a live PostgreSQL wait-for cycle correlated to exact concrete OTel executions.",
        "instances": [
            {
                "id": stable_evidence_id("lock_cycle", incident_id, execution_ids),
                "observation": "observation.database.lock_wait_time",
                "state": "observed",
                "observed_at": observed_at,
                "confidence": "high",
                "source": {
                    "type": "probe",
                    "name": "probe.database.inspect_lock_waits",
                    "attributes": {"postgresql.correlation": "pg_blocking_pids"},
                },
                "scope": scope,
                "measurement": {"value": 2, "unit": "wait_edges", "comparison": "present"},
                "labels": common_labels,
                "note": "A mutual two-backend wait-for cycle was observed before deadlock resolution.",
            },
            {
                "id": stable_evidence_id("deadlock_error", incident_id, execution_ids),
                "observation": "observation.database.deadlock_error",
                "state": "observed",
                "observed_at": observed_at,
                "confidence": "high",
                "source": {
                    "type": "probe",
                    "name": "probe.database.inspect_deadlock_errors",
                    "attributes": {"postgresql.sqlstate": "40P01"},
                },
                "scope": scope,
                "measurement": {"value": "40P01", "comparison": "present"},
                "labels": common_labels,
                "note": "One correlated PostgreSQL participant was aborted by the deadlock detector with SQLSTATE 40P01.",
            },
        ],
    }
    validate_runtime_references(document, load_concepts(ROOT))
    return document


def build_correlation(static: dict[str, Any], runtime: dict[str, Any], dsn: str) -> dict[str, Any]:
    validate_runtime_document(runtime)
    if static["system_id"] != runtime["system_id"] or static["revision"] != runtime["revision"]:
        raise ValueError("static and runtime concrete facts are not revision-aligned")

    specs = participant_specs(static, runtime)
    resources = [resource for spec in specs for resource in spec["resource_order"]]
    database_version = setup_database(dsn, resources)
    participants, wait_edges = run_deadlock(dsn, specs)

    victims = [participant for participant in participants if participant["outcome"] == "deadlock_aborted"]
    if len(victims) != 1 or victims[0]["sqlstate"] != "40P01":
        raise ValueError(f"expected exactly one PostgreSQL 40P01 victim, got: {victims}")
    committed = [participant for participant in participants if participant["outcome"] == "committed"]
    if len(committed) != 1:
        raise ValueError("expected the non-victim deadlock participant to commit")

    victim = victims[0]
    document = {
        "schema_version": "0.1",
        "kind": "concrete_database_deadlock_evidence",
        "system_id": static["system_id"],
        "revision": static["revision"],
        "incident_id": runtime["incident_id"],
        "observed_at": utc_now(),
        "participants": participants,
        "wait_edges": wait_edges,
        "cycle": {
            "state": "observed",
            "backend_pids": sorted(participant["backend_pid"] for participant in participants),
            "execution_ids": sorted(participant["execution_id"] for participant in participants),
        },
        "deadlock_event": {
            "state": "observed",
            "sqlstate": "40P01",
            "victim_backend_pid": victim["backend_pid"],
            "victim_execution_id": victim["execution_id"],
        },
        "source": {
            "type": "probe",
            "name": "postgresql_concrete_deadlock_correlation",
            "database_version": database_version,
        },
        "limitations": [
            "The live lab correlates PostgreSQL sessions to OTel executions through an explicit application_name trace/span binding.",
            "The observed mutual wait-for cycle proves the two correlated executions participated in the deadlock, but does not expose every internal PostgreSQL lock object or lock mode.",
            "Resource order is bound to the exact SQL operations issued by this controlled lab and to the revision-pinned static precondition; production instrumentation must provide an equivalent trustworthy correlation channel.",
        ],
    }
    validate_correlation_document(document)
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a live PostgreSQL D2.2 deadlock and correlate its wait-for cycle to exact OTel concrete executions.")
    parser.add_argument("--static-facts", required=True, type=Path)
    parser.add_argument("--runtime-facts", required=True, type=Path)
    parser.add_argument("--correlation-output", required=True, type=Path)
    parser.add_argument("--runtime-evidence-output", required=True, type=Path)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:55433/postgres"))
    args = parser.parse_args()

    try:
        static = load_static_document(args.static_facts)
        runtime = load_json(args.runtime_facts)
        correlation = build_correlation(static, runtime, args.database_url)
        runtime_evidence = build_runtime_evidence(correlation)
    except (OSError, ValueError, psycopg.Error) as exc:
        raise SystemExit(str(exc)) from exc

    args.correlation_output.write_text(json.dumps(correlation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.runtime_evidence_output.write_text(json.dumps(runtime_evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "participants": len(correlation["participants"]),
        "wait_edges": len(correlation["wait_edges"]),
        "sqlstate": correlation["deadlock_event"]["sqlstate"],
        "victim_execution_id": correlation["deadlock_event"]["victim_execution_id"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

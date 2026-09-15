#!/usr/bin/env python3

from __future__ import annotations

import os
import threading
import time

import psycopg

from postgresql_health_provider import collect_postgresql_health

DATABASE_URL = os.environ["POSTGRESQL_HEALTH_DATABASE_URL"]


def main() -> int:
    with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
        admin.execute("DROP TABLE IF EXISTS causcope_health_probe")
        admin.execute(
            "CREATE TABLE causcope_health_probe (id integer PRIMARY KEY, value integer) "
            "WITH (autovacuum_enabled=false, autovacuum_vacuum_threshold=0, autovacuum_vacuum_scale_factor=0)"
        )
        admin.execute("INSERT INTO causcope_health_probe VALUES (1, 0), (2, 0)")

    blocker = psycopg.connect(DATABASE_URL)
    waiter = psycopg.connect(DATABASE_URL)
    waiter_error: list[BaseException] = []
    try:
        blocker.execute("UPDATE causcope_health_probe SET value = value + 1 WHERE id = 1")
        time.sleep(1.1)

        def wait_on_lock() -> None:
            try:
                waiter.execute("UPDATE causcope_health_probe SET value = value + 1 WHERE id = 1")
            except BaseException as exc:  # pragma: no cover - surfaced below
                waiter_error.append(exc)

        thread = threading.Thread(target=wait_on_lock, daemon=True)
        thread.start()

        deadline = time.monotonic() + 10
        observed = None
        while time.monotonic() < deadline:
            observed = collect_postgresql_health(DATABASE_URL, long_transaction_seconds=1)
            if observed["blocking_chains"]:
                break
            time.sleep(0.1)
        if observed is None or not observed["blocking_chains"]:
            raise AssertionError("live PostgreSQL collector did not observe the blocking chain")
        if not observed["long_running_transactions"]:
            raise AssertionError("live PostgreSQL collector did not observe the long-running transaction")
        disabled = [
            table for table in observed["vacuum"]["tables"]
            if table["table"] == "causcope_health_probe" and not table["autovacuum_enabled"]
        ]
        if len(disabled) != 1:
            raise AssertionError("live PostgreSQL collector did not preserve per-table autovacuum disablement")
        serialized = repr(observed).lower()
        if "update causcope_health_probe" in serialized:
            raise AssertionError("collector leaked SQL text into the health snapshot")

        blocker.rollback()
        thread.join(timeout=5)
        if thread.is_alive():
            raise AssertionError("blocked transaction did not resume after blocker rollback")
        if waiter_error:
            raise waiter_error[0]
        waiter.rollback()
    finally:
        try:
            blocker.rollback()
        finally:
            blocker.close()
        try:
            waiter.rollback()
        finally:
            waiter.close()
        with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
            admin.execute("DROP TABLE IF EXISTS causcope_health_probe")

    print("live PostgreSQL blocking, transaction, and autovacuum health evidence verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", "/data/shop.db"))
LOCK_SECONDS = int(os.environ.get("LOCK_SECONDS", "120"))


def wait_for_database() -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if DB_PATH.exists():
            try:
                connection = sqlite3.connect(DB_PATH, timeout=0.2)
                connection.execute("SELECT 1 FROM scenario_lock LIMIT 1").fetchone()
                connection.close()
                return
            except sqlite3.Error:
                pass
        time.sleep(0.25)
    raise RuntimeError(f"database was not ready: {DB_PATH}")


def main() -> int:
    wait_for_database()
    connection = sqlite3.connect(DB_PATH, timeout=1)
    try:
        connection.execute("PRAGMA busy_timeout=1000")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE scenario_lock SET touched_at = CURRENT_TIMESTAMP WHERE id = 1"
        )
        print(
            f"scenario=sqlite-write-lock state=active seconds={LOCK_SECONDS}",
            flush=True,
        )
        time.sleep(LOCK_SECONDS)
        connection.rollback()
        print("scenario=sqlite-write-lock state=released", flush=True)
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())

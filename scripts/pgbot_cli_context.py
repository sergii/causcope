#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from runtime_evidence import parse_timestamp

PGBOT_EXECUTABLE = "pgbot"
PGBOT_REPORT_EXIT_CODES = {0, 1, 2}
DEFAULT_TIMEOUT_SECONDS = 30


def validate_pgbot_context_shape(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ValueError("pgbot JSON output must be an object")
    if not isinstance(document.get("schema_version"), str):
        raise ValueError("pgbot JSON output must include schema_version")
    if not isinstance(document.get("collected_at"), str):
        raise ValueError("pgbot JSON output must include collected_at")
    if not isinstance(document.get("findings"), list):
        raise ValueError("pgbot JSON output must include a findings array")
    parse_timestamp(document["collected_at"], "pgbot.collected_at")
    return document


@dataclass(frozen=True)
class PgbotCliContextSupplier:
    """Run only the deterministic `pgbot inspect --json` read surface."""

    database_url_env: str
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    def _executable(self) -> str | None:
        return shutil.which(PGBOT_EXECUTABLE)

    def availability(self, _adapter: dict[str, Any]) -> tuple[bool, str | None]:
        executable = self._executable()
        if executable is None:
            return False, "pgbot executable is not available on PATH"
        value = os.environ.get(self.database_url_env)
        if not isinstance(value, str) or not value:
            return False, f"required database URL environment variable is not set: {self.database_url_env}"
        return True, None

    def __call__(self) -> dict[str, Any]:
        executable = self._executable()
        if executable is None:
            raise ValueError("pgbot executable is not available on PATH")
        database_url = os.environ.get(self.database_url_env)
        if not isinstance(database_url, str) or not database_url:
            raise ValueError(
                f"required database URL environment variable is not set: {self.database_url_env}"
            )

        child_env = dict(os.environ)
        child_env["DATABASE_URL"] = database_url
        child_env.pop("PGBOT_DATABASE_URL", None)

        try:
            completed = subprocess.run(
                [executable, "inspect", "--json"],
                env=child_env,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError(
                f"pgbot inspect exceeded the configured {self.timeout_seconds}s timeout"
            ) from exc
        except OSError as exc:
            raise ValueError("pgbot inspect could not be started") from exc

        if completed.returncode not in PGBOT_REPORT_EXIT_CODES:
            raise ValueError(
                f"pgbot inspect failed with exit code {completed.returncode}; "
                "connection details and stderr are intentionally not included"
            )

        try:
            document = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("pgbot inspect did not return valid JSON") from exc
        return validate_pgbot_context_shape(document)

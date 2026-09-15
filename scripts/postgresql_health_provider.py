#!/usr/bin/env python3

from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from autonomous_investigation import ProbeInsufficientEvidence
from live_diagnosis import normalize_scope, scope_key

POSTGRESQL_HEALTH_PROVIDER_ID = "provider.postgresql.health"
POSTGRESQL_HEALTH_INSTRUMENT = "postgresql"
DEFAULT_LONG_TRANSACTION_SECONDS = 60
SUPPORTED_PROBES = {
    "probe.database.inspect_blocking_chains",
    "probe.database.inspect_long_running_transactions",
    "probe.database.inspect_vacuum_health",
}

HealthCollector = Callable[[], dict[str, Any]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_reloptions(options: Any) -> dict[str, str]:
    parsed: dict[str, str] = {}
    if not isinstance(options, list):
        return parsed
    for option in options:
        if not isinstance(option, str) or "=" not in option:
            continue
        key, value = option.split("=", 1)
        parsed[key] = value
    return parsed


def _bool_setting(value: Any) -> bool:
    return str(value).strip().lower() in {"on", "true", "yes", "1"}


def _blocking_chains(activity: list[dict[str, Any]]) -> list[list[int]]:
    edges: dict[int, list[int]] = {}
    for row in activity:
        pid = int(row["pid"])
        blockers = sorted({int(value) for value in (row.get("blocking_pids") or [])})
        if blockers:
            edges[pid] = blockers

    chains: set[tuple[int, ...]] = set()

    def walk(path: tuple[int, ...]) -> None:
        current = path[-1]
        blockers = edges.get(current, [])
        if not blockers:
            chains.add(path)
            return
        advanced = False
        for blocker in blockers:
            if blocker in path:
                chains.add(path + (blocker,))
                continue
            advanced = True
            walk(path + (blocker,))
        if not advanced and blockers:
            chains.add(path)

    for blocked_pid in sorted(edges):
        walk((blocked_pid,))

    # Keep maximal paths. A nested waiter should not duplicate the suffix of a
    # longer chain that already preserves the same dependency structure.
    maximal: list[tuple[int, ...]] = []
    for chain in sorted(chains, key=lambda item: (-len(item), item)):
        if any(len(chain) < len(other) and other[-len(chain) :] == chain for other in maximal):
            continue
        maximal.append(chain)
    return [list(chain) for chain in sorted(maximal)]


def _effective_float(options: dict[str, str], key: str, default: float) -> float:
    value = options.get(key)
    return default if value is None else float(value)


def _effective_bool(options: dict[str, str], key: str, default: bool) -> bool:
    value = options.get(key)
    return default if value is None else _bool_setting(value)


def collect_postgresql_health(
    database_url: str,
    *,
    long_transaction_seconds: int = DEFAULT_LONG_TRANSACTION_SECONDS,
) -> dict[str, Any]:
    if not database_url:
        raise ValueError("PostgreSQL health collection requires a database URL")
    if long_transaction_seconds < 1:
        raise ValueError("long transaction threshold must be at least one second")

    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise ValueError("psycopg is required for direct PostgreSQL health collection") from exc

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        identity = connection.execute(
            """
            SELECT current_database() AS database,
                   current_setting('autovacuum') AS autovacuum,
                   current_setting('autovacuum_vacuum_threshold') AS vacuum_threshold,
                   current_setting('autovacuum_vacuum_scale_factor') AS vacuum_scale_factor,
                   current_setting('autovacuum_vacuum_max_threshold', true) AS vacuum_max_threshold
            """
        ).fetchone()
        activity = connection.execute(
            """
            SELECT pid,
                   state,
                   backend_type,
                   wait_event_type,
                   pg_blocking_pids(pid) AS blocking_pids,
                   CASE WHEN xact_start IS NULL THEN NULL
                        ELSE EXTRACT(EPOCH FROM (clock_timestamp() - xact_start))
                   END AS xact_age_seconds
              FROM pg_stat_activity
             WHERE datname = current_database()
               AND pid <> pg_backend_pid()
            """
        ).fetchall()
        tables = connection.execute(
            """
            SELECT stats.schemaname,
                   stats.relname,
                   stats.n_dead_tup,
                   class.reltuples,
                   class.reloptions
              FROM pg_stat_user_tables AS stats
              JOIN pg_class AS class ON class.oid = stats.relid
             ORDER BY stats.schemaname, stats.relname
            """
        ).fetchall()

    activity_rows = [dict(row) for row in activity]
    long_transactions = []
    for row in activity_rows:
        age = row.get("xact_age_seconds")
        if row.get("backend_type") != "client backend" or age is None:
            continue
        age_seconds = float(age)
        if age_seconds >= long_transaction_seconds:
            long_transactions.append(
                {
                    "pid": int(row["pid"]),
                    "state": str(row.get("state") or "unknown"),
                    "age_seconds": age_seconds,
                }
            )
    long_transactions.sort(key=lambda row: (-row["age_seconds"], row["pid"]))

    global_autovacuum = _bool_setting(identity["autovacuum"])
    global_threshold = float(identity["vacuum_threshold"])
    global_scale = float(identity["vacuum_scale_factor"])
    max_setting = identity.get("vacuum_max_threshold")
    global_max = None if max_setting in (None, "", "-1") else float(max_setting)

    table_health: list[dict[str, Any]] = []
    for raw in tables:
        row = dict(raw)
        options = _parse_reloptions(row.get("reloptions"))
        enabled = global_autovacuum and _effective_bool(options, "autovacuum_enabled", True)
        threshold = _effective_float(options, "autovacuum_vacuum_threshold", global_threshold)
        scale = _effective_float(options, "autovacuum_vacuum_scale_factor", global_scale)
        reltuples = max(float(row.get("reltuples") or 0.0), 0.0)
        trigger = threshold + scale * reltuples
        table_max_value = options.get("autovacuum_vacuum_max_threshold")
        table_max = global_max if table_max_value is None else (
            None if table_max_value == "-1" else float(table_max_value)
        )
        if table_max is not None:
            trigger = min(trigger, table_max)
        dead_tuples = float(row.get("n_dead_tup") or 0.0)
        pressure_ratio = dead_tuples / trigger if trigger > 0 else (float("inf") if dead_tuples > 0 else 0.0)
        table_health.append(
            {
                "schema": str(row["schemaname"]),
                "table": str(row["relname"]),
                "dead_tuples": dead_tuples,
                "estimated_tuples": reltuples,
                "vacuum_trigger": trigger,
                "pressure_ratio": pressure_ratio,
                "autovacuum_enabled": enabled,
                "trigger_exceeded": dead_tuples > trigger,
            }
        )

    return {
        "collected_at": _utc_now(),
        "database": str(identity["database"]),
        "long_transaction_threshold_seconds": long_transaction_seconds,
        "blocking_chains": _blocking_chains(activity_rows),
        "long_running_transactions": long_transactions,
        "vacuum": {
            "autovacuum_enabled": global_autovacuum,
            "tables": table_health,
        },
    }


@dataclass(frozen=True)
class PostgresqlHealthCollector:
    database_url_env: str
    long_transaction_seconds: int = DEFAULT_LONG_TRANSACTION_SECONDS

    def availability(self) -> tuple[bool, str | None]:
        value = os.environ.get(self.database_url_env)
        if not isinstance(value, str) or not value:
            return False, f"required database URL environment variable is not set: {self.database_url_env}"
        try:
            import psycopg  # noqa: F401
        except ImportError:
            return False, "psycopg is not available"
        return True, None

    def __call__(self) -> dict[str, Any]:
        database_url = os.environ.get(self.database_url_env)
        if not isinstance(database_url, str) or not database_url:
            raise ValueError(
                f"required database URL environment variable is not set: {self.database_url_env}"
            )
        return collect_postgresql_health(
            database_url,
            long_transaction_seconds=self.long_transaction_seconds,
        )


class PostgresqlHealthAutonomousProvider:
    def __init__(
        self,
        *,
        concepts: dict[str, dict[str, Any]],
        incident_id: str,
        scope: dict[str, Any],
        target_resource: str,
        collector: HealthCollector,
        source_uri: str = "postgresql://health",
    ) -> None:
        if not incident_id:
            raise ValueError("PostgreSQL health provider requires incident_id")
        if not target_resource:
            raise ValueError("PostgreSQL health provider requires target_resource")
        self.concepts = concepts
        self.incident_id = incident_id
        self.scope = normalize_scope(scope, concepts)
        self.target_resource = target_resource
        self.collector = collector
        self.source_uri = source_uri
        for probe_id in SUPPORTED_PROBES:
            probe = concepts.get(probe_id)
            if not isinstance(probe, dict) or probe.get("kind") != "probe":
                raise ValueError(f"PostgreSQL health provider references unknown probe: {probe_id}")
            if probe.get("risk") != "read_only":
                raise ValueError(f"PostgreSQL health provider refuses non-read-only probe: {probe_id}")

    @property
    def supported_probe_ids(self) -> set[str]:
        return set(SUPPORTED_PROBES)

    def _availability(self) -> dict[str, str | None]:
        checker = getattr(self.collector, "availability", None)
        if not callable(checker):
            return {"state": "unknown", "reason": "collector has no non-invasive availability check"}
        available, reason = checker()
        return {"state": "available" if available else "unavailable", "reason": reason}

    def capability_projection(self) -> dict[str, Any]:
        probes = []
        for probe_id in sorted(SUPPORTED_PROBES):
            probe = self.concepts[probe_id]
            probes.append(
                {
                    "probe": {"id": probe_id, "title": probe.get("title", probe_id), "risk": "read_only"},
                    "requires": sorted(probe.get("requires", [])),
                    "mapped_observations": sorted(probe.get("produces", [])),
                }
            )
        return {
            "id": POSTGRESQL_HEALTH_PROVIDER_ID,
            "instrument": POSTGRESQL_HEALTH_INSTRUMENT,
            "transport": "postgresql_catalog",
            "scope_mode": "fixed_exact",
            "scope": copy.deepcopy(self.scope),
            "availability": self._availability(),
            "contract": {"name": "postgresql_catalog_health", "accepted_schema_versions": ["0.1"]},
            "evidence_semantics": {
                "complete_snapshot": True,
                "negative_result": "absent_evidence",
                "sql_text_collected": False,
                "causal_authority": False,
            },
            "probes": probes,
        }

    def _validate_scope(self, scope: dict[str, Any] | None) -> dict[str, Any]:
        normalized = normalize_scope(scope, self.concepts)
        if scope_key(normalized) != scope_key(self.scope):
            raise ProbeInsufficientEvidence(
                "PostgreSQL health provider scope does not match the selected diagnosis scope"
            )
        return normalized

    def _instance(
        self,
        *,
        probe_id: str,
        observation: str,
        state: str,
        collected_at: str,
        database: str,
        measurement: dict[str, Any],
        labels: dict[str, str],
        scope: dict[str, Any],
    ) -> dict[str, Any]:
        bound_scope = copy.deepcopy(scope)
        bound_scope.setdefault("attributes", {})["target_resource"] = self.target_resource
        source_attributes = {
            "provider": POSTGRESQL_HEALTH_PROVIDER_ID,
            "instrument": POSTGRESQL_HEALTH_INSTRUMENT,
            "database": database,
            "target_resource": self.target_resource,
        }
        return {
            "id": f"evidence.postgresql_health.{probe_id.rsplit('.', 1)[-1]}.{observation.rsplit('.', 1)[-1]}",
            "observation": observation,
            "state": state,
            "observed_at": collected_at,
            "confidence": "high",
            "source": {
                "type": "probe",
                "name": probe_id,
                "uri": self.source_uri,
                "attributes": source_attributes,
            },
            "scope": bound_scope,
            "measurement": measurement,
            "labels": {
                "probe": probe_id,
                "provider": POSTGRESQL_HEALTH_PROVIDER_ID,
                **labels,
            },
            "note": "Direct read-only PostgreSQL catalog evidence. Raw SQL text is intentionally not collected; this evidence is not causal authority.",
        }

    def execute(self, probe_id: str, target: str, scope: dict[str, Any] | None) -> dict[str, Any]:
        if probe_id not in SUPPORTED_PROBES:
            raise ValueError(f"unsupported PostgreSQL health probe: {probe_id}")
        normalized_scope = self._validate_scope(scope)
        snapshot = self.collector()
        collected_at = str(snapshot["collected_at"])
        database = str(snapshot["database"])
        instances: list[dict[str, Any]] = []

        if probe_id == "probe.database.inspect_blocking_chains":
            chains = snapshot.get("blocking_chains", [])
            max_depth = max((len(chain) - 1 for chain in chains), default=0)
            labels = {"chain_count": str(len(chains)), "max_depth": str(max_depth)}
            state = "observed" if chains else "absent"
            instances.append(self._instance(
                probe_id=probe_id,
                observation="observation.database.blocking_chain",
                state=state,
                collected_at=collected_at,
                database=database,
                measurement={"value": len(chains), "unit": "chains", "comparison": "present" if chains else "absent"},
                labels=labels,
                scope=normalized_scope,
            ))
            instances.append(self._instance(
                probe_id=probe_id,
                observation="observation.database.lock_wait_event",
                state=state,
                collected_at=collected_at,
                database=database,
                measurement={"value": len(chains), "unit": "blocked_sessions", "comparison": "present" if chains else "absent"},
                labels=labels,
                scope=normalized_scope,
            ))
        elif probe_id == "probe.database.inspect_long_running_transactions":
            transactions = snapshot.get("long_running_transactions", [])
            max_age = max((float(row["age_seconds"]) for row in transactions), default=0.0)
            threshold = int(snapshot["long_transaction_threshold_seconds"])
            instances.append(self._instance(
                probe_id=probe_id,
                observation="observation.database.long_running_transaction",
                state="observed" if transactions else "absent",
                collected_at=collected_at,
                database=database,
                measurement={"value": max_age, "baseline": threshold, "unit": "seconds", "comparison": "above_baseline" if transactions else "below_baseline"},
                labels={"transaction_count": str(len(transactions)), "threshold_seconds": str(threshold)},
                scope=normalized_scope,
            ))
        else:
            vacuum = snapshot.get("vacuum", {})
            tables = vacuum.get("tables", [])
            pressured = [row for row in tables if row.get("trigger_exceeded") is True]
            disabled = [row for row in tables if row.get("autovacuum_enabled") is False]
            max_ratio = max((float(row["pressure_ratio"]) for row in pressured), default=0.0)
            instances.append(self._instance(
                probe_id=probe_id,
                observation="observation.database.vacuum_pressure",
                state="observed" if pressured else "absent",
                collected_at=collected_at,
                database=database,
                measurement={"value": max_ratio, "baseline": 1.0, "unit": "trigger_ratio", "comparison": "above_baseline" if pressured else "below_baseline"},
                labels={"pressured_table_count": str(len(pressured)), "table_count": str(len(tables))},
                scope=normalized_scope,
            ))
            instances.append(self._instance(
                probe_id=probe_id,
                observation="observation.database.autovacuum_disabled",
                state="observed" if disabled else "absent",
                collected_at=collected_at,
                database=database,
                measurement={"value": len(disabled), "unit": "tables", "comparison": "present" if disabled else "absent"},
                labels={"disabled_table_count": str(len(disabled)), "global_autovacuum": "on" if vacuum.get("autovacuum_enabled") else "off"},
                scope=normalized_scope,
            ))

        return {
            "schema_version": "0.1",
            "kind": "runtime_evidence",
            "incident_id": self.incident_id,
            "description": f"Direct PostgreSQL health evidence for {probe_id} on {self.target_resource}.",
            "instances": instances,
        }

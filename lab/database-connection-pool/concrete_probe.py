import json
import os
import secrets
import statistics
import threading
import time
import urllib.request

import psycopg

APP_HOST = os.environ.get("APP_HOST", "app")
APP_PORT = int(os.environ.get("APP_PORT", "8080"))
BASE_URL = f"http://{APP_HOST}:{APP_PORT}"
DB_HOST = os.environ.get("DB_HOST", "db")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_USER = os.environ.get("DB_USER", "causcope")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "causcope")
DB_NAME = os.environ.get("DB_NAME", "causcope")
SYSTEM_ID = os.environ.get("CAUSCOPE_SYSTEM_ID", "database-connection-pool-app")
REVISION = os.environ.get("CAUSCOPE_REVISION", "fixture-revision")
REPOSITORY = os.environ.get("CAUSCOPE_REPOSITORY", "example://database-connection-pool-app")
INCIDENT_ID = os.environ.get("CAUSCOPE_INCIDENT_ID", "INC-D3-1-CONCRETE")
CODE_SYMBOL = os.environ.get("CAUSCOPE_CODE_SYMBOL", "code:Handler#do_GET()")
POOL_ID = os.environ.get("CAUSCOPE_POOL_ID", "pool:application_database")
POOL_CONFIG_NAME = os.environ.get("CAUSCOPE_POOL_CONFIG_NAME", "application_database")
DEPENDENCY_ID = os.environ.get("CAUSCOPE_DEPENDENCY_ID", "dependency:postgresql")
CONFIGURED_CAPACITY = int(os.environ.get("CAUSCOPE_POOL_CAPACITY", "1"))
HOLD_MS = int(os.environ.get("HOLD_MS", "500"))
BASELINE_SAMPLES = int(os.environ.get("BASELINE_SAMPLES", "3"))
RECOVERY_SAMPLES = int(os.environ.get("RECOVERY_SAMPLES", "3"))

CONNINFO = (
    f"host={DB_HOST} port={DB_PORT} user={DB_USER} "
    f"password={DB_PASSWORD} dbname={DB_NAME}"
)


def request_json(path, *, headers=None, timeout=10):
    request = urllib.request.Request(f"{BASE_URL}{path}", headers=headers or {})
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read())
    return payload, (time.monotonic() - started) * 1000.0


def work_sample(*, traced=False):
    headers = {}
    if traced:
        headers = {
            "X-Causcope-Trace-Id": secrets.token_hex(16),
            "X-Causcope-Span-Id": secrets.token_hex(8),
        }
    payload, external_ms = request_json("/work", headers=headers)
    result = {
        "checkout_wait_ms": float(payload["checkout_wait_ms"]),
        "dependency_latency_ms": float(payload["database_query_latency_ms"]),
        "request_latency_ms": float(payload["request_latency_ms"]),
        "external_request_latency_ms": external_ms,
        "dependency_backend_id": str(payload["database_backend_pid"]),
    }
    if traced:
        telemetry = payload.get("telemetry")
        if not isinstance(telemetry, dict):
            raise RuntimeError("traced /work request did not return telemetry binding")
        if telemetry.get("system_id") != SYSTEM_ID:
            raise RuntimeError("server telemetry system_id does not match requested system")
        if telemetry.get("revision") != REVISION:
            raise RuntimeError("server telemetry revision does not match requested revision")
        if telemetry.get("code_symbol") != CODE_SYMBOL:
            raise RuntimeError("server telemetry code symbol does not match expected symbol")
        for timestamp_key in (
            "start_time_unix_nano",
            "checkout_time_unix_nano",
            "end_time_unix_nano",
        ):
            if not str(telemetry.get(timestamp_key, "")).isdigit():
                raise RuntimeError(f"server telemetry lacks valid {timestamp_key}")
        result["telemetry"] = telemetry
    return result


def median_sample(samples):
    return {
        "checkout_wait_ms": statistics.median(item["checkout_wait_ms"] for item in samples),
        "request_latency_ms": statistics.median(item["request_latency_ms"] for item in samples),
        "dependency_latency_ms": statistics.median(item["dependency_latency_ms"] for item in samples),
    }


def wait_for_holder():
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        status, _ = request_json("/status")
        if status.get("holder_active"):
            return status
        time.sleep(0.005)
    raise RuntimeError("holder did not acquire the application pool connection")


def direct_database_control():
    started = time.monotonic()
    with psycopg.connect(CONNINFO, connect_timeout=5) as connection:
        query_started = time.monotonic()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1, pg_backend_pid()")
            _one, backend_pid = cursor.fetchone()
        query_latency_ms = (time.monotonic() - query_started) * 1000.0
    total_latency_ms = (time.monotonic() - started) * 1000.0
    return {
        "dependency_id": DEPENDENCY_ID,
        "reachable": True,
        "total_latency_ms": total_latency_ms,
        "query_latency_ms": query_latency_ms,
        "backend_id": str(backend_pid),
    }


def otlp_payload(telemetry, intervention):
    def attr(key, value):
        return {"key": key, "value": {"stringValue": str(value)}}

    checkout_event = {
        "timeUnixNano": telemetry["checkout_time_unix_nano"],
        "name": "causcope.pool.checkout",
        "attributes": [
            attr("causcope.pool_id", POOL_ID),
            attr("causcope.pool.technology", "psycopg_pool"),
            attr("causcope.pool.config_name", POOL_CONFIG_NAME),
            attr("causcope.pool.checkout_wait_ms", intervention["checkout_wait_ms"]),
        ],
    }

    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        attr("service.name", SYSTEM_ID),
                        attr("causcope.system_id", SYSTEM_ID),
                        attr("causcope.revision", REVISION),
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "causcope.connection_pool_fixture"},
                        "spans": [
                            {
                                "traceId": telemetry["trace_id"],
                                "spanId": telemetry["span_id"],
                                "name": "GET /work",
                                "startTimeUnixNano": telemetry["start_time_unix_nano"],
                                "endTimeUnixNano": telemetry["end_time_unix_nano"],
                                "attributes": [
                                    attr("causcope.code_symbol", CODE_SYMBOL),
                                ],
                                "events": [checkout_event],
                            }
                        ],
                    }
                ],
            }
        ]
    }


baseline_samples = [work_sample() for _ in range(BASELINE_SAMPLES)]
baseline = median_sample(baseline_samples)

holder_error = []


def hold_connection():
    try:
        request_json(f"/hold?ms={HOLD_MS}", timeout=10)
    except Exception as exc:
        holder_error.append(repr(exc))


holder = threading.Thread(target=hold_connection)
holder.start()
status = wait_for_holder()
dependency_control = direct_database_control()
intervention = work_sample(traced=True)
holder.join(timeout=10)
if holder.is_alive():
    raise RuntimeError("holder request did not finish")
if holder_error:
    raise RuntimeError(holder_error[0])

recovery_samples = [work_sample() for _ in range(RECOVERY_SAMPLES)]
recovery = median_sample(recovery_samples)

wait_delta = intervention["checkout_wait_ms"] - baseline["checkout_wait_ms"]
request_delta = intervention["request_latency_ms"] - baseline["request_latency_ms"]
query_delta = intervention["dependency_latency_ms"] - baseline["dependency_latency_ms"]
explanation_error = abs(request_delta - wait_delta)
recovery_wait_delta = abs(recovery["checkout_wait_ms"] - baseline["checkout_wait_ms"])
recovery_request_delta = abs(recovery["request_latency_ms"] - baseline["request_latency_ms"])

thresholds = {
    "min_pool_wait_delta_ms": 180.0,
    "min_request_delta_ms": 180.0,
    "max_query_delta_ms": 25.0,
    "max_wait_explanation_error_ms": 50.0,
    "max_direct_database_total_ms": 150.0,
    "max_recovery_wait_delta_ms": 25.0,
    "max_recovery_request_delta_ms": 50.0,
}

assertions = {
    "application_pool_was_at_capacity": int(status["pool_busy"]) == int(status["pool_capacity"]),
    "pool_checkout_wait_increased": wait_delta >= thresholds["min_pool_wait_delta_ms"],
    "request_latency_increased": request_delta >= thresholds["min_request_delta_ms"],
    "query_latency_stayed_near_baseline": abs(query_delta) <= thresholds["max_query_delta_ms"],
    "database_still_accepts_direct_connections": (
        dependency_control["reachable"]
        and dependency_control["total_latency_ms"] <= thresholds["max_direct_database_total_ms"]
    ),
    "checkout_wait_explains_request_delta": explanation_error <= thresholds["max_wait_explanation_error_ms"],
    "recovery_checkout_wait_returned_to_baseline": recovery_wait_delta <= thresholds["max_recovery_wait_delta_ms"],
    "recovery_request_latency_returned_to_baseline": recovery_request_delta <= thresholds["max_recovery_request_delta_ms"],
}

telemetry = intervention["telemetry"]
evidence = {
    "schema_version": "0.1",
    "kind": "resource_pool_runtime_evidence",
    "system_id": SYSTEM_ID,
    "revision": {
        "type": "git",
        "value": REVISION,
        "repository": REPOSITORY,
    },
    "incident_id": INCIDENT_ID,
    "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "pool": {
        "id": POOL_ID,
        "technology": "psycopg_pool",
        "configured_capacity": CONFIGURED_CAPACITY,
        "observed_capacity": int(status["pool_capacity"]),
        "busy": int(status["pool_busy"]),
        "utilization": float(status["pool_utilization"]),
    },
    "request": {
        "code_symbol": CODE_SYMBOL,
        "trace_id": telemetry["trace_id"],
        "span_id": telemetry["span_id"],
        "checkout_wait_ms": intervention["checkout_wait_ms"],
        "request_latency_ms": intervention["request_latency_ms"],
        "dependency_latency_ms": intervention["dependency_latency_ms"],
        "dependency_backend_id": intervention["dependency_backend_id"],
    },
    "dependency_control": dependency_control,
    "baseline": baseline,
    "recovery": recovery,
    "assertions": assertions,
    "source": {
        "type": "probe",
        "name": "connection_pool_concrete_probe",
        "uri": "live:database-connection-pool",
    },
    "limitations": [
        "The fixture uses a pool capacity of one to make resource contention deterministic.",
        "The request trace proves execution of the instrumented handler but does not by itself prove why checkout waited.",
        "The direct PostgreSQL control distinguishes application-pool saturation from database-wide connection admission exhaustion only for the measured window.",
    ],
}

print(
    json.dumps(
        {"evidence": evidence, "otlp": otlp_payload(telemetry, intervention)},
        sort_keys=True,
    )
)

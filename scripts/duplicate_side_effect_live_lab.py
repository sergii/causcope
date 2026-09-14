#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import jsonschema

from causal_projection import load_concepts
from concrete_system_facts import load_document
from duplicate_side_effect_xray_projection import project as project_static
from runtime_evidence import validate_runtime_references

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "concrete-duplicate-side-effect-evidence.schema.json"
DATABASE_BOUNDARY = "boundary.application.external_dependency"
INCIDENT_ID = "INC-DUP-EFFECT-XRAY"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def stable_hex(label: str, length: int) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()[:length]


class ProviderState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.effects: list[dict[str, Any]] = []
        self.idempotency: dict[str, str] = {}
        self.request_counts: dict[str, int] = {}

    def process(
        self,
        *,
        job_id: str,
        business_event_id: str,
        trace_id: str,
        span_id: str,
        idempotency_key: str | None,
    ) -> tuple[dict[str, Any], bool, bool]:
        with self.lock:
            request_count = self.request_counts.get(business_event_id, 0) + 1
            self.request_counts[business_event_id] = request_count
            should_delay = request_count == 1

            if idempotency_key and idempotency_key in self.idempotency:
                effect_id = self.idempotency[idempotency_key]
                effect = next(item for item in self.effects if item["effect_id"] == effect_id)
                return dict(effect), True, should_delay

            effect = {
                "effect_id": f"effect-{len(self.effects) + 1}",
                "job_id": job_id,
                "business_event_id": business_event_id,
                "trace_id": trace_id,
                "span_id": span_id,
                "idempotency_key": idempotency_key,
            }
            self.effects.append(effect)
            if idempotency_key:
                self.idempotency[idempotency_key] = effect["effect_id"]
            return dict(effect), False, should_delay

    def effects_for(self, business_event_id: str) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(item) for item in self.effects if item["business_event_id"] == business_event_id]


def handler_class(state: ProviderState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def do_POST(self) -> None:
            if self.path != "/charges":
                self.send_error(404)
                return

            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            business_event_id = str(payload["payment_id"])
            job_id = self.headers.get("X-Causcope-Job-Id", "")
            trace_id = self.headers.get("X-Causcope-Trace-Id", "")
            span_id = self.headers.get("X-Causcope-Span-Id", "")
            idempotency_key = self.headers.get("Idempotency-Key")
            if not job_id or not trace_id or not span_id:
                self.send_error(400)
                return

            effect, deduplicated, should_delay = state.process(
                job_id=job_id,
                business_event_id=business_event_id,
                trace_id=trace_id,
                span_id=span_id,
                idempotency_key=idempotency_key,
            )
            if should_delay:
                time.sleep(0.20)

            body = json.dumps(
                {
                    "effect_id": effect["effect_id"],
                    "deduplicated": deduplicated,
                }
            ).encode("utf-8")
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                return

    return Handler


def run_ruby_attempt(
    runner: Path,
    *,
    business_event_id: str,
    job_id: str,
    endpoint: str,
    trace_id: str,
    span_id: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    started = time.time_ns()
    completed = subprocess.run(
        [
            "ruby",
            str(runner),
            business_event_id,
            job_id,
            endpoint,
            trace_id,
            span_id,
            str(timeout_seconds),
        ],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    ended = time.time_ns()
    if completed.returncode == 0:
        outcome = "success"
    elif "Net::ReadTimeout" in completed.stderr or "read timeout" in completed.stderr.lower():
        outcome = "timeout"
    else:
        outcome = "error"
    return {
        "start_time_unix_nano": started,
        "end_time_unix_nano": ended,
        "client_outcome": outcome,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def run_python_attempt(
    *,
    business_event_id: str,
    job_id: str,
    endpoint: str,
    trace_id: str,
    span_id: str,
    timeout_seconds: float,
    idempotency_key: str,
) -> dict[str, Any]:
    payload = json.dumps({"payment_id": business_event_id}).encode("utf-8")
    request = urllib.request.Request(endpoint, data=payload, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("X-Causcope-Job-Id", job_id)
    request.add_header("X-Causcope-Trace-Id", trace_id)
    request.add_header("X-Causcope-Span-Id", span_id)
    request.add_header("Idempotency-Key", idempotency_key)
    started = time.time_ns()
    body: dict[str, Any] | None = None
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        outcome = "success"
    except (TimeoutError, socket.timeout):
        outcome = "timeout"
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            outcome = "timeout"
        else:
            outcome = "error"
    ended = time.time_ns()
    return {
        "start_time_unix_nano": started,
        "end_time_unix_nano": ended,
        "client_outcome": outcome,
        "response": body,
    }


def bind_provider_effects(attempts: list[dict[str, Any]], effects: list[dict[str, Any]]) -> None:
    effect_by_execution = {(item["trace_id"], item["span_id"]): item for item in effects}
    for attempt in attempts:
        effect = effect_by_execution.get((attempt["trace_id"], attempt["span_id"]))
        attempt["provider_effect_committed"] = effect is not None
        if effect is not None:
            attempt["provider_effect_id"] = effect["effect_id"]
        else:
            attempt.setdefault("provider_effect_id", None)
        attempt.setdefault("provider_deduplicated", False)


def build_otlp(static: dict[str, Any], code_symbol: str, attempts: list[dict[str, Any]]) -> dict[str, Any]:
    spans = []
    for attempt in attempts:
        spans.append(
            {
                "traceId": attempt["trace_id"],
                "spanId": attempt["span_id"],
                "name": "CapturePaymentJob#perform",
                "kind": "SPAN_KIND_CONSUMER",
                "startTimeUnixNano": str(attempt["start_time_unix_nano"]),
                "endTimeUnixNano": str(attempt["end_time_unix_nano"]),
                "attributes": [
                    {"key": "causcope.code_symbol", "value": {"stringValue": code_symbol}},
                    {"key": "causcope.system_id", "value": {"stringValue": static["system_id"]}},
                    {"key": "causcope.revision", "value": {"stringValue": static["revision"]["value"]}},
                    {"key": "causcope.job_id", "value": {"stringValue": attempt["job_id"]}},
                    {"key": "causcope.business_event_id", "value": {"stringValue": attempt["business_event_id"]}},
                ],
            }
        )
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "payments-worker"}}
                    ]
                },
                "scopeSpans": [{"scope": {"name": "causcope-live-lab"}, "spans": spans}],
            }
        ]
    }


def build_runtime_evidence(unsafe: dict[str, Any]) -> dict[str, Any]:
    observed_at = utc_now()
    identity = hashlib.sha256(
        f"{INCIDENT_ID}\0{unsafe['job_id']}\0{unsafe['business_event_id']}".encode("utf-8")
    ).hexdigest()[:12]
    document = {
        "schema_version": "0.1",
        "kind": "runtime_evidence",
        "incident_id": INCIDENT_ID,
        "description": "Observed duplicate external business effect after an ambiguous first job attempt and retry.",
        "instances": [
            {
                "id": f"evidence.duplicate_effect.{identity}",
                "observation": "observation.application.duplicate_side_effect",
                "state": "observed",
                "observed_at": observed_at,
                "confidence": "high",
                "source": {"type": "experiment", "name": "duplicate-side-effect-live-lab"},
                "scope": {
                    "boundaries": [DATABASE_BOUNDARY],
                    "attributes": {
                        "service": "payments-worker",
                        "dependency": "payments",
                        "job_id": unsafe["job_id"],
                        "business_event_id": unsafe["business_event_id"],
                    },
                },
                "measurement": {
                    "value": len(unsafe["provider_effects"]),
                    "unit": "provider_effects",
                    "comparison": "present",
                },
                "labels": {
                    "mechanism": "retry_after_ambiguous_external_effect",
                    "idempotency_key": "absent",
                },
            }
        ],
    }
    validate_runtime_references(document, load_concepts(ROOT))
    return document


def validate_evidence(document: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        rendered = "; ".join(error.message for error in errors)
        raise ValueError(f"duplicate side-effect evidence validation failed: {rendered}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a real HTTP ambiguous-outcome + retry duplicate-side-effect lab.")
    parser.add_argument("--static-facts", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--otlp-output", required=True, type=Path)
    parser.add_argument("--evidence-output", required=True, type=Path)
    parser.add_argument("--runtime-evidence-output", required=True, type=Path)
    args = parser.parse_args()

    static = load_document(args.static_facts)
    xray = project_static(static)
    matches = xray["structural_preconditions"]["matches"]
    if len(matches) != 1:
        raise SystemExit(f"live lab requires exactly one duplicate-side-effect precondition, got {len(matches)}")
    code_symbol = matches[0]["code_symbol"]

    state = ProviderState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/charges"
    runner = args.workspace.resolve() / "run_job.rb"

    try:
        unsafe_job_id = "job-unsafe-001"
        unsafe_event = "payment-unsafe-001"
        unsafe_attempts: list[dict[str, Any]] = []
        for attempt_no, timeout_seconds in ((1, 0.05), (2, 1.0)):
            trace_id = stable_hex(f"unsafe:{attempt_no}:trace", 32)
            span_id = stable_hex(f"unsafe:{attempt_no}:span", 16)
            attempt = run_ruby_attempt(
                runner,
                business_event_id=unsafe_event,
                job_id=unsafe_job_id,
                endpoint=endpoint,
                trace_id=trace_id,
                span_id=span_id,
                timeout_seconds=timeout_seconds,
            )
            attempt.update(
                {
                    "attempt": attempt_no,
                    "job_id": unsafe_job_id,
                    "business_event_id": unsafe_event,
                    "trace_id": trace_id,
                    "span_id": span_id,
                    "idempotency_key": None,
                }
            )
            unsafe_attempts.append(attempt)

        time.sleep(0.25)
        unsafe_effects = state.effects_for(unsafe_event)
        bind_provider_effects(unsafe_attempts, unsafe_effects)
        if [item["client_outcome"] for item in unsafe_attempts] != ["timeout", "success"]:
            raise ValueError(f"unsafe scenario did not produce timeout then success: {unsafe_attempts}")
        if len(unsafe_effects) != 2:
            raise ValueError(f"unsafe retry should commit two effects, got {len(unsafe_effects)}")

        protected_job_id = "job-protected-001"
        protected_event = "payment-protected-001"
        protected_key = "idem-payment-protected-001"
        protected_attempts: list[dict[str, Any]] = []
        for attempt_no, timeout_seconds in ((1, 0.05), (2, 1.0)):
            trace_id = stable_hex(f"protected:{attempt_no}:trace", 32)
            span_id = stable_hex(f"protected:{attempt_no}:span", 16)
            attempt = run_python_attempt(
                business_event_id=protected_event,
                job_id=protected_job_id,
                endpoint=endpoint,
                trace_id=trace_id,
                span_id=span_id,
                timeout_seconds=timeout_seconds,
                idempotency_key=protected_key,
            )
            response = attempt.pop("response", None)
            attempt.update(
                {
                    "attempt": attempt_no,
                    "job_id": protected_job_id,
                    "business_event_id": protected_event,
                    "trace_id": trace_id,
                    "span_id": span_id,
                    "idempotency_key": protected_key,
                    "provider_effect_id": response.get("effect_id") if response else None,
                    "provider_deduplicated": bool(response and response.get("deduplicated")),
                }
            )
            protected_attempts.append(attempt)

        time.sleep(0.25)
        protected_effects = state.effects_for(protected_event)
        bind_provider_effects(protected_attempts, protected_effects)
        if [item["client_outcome"] for item in protected_attempts] != ["timeout", "success"]:
            raise ValueError("protected scenario did not preserve the ambiguous timeout + retry shape")
        if len(protected_effects) != 1:
            raise ValueError(f"idempotent recovery should commit one effect, got {len(protected_effects)}")
        protected_attempts[1]["provider_effect_id"] = protected_effects[0]["effect_id"]
        protected_attempts[1]["provider_deduplicated"] = True

        unsafe = {
            "job_id": unsafe_job_id,
            "business_event_id": unsafe_event,
            "attempts": unsafe_attempts,
            "provider_effects": unsafe_effects,
            "expected_effect_count": 2,
        }
        protected = {
            "job_id": protected_job_id,
            "business_event_id": protected_event,
            "attempts": protected_attempts,
            "provider_effects": protected_effects,
            "expected_effect_count": 1,
        }
        evidence = {
            "schema_version": "0.1",
            "kind": "concrete_duplicate_side_effect_evidence",
            "system_id": static["system_id"],
            "revision": static["revision"],
            "incident_id": INCIDENT_ID,
            "code_symbol": code_symbol,
            "unsafe": unsafe,
            "protected": protected,
            "source": {"type": "experiment", "name": "duplicate-side-effect-live-lab"},
            "limitations": [
                "The retry scheduler is a bounded local harness rather than a production Sidekiq/Redis deployment.",
                "The unsafe path executes the real Ruby job and HTTP client source; the protected recovery directly exercises the same provider with a stable idempotency key.",
                "This proves one ambiguous-response retry mechanism, not every source of duplicate business effects.",
            ],
        }
        validate_evidence(evidence)
        otlp = build_otlp(static, code_symbol, unsafe_attempts)
        runtime_evidence = build_runtime_evidence(unsafe)

        args.otlp_output.write_text(json.dumps(otlp, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.evidence_output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        args.runtime_evidence_output.write_text(
            json.dumps(runtime_evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "status": "ok",
                    "unsafe_effects": len(unsafe_effects),
                    "protected_effects": len(protected_effects),
                    "first_outcome": unsafe_attempts[0]["client_outcome"],
                    "retry_outcome": unsafe_attempts[1]["client_outcome"],
                },
                sort_keys=True,
            )
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

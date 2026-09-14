#!/usr/bin/env python3

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlsplit

from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)

from concrete_system_facts import load_document as load_static_document
from otel_concrete_runtime_facts import (
    CODE_SYMBOL_ATTRIBUTE,
    build_document,
    iter_spans,
    validate_runtime_document,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4318
DEFAULT_MAX_BODY_BYTES = 10 * 1024 * 1024
PROTOBUF_MEDIA_TYPES = {"application/x-protobuf", "application/protobuf"}


class RequestTooLarge(ValueError):
    pass


class UnsupportedMediaType(ValueError):
    pass


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def derive_overlaps(executions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    overlaps: list[dict[str, Any]] = []
    ordered = sorted(executions, key=lambda item: item["id"])
    for left_index, left in enumerate(ordered):
        for right in ordered[left_index + 1 :]:
            if left["code_symbol"] == right["code_symbol"]:
                continue
            left_start = parse_timestamp(left["start_time"])
            left_end = parse_timestamp(left["end_time"])
            right_start = parse_timestamp(right["start_time"])
            right_end = parse_timestamp(right["end_time"])
            overlap_seconds = (min(left_end, right_end) - max(left_start, right_start)).total_seconds()
            if overlap_seconds <= 0:
                continue
            overlaps.append(
                {
                    "left_execution": left["id"],
                    "right_execution": right["id"],
                    "left_code_symbol": left["code_symbol"],
                    "right_code_symbol": right["code_symbol"],
                    "overlap_ms": overlap_seconds * 1000.0,
                }
            )
    return overlaps


def protobuf_request_to_otlp_json(request: ExportTraceServiceRequest) -> dict[str, Any]:
    payload = MessageToDict(request, preserving_proto_field_name=False)
    resource_json = payload.get("resourceSpans", [])
    for resource_index, resource_span in enumerate(request.resource_spans):
        if resource_index >= len(resource_json):
            continue
        scope_json = resource_json[resource_index].get("scopeSpans", [])
        for scope_index, scope_span in enumerate(resource_span.scope_spans):
            if scope_index >= len(scope_json):
                continue
            spans_json = scope_json[scope_index].get("spans", [])
            for span_index, span in enumerate(scope_span.spans):
                if span_index >= len(spans_json):
                    continue
                rendered = spans_json[span_index]
                rendered["traceId"] = span.trace_id.hex()
                rendered["spanId"] = span.span_id.hex()
                if span.parent_span_id:
                    rendered["parentSpanId"] = span.parent_span_id.hex()
    return payload


def decode_otlp_payload(body: bytes, content_type: str) -> tuple[dict[str, Any], str]:
    if content_type == "application/json":
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body must be valid UTF-8 OTLP JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("OTLP trace payload must be a JSON object")
        return payload, "json"

    if content_type in PROTOBUF_MEDIA_TYPES:
        request = ExportTraceServiceRequest()
        try:
            request.ParseFromString(body)
        except Exception as exc:  # protobuf raises implementation-specific decode errors
            raise ValueError("request body must be a valid OTLP ExportTraceServiceRequest") from exc
        return protobuf_request_to_otlp_json(request), "protobuf"

    raise UnsupportedMediaType(
        "OTLP receiver supports application/json and application/x-protobuf, "
        f"got {content_type}"
    )


def explicitly_bound(payload: dict[str, Any]) -> bool:
    return any(CODE_SYMBOL_ATTRIBUTE in attributes for _span, attributes in iter_spans(payload))


class ConcreteRuntimeStore:
    def __init__(
        self,
        *,
        static_document: dict[str, Any],
        incident_id: str,
        snapshot_path: Path | None,
        source_uri: str | None,
    ) -> None:
        self.static_document = static_document
        self.incident_id = incident_id
        self.snapshot_path = snapshot_path
        self.source_uri = source_uri
        self._executions: dict[str, dict[str, Any]] = {}
        self._lock = RLock()
        self._accepted_requests_total = 0
        self._ignored_unbound_requests_total = 0
        self._matched_executions_total = 0
        self._duplicate_executions_total = 0

    def _document(self) -> dict[str, Any] | None:
        if not self._executions:
            return None
        executions = sorted(self._executions.values(), key=lambda item: item["id"])
        document = {
            "schema_version": "0.1",
            "kind": "concrete_runtime_facts",
            "system_id": self.static_document["system_id"],
            "revision": self.static_document["revision"],
            "incident_id": self.incident_id,
            "executions": executions,
            "overlaps": derive_overlaps(executions),
            "limitations": [
                "Only spans carrying an explicit causcope.code_symbol binding are projected into concrete runtime facts.",
                "The receiver validates system and revision identity against the pinned concrete-system facts and rejects mismatches.",
                "Temporal overlap proves concurrent span intervals, not simultaneous database lock ownership or a database wait-for cycle.",
            ],
        }
        validate_runtime_document(document)
        return document

    def _write_snapshot(self, document: dict[str, Any]) -> None:
        if self.snapshot_path is None:
            return
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.snapshot_path.with_name(self.snapshot_path.name + ".tmp")
        temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.snapshot_path)

    def ingest(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._accepted_requests_total += 1
            if not explicitly_bound(payload):
                self._ignored_unbound_requests_total += 1
                return self.status()

            batch = build_document(
                self.static_document,
                payload,
                incident_id=self.incident_id,
                source_uri=self.source_uri,
            )
            for execution in batch["executions"]:
                current = self._executions.get(execution["id"])
                if current is None:
                    self._executions[execution["id"]] = execution
                    self._matched_executions_total += 1
                    continue
                if current != execution:
                    raise ValueError(
                        "deterministic concrete execution id was replayed with different content: "
                        + execution["id"]
                    )
                self._duplicate_executions_total += 1

            document = self._document()
            if document is not None:
                self._write_snapshot(document)
            return self.status()

    def runtime(self) -> dict[str, Any] | None:
        with self._lock:
            return self._document()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": "ok",
                "system_id": self.static_document["system_id"],
                "revision": self.static_document["revision"]["value"],
                "incident_id": self.incident_id,
                "stored_executions": len(self._executions),
                "accepted_requests_total": self._accepted_requests_total,
                "ignored_unbound_requests_total": self._ignored_unbound_requests_total,
                "matched_executions_total": self._matched_executions_total,
                "duplicate_executions_total": self._duplicate_executions_total,
            }


class ReceiverState:
    def __init__(
        self,
        *,
        store: ConcreteRuntimeStore,
        max_body_bytes: int,
        verbose: bool,
    ) -> None:
        self.store = store
        self.max_body_bytes = max_body_bytes
        self.verbose = verbose


def make_handler(state: ReceiverState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "CauscopeConcreteOTLP/0.1"

        def log_message(self, format: str, *args: Any) -> None:
            if state.verbose:
                super().log_message(format, *args)

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            self._send(status, json.dumps(payload, sort_keys=True).encode("utf-8"), "application/json")

        def _error(self, status: int, code: str, message: str) -> None:
            self._send_json(status, {"error": {"code": code, "message": message}})

        def _read_payload(self) -> tuple[dict[str, Any], str]:
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                raise ValueError("Content-Length is required")
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise ValueError("Content-Length must be an integer") from exc
            if length < 0:
                raise ValueError("Content-Length must not be negative")
            if length > state.max_body_bytes:
                raise RequestTooLarge(f"compressed request body exceeds {state.max_body_bytes} bytes")

            body = self.rfile.read(length)
            encoding = self.headers.get("Content-Encoding", "identity").strip().lower()
            if encoding in ("", "identity"):
                decoded = body
            elif encoding == "gzip":
                try:
                    decoded = gzip.decompress(body)
                except OSError as exc:
                    raise ValueError("invalid gzip request body") from exc
            else:
                raise UnsupportedMediaType(f"unsupported Content-Encoding: {encoding}")

            if len(decoded) > state.max_body_bytes:
                raise RequestTooLarge(f"decoded request body exceeds {state.max_body_bytes} bytes")

            content_type = self.headers.get_content_type()
            return decode_otlp_payload(decoded, content_type)

        def do_POST(self) -> None:
            if urlsplit(self.path).path != "/v1/traces":
                self._error(404, "not_found", "unknown receiver endpoint")
                return
            try:
                payload, wire_format = self._read_payload()
                state.store.ingest(payload)
            except RequestTooLarge as exc:
                self._error(413, "request_too_large", str(exc))
                return
            except UnsupportedMediaType as exc:
                self._error(415, "unsupported_media_type", str(exc))
                return
            except ValueError as exc:
                self._error(400, "invalid_argument", str(exc))
                return
            except OSError as exc:
                self._error(500, "snapshot_write_failed", str(exc))
                return

            if wire_format == "protobuf":
                response = ExportTraceServiceResponse().SerializeToString()
                self._send(200, response, "application/x-protobuf")
            else:
                self._send_json(200, {})

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/health":
                self._send_json(200, {"status": "ok"})
                return
            if path == "/status":
                self._send_json(200, state.store.status())
                return
            if path == "/runtime":
                runtime = state.store.runtime()
                if runtime is None:
                    self._error(404, "no_runtime", "no explicitly bound concrete executions have been received")
                    return
                self._send_json(200, runtime)
                return
            self._error(404, "not_found", "unknown receiver endpoint")

    return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Receive OTLP/HTTP JSON or protobuf traces and project explicitly bound spans "
            "into revision-bound Causcope concrete runtime facts."
        )
    )
    parser.add_argument("--static-facts", required=True, type=Path)
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--max-body-bytes", type=int, default=DEFAULT_MAX_BODY_BYTES)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--source-uri")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    if args.max_body_bytes <= 0:
        parser.error("--max-body-bytes must be positive")

    try:
        static_document = load_static_document(args.static_facts)
        store = ConcreteRuntimeStore(
            static_document=static_document,
            incident_id=args.incident_id,
            snapshot_path=args.snapshot,
            source_uri=args.source_uri or "otlp:http",
        )
        state = ReceiverState(store=store, max_body_bytes=args.max_body_bytes, verbose=args.verbose)
        server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
        server.daemon_threads = True
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    host, port = server.server_address[:2]
    print(
        f"Causcope concrete OTLP receiver listening on http://{host}:{port}/v1/traces "
        f"for incident {args.incident_id}",
        file=sys.stderr,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

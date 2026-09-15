#!/usr/bin/env python3

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from causal_projection import ROOT
from runtime_evidence import format_timestamp, parse_timestamp

EVENT_SCHEMA_PATH = ROOT / "schema" / "routed-execution-set-journal-event.schema.json"
JOURNAL_SUFFIX = ".journal.jsonl"
EVENT_TYPES = ("set_started", "member_succeeded", "set_committed")
EXECUTION_SET_ID_RE = re.compile(r"^execution-set\.[0-9a-f]{16}$")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _event_hash(event_without_hash: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(event_without_hash).encode("utf-8")).hexdigest()


def _load_event_schema(path: Path = EVENT_SCHEMA_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_execution_set_journal_event(
    event: dict[str, Any],
    *,
    schema_path: Path = EVENT_SCHEMA_PATH,
) -> None:
    validator = Draft202012Validator(
        _load_event_schema(schema_path),
        format_checker=FormatChecker(),
    )
    errors = sorted(validator.iter_errors(event), key=lambda error: list(error.path))
    if errors:
        raise ValueError(
            "execution-set journal event schema validation failed: "
            + "; ".join(error.message for error in errors)
        )


def journal_path(state_dir: Path, execution_set_id: str) -> Path:
    if not EXECUTION_SET_ID_RE.fullmatch(execution_set_id):
        raise ValueError(f"invalid execution-set id for journal path: {execution_set_id}")
    return state_dir / f"{execution_set_id}{JOURNAL_SUFFIX}"


def execution_set_contract(execution_set: dict[str, Any]) -> dict[str, Any]:
    members = []
    for member in execution_set.get("members", []):
        instrument = member.get("instrument", {})
        members.append(
            {
                "ordinal": member["ordinal"],
                "target_resource": member["target_resource"],
                "instrument_id": instrument.get("id"),
                "supporting_relationship_ids": sorted(
                    member.get("supporting_relationship_ids", [])
                ),
            }
        )
    return {
        "scope": copy.deepcopy(execution_set.get("scope")),
        "diagnosis_target": execution_set["diagnosis_target"],
        "probe_id": execution_set["probe_id"],
        "members": members,
    }


def _read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if not path.is_file():
        raise ValueError(f"execution-set journal path is not a file: {path}")

    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.rstrip("\r\n")
                if not line:
                    raise ValueError(
                        f"execution-set journal contains an empty line at {line_number}"
                    )
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"execution-set journal line {line_number} is invalid JSON: {exc}"
                    ) from exc
                if not isinstance(event, dict):
                    raise ValueError(
                        f"execution-set journal line {line_number} must be a JSON object"
                    )
                events.append(event)
    except OSError as exc:
        raise ValueError(f"cannot read execution-set journal {path}: {exc}") from exc
    return events


def verify_execution_set_journal(
    state_dir: Path,
    execution_set_id: str,
) -> dict[str, Any]:
    path = journal_path(state_dir, execution_set_id)
    events = _read_lines(path)
    previous_hash: str | None = None
    identity: tuple[str, str, int] | None = None
    transition_keys: set[tuple[str, str | None]] = set()

    for index, event in enumerate(events, start=1):
        validate_execution_set_journal_event(event)
        parse_timestamp(event["recorded_at"], "execution-set journal recorded_at")
        if event["sequence"] != index:
            raise ValueError(
                f"execution-set journal sequence mismatch at line {index}: "
                f"expected {index}, got {event['sequence']}"
            )
        if event["previous_hash"] != previous_hash:
            raise ValueError(
                f"execution-set journal previous_hash mismatch at sequence {index}"
            )
        unsigned = {
            key: copy.deepcopy(value)
            for key, value in event.items()
            if key != "event_hash"
        }
        if event["event_hash"] != _event_hash(unsigned):
            raise ValueError(
                f"execution-set journal event_hash mismatch at sequence {index}"
            )

        current_identity = (
            event["incident_id"],
            event["execution_set_id"],
            event["evidence_revision"],
        )
        if event["execution_set_id"] != execution_set_id:
            raise ValueError("execution-set journal contains a different execution_set_id")
        if identity is None:
            identity = current_identity
        elif identity != current_identity:
            raise ValueError("execution-set journal identity changed inside one file")

        member_target = None
        if event["event_type"] == "member_succeeded":
            member_target = event["data"].get("target_resource")
            if not isinstance(member_target, str) or not member_target:
                raise ValueError("member_succeeded event requires target_resource")
        key = (event["event_type"], member_target)
        if key in transition_keys:
            raise ValueError(
                f"execution-set journal contains duplicate transition: {key[0]} {key[1] or ''}".rstrip()
            )
        transition_keys.add(key)
        previous_hash = event["event_hash"]

    return {
        "schema_version": "0.1",
        "kind": "routed_execution_set_journal",
        "path": str(path),
        "verified": True,
        "event_count": len(events),
        "head_hash": previous_hash,
        "events": copy.deepcopy(events),
    }


def _transition_key(event_type: str, data: dict[str, Any]) -> tuple[str, str | None]:
    if event_type == "member_succeeded":
        target = data.get("target_resource")
        if not isinstance(target, str) or not target:
            raise ValueError("member_succeeded journal data requires target_resource")
        return event_type, target
    return event_type, None


def _semantic_identity(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_type": event["event_type"],
        "incident_id": event["incident_id"],
        "execution_set_id": event["execution_set_id"],
        "evidence_revision": event["evidence_revision"],
        "data": copy.deepcopy(event["data"]),
    }


def append_execution_set_journal_event(
    state_dir: Path,
    *,
    event_type: str,
    incident_id: str,
    execution_set_id: str,
    evidence_revision: int,
    data: dict[str, Any],
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unsupported execution-set journal event type: {event_type}")
    if not incident_id:
        raise ValueError("execution-set journal incident_id must not be empty")
    if not isinstance(evidence_revision, int) or evidence_revision < 0:
        raise ValueError("execution-set journal evidence_revision must be non-negative")
    if not isinstance(data, dict):
        raise ValueError("execution-set journal data must be an object")

    recorded_at = (recorded_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    projection = verify_execution_set_journal(state_dir, execution_set_id)
    events = projection["events"]
    transition_key = _transition_key(event_type, data)
    proposed_identity = {
        "event_type": event_type,
        "incident_id": incident_id,
        "execution_set_id": execution_set_id,
        "evidence_revision": evidence_revision,
        "data": copy.deepcopy(data),
    }

    matches = [
        event
        for event in events
        if _transition_key(event["event_type"], event["data"]) == transition_key
    ]
    if matches:
        if len(matches) != 1:
            raise ValueError("execution-set journal contains duplicate transition keys")
        existing = matches[0]
        if _semantic_identity(existing) != proposed_identity:
            raise ValueError(
                f"execution-set journal already contains a conflicting {event_type} transition"
            )
        return {**copy.deepcopy(existing), "already_recorded": True}

    if events:
        first = events[0]
        expected_identity = (
            first["incident_id"],
            first["execution_set_id"],
            first["evidence_revision"],
        )
        if expected_identity != (incident_id, execution_set_id, evidence_revision):
            raise ValueError("execution-set journal append identity does not match existing journal")

    previous_hash = events[-1]["event_hash"] if events else None
    unsigned = {
        "schema_version": "0.1",
        "kind": "routed_execution_set_journal_event",
        "sequence": len(events) + 1,
        "event_type": event_type,
        "recorded_at": format_timestamp(recorded_at),
        "incident_id": incident_id,
        "execution_set_id": execution_set_id,
        "evidence_revision": evidence_revision,
        "data": copy.deepcopy(data),
        "previous_hash": previous_hash,
    }
    event = {**unsigned, "event_hash": _event_hash(unsigned)}
    validate_execution_set_journal_event(event)

    path = journal_path(state_dir, execution_set_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ValueError(f"cannot append execution-set journal {path}: {exc}") from exc
    return {**copy.deepcopy(event), "already_recorded": False}


def load_execution_set_resume_state(
    state_dir: Path,
    *,
    incident_id: str,
    evidence_revision: int,
    execution_set: dict[str, Any],
) -> dict[str, Any]:
    projection = verify_execution_set_journal(state_dir, execution_set["id"])
    events = projection["events"]
    contract = execution_set_contract(execution_set)
    if not events:
        return {
            "state": "not_started",
            "contract": contract,
            "member_events": {},
            "committed_event": None,
            "journal": projection,
        }

    first = events[0]
    if (
        first["incident_id"] != incident_id
        or first["evidence_revision"] != evidence_revision
        or first["execution_set_id"] != execution_set["id"]
    ):
        raise ValueError("execution-set journal does not match current incident revision")
    if first["event_type"] != "set_started":
        raise ValueError("execution-set journal must begin with set_started")
    if first["data"].get("contract") != contract:
        raise ValueError("execution-set journal contract does not match current routed set")

    member_events: dict[str, dict[str, Any]] = {}
    committed_event = None
    for event in events[1:]:
        if event["event_type"] == "member_succeeded":
            target = event["data"]["target_resource"]
            member_events[target] = copy.deepcopy(event)
        elif event["event_type"] == "set_committed":
            committed_event = copy.deepcopy(event)

    return {
        "state": "committed" if committed_event is not None else "in_progress",
        "contract": contract,
        "member_events": member_events,
        "committed_event": committed_event,
        "journal": projection,
    }

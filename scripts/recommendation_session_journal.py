#!/usr/bin/env python3

from __future__ import annotations

import argparse
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
from probe_filesystem_claim import (
    ProbeFilesystemClaimError,
    acquire_probe_filesystem_claim,
)
from recommendation_information_gaps import project as project_information_gaps
from runtime_evidence import format_timestamp, parse_timestamp

EVENT_SCHEMA_PATH = ROOT / "schema" / "recommendation-session-event.schema.json"
SESSION_SCHEMA_PATH = ROOT / "schema" / "recommendation-session.schema.json"
RECOMMENDATION_SCHEMA_PATH = ROOT / "schema" / "architectural-recommendation-projection.schema.json"
GAP_SCHEMA_PATH = ROOT / "schema" / "recommendation-information-gap-projection.schema.json"
ACQUISITION_SCHEMA_PATH = ROOT / "schema" / "recommendation-evidence-acquisition-result.schema.json"
CLAIM_PURPOSE = "recommendation_session_journal"
SESSION_ID_PATTERN = re.compile(r"^recommendation-session\.[0-9a-f]{16}$")
CLOSED_STATUSES = {"approved", "rejected", "stopped"}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _event_hash(event_without_hash: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(event_without_hash).encode("utf-8")).hexdigest()


def _load_schema(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    Draft202012Validator.check_schema(schema)
    return schema


def _validate_schema(document: dict[str, Any], path: Path, label: str) -> None:
    validator = Draft202012Validator(
        _load_schema(path),
        format_checker=FormatChecker(),
    )
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        raise ValueError(
            f"{label} schema validation failed: "
            + "; ".join(error.message for error in errors)
        )


def _snapshot_identity(recommendation_projection: dict[str, Any]) -> dict[str, Any]:
    query_object = recommendation_projection["causal_basis"]["query_object"]
    if recommendation_projection["problem"]["query_object"] != query_object:
        raise ValueError("recommendation projection query identity is internally inconsistent")
    return {
        "system_id": recommendation_projection["system_id"],
        "revision": copy.deepcopy(recommendation_projection["revision"]),
        "incident_id": recommendation_projection["incident_id"],
        "recommendation_id": recommendation_projection["recommendation_id"],
        "subject_resource": recommendation_projection["subject_resource"],
        "query_object": query_object,
    }


def derive_recommendation_session_id(identity: dict[str, Any]) -> str:
    digest = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:16]
    return f"recommendation-session.{digest}"


def recommendation_session_path(session_dir: Path, session_id: str) -> Path:
    if SESSION_ID_PATTERN.fullmatch(session_id) is None:
        raise ValueError("invalid recommendation session id")
    return session_dir / f"{session_id}.journal.jsonl"


def _validate_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "recommendation_projection",
        "information_gap_projection",
    }:
        raise ValueError(
            "recommendation session snapshot must contain exactly recommendation_projection and information_gap_projection"
        )
    recommendation_projection = snapshot["recommendation_projection"]
    gap_projection = snapshot["information_gap_projection"]
    if not isinstance(recommendation_projection, dict) or not isinstance(gap_projection, dict):
        raise ValueError("recommendation session snapshot projections must be objects")

    _validate_schema(
        recommendation_projection,
        RECOMMENDATION_SCHEMA_PATH,
        "architectural recommendation projection",
    )
    _validate_schema(
        gap_projection,
        GAP_SCHEMA_PATH,
        "recommendation information gap projection",
    )
    expected_gap_projection = project_information_gaps(recommendation_projection)
    if gap_projection != expected_gap_projection:
        raise ValueError(
            "recommendation session information-gap projection is not the deterministic projection of its recommendation snapshot"
        )

    for key in ("system_id", "revision", "incident_id", "recommendation_id", "subject_resource"):
        if gap_projection[key] != recommendation_projection[key]:
            raise ValueError(f"recommendation session snapshot identity mismatch for {key}")
    if gap_projection["recommendation_state"] != recommendation_projection["state"]:
        raise ValueError("recommendation session snapshot maturity state is inconsistent")
    return _snapshot_identity(recommendation_projection)


def _status_from_snapshot(snapshot: dict[str, Any]) -> str:
    kind = snapshot["information_gap_projection"]["next_action"]["kind"]
    if kind == "human_decision":
        return "awaiting_human_decision"
    if kind == "stop_candidate":
        return "candidate_rejected"
    return "active"


def _compact_action(action: dict[str, Any]) -> dict[str, Any]:
    result = {
        "kind": action["kind"],
        "execution_boundary": action["execution_boundary"],
    }
    for key in ("gap_id", "probe_id", "requested_observation"):
        if key in action:
            result[key] = action[key]
    return result


def _validate_acquisition_result(
    acquisition: dict[str, Any],
    *,
    before_snapshot: dict[str, Any],
    after_snapshot: dict[str, Any],
    action: dict[str, Any],
    identity: dict[str, Any],
) -> None:
    if not isinstance(acquisition, dict):
        raise ValueError("read-only probe result must contain an acquisition result object")
    _validate_schema(
        acquisition,
        ACQUISITION_SCHEMA_PATH,
        "recommendation evidence acquisition result",
    )
    for key in ("system_id", "revision", "incident_id", "recommendation_id", "subject_resource"):
        if acquisition[key] != identity[key]:
            raise ValueError(f"recommendation acquisition identity mismatch for {key}")

    before_recommendation = before_snapshot["recommendation_projection"]
    before_gap = before_snapshot["information_gap_projection"]
    after_recommendation = after_snapshot["recommendation_projection"]
    after_gap = after_snapshot["information_gap_projection"]

    if acquisition["previous_state"] != before_recommendation["state"]:
        raise ValueError("recommendation acquisition previous_state does not match session state")
    if acquisition["probe_id"] != action.get("probe_id"):
        raise ValueError("recommendation acquisition probe_id does not match current action")
    if acquisition["requested_observation"] != action.get("requested_observation"):
        raise ValueError("recommendation acquisition observation does not match current action")
    if acquisition["routing"]["target_resource"] != identity["subject_resource"]:
        raise ValueError("recommendation acquisition target does not match session subject")
    if acquisition["routing"]["instrument_id"] != before_recommendation["provider_instance"]:
        raise ValueError("recommendation acquisition provider does not match the pinned recommendation provider")
    if acquisition["recommendation_state"] != after_recommendation["state"]:
        raise ValueError("recommendation acquisition resulting state does not match next snapshot")
    if acquisition["information_gap_status"] != after_gap["status"]:
        raise ValueError("recommendation acquisition gap status does not match next snapshot")
    if acquisition["next_action"] != _compact_action(after_gap["next_action"]):
        raise ValueError("recommendation acquisition next action does not match next snapshot")

    expected_progressed = (
        before_recommendation["state"] != after_recommendation["state"]
        or before_gap["status"] != after_gap["status"]
        or before_gap["next_action"] != after_gap["next_action"]
    )
    if acquisition["progressed"] is not expected_progressed:
        raise ValueError("recommendation acquisition progressed flag does not match the session transition")
    if not acquisition["evidence"]["matching_instance_ids"]:
        raise ValueError("recommendation acquisition recorded no matching evidence instances")
    parse_timestamp(acquisition["acquisition_time"], "recommendation acquisition time")


def _validate_action_transition(
    *,
    before_snapshot: dict[str, Any],
    after_snapshot: dict[str, Any],
    action: dict[str, Any],
    result: dict[str, Any],
    identity: dict[str, Any],
) -> str:
    if not isinstance(result, dict) or result.get("kind") != action["kind"]:
        raise ValueError("recommendation action result kind does not match the current next action")

    after_identity = _validate_snapshot(after_snapshot)
    if after_identity != identity:
        raise ValueError("recommendation session action attempted to change immutable session identity")

    kind = action["kind"]
    if kind == "read_only_probe":
        if action["execution_boundary"] != "existing_read_only_probe":
            raise ValueError("read-only recommendation action has an unexpected execution boundary")
        _validate_acquisition_result(
            result["acquisition_result"],
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            action=action,
            identity=identity,
        )
        return _status_from_snapshot(after_snapshot)

    if kind == "operator_question":
        if action["execution_boundary"] != "question_only":
            raise ValueError("operator question has an unexpected execution boundary")
        if result.get("gap_id") != action.get("gap_id"):
            raise ValueError("operator answer gap_id does not match the current information gap")
        return _status_from_snapshot(after_snapshot)

    if kind == "safe_experiment":
        if action["execution_boundary"] != "experiment_plan_only":
            raise ValueError("safe experiment has an unexpected execution boundary")
        if result.get("gap_id") != action.get("gap_id"):
            raise ValueError("experiment result gap_id does not match the current information gap")
        benefit = after_snapshot["recommendation_projection"].get("benefit", {})
        evidence_ref = benefit.get("evidence_ref") if isinstance(benefit, dict) else None
        if evidence_ref is not None and result.get("result_ref") != evidence_ref:
            raise ValueError("experiment result reference does not match the next recommendation evidence reference")
        outcome = result.get("reported_outcome")
        next_state = after_snapshot["recommendation_projection"]["state"]
        if outcome == "demonstrated" and next_state != "READY_FOR_HUMAN_REVIEW":
            raise ValueError("demonstrated experiment result must project to READY_FOR_HUMAN_REVIEW")
        if outcome == "not_demonstrated" and next_state != "BENEFIT_NOT_DEMONSTRATED":
            raise ValueError("failed experiment result must project to BENEFIT_NOT_DEMONSTRATED")
        if outcome == "inconclusive" and next_state not in {"EXPERIMENT_REQUIRED", "ESTIMATED_BENEFIT"}:
            raise ValueError("inconclusive experiment result cannot advance recommendation maturity")
        return _status_from_snapshot(after_snapshot)

    if kind == "human_decision":
        if action["execution_boundary"] != "human_decision_required":
            raise ValueError("human decision has an unexpected execution boundary")
        if after_snapshot != before_snapshot:
            raise ValueError("human decision must not rewrite recommendation evidence or maturity")
        decision = result.get("decision")
        if decision == "approved":
            return "approved"
        if decision == "rejected":
            return "rejected"
        raise ValueError("unsupported human decision result")

    if kind == "stop_candidate":
        if action["execution_boundary"] != "stop_without_more_evidence":
            raise ValueError("stop-candidate action has an unexpected execution boundary")
        if after_snapshot != before_snapshot:
            raise ValueError("stop-candidate action must not rewrite recommendation evidence or maturity")
        return "stopped"

    raise ValueError(f"unsupported recommendation action kind: {kind}")


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if not path.is_file():
        raise ValueError(f"recommendation session journal path is not a file: {path}")
    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.rstrip("\r\n")
                if not line:
                    raise ValueError(
                        f"recommendation session journal contains an empty line at {line_number}"
                    )
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"recommendation session journal line {line_number} is invalid JSON: {exc}"
                    ) from exc
                if not isinstance(event, dict):
                    raise ValueError(
                        f"recommendation session journal line {line_number} must be a JSON object"
                    )
                events.append(event)
    except OSError as exc:
        raise ValueError(f"cannot read recommendation session journal {path}: {exc}") from exc
    return events


def _append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ValueError(f"cannot append recommendation session journal {path}: {exc}") from exc


def _validate_event(event: dict[str, Any]) -> None:
    _validate_schema(event, EVENT_SCHEMA_PATH, "recommendation session event")
    parse_timestamp(event["recorded_at"], "recommendation session event recorded_at")


def _event_ack(event: dict[str, Any], *, already_recorded: bool) -> dict[str, Any]:
    return {
        "sequence": event["sequence"],
        "event_hash": event["event_hash"],
        "previous_hash": event["previous_hash"],
        "already_recorded": already_recorded,
    }


def _verify_internal(
    session_dir: Path,
    session_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    path = recommendation_session_path(session_dir, session_id)
    events = _read_events(path)
    if not events:
        raise ValueError(f"recommendation session journal does not exist: {path}")

    previous_hash: str | None = None
    identity: dict[str, Any] | None = None
    snapshot: dict[str, Any] | None = None
    status: str | None = None

    for index, event in enumerate(events, start=1):
        _validate_event(event)
        if event["sequence"] != index:
            raise ValueError(
                f"recommendation session journal sequence mismatch at line {index}: expected {index}, got {event['sequence']}"
            )
        if event["previous_hash"] != previous_hash:
            raise ValueError(
                f"recommendation session journal previous_hash mismatch at sequence {index}"
            )
        unsigned = {key: copy.deepcopy(value) for key, value in event.items() if key != "event_hash"}
        if event["event_hash"] != _event_hash(unsigned):
            raise ValueError(
                f"recommendation session journal event_hash mismatch at sequence {index}"
            )
        if event["session_id"] != session_id:
            raise ValueError("recommendation session journal contains a different session id")

        if index == 1:
            if event["event_type"] != "session_started":
                raise ValueError("recommendation session journal must begin with session_started")
            snapshot = copy.deepcopy(event["data"]["snapshot"])
            identity = _validate_snapshot(snapshot)
            if event["identity"] != identity:
                raise ValueError("recommendation session start event identity does not match its snapshot")
            if derive_recommendation_session_id(identity) != session_id:
                raise ValueError("recommendation session id does not match immutable session identity")
            status = _status_from_snapshot(snapshot)
        else:
            if event["event_type"] != "action_result_recorded":
                raise ValueError("recommendation session journal contains an unsupported transition event")
            if identity is None or snapshot is None or status is None:
                raise ValueError("recommendation session replay lost its initial state")
            if status in CLOSED_STATUSES:
                raise ValueError("recommendation session journal contains an event after terminal closure")
            if event["identity"] != identity:
                raise ValueError("recommendation session event changed immutable identity")
            data = event["data"]
            if data["expected_session_revision"] != index - 1:
                raise ValueError(
                    "recommendation session event expected_session_revision does not match prior revision"
                )
            current_action = snapshot["information_gap_projection"]["next_action"]
            if data["action"] != current_action:
                raise ValueError("recommendation session event action does not match prior next_action")
            next_snapshot = copy.deepcopy(data["snapshot"])
            status = _validate_action_transition(
                before_snapshot=snapshot,
                after_snapshot=next_snapshot,
                action=current_action,
                result=data["result"],
                identity=identity,
            )
            snapshot = next_snapshot

        previous_hash = event["event_hash"]

    assert identity is not None and snapshot is not None and status is not None and previous_hash is not None
    recommendation_projection = snapshot["recommendation_projection"]
    gap_projection = snapshot["information_gap_projection"]
    session = {
        "schema_version": "0.1",
        "kind": "recommendation_session",
        "session_id": session_id,
        "identity": copy.deepcopy(identity),
        "session_revision": len(events),
        "status": status,
        "recommendation_state": recommendation_projection["state"],
        "information_gap_status": gap_projection["status"],
        "next_action": copy.deepcopy(gap_projection["next_action"]),
        "started_at": events[0]["recorded_at"],
        "updated_at": events[-1]["recorded_at"],
        "event_count": len(events),
        "head_hash": previous_hash,
        "verified": True,
    }
    _validate_schema(session, SESSION_SCHEMA_PATH, "recommendation session")
    return session, events, snapshot


def verify_recommendation_session(session_dir: Path, session_id: str) -> dict[str, Any]:
    session, _events, _snapshot = _verify_internal(session_dir, session_id)
    return session


def start_recommendation_session(
    session_dir: Path,
    *,
    recommendation_projection: dict[str, Any],
    information_gap_projection: dict[str, Any],
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    snapshot = {
        "recommendation_projection": copy.deepcopy(recommendation_projection),
        "information_gap_projection": copy.deepcopy(information_gap_projection),
    }
    identity = _validate_snapshot(snapshot)
    session_id = derive_recommendation_session_id(identity)
    recorded_at = (recorded_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    path = recommendation_session_path(session_dir, session_id)

    try:
        with acquire_probe_filesystem_claim(
            session_dir,
            purpose=CLAIM_PURPOSE,
            identity={"session_id": session_id},
            acquired_at=recorded_at,
        ):
            if path.exists():
                session, events, _current_snapshot = _verify_internal(session_dir, session_id)
                first = events[0]
                if first["data"]["snapshot"] != snapshot:
                    raise ValueError("recommendation session already exists with a conflicting initial snapshot")
                return {
                    "session": session,
                    "journal_event": _event_ack(first, already_recorded=True),
                }

            event_without_hash = {
                "schema_version": "0.1",
                "kind": "recommendation_session_event",
                "sequence": 1,
                "event_type": "session_started",
                "recorded_at": format_timestamp(recorded_at),
                "session_id": session_id,
                "identity": copy.deepcopy(identity),
                "data": {"snapshot": snapshot},
                "previous_hash": None,
            }
            event = {
                **event_without_hash,
                "event_hash": _event_hash(event_without_hash),
            }
            _validate_event(event)
            _append_event(path, event)
            session, _events, _snapshot = _verify_internal(session_dir, session_id)
            return {
                "session": session,
                "journal_event": _event_ack(event, already_recorded=False),
            }
    except ProbeFilesystemClaimError as exc:
        raise ValueError(str(exc)) from exc


def record_recommendation_action_result(
    session_dir: Path,
    *,
    session_id: str,
    expected_session_revision: int,
    result: dict[str, Any],
    next_recommendation_projection: dict[str, Any],
    next_information_gap_projection: dict[str, Any],
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    if expected_session_revision < 1:
        raise ValueError("expected_session_revision must be at least 1")
    next_snapshot = {
        "recommendation_projection": copy.deepcopy(next_recommendation_projection),
        "information_gap_projection": copy.deepcopy(next_information_gap_projection),
    }
    _validate_snapshot(next_snapshot)
    recorded_at = (recorded_at or datetime.now(timezone.utc)).astimezone(timezone.utc)

    try:
        with acquire_probe_filesystem_claim(
            session_dir,
            purpose=CLAIM_PURPOSE,
            identity={"session_id": session_id},
            acquired_at=recorded_at,
        ):
            session, events, current_snapshot = _verify_internal(session_dir, session_id)
            if expected_session_revision < session["session_revision"]:
                if expected_session_revision == session["session_revision"] - 1:
                    last = events[-1]
                    if (
                        last["event_type"] == "action_result_recorded"
                        and last["data"]["expected_session_revision"] == expected_session_revision
                        and last["data"]["result"] == result
                        and last["data"]["snapshot"] == next_snapshot
                    ):
                        return {
                            "session": session,
                            "journal_event": _event_ack(last, already_recorded=True),
                        }
                raise ValueError(
                    f"stale recommendation session revision: expected {expected_session_revision}, current {session['session_revision']}"
                )
            if expected_session_revision != session["session_revision"]:
                raise ValueError(
                    f"recommendation session revision mismatch: expected {expected_session_revision}, current {session['session_revision']}"
                )
            if session["status"] in CLOSED_STATUSES:
                raise ValueError("recommendation session is already terminally closed")

            action = copy.deepcopy(current_snapshot["information_gap_projection"]["next_action"])
            identity = copy.deepcopy(session["identity"])
            _validate_action_transition(
                before_snapshot=current_snapshot,
                after_snapshot=next_snapshot,
                action=action,
                result=result,
                identity=identity,
            )
            data = {
                "expected_session_revision": expected_session_revision,
                "action": action,
                "result": copy.deepcopy(result),
                "snapshot": next_snapshot,
            }
            event_without_hash = {
                "schema_version": "0.1",
                "kind": "recommendation_session_event",
                "sequence": session["session_revision"] + 1,
                "event_type": "action_result_recorded",
                "recorded_at": format_timestamp(recorded_at),
                "session_id": session_id,
                "identity": identity,
                "data": data,
                "previous_hash": session["head_hash"],
            }
            event = {
                **event_without_hash,
                "event_hash": _event_hash(event_without_hash),
            }
            _validate_event(event)
            path = recommendation_session_path(session_dir, session_id)
            _append_event(path, event)
            next_session, _events, _snapshot = _verify_internal(session_dir, session_id)
            return {
                "session": next_session,
                "journal_event": _event_ack(event, already_recorded=False),
            }
    except ProbeFilesystemClaimError as exc:
        raise ValueError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify and inspect an event-sourced Causcope recommendation session."
    )
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        session = verify_recommendation_session(args.session_dir, args.session_id)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(session, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

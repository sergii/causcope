#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from causal_projection import ROOT
from routed_execution_set_journal import (
    EXECUTION_SET_ID_RE,
    JOURNAL_SUFFIX,
    journal_path,
    load_execution_set_resume_state,
    verify_execution_set_journal,
)
from routed_execution_sets import validate_routed_execution_sets

SCHEMA_PATH = ROOT / "schema" / "routed-execution-set-status.schema.json"
STATES = ("pending", "in_progress", "ready_to_commit", "committed", "stranded")


def _load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_execution_set_status(
    document: dict[str, Any],
    *,
    schema_path: Path = SCHEMA_PATH,
) -> None:
    validator = Draft202012Validator(
        _load_schema(schema_path),
        format_checker=FormatChecker(),
    )
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        raise ValueError(
            "execution-set status schema validation failed: "
            + "; ".join(error.message for error in errors)
        )

    summary = document["summary"]
    if summary["total"] != len(document["sets"]):
        raise ValueError("execution-set status summary total does not match set count")
    if summary["current"] + summary["historical"] != summary["total"]:
        raise ValueError("execution-set status current/historical counts do not add up")
    if sum(summary[state] for state in STATES) != summary["total"]:
        raise ValueError("execution-set status lifecycle counts do not add up")

    for item in document["sets"]:
        progress = item["progress"]
        if progress["completed_members"] + progress["remaining_members"] != progress["total_members"]:
            raise ValueError(
                f"execution-set status progress does not add up: {item['execution_set_id']}"
            )
        if progress["completed_members"] > progress["total_members"]:
            raise ValueError(
                f"execution-set status completed count exceeds total: {item['execution_set_id']}"
            )
        if len(item["members"]) != progress["total_members"]:
            raise ValueError(
                f"execution-set status member list does not match progress total: {item['execution_set_id']}"
            )
        succeeded = sum(1 for member in item["members"] if member["state"] == "succeeded")
        if succeeded != progress["completed_members"]:
            raise ValueError(
                f"execution-set status succeeded member count does not match progress: {item['execution_set_id']}"
            )


def _coerce_execution_sets(document: dict[str, Any]) -> dict[str, Any]:
    kind = document.get("kind")
    if kind == "routed_execution_sets":
        projection = copy.deepcopy(document)
    elif kind == "routed_agent_plan":
        projection = {
            "schema_version": "0.1",
            "kind": "routed_execution_sets",
            "incident_id": document.get("incident_id"),
            "evidence_revision": document.get("evidence_revision"),
            "sets": copy.deepcopy(document.get("execution_sets", [])),
        }
    else:
        raise ValueError(
            "status projection requires routed_execution_sets or routed_agent_plan input"
        )
    validate_routed_execution_sets(projection)
    return projection


def load_execution_sets_document(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read execution-set input {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"execution-set input is invalid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("execution-set input must be a JSON object")
    return _coerce_execution_sets(document)


def _journal_metadata(
    *,
    present: bool,
    integrity: str,
    projection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    projection = projection or {}
    return {
        "present": present,
        "integrity": integrity,
        "event_count": int(projection.get("event_count", 0)),
        "head_hash": projection.get("head_hash"),
    }


def _member_rows(
    members: list[dict[str, Any]],
    member_events: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for member in sorted(
        members,
        key=lambda item: (item.get("ordinal", 0), item.get("target_resource", "")),
    ):
        target = member.get("target_resource")
        event = member_events.get(target) if isinstance(target, str) else None
        event_data = event.get("data", {}) if isinstance(event, dict) else {}
        instrument_id = member.get("instrument_id")
        if instrument_id is None:
            instrument = member.get("instrument", {})
            if isinstance(instrument, dict):
                instrument_id = instrument.get("id")
        rows.append(
            {
                "ordinal": member["ordinal"],
                "target_resource": target,
                "instrument_id": instrument_id,
                "state": "succeeded" if event is not None else "pending",
                "produced_instance_ids": (
                    sorted(event_data.get("produced_instance_ids", []))
                    if event is not None
                    else []
                ),
            }
        )
    return rows


def _timestamps(events: list[dict[str, Any]]) -> tuple[str | None, str | None, str | None]:
    if not events:
        return None, None, None
    started_at = events[0].get("recorded_at")
    updated_at = events[-1].get("recorded_at")
    committed = next(
        (event for event in events if event.get("event_type") == "set_committed"),
        None,
    )
    return (
        started_at if isinstance(started_at, str) else None,
        updated_at if isinstance(updated_at, str) else None,
        committed.get("recorded_at") if isinstance(committed, dict) else None,
    )


def _status_item(
    *,
    execution_set_id: str,
    incident_id: str,
    evidence_revision: int,
    current: bool,
    current_route_state: str | None,
    state: str,
    executable: bool,
    reason: str,
    diagnosis_target: str | None,
    probe_id: str | None,
    members: list[dict[str, Any]],
    journal: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    completed = sum(1 for member in members if member["state"] == "succeeded")
    total = len(members)
    started_at, updated_at, committed_at = _timestamps(events)
    return {
        "execution_set_id": execution_set_id,
        "incident_id": incident_id,
        "evidence_revision": evidence_revision,
        "current": current,
        "current_route_state": current_route_state,
        "state": state,
        "executable": executable,
        "reason": reason,
        "diagnosis_target": diagnosis_target,
        "probe_id": probe_id,
        "progress": {
            "total_members": total,
            "completed_members": completed,
            "remaining_members": total - completed,
        },
        "members": members,
        "journal": journal,
        "started_at": started_at,
        "updated_at": updated_at,
        "committed_at": committed_at,
    }


def _current_status(
    execution_set: dict[str, Any],
    *,
    incident_id: str,
    evidence_revision: int,
    state_dir: Path,
) -> dict[str, Any]:
    path = journal_path(state_dir, execution_set["id"])
    if not path.exists():
        members = _member_rows(execution_set.get("members", []), {})
        ready = execution_set.get("state") == "ready"
        reason = (
            "current execution set has not started"
            if ready
            else f"current execution set is blocked: {execution_set.get('reason', 'unknown reason')}"
        )
        return _status_item(
            execution_set_id=execution_set["id"],
            incident_id=incident_id,
            evidence_revision=evidence_revision,
            current=True,
            current_route_state=execution_set.get("state"),
            state="pending",
            executable=ready,
            reason=reason,
            diagnosis_target=execution_set.get("diagnosis_target"),
            probe_id=execution_set.get("probe_id"),
            members=members,
            journal=_journal_metadata(present=False, integrity="absent"),
            events=[],
        )

    try:
        resume = load_execution_set_resume_state(
            state_dir,
            incident_id=incident_id,
            evidence_revision=evidence_revision,
            execution_set=execution_set,
        )
    except (OSError, ValueError) as exc:
        members = _member_rows(execution_set.get("members", []), {})
        return _status_item(
            execution_set_id=execution_set["id"],
            incident_id=incident_id,
            evidence_revision=evidence_revision,
            current=True,
            current_route_state=execution_set.get("state"),
            state="stranded",
            executable=False,
            reason=f"journal verification or current-set contract validation failed: {exc}",
            diagnosis_target=execution_set.get("diagnosis_target"),
            probe_id=execution_set.get("probe_id"),
            members=members,
            journal=_journal_metadata(present=True, integrity="invalid"),
            events=[],
        )

    events = resume["journal"]["events"]
    member_events = resume["member_events"]
    members = _member_rows(execution_set.get("members", []), member_events)
    completed = len(member_events)
    total = len(members)

    if resume["state"] == "committed":
        state = "committed"
        executable = False
        reason = "journal records a successful incident-state commit"
    elif execution_set.get("state") != "ready":
        state = "stranded"
        executable = False
        reason = (
            "journal exists but current execution set is blocked: "
            f"{execution_set.get('reason', 'unknown reason')}"
        )
    elif completed == total and total > 0:
        state = "ready_to_commit"
        executable = True
        reason = "all members are durably journaled; final incident-state commit is pending"
    else:
        state = "in_progress"
        executable = True
        reason = f"{completed}/{total} members are durably journaled"

    return _status_item(
        execution_set_id=execution_set["id"],
        incident_id=incident_id,
        evidence_revision=evidence_revision,
        current=True,
        current_route_state=execution_set.get("state"),
        state=state,
        executable=executable,
        reason=reason,
        diagnosis_target=execution_set.get("diagnosis_target"),
        probe_id=execution_set.get("probe_id"),
        members=members,
        journal=_journal_metadata(
            present=True,
            integrity="verified",
            projection=resume["journal"],
        ),
        events=events,
    )


def _historical_status(
    projection: dict[str, Any],
    *,
    current_incident_id: str,
) -> dict[str, Any] | None:
    events = projection.get("events", [])
    if not events:
        return None
    first = events[0]
    if first.get("incident_id") != current_incident_id:
        return None

    execution_set_id = first.get("execution_set_id")
    if not isinstance(execution_set_id, str):
        return None
    evidence_revision = first.get("evidence_revision")
    if not isinstance(evidence_revision, int):
        return None

    contract = (
        first.get("data", {}).get("contract")
        if first.get("event_type") == "set_started"
        else None
    )
    contract = contract if isinstance(contract, dict) else {}
    contract_members = contract.get("members", [])
    if not isinstance(contract_members, list):
        contract_members = []

    member_events = {
        event["data"]["target_resource"]: event
        for event in events
        if event.get("event_type") == "member_succeeded"
        and isinstance(event.get("data"), dict)
        and isinstance(event["data"].get("target_resource"), str)
    }
    members = _member_rows(
        [member for member in contract_members if isinstance(member, dict)],
        member_events,
    )
    committed = next(
        (event for event in events if event.get("event_type") == "set_committed"),
        None,
    )

    if committed is not None:
        state = "committed"
        reason = "historical journal records a successful incident-state commit"
    else:
        state = "stranded"
        reason = "journaled execution set is no longer present in the current routed plan"

    return _status_item(
        execution_set_id=execution_set_id,
        incident_id=current_incident_id,
        evidence_revision=evidence_revision,
        current=False,
        current_route_state=None,
        state=state,
        executable=False,
        reason=reason,
        diagnosis_target=(
            contract.get("diagnosis_target")
            if isinstance(contract.get("diagnosis_target"), str)
            else None
        ),
        probe_id=contract.get("probe_id") if isinstance(contract.get("probe_id"), str) else None,
        members=members,
        journal=_journal_metadata(
            present=True,
            integrity="verified",
            projection=projection,
        ),
        events=events,
    )


def build_execution_set_status(
    execution_sets_document: dict[str, Any],
    state_dir: Path,
) -> dict[str, Any]:
    execution_sets = _coerce_execution_sets(execution_sets_document)
    incident_id = execution_sets["incident_id"]
    evidence_revision = execution_sets["evidence_revision"]

    if state_dir.exists() and not state_dir.is_dir():
        raise ValueError(f"execution-set state path is not a directory: {state_dir}")

    current_by_id = {item["id"]: item for item in execution_sets["sets"]}
    statuses = [
        _current_status(
            item,
            incident_id=incident_id,
            evidence_revision=evidence_revision,
            state_dir=state_dir,
        )
        for item in sorted(execution_sets["sets"], key=lambda item: item["id"])
    ]

    if state_dir.exists():
        for path in sorted(state_dir.glob(f"*{JOURNAL_SUFFIX}")):
            execution_set_id = path.name[: -len(JOURNAL_SUFFIX)]
            if execution_set_id in current_by_id:
                continue
            if not EXECUTION_SET_ID_RE.fullmatch(execution_set_id):
                continue
            try:
                projection = verify_execution_set_journal(state_dir, execution_set_id)
            except (OSError, ValueError):
                # Invalid non-current journals cannot be safely attributed to this incident.
                continue
            historical = _historical_status(
                projection,
                current_incident_id=incident_id,
            )
            if historical is not None:
                statuses.append(historical)

    statuses.sort(
        key=lambda item: (
            0 if item["current"] else 1,
            -item["evidence_revision"],
            item["execution_set_id"],
        )
    )

    summary = {
        "total": len(statuses),
        "current": sum(1 for item in statuses if item["current"]),
        "historical": sum(1 for item in statuses if not item["current"]),
        **{
            state: sum(1 for item in statuses if item["state"] == state)
            for state in STATES
        },
    }
    document = {
        "schema_version": "0.1",
        "kind": "routed_execution_set_status",
        "incident_id": incident_id,
        "current_evidence_revision": evidence_revision,
        "summary": summary,
        "sets": statuses,
    }
    validate_execution_set_status(document)
    return document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Project operator-facing lifecycle status for current and historical "
            "Causcope routed execution sets."
        )
    )
    parser.add_argument(
        "--execution-sets",
        type=Path,
        required=True,
        help="routed_execution_sets or routed_agent_plan JSON document",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        required=True,
        help="directory containing durable execution-set journals",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        execution_sets = load_execution_sets_document(args.execution_sets)
        document = build_execution_set_status(execution_sets, args.state_dir)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(document, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

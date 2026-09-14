#!/usr/bin/env python3

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

COMMIT_SCHEMA_VERSION = "0.1"
FaultHook = Callable[[str], None]


class IncidentStateCommitError(ValueError):
    pass


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def canonical_hash(document: dict[str, Any]) -> str:
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def durable_atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(_canonical_bytes(document))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _durable_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    _fsync_directory(path.parent)


def default_commit_path(snapshot_path: Path) -> Path:
    return snapshot_path.with_name(snapshot_path.name + ".commit.json")


def _validate_commit(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise IncidentStateCommitError("incident state commit journal must be a JSON object")
    required = {
        "schema_version",
        "kind",
        "incident_id",
        "from_evidence_revision",
        "to_evidence_revision",
        "evidence_hash",
        "diagnosis_hash",
        "runtime_evidence",
        "diagnosis_snapshot",
    }
    if set(document) != required:
        raise IncidentStateCommitError("incident state commit journal has an invalid shape")
    if document.get("schema_version") != COMMIT_SCHEMA_VERSION or document.get("kind") != "incident_state_commit":
        raise IncidentStateCommitError("unsupported incident state commit journal")
    incident_id = document.get("incident_id")
    if not isinstance(incident_id, str) or not incident_id:
        raise IncidentStateCommitError("incident state commit requires incident_id")
    old_revision = document.get("from_evidence_revision")
    new_revision = document.get("to_evidence_revision")
    if not isinstance(old_revision, int) or not isinstance(new_revision, int) or new_revision != old_revision + 1:
        raise IncidentStateCommitError("incident state commit revisions must advance exactly once")
    evidence = document.get("runtime_evidence")
    snapshot = document.get("diagnosis_snapshot")
    if not isinstance(evidence, dict) or not isinstance(snapshot, dict):
        raise IncidentStateCommitError("incident state commit documents must be JSON objects")
    if evidence.get("incident_id") != incident_id or snapshot.get("incident_id") != incident_id:
        raise IncidentStateCommitError("incident state commit documents belong to another incident")
    if snapshot.get("evidence_revision") != new_revision:
        raise IncidentStateCommitError("incident state commit diagnosis revision does not match target revision")
    if document.get("evidence_hash") != canonical_hash(evidence):
        raise IncidentStateCommitError("incident state commit evidence hash mismatch")
    if document.get("diagnosis_hash") != canonical_hash(snapshot):
        raise IncidentStateCommitError("incident state commit diagnosis hash mismatch")
    return copy.deepcopy(document)


def prepare_commit(
    *,
    incident_id: str,
    from_evidence_revision: int,
    runtime_evidence: dict[str, Any],
    diagnosis_snapshot: dict[str, Any],
) -> dict[str, Any]:
    document = {
        "schema_version": COMMIT_SCHEMA_VERSION,
        "kind": "incident_state_commit",
        "incident_id": incident_id,
        "from_evidence_revision": from_evidence_revision,
        "to_evidence_revision": from_evidence_revision + 1,
        "evidence_hash": canonical_hash(runtime_evidence),
        "diagnosis_hash": canonical_hash(diagnosis_snapshot),
        "runtime_evidence": copy.deepcopy(runtime_evidence),
        "diagnosis_snapshot": copy.deepcopy(diagnosis_snapshot),
    }
    return _validate_commit(document)


def commit_incident_state(
    *,
    commit_path: Path,
    runtime_evidence_path: Path,
    snapshot_path: Path,
    commit: dict[str, Any],
    fault_hook: FaultHook | None = None,
) -> None:
    validated = _validate_commit(commit)
    durable_atomic_write_json(commit_path, validated)
    if fault_hook is not None:
        fault_hook("journal_durable")

    durable_atomic_write_json(runtime_evidence_path, validated["runtime_evidence"])
    if fault_hook is not None:
        fault_hook("evidence_replaced")

    durable_atomic_write_json(snapshot_path, validated["diagnosis_snapshot"])
    if fault_hook is not None:
        fault_hook("diagnosis_replaced")

    _durable_unlink(commit_path)
    if fault_hook is not None:
        fault_hook("commit_cleared")


def recover_incident_state_commit(
    *,
    commit_path: Path,
    runtime_evidence_path: Path,
    snapshot_path: Path,
) -> dict[str, Any] | None:
    if not commit_path.exists():
        return None
    try:
        document = json.loads(commit_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IncidentStateCommitError(f"cannot recover incident state commit journal: {exc}") from exc
    validated = _validate_commit(document)

    # A durable journal is the commit point. Recovery always rolls forward to the
    # exact evidence + deterministic diagnosis pair captured by that journal.
    durable_atomic_write_json(runtime_evidence_path, validated["runtime_evidence"])
    durable_atomic_write_json(snapshot_path, validated["diagnosis_snapshot"])
    _durable_unlink(commit_path)
    return {
        "kind": "incident_state_commit_recovery",
        "incident_id": validated["incident_id"],
        "evidence_revision": validated["to_evidence_revision"],
        "evidence_hash": validated["evidence_hash"],
        "diagnosis_hash": validated["diagnosis_hash"],
    }

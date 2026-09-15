#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from causal_projection import ROOT
from routed_execution_set_journal import execution_set_contract, verify_execution_set_journal
from routed_execution_set_status import (
    build_execution_set_status,
    load_execution_sets_document,
)
from routed_execution_sets import validate_routed_execution_sets

SCHEMA_PATH = ROOT / "schema" / "routed-execution-set-recovery.schema.json"
CLASSIFICATIONS = (
    "safe_to_resume",
    "safe_to_replay",
    "requires_operator_review",
    "superseded",
    "garbage_collectable",
)


def _load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_execution_set_recovery(
    document: dict[str, Any],
    *,
    schema_path: Path = SCHEMA_PATH,
) -> None:
    errors = sorted(
        Draft202012Validator(_load_schema(schema_path)).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ValueError(
            "execution-set recovery schema validation failed: "
            + "; ".join(error.message for error in errors)
        )
    summary = document["summary"]
    if summary["total"] != len(document["candidates"]):
        raise ValueError("execution-set recovery summary total does not match candidate count")
    if sum(summary[name] for name in CLASSIFICATIONS) != summary["total"]:
        raise ValueError("execution-set recovery classification counts do not add up")


def _current_contracts(execution_sets: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: execution_set_contract(item)
        for item in execution_sets["sets"]
    }


def _historical_contract(state_dir: Path, execution_set_id: str) -> dict[str, Any] | None:
    projection = verify_execution_set_journal(state_dir, execution_set_id)
    events = projection.get("events", [])
    if not events:
        return None
    first = events[0]
    if first.get("event_type") != "set_started":
        return None
    data = first.get("data")
    if not isinstance(data, dict):
        return None
    contract = data.get("contract")
    return copy.deepcopy(contract) if isinstance(contract, dict) else None


def _equivalent_current_set(
    historical_contract: dict[str, Any],
    execution_sets: dict[str, Any],
    contracts: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    matches = [
        item
        for item in execution_sets["sets"]
        if contracts[item["id"]] == historical_contract
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda item: item["id"])[0]


def _candidate(
    status: dict[str, Any],
    *,
    classification: str,
    reason: str,
    current_execution_set_id: str | None,
) -> dict[str, Any]:
    return {
        "execution_set_id": status["execution_set_id"],
        "evidence_revision": status["evidence_revision"],
        "current": status["current"],
        "lifecycle_state": status["state"],
        "journal_integrity": status["journal"]["integrity"],
        "classification": classification,
        "reason": reason,
        "current_execution_set_id": current_execution_set_id,
        "advisory_only": True,
        "automatic_cleanup_allowed": False,
    }


def build_execution_set_recovery(
    execution_sets_document: dict[str, Any],
    state_dir: Path,
) -> dict[str, Any]:
    execution_sets = copy.deepcopy(execution_sets_document)
    validate_routed_execution_sets(execution_sets)
    status = build_execution_set_status(execution_sets, state_dir)
    contracts = _current_contracts(execution_sets)
    current_by_id = {item["id"]: item for item in execution_sets["sets"]}
    candidates: list[dict[str, Any]] = []

    for item in status["sets"]:
        if item["journal"]["present"] is not True:
            continue
        lifecycle = item["state"]
        if lifecycle == "pending":
            continue

        if item["journal"]["integrity"] == "invalid":
            candidates.append(
                _candidate(
                    item,
                    classification="requires_operator_review",
                    reason="journal integrity or exact current-set contract validation failed; no stored evidence may be trusted automatically",
                    current_execution_set_id=item["execution_set_id"] if item["current"] else None,
                )
            )
            continue

        if item["current"] and lifecycle in {"in_progress", "ready_to_commit"}:
            current = current_by_id.get(item["execution_set_id"])
            if current is not None and current.get("state") == "ready" and item["executable"]:
                candidates.append(
                    _candidate(
                        item,
                        classification="safe_to_resume",
                        reason="the exact revision-bound set is still current, route-ready, and journal-verified; the existing controller may resume without repeating durable member results",
                        current_execution_set_id=item["execution_set_id"],
                    )
                )
            else:
                candidates.append(
                    _candidate(
                        item,
                        classification="requires_operator_review",
                        reason="durable progress exists but the exact current set is no longer route-ready or executable",
                        current_execution_set_id=item["execution_set_id"],
                    )
                )
            continue

        if item["current"]:
            candidates.append(
                _candidate(
                    item,
                    classification="requires_operator_review",
                    reason="a journaled current set is in a lifecycle state that must not be recovered automatically",
                    current_execution_set_id=item["execution_set_id"],
                )
            )
            continue

        if lifecycle == "committed":
            candidates.append(
                _candidate(
                    item,
                    classification="garbage_collectable",
                    reason="the historical journal records a successful commit; it is a retention candidate, but this projection never deletes audit history automatically",
                    current_execution_set_id=None,
                )
            )
            continue

        if lifecycle == "stranded":
            historical_contract = _historical_contract(state_dir, item["execution_set_id"])
            if historical_contract is None:
                candidates.append(
                    _candidate(
                        item,
                        classification="requires_operator_review",
                        reason="the verified historical journal does not expose a usable set_started contract",
                        current_execution_set_id=None,
                    )
                )
                continue
            equivalent = _equivalent_current_set(historical_contract, execution_sets, contracts)
            if equivalent is None:
                candidates.append(
                    _candidate(
                        item,
                        classification="superseded",
                        reason="the old revision-bound set is no longer current and no exact semantic route contract exists in the current plan; its durable member results must not be reused",
                        current_execution_set_id=None,
                    )
                )
            elif equivalent.get("state") == "ready":
                candidates.append(
                    _candidate(
                        item,
                        classification="safe_to_replay",
                        reason="the old revision-bound journal cannot resume, but an exact equivalent route contract is ready in the current revision; execute the current set from scratch rather than reusing stale member evidence",
                        current_execution_set_id=equivalent["id"],
                    )
                )
            else:
                candidates.append(
                    _candidate(
                        item,
                        classification="requires_operator_review",
                        reason="an exact equivalent current route contract exists, but the current execution set is blocked",
                        current_execution_set_id=equivalent["id"],
                    )
                )

    candidates.sort(
        key=lambda item: (
            0 if item["current"] else 1,
            -item["evidence_revision"],
            item["execution_set_id"],
        )
    )
    document = {
        "schema_version": "0.1",
        "kind": "routed_execution_set_recovery",
        "incident_id": execution_sets["incident_id"],
        "current_evidence_revision": execution_sets["evidence_revision"],
        "summary": {
            "total": len(candidates),
            **{
                name: sum(1 for item in candidates if item["classification"] == name)
                for name in CLASSIFICATIONS
            },
        },
        "candidates": candidates,
    }
    validate_execution_set_recovery(document)
    return document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Project advisory recovery policy for journaled routed execution sets."
    )
    parser.add_argument("--execution-sets", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    execution_sets = load_execution_sets_document(args.execution_sets)
    document = build_execution_set_recovery(execution_sets, args.state_dir)
    print(json.dumps(document, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

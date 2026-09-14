#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from causal_projection import ROOT, load_concepts
from live_diagnosis import normalize_scope, scope_key
from runtime_evidence import load_runtime_evidence


class VerificationProtocolError(ValueError):
    pass


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise VerificationProtocolError(f"invalid RFC3339 timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise VerificationProtocolError(f"timestamp must include timezone: {value}")
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _find_diagnosis(snapshot: dict[str, Any], *, target: str, scope: dict[str, Any] | None) -> dict[str, Any]:
    wanted = scope_key(scope)
    matches = [
        diagnosis
        for partition in snapshot.get("partitions", [])
        if scope_key(partition.get("scope")) == wanted
        for diagnosis in partition.get("diagnoses", [])
        if diagnosis.get("target") == target
    ]
    if len(matches) != 1:
        raise VerificationProtocolError(
            f"expected exactly one diagnosis for target {target} and original scope, got {len(matches)}"
        )
    return matches[0]


def build_verification_contract(
    *,
    snapshot: dict[str, Any],
    target: str,
    scope: dict[str, Any] | None,
    fix_applied_at: datetime,
    concepts: dict[str, dict[str, Any]],
    criteria_observations: list[str] | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    incident_id = snapshot.get("incident_id")
    revision = snapshot.get("evidence_revision")
    if not isinstance(incident_id, str) or not incident_id:
        raise VerificationProtocolError("diagnosis snapshot requires incident_id")
    if not isinstance(revision, int) or revision < 0:
        raise VerificationProtocolError("diagnosis snapshot requires non-negative evidence_revision")

    normalized_scope = normalize_scope(scope, concepts)
    _find_diagnosis(snapshot, target=target, scope=normalized_scope)

    observations = criteria_observations or [target]
    observations = list(dict.fromkeys(observations))
    if not observations or any(not isinstance(item, str) or not item for item in observations):
        raise VerificationProtocolError("verification criteria must contain non-empty observation ids")
    for observation in observations:
        concept = concepts.get(observation)
        if not isinstance(concept, dict) or concept.get("kind") != "observation":
            raise VerificationProtocolError(f"verification criterion is not a canonical observation: {observation}")

    created = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    fixed = fix_applied_at.astimezone(timezone.utc)
    if created < fixed:
        raise VerificationProtocolError("verification contract cannot be created before fix_applied_at")

    return {
        "schema_version": "0.1",
        "kind": "verification_contract",
        "incident_id": incident_id,
        "baseline_evidence_revision": revision,
        "target": target,
        "original_scope": copy.deepcopy(normalized_scope),
        "fix_applied_at": _format_timestamp(fixed),
        "created_at": _format_timestamp(created),
        "criteria": [
            {"observation": observation, "expected_state": "absent"}
            for observation in observations
        ],
    }


def _active_post_fix_instances(
    *,
    evidence: dict[str, Any],
    observation: str,
    scope: dict[str, Any] | None,
    fix_applied_at: datetime,
    evaluated_at: datetime,
    concepts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    wanted_scope = scope_key(scope)
    output: list[tuple[datetime, dict[str, Any]]] = []
    for instance in evidence.get("instances", []):
        if instance.get("observation") != observation:
            continue
        normalized_scope = normalize_scope(instance.get("scope"), concepts)
        if scope_key(normalized_scope) != wanted_scope:
            continue
        observed_at = _parse_timestamp(instance.get("observed_at"))
        if observed_at < fix_applied_at or observed_at > evaluated_at:
            continue
        expires_at = instance.get("expires_at")
        if expires_at is not None and _parse_timestamp(expires_at) < evaluated_at:
            continue
        output.append((observed_at, instance))

    output.sort(key=lambda item: (item[0], item[1].get("id", "")))
    return [copy.deepcopy(item[1]) for item in output]


def evaluate_verification(
    *,
    contract: dict[str, Any],
    evidence: dict[str, Any],
    concepts: dict[str, dict[str, Any]],
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    if contract.get("kind") != "verification_contract":
        raise VerificationProtocolError("expected verification_contract")
    if evidence.get("kind") != "runtime_evidence":
        raise VerificationProtocolError("expected runtime_evidence")
    if evidence.get("incident_id") != contract.get("incident_id"):
        raise VerificationProtocolError("verification contract and evidence belong to different incidents")

    scope = normalize_scope(contract.get("original_scope"), concepts)
    fixed = _parse_timestamp(contract.get("fix_applied_at"))
    now = (evaluated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if now < fixed:
        raise VerificationProtocolError("cannot evaluate verification before fix_applied_at")

    criterion_results: list[dict[str, Any]] = []
    for criterion in contract.get("criteria", []):
        observation = criterion.get("observation")
        if criterion.get("expected_state") != "absent":
            raise VerificationProtocolError("verification v0 supports only expected_state=absent")
        instances = _active_post_fix_instances(
            evidence=evidence,
            observation=observation,
            scope=scope,
            fix_applied_at=fixed,
            evaluated_at=now,
            concepts=concepts,
        )
        if not instances:
            criterion_results.append(
                {
                    "observation": observation,
                    "expected_state": "absent",
                    "status": "inconclusive",
                    "evidence_instance_ids": [],
                    "reason": "no active post-fix evidence for the original incident scope",
                }
            )
            continue

        latest_time = max(_parse_timestamp(item["observed_at"]) for item in instances)
        latest = [item for item in instances if _parse_timestamp(item["observed_at"]) == latest_time]
        latest_ids = sorted(item["id"] for item in latest)

        # A same-timestamp conflict fails toward regression; an observed failure must
        # never be hidden by a simultaneous absent sample.
        if any(item.get("state") == "observed" for item in latest):
            status = "regressed"
            reason = "latest post-fix evidence still observes the original failure condition"
        elif all(item.get("state") == "absent" for item in latest):
            status = "resolved"
            reason = "latest active post-fix evidence explicitly reports the failure condition absent"
        else:
            status = "inconclusive"
            reason = "latest post-fix evidence does not establish an explicit state"

        criterion_results.append(
            {
                "observation": observation,
                "expected_state": "absent",
                "status": status,
                "evidence_instance_ids": latest_ids,
                "reason": reason,
            }
        )

    statuses = {item["status"] for item in criterion_results}
    if "regressed" in statuses:
        outcome = "regressed"
    elif statuses == {"resolved"}:
        outcome = "resolved"
    else:
        outcome = "inconclusive"

    return {
        "schema_version": "0.1",
        "kind": "verification_result",
        "incident_id": contract["incident_id"],
        "target": contract["target"],
        "baseline_evidence_revision": contract["baseline_evidence_revision"],
        "original_scope": copy.deepcopy(scope),
        "fix_applied_at": contract["fix_applied_at"],
        "evaluated_at": _format_timestamp(now),
        "outcome": outcome,
        "criteria": criterion_results,
    }


def _load_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise VerificationProtocolError(f"{path} must contain a JSON object")
    return document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or evaluate Causcope verification contracts.")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Freeze an original failing scope into a verification contract")
    create.add_argument("--snapshot", type=Path, required=True)
    create.add_argument("--target", required=True)
    create.add_argument("--scope", type=Path, help="JSON file containing the exact diagnosis scope; omit for null scope")
    create.add_argument("--fix-applied-at", required=True)
    create.add_argument("--criterion", action="append", dest="criteria")

    evaluate = sub.add_parser("evaluate", help="Evaluate post-fix evidence against a verification contract")
    evaluate.add_argument("--contract", type=Path, required=True)
    evaluate.add_argument("--evidence", type=Path, required=True)
    evaluate.add_argument("--as-of")
    return parser


def main(root: Path = ROOT) -> int:
    args = build_parser().parse_args()
    concepts = load_concepts(root)
    if args.command == "create":
        scope = _load_json(args.scope) if args.scope else None
        contract = build_verification_contract(
            snapshot=_load_json(args.snapshot),
            target=args.target,
            scope=scope,
            fix_applied_at=_parse_timestamp(args.fix_applied_at),
            concepts=concepts,
            criteria_observations=args.criteria,
        )
        print(json.dumps(contract, indent=2, sort_keys=True))
        return 0

    contract = _load_json(args.contract)
    evidence = load_runtime_evidence(args.evidence)
    result = evaluate_verification(
        contract=contract,
        evidence=evidence,
        concepts=concepts,
        evaluated_at=_parse_timestamp(args.as_of) if args.as_of else None,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

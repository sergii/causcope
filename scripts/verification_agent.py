#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from autonomous_investigation import ProbeInsufficientEvidence
from causal_projection import ROOT
from instrument_router import InstrumentRouter
from live_diagnosis import normalize_scope, scope_key
from runtime_evidence_composition import compose_runtime_evidence
from verification_protocol import evaluate_verification

SCHEMA_PATH = ROOT / "schema" / "verification-agent-plan.schema.json"


class VerificationAgentError(ValueError):
    pass


def _schema() -> dict[str, Any]:
    document = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(document)
    return document


def validate_verification_agent_plan(document: dict[str, Any]) -> None:
    errors = sorted(Draft202012Validator(_schema()).iter_errors(document), key=lambda error: list(error.path))
    if errors:
        raise VerificationAgentError(
            "verification agent plan schema validation failed: "
            + "; ".join(error.message for error in errors)
        )


def _candidate_probes(observation: str, concepts: dict[str, dict[str, Any]]) -> list[str]:
    output = []
    for concept_id, concept in concepts.items():
        if concept.get("kind") != "probe" or concept.get("risk") != "read_only":
            continue
        if observation in concept.get("produces", []):
            output.append(concept_id)
    return sorted(output)


def _route_produces_observation(route: dict[str, Any], observation: str) -> bool:
    selection = route.get("selection")
    if not isinstance(selection, dict):
        return False
    selected_id = selection.get("instrument", {}).get("id")
    return any(
        candidate.get("eligible") is True
        and candidate.get("instrument", {}).get("id") == selected_id
        and observation in candidate.get("observations", [])
        for candidate in route.get("candidates", [])
    )


def build_verification_agent_plan(
    *,
    contract: dict[str, Any],
    evidence: dict[str, Any],
    concepts: dict[str, dict[str, Any]],
    router: InstrumentRouter,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    result = evaluate_verification(
        contract=contract,
        evidence=evidence,
        concepts=concepts,
        evaluated_at=evaluated_at,
    )
    scope = normalize_scope(contract.get("original_scope"), concepts)
    criteria = []
    for criterion_result in result["criteria"]:
        observation = criterion_result["observation"]
        current_status = criterion_result["status"]
        probes = _candidate_probes(observation, concepts)
        selected_probe = None
        selected_route = None

        if current_status == "resolved":
            action = "already_satisfied"
        elif current_status == "regressed":
            action = "regression_detected"
        elif not probes:
            action = "no_canonical_probe"
        else:
            action = "no_safe_instrument"
            for probe_id in probes:
                route = router.route(probe_id, scope, execution_requirement="direct")
                if route.get("selection") is None:
                    continue
                if not _route_produces_observation(route, observation):
                    continue
                selected_probe = probe_id
                selected_route = route
                action = "execute_direct_probe"
                break

        criteria.append(
            {
                "observation": observation,
                "expected_state": "absent",
                "current_status": current_status,
                "action": action,
                "candidate_probes": probes,
                "selected_probe": selected_probe,
                "routing": copy.deepcopy(selected_route),
            }
        )

    document = {
        "schema_version": "0.1",
        "kind": "verification_agent_plan",
        "incident_id": contract["incident_id"],
        "baseline_evidence_revision": contract["baseline_evidence_revision"],
        "target": contract["target"],
        "original_scope": copy.deepcopy(scope),
        "fix_applied_at": contract["fix_applied_at"],
        "outcome_before": result["outcome"],
        "criteria": criteria,
        "executable": any(item["action"] == "execute_direct_probe" for item in criteria),
    }
    validate_verification_agent_plan(document)
    return document


def _validate_verification_evidence(
    *,
    produced: dict[str, Any],
    contract: dict[str, Any],
    observation: str,
    concepts: dict[str, dict[str, Any]],
) -> None:
    if produced.get("kind") != "runtime_evidence":
        raise VerificationAgentError("verification instrument must return runtime_evidence")
    if produced.get("incident_id") != contract.get("incident_id"):
        raise VerificationAgentError("verification instrument returned evidence for another incident")
    wanted_scope = scope_key(normalize_scope(contract.get("original_scope"), concepts))
    matching = 0
    for instance in produced.get("instances", []):
        if instance.get("observation") != observation:
            continue
        if scope_key(normalize_scope(instance.get("scope"), concepts)) != wanted_scope:
            raise VerificationAgentError("verification instrument attempted cross-scope evidence")
        matching += 1
    if matching == 0:
        raise VerificationAgentError(
            f"verification instrument did not emit requested criterion observation {observation}"
        )


def run_autonomous_verification(
    *,
    contract: dict[str, Any],
    evidence: dict[str, Any],
    concepts: dict[str, dict[str, Any]],
    router: InstrumentRouter,
    evaluated_at: datetime | None = None,
    max_steps: int = 4,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if max_steps < 1 or max_steps > 16:
        raise VerificationAgentError("max_steps must be between 1 and 16")
    now = (evaluated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    current = copy.deepcopy(evidence)
    attempted: set[str] = set()
    steps: list[dict[str, Any]] = []

    for index in range(1, max_steps + 1):
        result = evaluate_verification(contract=contract, evidence=current, concepts=concepts, evaluated_at=now)
        if result["outcome"] in {"resolved", "regressed"}:
            stop_reason = result["outcome"]
            break
        plan = build_verification_agent_plan(
            contract=contract,
            evidence=current,
            concepts=concepts,
            router=router,
            evaluated_at=now,
        )
        executable = [
            item for item in plan["criteria"]
            if item["action"] == "execute_direct_probe" and item["observation"] not in attempted
        ]
        if not executable:
            stop_reason = "no_executable_verification_route"
            break
        criterion = executable[0]
        observation = criterion["observation"]
        probe_id = criterion["selected_probe"]
        attempted.add(observation)
        try:
            produced = router.execute(probe_id, contract["target"], copy.deepcopy(contract.get("original_scope")))
        except ProbeInsufficientEvidence as exc:
            steps.append(
                {
                    "index": index,
                    "status": "insufficient_evidence",
                    "observation": observation,
                    "probe_id": probe_id,
                    "instrument_id": criterion["routing"]["selection"]["instrument"]["id"],
                    "reason": str(exc),
                    "evidence_instance_ids": [],
                }
            )
            continue

        _validate_verification_evidence(
            produced=produced,
            contract=contract,
            observation=observation,
            concepts=concepts,
        )
        old_ids = {item["id"] for item in current.get("instances", [])}
        current = compose_runtime_evidence([current, produced], concepts)
        new_ids = sorted(item["id"] for item in current["instances"] if item["id"] not in old_ids)
        after = evaluate_verification(contract=contract, evidence=current, concepts=concepts, evaluated_at=now)
        steps.append(
            {
                "index": index,
                "status": "completed",
                "observation": observation,
                "probe_id": probe_id,
                "instrument_id": criterion["routing"]["selection"]["instrument"]["id"],
                "reason": None,
                "evidence_instance_ids": new_ids,
                "outcome_after": after["outcome"],
            }
        )
    else:
        stop_reason = "max_steps"

    final_result = evaluate_verification(contract=contract, evidence=current, concepts=concepts, evaluated_at=now)
    report = {
        "schema_version": "0.1",
        "kind": "autonomous_verification_run",
        "incident_id": contract["incident_id"],
        "target": contract["target"],
        "original_scope": copy.deepcopy(normalize_scope(contract.get("original_scope"), concepts)),
        "fix_applied_at": contract["fix_applied_at"],
        "evaluated_at": final_result["evaluated_at"],
        "max_steps": max_steps,
        "stop_reason": stop_reason,
        "outcome": final_result["outcome"],
        "steps": steps,
    }
    return current, final_result, report

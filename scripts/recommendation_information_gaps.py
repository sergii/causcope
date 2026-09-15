#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from causal_projection import ROOT, load_concepts

INPUT_SCHEMA = ROOT / "schema" / "architectural-recommendation-projection.schema.json"
OUTPUT_SCHEMA = ROOT / "schema" / "recommendation-information-gap-projection.schema.json"
SUPPORTED_RECOMMENDATION = "recommendation.database.denormalize_read_model"

RANKING_PRIORITY = [
    "refresh_active_problem_evidence",
    "establish_workload_materiality",
    "establish_business_semantics",
    "define_bounded_candidate_change",
    "establish_maintenance_semantics",
    "quantify_tradeoff_cost",
    "define_verification_plan",
    "demonstrate_benefit",
    "gap_id",
]

LIMITATIONS = [
    "Information-gap ranking does not change causal ranking or recommendation maturity by itself.",
    "Operator questions are requests for domain knowledge, not inferred facts.",
    "Read-only probes are referenced from the existing probe catalog but are not executed by this projection.",
    "Safe experiments are plans only; this projection never authorizes state-changing execution.",
]

GAP_RULES: dict[str, dict[str, Any]] = {
    "workload.read_frequency_per_minute_positive": {
        "id": "information_gap.workload.read_frequency",
        "category": "workload",
        "priority": 20,
        "decision_leverage": "can_invalidate_candidate",
        "acquisition_kind": "operator_question",
        "question": "What is the measured production read frequency for this exact workload during the relevant window?",
        "why_now": "If the workload is not materially exercised, spending effort on a structural read-model change is premature.",
    },
    "workload.query_contribution_known": {
        "id": "information_gap.workload.query_contribution",
        "category": "workload",
        "priority": 21,
        "decision_leverage": "can_invalidate_candidate",
        "acquisition_kind": "operator_question",
        "question": "What measured share of the affected request latency or SLO miss is attributable to this exact query path?",
        "why_now": "A slow database query does not justify architecture work unless it materially contributes to the system outcome being optimized.",
    },
    "business_semantics": {
        "id": "information_gap.business_semantics.consistency_contract",
        "category": "business_semantics",
        "priority": 30,
        "decision_leverage": "can_invalidate_candidate",
        "acquisition_kind": "operator_question",
        "question": "What is the source of truth, what consistency invariant must remain true, and how stale may the derived value be? Is duplicated data a mutable shared fact, a historical snapshot, or an intentional projection?",
        "why_now": "Business and consistency semantics can make a proposed normalization or denormalization change invalid even when the current query is expensive.",
    },
    "proposed_change": {
        "id": "information_gap.candidate_design.bounded_change",
        "category": "candidate_design",
        "priority": 40,
        "decision_leverage": "constrains_design",
        "acquisition_kind": "operator_question",
        "question": "What exact bounded structural change is being considered for this workload, and which read path would consume it?",
        "why_now": "Benefit, consistency cost, and verification cannot be evaluated against an unspecified architecture change.",
    },
    "maintenance": {
        "id": "information_gap.maintenance.consistency_strategy",
        "category": "maintenance",
        "priority": 50,
        "decision_leverage": "constrains_design",
        "acquisition_kind": "operator_question",
        "question": "How will the derived state be updated, retried after duplicate delivery, handled on partial failure, and reconciled when drift occurs?",
        "why_now": "For denormalized state, retry, partial-failure, and reconciliation behavior are part of the architecture decision rather than implementation details.",
    },
    "cost": {
        "id": "information_gap.cost.maintenance_cost",
        "category": "cost",
        "priority": 60,
        "decision_leverage": "quantifies_tradeoff",
        "acquisition_kind": "operator_question",
        "question": "What write amplification, storage growth, operational complexity, and new failure modes would this candidate introduce?",
        "why_now": "A read-latency win is incomplete unless the write and operational costs are explicit.",
    },
    "verification": {
        "id": "information_gap.verification.plan",
        "category": "verification",
        "priority": 70,
        "decision_leverage": "defines_verification",
        "acquisition_kind": "operator_question",
        "question": "What bounded before/after, shadow-read, or equivalent experiment will verify both performance and correctness, and what rollback criteria apply?",
        "why_now": "A recommendation should not advance to benefit claims until success criteria and rollback are defined.",
    },
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return document


def validate_schema(document: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ValueError(
            f"{label} schema validation failed: "
            + "; ".join(error.message for error in errors)
        )


def _gap_from_rule(missing_assumption: str) -> dict[str, Any]:
    rule = GAP_RULES.get(missing_assumption)
    if rule is None:
        raise ValueError(
            "unsupported recommendation missing_assumption; add explicit information-gap semantics first: "
            + missing_assumption
        )
    return {
        "id": rule["id"],
        "category": rule["category"],
        "rank": rule["priority"],
        "decision_leverage": rule["decision_leverage"],
        "acquisition_kind": rule["acquisition_kind"],
        "question": rule["question"],
        "why_now": rule["why_now"],
        "blocks_progression": True,
        "missing_assumption": missing_assumption,
    }


def _problem_evidence_gap(projection: dict[str, Any]) -> dict[str, Any]:
    gap: dict[str, Any] = {
        "id": "information_gap.problem_evidence.active_query_latency",
        "category": "problem_evidence",
        "rank": 10,
        "decision_leverage": "refreshes_evidence",
        "acquisition_kind": "read_only_probe",
        "question": "Does a fresh exact-target measurement still show the query-latency problem for this workload?",
        "why_now": "Architecture work should not proceed from stale or missing query-latency evidence.",
        "blocks_progression": True,
        "probe_id": "probe.database.measure_query_latency",
        "requested_observation": "observation.database.query_latency",
    }
    if "evidence_scope" in projection:
        gap["scope"] = copy.deepcopy(projection["evidence_scope"])
    return gap


def _benefit_gap(projection: dict[str, Any], *, measured_required: bool) -> dict[str, Any]:
    verification = projection.get("verification", {})
    experiment = verification.get("experiment") if isinstance(verification, dict) else None
    if measured_required:
        question = (
            "What measured before/after result does the bounded verification experiment produce for the real or representative workload?"
        )
        why_now = (
            "Planner or benchmark evidence can support a candidate, but it is not a measured production improvement."
        )
    else:
        question = (
            "Does the bounded verification experiment demonstrate a meaningful benefit over the current read path?"
        )
        why_now = (
            "The semantic and maintenance preconditions are present, but the candidate still lacks trustworthy benefit evidence."
        )
    if isinstance(experiment, str) and experiment:
        question += " Planned experiment: " + experiment
    return {
        "id": "information_gap.benefit.measured_improvement" if measured_required else "information_gap.benefit.demonstrated_improvement",
        "category": "benefit",
        "rank": 80,
        "decision_leverage": "demonstrates_benefit",
        "acquisition_kind": "safe_experiment",
        "question": question,
        "why_now": why_now,
        "blocks_progression": True,
    }


def _validate_catalog_probe(gap: dict[str, Any], concepts: dict[str, dict[str, Any]]) -> None:
    if gap["acquisition_kind"] != "read_only_probe":
        return
    probe_id = gap.get("probe_id")
    probe = concepts.get(probe_id)
    if not isinstance(probe, dict) or probe.get("kind") != "probe":
        raise ValueError(f"information gap references unknown probe: {probe_id}")
    if probe.get("risk") != "read_only":
        raise ValueError(f"information gap probe must be read_only: {probe_id}")
    observation = gap.get("requested_observation")
    if observation not in probe.get("produces", []):
        raise ValueError(
            f"information gap probe {probe_id} does not produce requested observation: {observation}"
        )


def _action_from_gap(gap: dict[str, Any]) -> dict[str, Any]:
    kind = gap["acquisition_kind"]
    boundaries = {
        "operator_question": "question_only",
        "read_only_probe": "existing_read_only_probe",
        "safe_experiment": "experiment_plan_only",
    }
    action: dict[str, Any] = {
        "kind": kind,
        "gap_id": gap["id"],
        "prompt": gap["question"],
        "reason": gap["why_now"],
        "execution_boundary": boundaries[kind],
    }
    for key in ("probe_id", "requested_observation", "scope"):
        if key in gap:
            action[key] = copy.deepcopy(gap[key])
    return action


def _terminal_action(state: str) -> dict[str, Any]:
    if state == "READY_FOR_HUMAN_REVIEW":
        return {
            "kind": "human_decision",
            "prompt": "Review the causal basis, measured benefit, consistency contract, maintenance cost, verification criteria, and rollback plan, then approve or reject the candidate architecture change.",
            "reason": "The evidence gate is satisfied, but architectural changes remain a human decision.",
            "execution_boundary": "human_decision_required",
        }
    if state == "BENEFIT_NOT_DEMONSTRATED":
        return {
            "kind": "stop_candidate",
            "prompt": "Stop advancing this candidate unless a materially different design or new evidence justifies reopening it.",
            "reason": "The bounded experiment did not demonstrate benefit, so the recommendation must not survive by inertia.",
            "execution_boundary": "stop_without_more_evidence",
        }
    raise ValueError(f"no terminal action for recommendation state: {state}")


def project(recommendation_projection: dict[str, Any]) -> dict[str, Any]:
    validate_schema(
        recommendation_projection,
        INPUT_SCHEMA,
        "architectural recommendation projection",
    )
    if recommendation_projection["recommendation_id"] != SUPPORTED_RECOMMENDATION:
        raise ValueError(
            "RFC 0067 proof supports only recommendation.database.denormalize_read_model"
        )

    state = recommendation_projection["state"]
    missing = recommendation_projection.get("missing_assumptions", [])
    if state == "INSUFFICIENT_CONTEXT" and not missing:
        raise ValueError("INSUFFICIENT_CONTEXT must expose at least one missing_assumption")
    if state in {
        "EXPERIMENT_REQUIRED",
        "BENEFIT_NOT_DEMONSTRATED",
        "ESTIMATED_BENEFIT",
        "READY_FOR_HUMAN_REVIEW",
    } and missing:
        raise ValueError(f"{state} must not retain missing_assumptions")

    gaps: list[dict[str, Any]] = []
    if state == "NO_PROBLEM_EVIDENCE":
        gaps.append(_problem_evidence_gap(recommendation_projection))
        gaps.extend(_gap_from_rule(item) for item in missing)
        status = "EVIDENCE_REFRESH_REQUIRED"
    elif state == "INSUFFICIENT_CONTEXT":
        gaps.extend(_gap_from_rule(item) for item in missing)
        status = "INFORMATION_GAP"
    elif state == "EXPERIMENT_REQUIRED":
        gaps.append(_benefit_gap(recommendation_projection, measured_required=False))
        status = "EXPERIMENT_REQUIRED"
    elif state == "ESTIMATED_BENEFIT":
        gaps.append(_benefit_gap(recommendation_projection, measured_required=True))
        status = "EXPERIMENT_REQUIRED"
    elif state == "BENEFIT_NOT_DEMONSTRATED":
        status = "CANDIDATE_REJECTED"
    elif state == "READY_FOR_HUMAN_REVIEW":
        status = "HUMAN_REVIEW_READY"
    else:
        raise ValueError(f"unsupported recommendation state: {state}")

    gaps.sort(key=lambda gap: (gap["rank"], gap["id"]))
    for index, gap in enumerate(gaps, start=1):
        gap["rank"] = index

    concepts = load_concepts(ROOT)
    for gap in gaps:
        _validate_catalog_probe(gap, concepts)

    if gaps:
        next_action = _action_from_gap(gaps[0])
    else:
        next_action = _terminal_action(state)

    output = {
        "schema_version": "0.1",
        "kind": "recommendation_information_gap_projection",
        "system_id": recommendation_projection["system_id"],
        "revision": copy.deepcopy(recommendation_projection["revision"]),
        "incident_id": recommendation_projection["incident_id"],
        "recommendation_id": recommendation_projection["recommendation_id"],
        "subject_resource": recommendation_projection["subject_resource"],
        "recommendation_state": state,
        "status": status,
        "gaps": gaps,
        "next_action": next_action,
        "ranking_method": {
            "type": "deterministic_ordinal",
            "purpose": "close_recommendation_information_gaps",
            "priority": RANKING_PRIORITY,
        },
        "limitations": LIMITATIONS,
    }
    validate_schema(output, OUTPUT_SCHEMA, "information gap projection")
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rank missing information and the next action for an architectural recommendation projection."
    )
    parser.add_argument("--recommendation-projection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        recommendation_projection = load_json(args.recommendation_projection)
        output = project(recommendation_projection)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    args.output.write_text(
        json.dumps(output, indent=2 if args.pretty else None, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

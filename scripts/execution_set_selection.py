#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
from typing import Any

RISK_ORDER = {"read_only": 0, "low": 1, "state_changing": 2, "high": 3}
SEMANTIC_PRIORITY = [
    "more_top_candidate_two_sided_alternatives",
    "more_top_candidate_contrast_components",
    "more_top_candidate_discriminated_alternatives",
    "more_two_sided_candidate_pairs",
    "more_contrast_components",
    "more_discriminated_candidate_pairs",
    "lower_probe_risk",
    "more_hypotheses_explicitly_tested",
]


def _scope_key(scope: dict[str, Any] | None) -> str:
    return json.dumps(scope, sort_keys=True, separators=(",", ":"))


def _semantic_priority(candidate: dict[str, Any]) -> tuple[int, ...]:
    factors = candidate.get("factors", {})
    if not isinstance(factors, dict):
        raise ValueError("probe candidate is missing semantic ranking factors")
    risk = candidate.get("risk")
    if risk not in RISK_ORDER:
        raise ValueError(f"probe candidate has unknown risk: {risk}")
    hypotheses_tested = candidate.get("hypotheses_tested", [])
    if not isinstance(hypotheses_tested, list):
        raise ValueError("probe candidate hypotheses_tested must be an array")

    def count(name: str) -> int:
        value = factors.get(name)
        if not isinstance(value, list):
            raise ValueError(f"probe candidate factor {name} must be an array")
        return len(value)

    def integer(name: str) -> int:
        value = factors.get(name)
        if not isinstance(value, int):
            raise ValueError(f"probe candidate factor {name} must be an integer")
        return value

    return (
        -count("top_candidate_two_sided_alternatives"),
        -integer("top_candidate_contrast_components"),
        -count("top_candidate_discriminated_alternatives"),
        -count("two_sided_candidate_pairs"),
        -integer("contrast_components"),
        -count("discriminated_candidate_pairs"),
        RISK_ORDER[risk],
        -len(hypotheses_tested),
    )


def _candidate_for_set(
    snapshot: dict[str, Any],
    execution_set: dict[str, Any],
) -> dict[str, Any]:
    wanted_scope = _scope_key(execution_set.get("scope"))
    wanted_target = execution_set.get("diagnosis_target")
    wanted_probe = execution_set.get("probe_id")
    matches: list[dict[str, Any]] = []

    for partition in snapshot.get("partitions", []):
        if not isinstance(partition, dict) or _scope_key(partition.get("scope")) != wanted_scope:
            continue
        for diagnosis in partition.get("diagnoses", []):
            if not isinstance(diagnosis, dict) or diagnosis.get("target") != wanted_target:
                continue
            ranking = diagnosis.get("probe_ranking", {})
            probes = ranking.get("probes", []) if isinstance(ranking, dict) else []
            if ranking.get("found") is not True or not isinstance(probes, list) or not probes:
                continue
            top = probes[0]
            probe = top.get("probe", {}) if isinstance(top, dict) else {}
            if isinstance(probe, dict) and probe.get("id") == wanted_probe:
                matches.append(top)

    if len(matches) != 1:
        raise ValueError(
            "ready execution set must map to exactly one current top semantic probe: "
            f"{execution_set.get('id')} matched {len(matches)}"
        )
    return matches[0]


def select_ready_execution_set(
    snapshot: dict[str, Any],
    execution_sets: dict[str, Any],
) -> dict[str, Any]:
    """Choose one ready set only when semantic evidence value makes it uniquely best.

    The comparison reuses the existing deterministic probe-ranking dimensions but
    deliberately omits the final probe-id lexical tie-break. Probe IDs, diagnosis
    targets, scopes, and execution-set IDs are identities, not evidence that one
    diagnostic question is more valuable than another. A semantic tie therefore
    remains ambiguous and cannot authorize autonomous execution.
    """

    if snapshot.get("kind") != "diagnosis_snapshot":
        raise ValueError("execution-set selection requires a diagnosis_snapshot")
    if execution_sets.get("kind") != "routed_execution_sets":
        raise ValueError("execution-set selection requires routed_execution_sets")
    if execution_sets.get("incident_id") != snapshot.get("incident_id"):
        raise ValueError("execution sets belong to another incident")
    if execution_sets.get("evidence_revision") != snapshot.get("evidence_revision"):
        raise ValueError("execution sets belong to another evidence revision")

    candidates: list[dict[str, Any]] = []
    for execution_set in execution_sets.get("sets", []):
        if not isinstance(execution_set, dict) or execution_set.get("state") != "ready":
            continue
        candidate = _candidate_for_set(snapshot, execution_set)
        if candidate.get("risk") != "read_only":
            continue
        priority = _semantic_priority(candidate)
        candidates.append(
            {
                "execution_set_id": execution_set["id"],
                "diagnosis_target": execution_set["diagnosis_target"],
                "scope": copy.deepcopy(execution_set.get("scope")),
                "probe_id": execution_set["probe_id"],
                "semantic_priority": list(priority),
                "best": False,
            }
        )

    if not candidates:
        return {
            "state": "none",
            "selected_execution_set_id": None,
            "reason": "no_read_only_ready_execution_set",
            "ranking_method": {
                "type": "deterministic_ordinal",
                "priority": SEMANTIC_PRIORITY,
                "lexical_tie_break": False,
            },
            "candidates": [],
        }

    best_priority = min(tuple(item["semantic_priority"]) for item in candidates)
    best = [item for item in candidates if tuple(item["semantic_priority"]) == best_priority]
    for item in best:
        item["best"] = True
    candidates.sort(key=lambda item: item["execution_set_id"])

    if len(best) != 1:
        return {
            "state": "ambiguous",
            "selected_execution_set_id": None,
            "reason": "semantic_priority_tie",
            "ranking_method": {
                "type": "deterministic_ordinal",
                "priority": SEMANTIC_PRIORITY,
                "lexical_tie_break": False,
            },
            "candidates": candidates,
        }

    return {
        "state": "selected",
        "selected_execution_set_id": best[0]["execution_set_id"],
        "reason": "unique_best_semantic_probe_priority",
        "ranking_method": {
            "type": "deterministic_ordinal",
            "priority": SEMANTIC_PRIORITY,
            "lexical_tie_break": False,
        },
        "candidates": candidates,
    }

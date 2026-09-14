#!/usr/bin/env python3

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Callable

from live_diagnosis import build_diagnosis_snapshot, normalize_scope, scope_key
from runtime_evidence import format_timestamp, validate_runtime_references
from runtime_evidence_composition import compose_runtime_evidence


class ProbeInsufficientEvidence(ValueError):
    """The selected read-only probe could not make a justified observed/absent claim."""


ProbeExecutor = Callable[[str, str, dict[str, Any] | None], dict[str, Any]]
Clock = Callable[[], datetime]


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _top_hypothesis(diagnosis: dict[str, Any] | None) -> str | None:
    if not isinstance(diagnosis, dict):
        return None
    ranking = diagnosis.get("ranking", {})
    candidates = ranking.get("candidates", []) if isinstance(ranking, dict) else []
    if not isinstance(candidates, list) or not candidates:
        return None
    source = candidates[0].get("source", {}) if isinstance(candidates[0], dict) else {}
    value = source.get("id") if isinstance(source, dict) else None
    return value if isinstance(value, str) else None


def _top_probe(diagnosis: dict[str, Any] | None) -> str | None:
    if not isinstance(diagnosis, dict):
        return None
    ranking = diagnosis.get("probe_ranking", {})
    probes = ranking.get("probes", []) if isinstance(ranking, dict) else []
    if not isinstance(probes, list) or not probes:
        return None
    probe = probes[0].get("probe", {}) if isinstance(probes[0], dict) else {}
    value = probe.get("id") if isinstance(probe, dict) else None
    return value if isinstance(value, str) else None


def _diagnosis_for(
    snapshot: dict[str, Any],
    *,
    target: str,
    scope: dict[str, Any] | None,
) -> dict[str, Any] | None:
    wanted = scope_key(scope)
    for partition in snapshot.get("partitions", []):
        if scope_key(partition.get("scope")) != wanted:
            continue
        for diagnosis in partition.get("diagnoses", []):
            if diagnosis.get("target") == target:
                return diagnosis
    return None


def _recommendations(
    snapshot: dict[str, Any],
    concepts: dict[str, dict[str, Any]],
    *,
    supported_probe_ids: set[str],
    attempted: set[tuple[str, str, str]],
) -> tuple[list[dict[str, Any]], bool]:
    """Return ranked supported probes without allowing one unavailable probe to block the rest."""
    output: list[dict[str, Any]] = []
    repeated = False
    for partition in snapshot.get("partitions", []):
        normalized_scope = normalize_scope(partition.get("scope"), concepts)
        scope_identity = scope_key(normalized_scope)
        for diagnosis in partition.get("diagnoses", []):
            target = diagnosis.get("target")
            if not isinstance(target, str):
                continue
            probe_ranking = diagnosis.get("probe_ranking", {})
            probes = probe_ranking.get("probes", []) if isinstance(probe_ranking, dict) else []
            if not isinstance(probes, list):
                continue
            for rank_index, candidate in enumerate(probes):
                probe_view = candidate.get("probe", {}) if isinstance(candidate, dict) else {}
                probe_id = probe_view.get("id") if isinstance(probe_view, dict) else None
                if not isinstance(probe_id, str) or probe_id not in supported_probe_ids:
                    continue
                probe = concepts.get(probe_id)
                if not isinstance(probe, dict) or probe.get("kind") != "probe":
                    raise ValueError(f"recommended probe is not a canonical probe concept: {probe_id}")
                if probe.get("risk") != "read_only":
                    raise ValueError(
                        f"autonomous execution refuses non-read-only recommended probe {probe_id}: "
                        f"risk={probe.get('risk')}"
                    )
                key = (target, scope_identity, probe_id)
                if key in attempted:
                    repeated = True
                    continue
                output.append(
                    {
                        "target": target,
                        "scope": copy.deepcopy(normalized_scope),
                        "probe_id": probe_id,
                        "probe_rank": rank_index + 1,
                        "before_top_hypothesis": _top_hypothesis(diagnosis),
                        "key": key,
                    }
                )

    output.sort(
        key=lambda item: (
            item["probe_rank"],
            item["target"],
            scope_key(item["scope"]),
            item["probe_id"],
        )
    )
    return output, repeated


def _validate_probe_evidence(
    document: dict[str, Any],
    *,
    incident_id: str,
    probe_id: str,
    scope: dict[str, Any] | None,
    concepts: dict[str, dict[str, Any]],
) -> None:
    if document.get("kind") != "runtime_evidence":
        raise ValueError("read-only probe executor must return a runtime_evidence document")
    if document.get("incident_id") != incident_id:
        raise ValueError("read-only probe evidence belongs to a different incident")
    validate_runtime_references(document, concepts)

    probe = concepts[probe_id]
    produced = set(probe.get("produces", []))
    if not produced:
        raise ValueError(f"canonical probe {probe_id} does not declare produced observations")

    instances = document.get("instances", [])
    if not isinstance(instances, list) or not instances:
        raise ValueError("read-only probe executor returned no evidence instances")
    wanted_scope = scope_key(scope)
    for instance in instances:
        observation = instance.get("observation")
        if observation not in produced:
            raise ValueError(
                f"read-only probe {probe_id} emitted undeclared observation {observation}"
            )
        source = instance.get("source", {})
        if source.get("type") != "probe" or source.get("name") != probe_id:
            raise ValueError(
                f"read-only probe evidence must preserve probe provenance for {probe_id}"
            )
        labels = instance.get("labels", {})
        if labels.get("probe") != probe_id:
            raise ValueError(f"read-only probe evidence must label probe={probe_id}")
        normalized_instance_scope = normalize_scope(instance.get("scope"), concepts)
        if scope_key(normalized_instance_scope) != wanted_scope:
            raise ValueError(
                f"read-only probe {probe_id} attempted to emit evidence outside its diagnosis scope"
            )


def run_autonomous_read_only_loop(
    *,
    evidence: dict[str, Any],
    snapshot: dict[str, Any],
    concepts: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    supported_probe_ids: set[str],
    execute_probe: ProbeExecutor,
    max_steps: int = 4,
    clock: Clock = _default_clock,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Execute only statically allowlisted read-only recommendations and re-rank after each result."""
    if max_steps < 1 or max_steps > 16:
        raise ValueError("max_steps must be between 1 and 16")
    incident_id = evidence.get("incident_id")
    if not isinstance(incident_id, str) or not incident_id:
        raise ValueError("runtime evidence must contain a non-empty incident_id")
    if snapshot.get("incident_id") != incident_id:
        raise ValueError("initial diagnosis snapshot and runtime evidence belong to different incidents")
    if not supported_probe_ids:
        raise ValueError("autonomous execution requires at least one statically supported probe")

    for probe_id in sorted(supported_probe_ids):
        probe = concepts.get(probe_id)
        if not isinstance(probe, dict) or probe.get("kind") != "probe":
            raise ValueError(f"unsupported autonomous probe registration: {probe_id}")
        if probe.get("risk") != "read_only":
            raise ValueError(
                f"autonomous probe registration refuses non-read-only probe {probe_id}: "
                f"risk={probe.get('risk')}"
            )

    current_evidence = copy.deepcopy(evidence)
    current_snapshot = copy.deepcopy(snapshot)
    revision = int(snapshot.get("evidence_revision", 0))
    started_at = clock().astimezone(timezone.utc)
    attempted: set[tuple[str, str, str]] = set()
    steps: list[dict[str, Any]] = []
    stop_reason = "max_steps"

    for index in range(1, max_steps + 1):
        recommendations, repeated = _recommendations(
            current_snapshot,
            concepts,
            supported_probe_ids=supported_probe_ids,
            attempted=attempted,
        )
        if not recommendations:
            stop_reason = "repeated_recommendation" if repeated else "no_executable_recommendation"
            break

        recommendation = recommendations[0]
        probe_id = recommendation["probe_id"]
        target = recommendation["target"]
        scope = recommendation["scope"]
        attempted.add(recommendation["key"])

        try:
            probe_evidence = execute_probe(probe_id, target, copy.deepcopy(scope))
        except ProbeInsufficientEvidence as exc:
            steps.append(
                {
                    "index": index,
                    "status": "insufficient_evidence",
                    "target": target,
                    "scope": copy.deepcopy(scope),
                    "probe_id": probe_id,
                    "probe_rank": recommendation["probe_rank"],
                    "before_top_hypothesis": recommendation["before_top_hypothesis"],
                    "after_top_hypothesis": recommendation["before_top_hypothesis"],
                    "next_probe_after": _top_probe(
                        _diagnosis_for(current_snapshot, target=target, scope=scope)
                    ),
                    "evidence_instance_ids": [],
                    "evidence_revision": revision,
                    "reason": str(exc),
                }
            )
            continue

        _validate_probe_evidence(
            probe_evidence,
            incident_id=incident_id,
            probe_id=probe_id,
            scope=scope,
            concepts=concepts,
        )
        existing_ids = {item["id"] for item in current_evidence.get("instances", [])}
        new_ids = [item["id"] for item in probe_evidence.get("instances", []) if item["id"] not in existing_ids]
        if not new_ids:
            stop_reason = "no_new_evidence"
            break

        current_evidence = compose_runtime_evidence(
            [current_evidence, probe_evidence],
            concepts,
        )
        revision += 1
        current_snapshot = build_diagnosis_snapshot(
            current_evidence,
            concepts,
            edges,
            as_of=clock().astimezone(timezone.utc),
            evidence_revision=revision,
        )
        after = _diagnosis_for(current_snapshot, target=target, scope=scope)
        steps.append(
            {
                "index": index,
                "status": "completed",
                "target": target,
                "scope": copy.deepcopy(scope),
                "probe_id": probe_id,
                "probe_rank": recommendation["probe_rank"],
                "before_top_hypothesis": recommendation["before_top_hypothesis"],
                "after_top_hypothesis": _top_hypothesis(after),
                "next_probe_after": _top_probe(after),
                "evidence_instance_ids": sorted(new_ids),
                "evidence_revision": revision,
                "reason": None,
            }
        )
    else:
        stop_reason = "max_steps"

    finished_at = clock().astimezone(timezone.utc)
    report = {
        "schema_version": "0.1",
        "kind": "autonomous_investigation_run",
        "incident_id": incident_id,
        "started_at": format_timestamp(started_at),
        "finished_at": format_timestamp(finished_at),
        "max_steps": max_steps,
        "initial_evidence_revision": int(snapshot.get("evidence_revision", 0)),
        "final_evidence_revision": revision,
        "stop_reason": stop_reason,
        "steps": steps,
    }
    return current_evidence, current_snapshot, report

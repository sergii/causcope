#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from runtime_evidence import load_runtime_evidence

POOL_WAIT = "observation.database.connection_pool_wait_time"
POOL_UTILIZATION = "observation.database.connection_pool_utilization"
QUERY_LATENCY = "observation.database.query_latency"
REQUEST_LATENCY = "observation.http.request_latency"
POOL_EXHAUSTION = "hypothesis.database.connection_pool_exhaustion"
INTERVENTION_KIND = "resource_capacity_release"


class CausalVerificationError(ValueError):
    pass


def _attributes(instance: dict[str, Any]) -> dict[str, str]:
    source = instance.get("source")
    attributes = source.get("attributes") if isinstance(source, dict) else None
    if not isinstance(attributes, dict):
        return {}
    return {str(key): str(value) for key, value in attributes.items()}


def _labels(instance: dict[str, Any]) -> dict[str, str]:
    labels = instance.get("labels")
    if not isinstance(labels, dict):
        return {}
    return {str(key): str(value) for key, value in labels.items()}


def _scope_key(scope: Any) -> str:
    return json.dumps(scope, sort_keys=True, separators=(",", ":"))


def _matching(
    instances: list[dict[str, Any]],
    *,
    observation: str,
    state: str,
    phase: str,
) -> list[dict[str, Any]]:
    return [
        item
        for item in instances
        if item.get("observation") == observation
        and item.get("state") == state
        and _attributes(item).get("causcope.verification_phase") == phase
    ]


def build_causal_verification_projection(
    snapshot: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    if snapshot.get("kind") != "diagnosis_snapshot":
        raise CausalVerificationError("snapshot must be a diagnosis_snapshot")
    if evidence.get("kind") != "runtime_evidence":
        raise CausalVerificationError("evidence must be a runtime_evidence bundle")
    if snapshot.get("incident_id") != evidence.get("incident_id"):
        raise CausalVerificationError("diagnosis and runtime evidence belong to different incidents")

    all_instances = [item for item in evidence.get("instances", []) if isinstance(item, dict)]
    groups: dict[str, list[dict[str, Any]]] = {}
    for instance in all_instances:
        verification_id = _attributes(instance).get("causcope.verification_id")
        if verification_id:
            groups.setdefault(verification_id, []).append(instance)

    claims: list[dict[str, Any]] = []
    by_id = {str(item.get("id")): item for item in all_instances if item.get("id")}

    for verification_id in sorted(groups):
        members = groups[verification_id]
        first_attributes = _attributes(members[0])
        hypothesis = first_attributes.get("causcope.baseline_leading_hypothesis")
        intervention_kind = first_attributes.get("causcope.intervention_kind")
        intervention_resource = first_attributes.get("causcope.intervention_resource")
        target_resource = first_attributes.get("causcope.target_resource")
        baseline_revision_raw = first_attributes.get("causcope.baseline_evidence_revision")

        reasons: list[str] = []
        try:
            baseline_revision = int(baseline_revision_raw or "")
        except ValueError:
            baseline_revision = -1
            reasons.append("baseline evidence revision is missing or invalid")

        identity = {
            (
                _attributes(item).get("causcope.baseline_leading_hypothesis"),
                _attributes(item).get("causcope.intervention_kind"),
                _attributes(item).get("causcope.intervention_resource"),
                _attributes(item).get("causcope.target_resource"),
                _attributes(item).get("causcope.baseline_evidence_revision"),
                _scope_key(item.get("scope")),
            )
            for item in members
        }
        if len(identity) != 1:
            reasons.append("verification evidence identity or exact scope is inconsistent")

        pre = _matching(
            members,
            observation=POOL_UTILIZATION,
            state="observed",
            phase="pre_intervention",
        )
        control = _matching(
            members,
            observation=QUERY_LATENCY,
            state="absent",
            phase="control",
        )
        recovered_wait = _matching(
            members,
            observation=POOL_WAIT,
            state="absent",
            phase="post_intervention",
        )
        recovered_request = _matching(
            members,
            observation=REQUEST_LATENCY,
            state="absent",
            phase="post_intervention",
        )

        if hypothesis != POOL_EXHAUSTION:
            reasons.append("baseline leading hypothesis was not connection-pool exhaustion")
        if intervention_kind != INTERVENTION_KIND:
            reasons.append("bounded intervention was not a resource-capacity release")
        if not target_resource:
            reasons.append("exact target resource is missing")
        if len(pre) != 1:
            reasons.append("exactly one pre-intervention saturated-pool observation is required")
        if len(control) != 1:
            reasons.append("exactly one non-elevated query-latency control is required")
        if len(recovered_wait) != 1:
            reasons.append("post-intervention checkout-wait recovery is required")
        if len(recovered_request) != 1:
            reasons.append("post-intervention request-latency recovery is required")

        seed_ids = {
            _attributes(item).get("causcope.seed_evidence_id")
            for item in members
            if _attributes(item).get("causcope.seed_evidence_id")
        }
        if len(seed_ids) != 1:
            reasons.append("verification must bind to exactly one canonical seed evidence instance")
            seed = None
        else:
            seed = by_id.get(next(iter(seed_ids)))
            if seed is None:
                reasons.append("canonical seed evidence instance is missing")
            elif seed.get("observation") != POOL_WAIT or seed.get("state") != "observed":
                reasons.append("canonical seed must be an observed connection-pool wait")
            elif _scope_key(seed.get("scope")) != _scope_key(members[0].get("scope")):
                reasons.append("canonical seed and verification evidence do not share exact scope")

        if pre:
            pre_labels = _labels(pre[0])
            if pre_labels.get("mechanism_explains_request_delta") != "true":
                reasons.append("pool wait did not explain the request-latency delta")
            if pre_labels.get("baseline_hypothesis_rank") != "1":
                reasons.append("verified hypothesis was not rank 1 before intervention")
        if control and _labels(control[0]).get("independent_database_control") != "reachable":
            reasons.append("independent database admission control was not established")

        evidence_ids = sorted(str(item["id"]) for item in members if item.get("id"))
        if seed is not None and seed.get("id"):
            evidence_ids = sorted(set(evidence_ids + [str(seed["id"])]))

        claims.append(
            {
                "id": verification_id,
                "hypothesis": hypothesis,
                "status": "verified" if not reasons else "incomplete",
                "baseline_evidence_revision": baseline_revision,
                "verified_at_evidence_revision": snapshot.get("evidence_revision"),
                "target_resource": target_resource,
                "scope": members[0].get("scope"),
                "intervention": {
                    "kind": intervention_kind,
                    "resource": intervention_resource,
                },
                "evidence_ids": evidence_ids,
                "predicted_outcomes": [
                    {"observation": POOL_WAIT, "state": "absent", "phase": "post_intervention"},
                    {"observation": REQUEST_LATENCY, "state": "absent", "phase": "post_intervention"},
                ],
                "controls": [
                    {"observation": QUERY_LATENCY, "state": "absent", "phase": "control"}
                ],
                "reasons": reasons,
            }
        )

    return {
        "schema_version": "0.1",
        "kind": "causal_verification_projection",
        "incident_id": snapshot["incident_id"],
        "evidence_revision": snapshot["evidence_revision"],
        "claims": claims,
    }


def load_snapshot(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise CausalVerificationError("diagnosis snapshot must contain a JSON object")
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Project intervention-based causal verification from canonical Investigation evidence."
    )
    parser.add_argument("--workspace", type=Path, default=Path(".causcope"))
    parser.add_argument("--require-verified", action="store_true")
    args = parser.parse_args(argv)
    workspace = args.workspace.expanduser().resolve()
    try:
        projection = build_causal_verification_projection(
            load_snapshot(workspace / "diagnosis.json"),
            load_runtime_evidence(workspace / "runtime-evidence.json"),
        )
    except (OSError, json.JSONDecodeError, CausalVerificationError, ValueError) as error:
        print(f"causcope causal verification: {error}", file=__import__("sys").stderr)
        return 2

    verified = [item for item in projection["claims"] if item["status"] == "verified"]
    if args.require_verified and not verified:
        print("causcope causal verification: no verified causal claim", file=__import__("sys").stderr)
        return 2
    print(json.dumps(projection, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

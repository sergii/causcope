#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import causcope_why
from causal_verification import build_causal_verification_projection
from runtime_evidence import load_runtime_evidence


def load_workspace_verification(workspace: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    evidence_path = workspace / causcope_why.WORKSPACE_RUNTIME_EVIDENCE
    if not evidence_path.exists():
        raise ValueError(
            f"canonical causal verification requires {evidence_path}; "
            "the diagnosis snapshot alone cannot establish intervention outcomes"
        )
    return build_causal_verification_projection(snapshot, load_runtime_evidence(evidence_path))


def verified_claims(projection: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        claim
        for claim in projection.get("claims", [])
        if isinstance(claim, dict) and claim.get("status") == "verified"
    ]


def render_verification(projection: dict[str, Any]) -> str:
    claims = projection.get("claims", [])
    lines = ["Causal verification"]
    if not claims:
        lines.append("  not established")
        return "\n".join(lines) + "\n"

    for claim in claims:
        status = str(claim.get("status", "incomplete")).upper()
        lines.append(f"  {status}: {claim.get('hypothesis', '<unknown>')}")
        target = claim.get("target_resource")
        if target:
            lines.append(f"    target: {target}")
        intervention = claim.get("intervention", {})
        if isinstance(intervention, dict):
            lines.append(
                "    intervention: "
                f"{intervention.get('kind', '<unknown>')} on {intervention.get('resource', '<unknown>')}"
            )
        lines.append(f"    canonical evidence: {len(claim.get('evidence_ids', []))} instances")
        if claim.get("predicted_outcomes"):
            outcome = "observed" if claim.get("status") == "verified" else "incomplete"
            lines.append(f"    predicted recovery: {outcome}")
        reasons = claim.get("reasons", [])
        if reasons:
            lines.append("    missing/invalid:")
            lines.extend(f"      - {reason}" for reason in reasons)
    return "\n".join(lines) + "\n"


def run_canonical_workspace(args: Any) -> int | None:
    snapshot = causcope_why.load_workspace_diagnosis(args.workspace)
    if snapshot is None:
        return None

    problem = causcope_why.workspace_problem(args, snapshot)
    if args.acquire:
        acquisition, snapshot, routing, target_resolution = causcope_why.acquire_workspace_evidence(
            snapshot, args.workspace
        )
    else:
        routing, target_resolution, _router, _information_gain_router = causcope_why.workspace_route_context(
            snapshot, args.workspace
        )
        acquisition = None

    verification = load_workspace_verification(args.workspace, snapshot)
    if args.require_confirmed and not verified_claims(verification):
        raise ValueError("causal diagnosis is not verified by canonical intervention evidence")

    if args.json:
        document: dict[str, Any] = {
            "kind": "causcope_why",
            "problem": problem,
            "status": "diagnosis_available",
            "diagnosis": snapshot,
            "routing": routing,
            "causal_verification": verification,
        }
        if target_resolution is not None:
            document["target_resolution"] = target_resolution
        if acquisition is not None:
            document["acquisition"] = acquisition
        print(json.dumps(document, indent=2, sort_keys=True))
    else:
        if acquisition is not None:
            print(causcope_why.render_acquisition(acquisition))
        print(causcope_why.render_workspace_diagnosis(problem, snapshot, routing), end="")
        print(render_verification(verification), end="")
    return 0

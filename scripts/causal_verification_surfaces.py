#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import causcope_why
from bounded_workspace_acquisition import acquire_best_workspace_evidence
from causal_verification import build_causal_verification_projection
from causal_verification_source import load_causal_verification_source
from workspace_autonomous_investigation import run_workspace_investigation


def load_workspace_verification(workspace: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    evidence_path = workspace / causcope_why.WORKSPACE_RUNTIME_EVIDENCE
    if not evidence_path.exists():
        raise ValueError(
            f"canonical causal verification requires {evidence_path}; "
            "the diagnosis snapshot alone cannot establish intervention outcomes"
        )
    return build_causal_verification_projection(
        snapshot, load_causal_verification_source(evidence_path)
    )


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


def render_autonomous_investigation(report: dict[str, Any]) -> str:
    lines = [
        "Autonomous investigation",
        f"  steps: {len(report.get('steps', []))}/{report.get('max_steps', '<unknown>')}",
        "  evidence revision: "
        f"{report.get('initial_evidence_revision', '<unknown>')} -> "
        f"{report.get('final_evidence_revision', '<unknown>')}",
        f"  stop: {report.get('stop_reason', '<unknown>')} ({report.get('stop_detail', '<unknown>')})",
    ]
    return "\n".join(lines) + "\n"


def run_canonical_workspace(args: Any) -> int | None:
    snapshot = causcope_why.load_workspace_diagnosis(args.workspace)
    if snapshot is None:
        return None

    problem = causcope_why.workspace_problem(args, snapshot)
    investigation = None
    acquisition = None

    if args.acquire:
        # Hidden compatibility path: explicit --acquire retains its historical
        # exactly-one-set contract. Normal product usage uses the bounded loop.
        acquisition, snapshot, routing, target_resolution = acquire_best_workspace_evidence(
            snapshot, args.workspace
        )
        acquisitions = [acquisition]
    else:
        investigation, snapshot, routing, target_resolution = run_workspace_investigation(
            snapshot,
            args.workspace,
            max_steps=4,
        )
        acquisitions = [
            step["acquisition"]
            for step in investigation.get("steps", [])
            if isinstance(step, dict) and isinstance(step.get("acquisition"), dict)
        ]
        if len(acquisitions) == 1:
            acquisition = acquisitions[0]

    if routing is None:
        routing, target_resolution, _router, _information_gain_router = causcope_why.workspace_route_context(
            snapshot, args.workspace
        )

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
        if investigation is not None:
            document["autonomous_investigation"] = investigation
        if acquisitions:
            document["acquisitions"] = acquisitions
        if acquisition is not None:
            # Compatibility for consumers that already read the single-step field.
            document["acquisition"] = acquisition
        print(json.dumps(document, indent=2, sort_keys=True))
    else:
        for result in acquisitions:
            print(causcope_why.render_acquisition(result))
        if investigation is not None:
            print(render_autonomous_investigation(investigation), end="")
        print(causcope_why.render_workspace_diagnosis(problem, snapshot, routing), end="")
        print(render_verification(verification), end="")
    return 0

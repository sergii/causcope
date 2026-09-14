#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from runtime_evidence import (
    build_scope_query,
    load_concepts,
    load_runtime_evidence,
    parse_scope_attribute,
    parse_timestamp,
    resolve_runtime_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
DATABASE_BOUNDARY = "boundary.application.database"
LOCK_WAIT_OBSERVATION = "observation.database.lock_wait_time"
DEADLOCK_ERROR_OBSERVATION = "observation.database.deadlock_error"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def state_for(observation: str, observed: set[str], absent: set[str]) -> str:
    if observation in observed:
        return "observed"
    if observation in absent:
        return "absent"
    return "unknown"


def project(
    xray: dict[str, Any],
    evidence_documents: list[tuple[str, dict[str, Any]]],
    *,
    as_of: datetime,
    scope_attributes: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    if xray.get("kind") != "d2_2_xray_projection":
        raise ValueError("input X-Ray document must be a d2_2_xray_projection")
    if xray.get("catalog_code") != "D2.2":
        raise ValueError("input X-Ray projection must describe D2.2")

    concepts = load_concepts(ROOT)
    scope_query = build_scope_query(
        boundaries=[DATABASE_BOUNDARY],
        attributes=scope_attributes,
    )

    observed: set[str] = set()
    absent: set[str] = set()
    evidence_contexts: list[dict[str, Any]] = []

    for source_path, document in evidence_documents:
        if document["incident_id"] != xray["incident_id"]:
            raise ValueError(
                f"runtime evidence incident mismatch: expected {xray['incident_id']!r}, "
                f"got {document['incident_id']!r} from {source_path}"
            )

        doc_observed, doc_absent, context = resolve_runtime_evidence(
            document,
            concepts,
            as_of=as_of,
            source_path=source_path,
            scope_query=scope_query,
        )
        observed.update(doc_observed)
        absent.update(doc_absent)
        evidence_contexts.append(context)

    conflicts = sorted(observed & absent)
    if conflicts:
        raise ValueError(
            "runtime evidence conflicts across supplied documents: " + ", ".join(conflicts)
        )

    lock_state = state_for(LOCK_WAIT_OBSERVATION, observed, absent)
    deadlock_state = state_for(DEADLOCK_ERROR_OBSERVATION, observed, absent)

    base_state = xray["risk_state"]
    if deadlock_state == "observed":
        epistemic_state = "EVENT_OBSERVED"
    elif lock_state == "observed":
        epistemic_state = "CONTENTION_OBSERVED"
    else:
        epistemic_state = base_state

    causal_link_state = "unconfirmed"
    causal_link_reason = (
        "Database evidence is scoped to the canonical application-database boundary but is not "
        "yet linked to the exact concrete transactions/resources from the static X-Ray model."
    )

    return {
        "schema_version": "0.1",
        "kind": "d2_2_database_evidence_projection",
        "catalog_code": "D2.2",
        "hypothesis": "hypothesis.database.deadlock",
        "system_id": xray["system_id"],
        "revision": xray["revision"],
        "incident_id": xray["incident_id"],
        "as_of": as_of.isoformat().replace("+00:00", "Z"),
        "structural_preconditions": xray["structural_preconditions"],
        "runtime_concurrency": xray["runtime_concurrency"],
        "database_contention": {
            "state": lock_state,
            "observation": LOCK_WAIT_OBSERVATION,
        },
        "deadlock_event": {
            "state": deadlock_state,
            "observation": DEADLOCK_ERROR_OBSERVATION,
        },
        "epistemic_state": epistemic_state,
        "causal_diagnosis": {
            "state": causal_link_state,
            "reason": causal_link_reason,
        },
        "scope_query": scope_query,
        "evidence_contexts": evidence_contexts,
        "limitations": [
            "Lock-wait evidence raises the D2.2 progression to CONTENTION_OBSERVED but does not prove a wait-for cycle.",
            "A canonical deadlock error raises the progression to EVENT_OBSERVED but does not by itself prove that the RFC 0048 concrete paths caused that event.",
            "CAUSAL_DIAGNOSIS_CONFIRMED is intentionally unavailable until database evidence can be linked to the concrete transactions/resources or an equivalent discriminating proof exists.",
            "Active absent deadlock evidence is preserved as absent but does not erase structural or runtime risk evidence.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extend a D2.2 concrete X-Ray projection with canonical database runtime evidence."
    )
    parser.add_argument("--xray", required=True, type=Path)
    parser.add_argument(
        "--evidence",
        required=True,
        action="append",
        type=Path,
        help="Runtime evidence document; repeat to compose multiple sources",
    )
    parser.add_argument("--as-of", required=True)
    parser.add_argument(
        "--scope-attribute",
        action="append",
        default=[],
        type=parse_scope_attribute,
        metavar="KEY=VALUE",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        xray = load_json(args.xray)
        evidence_documents = [
            (str(path), load_runtime_evidence(path)) for path in args.evidence
        ]
        as_of = parse_timestamp(args.as_of, "--as-of")
        output = project(
            xray,
            evidence_documents,
            as_of=as_of,
            scope_attributes=args.scope_attribute or None,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    rendered = json.dumps(output, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from causal_projection import load_concepts, load_edges  # noqa: E402
from live_diagnosis import build_diagnosis_snapshot  # noqa: E402
from runtime_evidence import validate_runtime_references  # noqa: E402
from structured_log_evidence import (  # noqa: E402
    build_runtime_evidence_from_logs,
    parse_structured_events,
)

SHOP_ROOT = Path(__file__).resolve().parent
COMPOSE_FILE = SHOP_ROOT / "compose.yaml"
DEFAULT_WORKSPACE = REPO_ROOT / ".causcope"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_incident_id(workspace: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    context_path = workspace / "incident-context.yaml"
    if not context_path.exists():
        raise ValueError(
            f"no incident context at {context_path}; run `./bin/causcope investigate ...` "
            "or pass --incident-id"
        )
    document = yaml.safe_load(context_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("incident_id"), str):
        raise ValueError(f"invalid incident context: {context_path}")
    return document["incident_id"]


def collect_app_logs(*, since: str | None = None) -> str:
    command = [
        "docker",
        "compose",
        "-f",
        str(COMPOSE_FILE),
        "logs",
        "--no-color",
        "--no-log-prefix",
    ]
    if since:
        command.extend(["--since", since])
    command.append("app")
    completed = subprocess.run(
        command,
        cwd=SHOP_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout


def _best_probe(diagnosis: dict[str, Any]) -> dict[str, Any] | None:
    probe_ranking = diagnosis.get("probe_ranking", {})
    probes = probe_ranking.get("probes", []) if isinstance(probe_ranking, dict) else []
    if not isinstance(probes, list) or not probes:
        return None
    first = probes[0]
    return first if isinstance(first, dict) else None


def summarize(snapshot: dict[str, Any]) -> dict[str, Any]:
    diagnoses: list[dict[str, Any]] = []
    for partition in snapshot.get("partitions", []):
        scope = partition.get("scope")
        for diagnosis in partition.get("diagnoses", []):
            ranking = diagnosis.get("ranking", {})
            candidates = ranking.get("candidates", []) if isinstance(ranking, dict) else []
            top = candidates[0] if isinstance(candidates, list) and candidates else None
            top_id = None
            if isinstance(top, dict):
                source = top.get("source", {})
                if isinstance(source, dict):
                    top_id = source.get("id")
            probe = _best_probe(diagnosis)
            probe_id = None
            if isinstance(probe, dict):
                probe_view = probe.get("probe", {})
                if isinstance(probe_view, dict):
                    probe_id = probe_view.get("id")
            diagnoses.append(
                {
                    "scope": scope,
                    "target": diagnosis.get("target"),
                    "top_hypothesis": top_id,
                    "next_probe": probe_id,
                    "candidate_count": len(candidates) if isinstance(candidates, list) else 0,
                }
            )
    return {
        "incident_id": snapshot["incident_id"],
        "evidence_revision": snapshot["evidence_revision"],
        "diagnoses": diagnoses,
    }


def run_bridge(
    *,
    workspace: Path,
    incident_id: str,
    since: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    raw_logs = collect_app_logs(since=since)
    events = parse_structured_events(raw_logs)
    now = utc_now()
    evidence = build_runtime_evidence_from_logs(
        events,
        incident_id=incident_id,
        source_name="docker-compose:causcope-shop/app",
        collected_at=now.isoformat().replace("+00:00", "Z"),
    )

    concepts = load_concepts(REPO_ROOT)
    validate_runtime_references(evidence, concepts)
    edges = load_edges(REPO_ROOT)
    diagnosis = build_diagnosis_snapshot(
        evidence,
        concepts,
        edges,
        as_of=now,
        evidence_revision=1,
    )
    summary = summarize(diagnosis)

    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "runtime-evidence.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (workspace / "diagnosis.json").write_text(
        json.dumps(diagnosis, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (workspace / "diagnosis-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (workspace / "source-shop-app.log").write_text(raw_logs, encoding="utf-8")
    return evidence, diagnosis, summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read Causcope Shop logs through a read-only source and run the Causcope evidence/diagnosis pipeline."
    )
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--incident-id")
    parser.add_argument(
        "--since",
        help="Optional Docker Compose logs --since value, for example 30s or 2026-09-14T00:00:00Z",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable summary")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        incident_id = load_incident_id(args.workspace, args.incident_id)
        evidence, diagnosis, summary = run_bridge(
            workspace=args.workspace,
            incident_id=incident_id,
            since=args.since,
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    print(f"Collected {len(evidence['instances'])} runtime evidence instances for {incident_id}")
    print(f"Diagnosis partitions: {len(diagnosis['partitions'])}")
    for item in summary["diagnoses"]:
        scope = json.dumps(item["scope"], sort_keys=True)
        print(f"- target={item['target']} scope={scope}")
        print(f"  top_hypothesis={item['top_hypothesis'] or 'unranked'}")
        print(f"  next_probe={item['next_probe'] or 'none'}")
    print(f"Wrote evidence and diagnosis to {args.workspace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

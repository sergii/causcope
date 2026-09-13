#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from scoping_projection import build_scoping_projection, load_incident_context, load_dimension_registry

DEFAULT_WORKSPACE = Path(".causcope")
DIMENSION_PREFIX = "investigation."
DIMENSION_TO_UNKNOWN = {
    "investigation.blast_radius": "who",
    "investigation.where": "where",
    "investigation.when": "when",
    "investigation.flow": "what",
    "investigation.client": "client",
    "investigation.change": "change",
    "investigation.dependency": "dependency",
    "investigation.data": "data",
    "investigation.reproducibility": "reproduction",
    "investigation.impact": "impact",
}
DIMENSION_EXAMPLES = {
    "investigation.blast_radius": "unit=users affected=8 total=120",
    "investigation.where": "environment=production region=eu-central",
    "investigation.when": "onset_at=2026-09-14T00:15:00Z pattern=intermittent",
    "investigation.flow": "feature=checkout operation='POST /checkout'",
    "investigation.client": "type=mobile os=iOS app_version=7.42.0",
    "investigation.change": "type=deploy timing=near_onset description='checkout release 2026.09.14.1'",
    "investigation.dependency": "name=stripe relationship=external",
    "investigation.data": "tenant=acme record_type=payment role=customer",
    "investigation.reproducibility": "status=sometimes conditions='production,EU,iOS 7.42'",
    "investigation.impact": "severity=high user_effect='checkout cannot complete'",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "incident")[:limit].rstrip("-")


def default_incident_id(summary: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"incident.local.{stamp}.{slugify(summary)}"


def workspace_paths(workspace: Path) -> dict[str, Path]:
    return {
        "context": workspace / "incident-context.yaml",
        "session": workspace / "investigation-session.yaml",
        "projection": workspace / "scoping-projection.json",
    }


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def write_yaml(path: Path, document: dict[str, Any]) -> None:
    atomic_write_text(path, yaml.safe_dump(document, sort_keys=False, allow_unicode=True))


def write_json(path: Path, document: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(document, indent=2, sort_keys=True) + "\n")


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"expected object in {path}")
    return document


def initial_context(summary: str, incident_id: str) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "kind": "incident_context",
        "incident_id": incident_id,
        "summary": summary,
        "reported_at": utc_now(),
        "scope": {},
        "time": {"pattern": "unknown"},
        "impact": {"severity": "unknown"},
        "reproduction": {"status": "unknown"},
        "unknowns": [
            "who",
            "where",
            "when",
            "what",
            "client",
            "change",
            "dependency",
            "data",
            "reproduction",
            "impact",
        ],
    }


def initial_session(incident_id: str) -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": "0.1",
        "kind": "investigation_session",
        "session_id": f"session.{incident_id}",
        "incident_id": incident_id,
        "status": "active",
        "context_revision": 0,
        "started_at": now,
        "updated_at": now,
        "events": [],
    }


def normalize_dimension(value: str) -> str:
    candidate = value if value.startswith(DIMENSION_PREFIX) else f"{DIMENSION_PREFIX}{value}"
    if candidate not in DIMENSION_TO_UNKNOWN:
        valid = ", ".join(item.removeprefix(DIMENSION_PREFIX) for item in DIMENSION_TO_UNKNOWN)
        raise ValueError(f"unknown dimension {value!r}; expected one of: {valid}")
    return candidate


def parse_pairs(items: list[str]) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"answer field must be key=value, got {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise ValueError(f"answer field must have non-empty key and value: {item!r}")
        pairs[key] = value
    if not pairs:
        raise ValueError("at least one key=value answer field is required")
    return pairs


def parse_bool(value: str) -> bool:
    lowered = value.lower()
    if lowered in {"1", "true", "yes", "y"}:
        return True
    if lowered in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"expected boolean value, got {value!r}")


def split_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def as_int(fields: dict[str, str], key: str) -> int | None:
    if key not in fields:
        return None
    try:
        value = int(fields[key])
    except ValueError as error:
        raise ValueError(f"{key} must be an integer") from error
    if value < 0:
        raise ValueError(f"{key} must be non-negative")
    return value


def as_float(fields: dict[str, str], key: str) -> float | None:
    if key not in fields:
        return None
    try:
        value = float(fields[key])
    except ValueError as error:
        raise ValueError(f"{key} must be numeric") from error
    return value


def set_list(target: dict[str, Any], key: str, fields: dict[str, str], *aliases: str) -> bool:
    for alias in aliases:
        if alias in fields:
            values = split_list(fields[alias])
            if not values:
                raise ValueError(f"{alias} must contain at least one value")
            target[key] = values
            return True
    return False


def remove_unknown(context: dict[str, Any], dimension: str) -> None:
    unknown = DIMENSION_TO_UNKNOWN[dimension]
    context["unknowns"] = [item for item in context.get("unknowns", []) if item != unknown]


def apply_dimension_answer(context: dict[str, Any], dimension: str, fields: dict[str, str]) -> None:
    scope = context.setdefault("scope", {})
    impact = context.setdefault("impact", {"severity": "unknown"})
    reproduction = context.setdefault("reproduction", {"status": "unknown"})

    if dimension == "investigation.blast_radius":
        changed = False
        if "subject" in fields or "subjects" in fields:
            set_list(scope, "subjects", fields, "subject", "subjects")
            changed = True
        population_keys = {"unit", "affected", "total", "percentage"}.intersection(fields)
        if population_keys:
            unit = fields.get("unit", "users")
            allowed_units = {"users", "accounts", "tenants", "requests", "devices", "jobs", "records", "other"}
            if unit not in allowed_units:
                raise ValueError(f"unit must be one of: {', '.join(sorted(allowed_units))}")
            population: dict[str, Any] = {"unit": unit}
            affected = as_int(fields, "affected")
            total = as_int(fields, "total")
            percentage = as_float(fields, "percentage")
            if affected is not None:
                population["affected"] = affected
            if total is not None:
                population["total"] = total
            if percentage is not None:
                if not 0 <= percentage <= 100:
                    raise ValueError("percentage must be between 0 and 100")
                population["percentage"] = percentage
            populations = impact.setdefault("populations", [])
            for index, existing in enumerate(populations):
                if existing.get("unit") == unit:
                    populations[index] = population
                    break
            else:
                populations.append(population)
            changed = True
        if not changed:
            raise ValueError("blast_radius expects subject=... and/or unit/affected/total/percentage")

    elif dimension == "investigation.where":
        changed = False
        changed |= set_list(scope, "environments", fields, "environment", "environments")
        changed |= set_list(scope, "regions", fields, "region", "regions")
        changed |= set_list(scope, "availability_zones", fields, "az", "availability_zone", "availability_zones")
        changed |= set_list(scope, "datacenters", fields, "datacenter", "datacenters")
        if not changed:
            raise ValueError("where expects environment=..., region=..., az=..., or datacenter=...")

    elif dimension == "investigation.when":
        allowed_patterns = {"continuous", "intermittent", "periodic", "single_event", "unknown"}
        time = context.setdefault("time", {"pattern": "unknown"})
        changed = False
        for key in ("onset_at", "last_known_good_at", "first_reported_at"):
            if key in fields:
                time[key] = fields[key]
                changed = True
        if "pattern" in fields:
            if fields["pattern"] not in allowed_patterns:
                raise ValueError(f"pattern must be one of: {', '.join(sorted(allowed_patterns))}")
            time["pattern"] = fields["pattern"]
            changed = True
        if "duration_seconds" in fields:
            duration = as_float(fields, "duration_seconds")
            if duration is None or duration < 0:
                raise ValueError("duration_seconds must be non-negative")
            time["duration_seconds"] = duration
            changed = True
        if not changed:
            raise ValueError("when expects onset_at, last_known_good_at, first_reported_at, pattern, or duration_seconds")

    elif dimension == "investigation.flow":
        changed = False
        changed |= set_list(scope, "features", fields, "feature", "features")
        changed |= set_list(scope, "operations", fields, "operation", "operations")
        if not changed:
            raise ValueError("flow expects feature=... and/or operation=...")

    elif dimension == "investigation.client":
        allowed_types = {"browser", "mobile", "desktop", "api", "worker", "device", "other"}
        client_type = fields.get("type")
        if not client_type:
            raise ValueError("client expects type=browser|mobile|desktop|api|worker|device|other")
        if client_type not in allowed_types:
            raise ValueError(f"type must be one of: {', '.join(sorted(allowed_types))}")
        client: dict[str, Any] = {"type": client_type}
        for key in ("name", "version", "os", "app_version"):
            if key in fields:
                client[key] = fields[key]
        attributes = {key[5:]: value for key, value in fields.items() if key.startswith("attr.")}
        if attributes:
            client["attributes"] = attributes
        scope["clients"] = [client]

    elif dimension == "investigation.change":
        if parse_bool(fields.get("none", "false")):
            context["changes"] = []
        else:
            if "description" not in fields:
                raise ValueError("change expects description=... or none=true")
            allowed_types = {"deploy", "feature_flag", "config", "migration", "dependency", "infrastructure", "data", "other"}
            allowed_timings = {"before_onset", "near_onset", "after_onset", "unknown"}
            change_type = fields.get("type", "other")
            timing = fields.get("timing", "unknown")
            if change_type not in allowed_types:
                raise ValueError(f"type must be one of: {', '.join(sorted(allowed_types))}")
            if timing not in allowed_timings:
                raise ValueError(f"timing must be one of: {', '.join(sorted(allowed_timings))}")
            change: dict[str, Any] = {"type": change_type, "description": fields["description"], "timing": timing}
            for key in ("occurred_at", "reference"):
                if key in fields:
                    change[key] = fields[key]
            context.setdefault("changes", []).append(change)

    elif dimension == "investigation.dependency":
        if parse_bool(fields.get("none", "false")):
            scope["dependencies"] = []
        else:
            if "name" not in fields:
                raise ValueError("dependency expects name=... or none=true")
            allowed = {"upstream", "downstream", "external", "peer", "unknown"}
            relationship = fields.get("relationship", "unknown")
            if relationship not in allowed:
                raise ValueError(f"relationship must be one of: {', '.join(sorted(allowed))}")
            dependency: dict[str, Any] = {"name": fields["name"], "relationship": relationship}
            for key in ("service", "boundary"):
                if key in fields:
                    dependency[key] = fields[key]
            attributes = {key[5:]: value for key, value in fields.items() if key.startswith("attr.")}
            if attributes:
                dependency["attributes"] = attributes
            scope.setdefault("dependencies", []).append(dependency)

    elif dimension == "investigation.data":
        if parse_bool(fields.get("none", "false")):
            scope["data"] = []
        else:
            data_scope: dict[str, Any] = {}
            for key in ("tenant", "record_type", "role", "permission", "age"):
                if key in fields:
                    data_scope[key] = fields[key]
            attributes = {key[5:]: value for key, value in fields.items() if key.startswith("attr.")}
            if attributes:
                data_scope["attributes"] = attributes
            if not data_scope:
                raise ValueError("data expects tenant, record_type, role, permission, age, attr.*, or none=true")
            scope.setdefault("data", []).append(data_scope)

    elif dimension == "investigation.reproducibility":
        allowed = {"always", "sometimes", "rare", "not_reproduced", "unknown"}
        if "status" in fields:
            if fields["status"] not in allowed:
                raise ValueError(f"status must be one of: {', '.join(sorted(allowed))}")
            reproduction["status"] = fields["status"]
        if "conditions" in fields:
            reproduction["conditions"] = split_list(fields["conditions"])
        if "steps" in fields:
            reproduction["steps"] = [item.strip() for item in fields["steps"].split(";") if item.strip()]
        if not {"status", "conditions", "steps"}.intersection(fields):
            raise ValueError("reproducibility expects status, conditions, and/or steps")

    elif dimension == "investigation.impact":
        allowed = {"unknown", "low", "medium", "high", "critical"}
        changed = False
        if "severity" in fields:
            if fields["severity"] not in allowed:
                raise ValueError(f"severity must be one of: {', '.join(sorted(allowed))}")
            impact["severity"] = fields["severity"]
            changed = True
        for key in ("user_effect", "business_effect"):
            if key in fields:
                impact[key] = fields[key]
                changed = True
        if not changed:
            raise ValueError("impact expects severity, user_effect, and/or business_effect")

    else:
        raise ValueError(f"unsupported dimension: {dimension}")

    remove_unknown(context, dimension)


def dimension_record(projection: dict[str, Any], dimension: str) -> dict[str, Any]:
    for item in projection["dimensions"]:
        if item["id"] == dimension:
            return item
    raise ValueError(f"dimension not present in projection: {dimension}")


def event_id(session: dict[str, Any]) -> str:
    return f"event.{len(session.get('events', [])) + 1:04d}"


def ensure_question_event(session: dict[str, Any], projection: dict[str, Any], dimension: str) -> dict[str, Any]:
    for event in reversed(session.get("events", [])):
        if event.get("type") == "question" and event.get("dimension") == dimension and event.get("status") == "pending":
            return event
    record = dimension_record(projection, dimension)
    event = {
        "id": event_id(session),
        "type": "question",
        "recorded_at": utc_now(),
        "dimension": dimension,
        "question": record["question"],
        "rationale": record["reason"],
        "status": "pending",
    }
    session.setdefault("events", []).append(event)
    return event


def persist_state(workspace: Path, context: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    projection = build_scoping_projection(context)
    paths = workspace_paths(workspace)
    write_yaml(paths["context"], context)
    write_yaml(paths["session"], session)
    write_json(paths["projection"], projection)
    return projection


def load_state(workspace: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    paths = workspace_paths(workspace)
    context = load_incident_context(paths["context"])
    session = read_yaml(paths["session"])
    projection = build_scoping_projection(context)
    write_json(paths["projection"], projection)
    return context, session, projection


def record_answer(workspace: Path, dimension: str, fields: dict[str, str]) -> dict[str, Any]:
    context, session, projection = load_state(workspace)
    dimension = normalize_dimension(dimension)
    question = ensure_question_event(session, projection, dimension)

    updated_context = copy.deepcopy(context)
    apply_dimension_answer(updated_context, dimension, fields)
    updated_projection = build_scoping_projection(updated_context)

    question["status"] = "answered"
    answer_text = " ".join(f"{key}={value}" for key, value in fields.items())
    session["events"].append(
        {
            "id": event_id(session),
            "type": "answer",
            "recorded_at": utc_now(),
            "dimension": dimension,
            "answer": answer_text,
            "source": "human",
        }
    )
    session["context_revision"] = int(session.get("context_revision", 0)) + 1
    session["updated_at"] = utc_now()

    paths = workspace_paths(workspace)
    write_yaml(paths["context"], updated_context)
    write_yaml(paths["session"], session)
    write_json(paths["projection"], updated_projection)
    return updated_projection


def print_next(projection: dict[str, Any]) -> None:
    action = projection.get("next_action")
    if not action:
        print("Scoping complete: all investigation dimensions are known.")
        return
    short = action["dimension"].removeprefix(DIMENSION_PREFIX)
    print(f"Next: {action['question']}")
    print(f"Dimension: {short}")
    print(f"Why: {action['reason']}")
    print(f"Answer example: causcope answer {short} {DIMENSION_EXAMPLES[action['dimension']]}")


def print_status(context: dict[str, Any], projection: dict[str, Any]) -> None:
    print(f"Incident: {context['incident_id']}")
    print(f"Summary: {context['summary']}")
    print(f"Scoping completeness: {projection['completeness'] * 100:.1f}%")
    print(f"Known: {projection['known_count']}  Partial: {projection['partial_count']}  Unknown: {projection['unknown_count']}")
    for item in projection["dimensions"]:
        marker = {"known": "✓", "partial": "~", "unknown": "?"}[item["state"]]
        print(f"  {marker} {item['title']}: {item['state']}")
    print()
    print_next(projection)


def report_text(context: dict[str, Any], session: dict[str, Any], projection: dict[str, Any]) -> str:
    lines = [
        f"# Incident report: {context['incident_id']}",
        "",
        context["summary"],
        "",
        "## Investigation state",
        "",
        f"Scoping completeness: {projection['completeness'] * 100:.1f}%",
        f"Known: {projection['known_count']}; partial: {projection['partial_count']}; unknown: {projection['unknown_count']}",
        "",
        "## Dimensions",
        "",
    ]
    for item in projection["dimensions"]:
        lines.append(f"- **{item['title']}**: {item['state']}")
        if item["signals"]:
            lines.append(f"  - signals: {', '.join(item['signals'])}")

    impact = context.get("impact", {})
    lines.extend(["", "## Impact", ""])
    lines.append(f"Severity: {impact.get('severity', 'unknown')}")
    if impact.get("user_effect"):
        lines.append(f"User effect: {impact['user_effect']}")
    if impact.get("business_effect"):
        lines.append(f"Business effect: {impact['business_effect']}")
    for population in impact.get("populations", []):
        details = [population.get("unit", "population")]
        if "affected" in population:
            details.append(f"affected={population['affected']}")
        if "total" in population:
            details.append(f"total={population['total']}")
        if "percentage" in population:
            details.append(f"percentage={population['percentage']}")
        lines.append("Population: " + ", ".join(details))

    scope = context.get("scope", {})
    lines.extend(["", "## Scope", ""])
    for key in ("environments", "regions", "availability_zones", "datacenters", "features", "operations", "subjects"):
        if scope.get(key):
            lines.append(f"{key}: {', '.join(scope[key])}")
    for client in scope.get("clients", []):
        lines.append("client: " + ", ".join(f"{key}={value}" for key, value in client.items() if key != "attributes"))
    for dependency in scope.get("dependencies", []):
        lines.append("dependency: " + ", ".join(f"{key}={value}" for key, value in dependency.items() if key != "attributes"))
    for data_scope in scope.get("data", []):
        lines.append("data: " + ", ".join(f"{key}={value}" for key, value in data_scope.items() if key != "attributes"))

    changes = context.get("changes")
    if changes is not None:
        lines.extend(["", "## Recent changes", ""])
        if not changes:
            lines.append("No relevant recent change recorded.")
        for change in changes:
            lines.append(f"- {change['type']}: {change['description']} ({change['timing']})")
        lines.append("")
        lines.append("Recent changes are context and correlation candidates, not causal proof.")

    comparisons = context.get("comparisons", [])
    if comparisons:
        lines.extend(["", "## Failing vs working comparisons", ""])
        for comparison in comparisons:
            lines.append(f"- Differences: {', '.join(comparison['differences'])}")

    answers = [event for event in session.get("events", []) if event.get("type") == "answer"]
    if answers:
        lines.extend(["", "## Recorded answers", ""])
        for event in answers:
            short = event["dimension"].removeprefix(DIMENSION_PREFIX)
            lines.append(f"- **{short}**: {event['answer']}")

    lines.extend(["", "## Next recommended action", ""])
    action = projection.get("next_action")
    if action:
        lines.append(action["question"])
        lines.append("")
        lines.append(f"Why: {action['reason']}")
    else:
        lines.append("Incident scoping is complete. Proceed to evidence collection and causal diagnosis.")
    return "\n".join(lines) + "\n"


def interactive_loop(workspace: Path) -> None:
    while True:
        context, _session, projection = load_state(workspace)
        action = projection.get("next_action")
        if not action:
            print("\nScoping complete. Run `causcope report` or proceed to evidence collection.")
            return
        dimension = action["dimension"]
        short = dimension.removeprefix(DIMENSION_PREFIX)
        print("\n" + action["question"])
        print("Why:", action["reason"])
        print("Enter key=value fields. Example:")
        print("  " + DIMENSION_EXAMPLES[dimension])
        print("Commands: /status, /quit")
        raw = input("> ").strip()
        if raw == "/quit":
            return
        if raw == "/status":
            print_status(context, projection)
            continue
        try:
            fields = parse_pairs(shlex.split(raw))
            projection = record_answer(workspace, short, fields)
            print(f"Recorded. Scoping completeness: {projection['completeness'] * 100:.1f}%")
        except (ValueError, FileNotFoundError) as error:
            print(f"Error: {error}", file=sys.stderr)


def add_workspace_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE, help="Investigation workspace (default: .causcope)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="causcope", description="Causcope incident investigation CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    investigate = subparsers.add_parser("investigate", help="Start a new incident investigation")
    investigate.add_argument("summary", help="Initial problem statement")
    investigate.add_argument("--incident-id", help="Stable incident identifier")
    investigate.add_argument("--non-interactive", action="store_true", help="Create state and print the first question without prompting")
    investigate.add_argument("--force", action="store_true", help="Replace an existing workspace")
    add_workspace_argument(investigate)

    next_parser = subparsers.add_parser("next", help="Show the next scoping question")
    next_parser.add_argument("--json", action="store_true", help="Print the complete scoping projection as JSON")
    add_workspace_argument(next_parser)

    status = subparsers.add_parser("status", help="Show current investigation scoping state")
    status.add_argument("--json", action="store_true", help="Print the complete scoping projection as JSON")
    add_workspace_argument(status)

    answer = subparsers.add_parser("answer", help="Record structured context for one investigation dimension")
    answer.add_argument("dimension", help="Dimension name, for example blast_radius, where, client, or impact")
    answer.add_argument("fields", nargs="+", help="Dimension-specific key=value fields")
    add_workspace_argument(answer)

    report = subparsers.add_parser("report", help="Render a human-readable incident scoping report")
    report.add_argument("--output", type=Path, help="Optional file path; stdout when omitted")
    add_workspace_argument(report)
    return parser


def command_investigate(args: argparse.Namespace) -> int:
    paths = workspace_paths(args.workspace)
    if paths["context"].exists() and not args.force:
        raise ValueError(f"workspace already contains an incident: {args.workspace}; use --force to replace it")
    incident_id = args.incident_id or default_incident_id(args.summary)
    context = initial_context(args.summary, incident_id)
    session = initial_session(incident_id)
    projection = persist_state(args.workspace, context, session)
    print(f"Started {incident_id} in {args.workspace}")
    print_next(projection)
    if not args.non_interactive:
        interactive_loop(args.workspace)
    return 0


def command_next(args: argparse.Namespace) -> int:
    _context, _session, projection = load_state(args.workspace)
    if args.json:
        print(json.dumps(projection, indent=2, sort_keys=True))
    else:
        print_next(projection)
    return 0


def command_status(args: argparse.Namespace) -> int:
    context, _session, projection = load_state(args.workspace)
    if args.json:
        print(json.dumps(projection, indent=2, sort_keys=True))
    else:
        print_status(context, projection)
    return 0


def command_answer(args: argparse.Namespace) -> int:
    fields = parse_pairs(args.fields)
    projection = record_answer(args.workspace, args.dimension, fields)
    print(f"Recorded {normalize_dimension(args.dimension).removeprefix(DIMENSION_PREFIX)}. Scoping completeness: {projection['completeness'] * 100:.1f}%")
    print_next(projection)
    return 0


def command_report(args: argparse.Namespace) -> int:
    context, session, projection = load_state(args.workspace)
    rendered = report_text(context, session, projection)
    if args.output:
        atomic_write_text(args.output, rendered)
        print(f"Wrote {args.output}")
    else:
        print(rendered, end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    commands = {
        "investigate": command_investigate,
        "next": command_next,
        "status": command_status,
        "answer": command_answer,
        "report": command_report,
    }
    try:
        return commands[args.command](args)
    except (ValueError, FileNotFoundError) as error:
        print(f"causcope: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

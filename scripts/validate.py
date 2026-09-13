#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CONCEPT_SCHEMA = ROOT / "schema" / "concept.schema.json"
RULE_SCHEMA = ROOT / "schema" / "rule.schema.json"
CLAIM_SCHEMA = ROOT / "schema" / "claim.schema.json"
EXPERIMENT_SCHEMA = ROOT / "schema" / "experiment.schema.json"
CAUSAL_EDGE_SCHEMA = ROOT / "schema" / "causal-edge.schema.json"
INCIDENT_CONTEXT_SCHEMA = ROOT / "schema" / "incident-context.schema.json"
INVESTIGATION_SESSION_SCHEMA = ROOT / "schema" / "investigation-session.schema.json"
INVESTIGATION_SCENARIO_SCHEMA = ROOT / "schema" / "investigation-scenario.schema.json"

REFERENCE_FIELDS = {"may_indicate", "tested_by", "produces", "requires", "preferred_tools", "prerequisites", "related_to"}
SCALAR_REFERENCE_FIELDS = {"source", "target"}


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def knowledge_files() -> list[Path]: return sorted((ROOT / "knowledge").rglob("*.yaml"))
def rule_files() -> list[Path]: return sorted((ROOT / "rules").rglob("*.yaml"))
def claim_files() -> list[Path]: return sorted((ROOT / "claims").rglob("*.yaml"))
def experiment_files() -> list[Path]: return sorted((ROOT / "experiments").rglob("*.yaml"))
def causal_files() -> list[Path]: return sorted((ROOT / "causal").rglob("*.yaml")) if (ROOT / "causal").exists() else []
def incident_context_files() -> list[Path]: return sorted((ROOT / "examples" / "incidents").rglob("*.yaml")) if (ROOT / "examples" / "incidents").exists() else []
def investigation_session_files() -> list[Path]: return sorted((ROOT / "examples" / "investigations").rglob("*.yaml")) if (ROOT / "examples" / "investigations").exists() else []
def investigation_scenario_files() -> list[Path]: return sorted((ROOT / "lab" / "investigation").rglob("scenario.yaml")) if (ROOT / "lab" / "investigation").exists() else []


def registry_ids() -> set[str]:
    ids: set[str] = set()
    capabilities = load_yaml(ROOT / "vocabulary" / "capabilities.yaml")
    for item in capabilities.get("capabilities", []): ids.add(item["id"])
    tools = load_yaml(ROOT / "vocabulary" / "tools.yaml")
    for item in tools.get("tools", []): ids.add(item["id"])
    return ids


def concept_references(concept: dict[str, Any]) -> Iterable[str]:
    for field in REFERENCE_FIELDS:
        for reference in concept.get(field, []): yield reference
    for field in SCALAR_REFERENCE_FIELDS:
        reference = concept.get(field)
        if reference: yield reference
    for prediction in concept.get("predictions", []): yield prediction["observation"]
    for falsifier in concept.get("falsifiers", []): yield falsifier["observation"]


def repo_path(relative_path: str) -> Path | None:
    path = (ROOT / relative_path).resolve()
    try: path.relative_to(ROOT)
    except ValueError: return None
    return path


def validate_runner(path: Path, runner: dict[str, Any], errors: list[str]) -> None:
    label = path.relative_to(ROOT)
    if runner.get("type") == "docker":
        build_context = runner.get("build_context")
        if not build_context: return
        context_path = repo_path(build_context)
        if context_path is None: errors.append(f"{label}: build context escapes repository: {build_context}")
        elif not (context_path / "Dockerfile").exists(): errors.append(f"{label}: Dockerfile missing in build context: {build_context}")
        return
    if runner.get("type") == "docker_compose":
        compose_file = runner.get("compose_file")
        if not compose_file: return
        compose_path = repo_path(compose_file)
        if compose_path is None:
            errors.append(f"{label}: compose file escapes repository: {compose_file}"); return
        if not compose_path.is_file():
            errors.append(f"{label}: compose file missing: {compose_file}"); return
        compose_document = load_yaml(compose_path) or {}
        services = compose_document.get("services", {})
        for field in ("setup_service", "evidence_service"):
            service = runner.get(field)
            if service and service not in services: errors.append(f"{label}: {field} not found in compose services: {service}")


def validate() -> None:
    concept_validator = Draft202012Validator(load_json(CONCEPT_SCHEMA))
    rule_validator = Draft202012Validator(load_json(RULE_SCHEMA))
    claim_validator = Draft202012Validator(load_json(CLAIM_SCHEMA))
    experiment_validator = Draft202012Validator(load_json(EXPERIMENT_SCHEMA))
    causal_validator = Draft202012Validator(load_json(CAUSAL_EDGE_SCHEMA))
    incident_context_validator = Draft202012Validator(load_json(INCIDENT_CONTEXT_SCHEMA))
    investigation_session_validator = Draft202012Validator(load_json(INVESTIGATION_SESSION_SCHEMA))
    investigation_scenario_validator = Draft202012Validator(load_json(INVESTIGATION_SCENARIO_SCHEMA))
    concepts: dict[str, dict[str, Any]] = {}
    claims: dict[str, dict[str, Any]] = {}
    experiments: dict[str, dict[str, Any]] = {}
    causal_edges: dict[str, dict[str, Any]] = {}
    incident_ids: set[str] = set()
    session_ids: set[str] = set()
    scenario_ids: set[str] = set()
    errors: list[str] = []

    for path in knowledge_files():
        document = load_yaml(path)
        for error in sorted(concept_validator.iter_errors(document), key=lambda item: list(item.path)): errors.append(f"{path.relative_to(ROOT)}: schema: {error.message}")
        concept_id = document.get("id")
        if concept_id in concepts: errors.append(f"{path.relative_to(ROOT)}: duplicate id: {concept_id}")
        else: concepts[concept_id] = document

    known_concept_ids = set(concepts) | registry_ids()
    for concept_id, concept in concepts.items():
        for reference in concept_references(concept):
            if reference not in known_concept_ids: errors.append(f"{concept_id}: unresolved reference: {reference}")
        if concept.get("kind") == "boundary":
            for field in ("source", "target"):
                ref = concept.get(field)
                target = concepts.get(ref)
                if target and target.get("kind") != "system_entity": errors.append(f"{concept_id}: {field} must reference a system_entity: {ref}")

    for path in claim_files():
        document = load_yaml(path)
        for error in sorted(claim_validator.iter_errors(document), key=lambda item: list(item.path)): errors.append(f"{path.relative_to(ROOT)}: schema: {error.message}")
        claim_id = document.get("id")
        if claim_id in claims or claim_id in known_concept_ids: errors.append(f"{path.relative_to(ROOT)}: duplicate id: {claim_id}")
        else: claims[claim_id] = document
        hypothesis = document.get("hypothesis")
        if hypothesis not in concepts: errors.append(f"{path.relative_to(ROOT)}: unresolved hypothesis: {hypothesis}")
        for prediction in document.get("predictions", []):
            observation = prediction.get("observation")
            if observation not in concepts: errors.append(f"{path.relative_to(ROOT)}: unresolved observation: {observation}")
        for entity_id in document.get("system_entities", []):
            entity = concepts.get(entity_id)
            if entity is None: errors.append(f"{path.relative_to(ROOT)}: unresolved system entity: {entity_id}")
            elif entity.get("kind") != "system_entity": errors.append(f"{path.relative_to(ROOT)}: not a system_entity: {entity_id}")
        for boundary_id in document.get("boundaries", []):
            boundary = concepts.get(boundary_id)
            if boundary is None: errors.append(f"{path.relative_to(ROOT)}: unresolved boundary: {boundary_id}")
            elif boundary.get("kind") != "boundary": errors.append(f"{path.relative_to(ROOT)}: not a boundary: {boundary_id}")

    for path in experiment_files():
        document = load_yaml(path)
        for error in sorted(experiment_validator.iter_errors(document), key=lambda item: list(item.path)): errors.append(f"{path.relative_to(ROOT)}: schema: {error.message}")
        experiment_id = document.get("id")
        if experiment_id in experiments or experiment_id in known_concept_ids or experiment_id in claims: errors.append(f"{path.relative_to(ROOT)}: duplicate id: {experiment_id}")
        else: experiments[experiment_id] = document
        for claim_id in document.get("claims", []):
            if claim_id not in claims: errors.append(f"{path.relative_to(ROOT)}: unresolved claim: {claim_id}")
        validate_runner(path, document.get("runner", {}), errors)

    causal_triples: set[tuple[str, str, str]] = set()
    for path in causal_files():
        document = load_yaml(path)
        for error in sorted(causal_validator.iter_errors(document), key=lambda item: list(item.path)): errors.append(f"{path.relative_to(ROOT)}: schema: {error.message}")
        edge_id = document.get("id")
        if edge_id in causal_edges or edge_id in known_concept_ids or edge_id in claims or edge_id in experiments:
            errors.append(f"{path.relative_to(ROOT)}: duplicate id: {edge_id}")
        else:
            causal_edges[edge_id] = document

        source = document.get("source")
        target = document.get("target")
        relation = document.get("relation")
        if source not in concepts: errors.append(f"{path.relative_to(ROOT)}: unresolved causal source concept: {source}")
        if target not in concepts: errors.append(f"{path.relative_to(ROOT)}: unresolved causal target concept: {target}")
        if source == target: errors.append(f"{path.relative_to(ROOT)}: causal self-edge is not allowed: {source}")
        triple = (source, relation, target)
        if triple in causal_triples: errors.append(f"{path.relative_to(ROOT)}: duplicate causal edge triple: {triple}")
        else: causal_triples.add(triple)

        evidence = document.get("evidence", {})
        evidence_claims = set(evidence.get("claims", []))
        evidence_experiments = set(evidence.get("experiments", []))
        for claim_id in evidence_claims:
            if claim_id not in claims: errors.append(f"{path.relative_to(ROOT)}: unresolved causal evidence claim: {claim_id}")
        for experiment_id in evidence_experiments:
            experiment = experiments.get(experiment_id)
            if experiment is None:
                errors.append(f"{path.relative_to(ROOT)}: unresolved causal evidence experiment: {experiment_id}")
                continue
            if evidence_claims and not (set(experiment.get("claims", [])) & evidence_claims):
                errors.append(f"{path.relative_to(ROOT)}: experiment {experiment_id} supports none of the listed causal evidence claims")

    for path in incident_context_files():
        document = load_yaml(path)
        for error in sorted(incident_context_validator.iter_errors(document), key=lambda item: list(item.path)):
            errors.append(f"{path.relative_to(ROOT)}: schema: {error.message}")
        incident_id = document.get("incident_id")
        if incident_id in incident_ids: errors.append(f"{path.relative_to(ROOT)}: duplicate incident_id: {incident_id}")
        else: incident_ids.add(incident_id)

        scope = document.get("scope", {})
        for entity_id in scope.get("entities", []):
            entity = concepts.get(entity_id)
            if entity is None: errors.append(f"{path.relative_to(ROOT)}: unresolved incident scope entity: {entity_id}")
            elif entity.get("kind") != "system_entity": errors.append(f"{path.relative_to(ROOT)}: incident scope entity is not a system_entity: {entity_id}")
        for boundary_id in scope.get("boundaries", []):
            boundary = concepts.get(boundary_id)
            if boundary is None: errors.append(f"{path.relative_to(ROOT)}: unresolved incident scope boundary: {boundary_id}")
            elif boundary.get("kind") != "boundary": errors.append(f"{path.relative_to(ROOT)}: incident scope boundary is not a boundary: {boundary_id}")
        for dependency in scope.get("dependencies", []):
            boundary_id = dependency.get("boundary")
            if not boundary_id: continue
            boundary = concepts.get(boundary_id)
            if boundary is None: errors.append(f"{path.relative_to(ROOT)}: unresolved dependency boundary: {boundary_id}")
            elif boundary.get("kind") != "boundary": errors.append(f"{path.relative_to(ROOT)}: dependency boundary is not a boundary: {boundary_id}")

    for path in investigation_session_files():
        document = load_yaml(path)
        for error in sorted(investigation_session_validator.iter_errors(document), key=lambda item: list(item.path)):
            errors.append(f"{path.relative_to(ROOT)}: schema: {error.message}")
        session_id = document.get("session_id")
        if session_id in session_ids: errors.append(f"{path.relative_to(ROOT)}: duplicate investigation session_id: {session_id}")
        else: session_ids.add(session_id)
        incident_id = document.get("incident_id")
        if incident_id not in incident_ids: errors.append(f"{path.relative_to(ROOT)}: unresolved investigation incident_id: {incident_id}")
        event_ids: set[str] = set()
        for event in document.get("events", []):
            event_id = event.get("id")
            if event_id in event_ids: errors.append(f"{path.relative_to(ROOT)}: duplicate investigation event id: {event_id}")
            else: event_ids.add(event_id)

    for path in investigation_scenario_files():
        document = load_yaml(path)
        for error in sorted(investigation_scenario_validator.iter_errors(document), key=lambda item: list(item.path)):
            errors.append(f"{path.relative_to(ROOT)}: schema: {error.message}")
        scenario_id = document.get("id")
        if scenario_id in scenario_ids: errors.append(f"{path.relative_to(ROOT)}: duplicate investigation scenario id: {scenario_id}")
        else: scenario_ids.add(scenario_id)
        context_ref = document.get("initial_context_file")
        context_path = repo_path(context_ref) if isinstance(context_ref, str) else None
        if context_path is None:
            errors.append(f"{path.relative_to(ROOT)}: invalid initial context path: {context_ref}")
        elif not context_path.is_file():
            errors.append(f"{path.relative_to(ROOT)}: initial context file missing: {context_ref}")
        else:
            context_document = load_yaml(context_path)
            for error in sorted(incident_context_validator.iter_errors(context_document), key=lambda item: list(item.path)):
                errors.append(f"{context_path.relative_to(ROOT)}: schema: {error.message}")

    dimension_registry = load_yaml(ROOT / "vocabulary" / "investigation-dimensions.yaml")
    dimensions = dimension_registry.get("dimensions", []) if isinstance(dimension_registry, dict) else []
    dimension_ids = [item.get("id") for item in dimensions if isinstance(item, dict)]
    dimension_orders = [item.get("order") for item in dimensions if isinstance(item, dict)]
    if len(dimensions) != 10 or len(set(dimension_ids)) != 10:
        errors.append("vocabulary/investigation-dimensions.yaml: expected exactly 10 unique dimensions")
    if sorted(dimension_orders) != list(range(1, 11)):
        errors.append("vocabulary/investigation-dimensions.yaml: dimension order must be 1 through 10")

    for path in rule_files():
        document = load_yaml(path)
        for error in sorted(rule_validator.iter_errors(document), key=lambda item: list(item.path)): errors.append(f"{path.relative_to(ROOT)}: schema: {error.message}")
        hypothesis = document.get("hypothesis"); observation = document.get("when", {}).get("observation")
        if hypothesis not in concepts: errors.append(f"{path.relative_to(ROOT)}: unresolved hypothesis: {hypothesis}")
        if observation not in concepts: errors.append(f"{path.relative_to(ROOT)}: unresolved observation: {observation}")

    if errors:
        for error in errors: print(f"ERROR: {error}")
        raise SystemExit(1)
    print(
        "Validated "
        f"{len(concepts)} concepts, {len(claims)} claims, "
        f"{len(experiments)} experiments, {len(causal_edges)} causal edges, "
        f"{len(incident_ids)} incident contexts, {len(session_ids)} investigation sessions, "
        f"{len(scenario_ids)} investigation scenarios, and {len(rule_files())} rules "
        "with no unresolved references."
    )


if __name__ == "__main__": validate()

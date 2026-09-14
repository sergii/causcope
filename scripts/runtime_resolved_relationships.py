#!/usr/bin/env python3

import argparse
import hashlib
import json
from pathlib import Path


LIMITATION = (
    "Runtime-resolved relationships are incident- and execution-scoped and must not be "
    "rewritten as unconditional static code-to-resource facts."
)


def load_json(path):
    return json.loads(Path(path).read_text())


def stable_relationship_id(system_id, revision, incident_id, interaction):
    payload = "\x1f".join(
        [
            system_id,
            revision,
            incident_id,
            interaction["id"],
            interaction["execution_id"],
            interaction["pool_id"],
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"runtime_relationship.opentelemetry.{digest}"


def project(static_document, runtime_document):
    if static_document.get("kind") != "concrete_system_facts":
        raise ValueError("static input must be concrete_system_facts")
    if runtime_document.get("kind") != "concrete_runtime_facts":
        raise ValueError("runtime input must be concrete_runtime_facts")

    system_id = static_document.get("system_id")
    if runtime_document.get("system_id") != system_id:
        raise ValueError("runtime system_id does not match static system_id")

    static_revision = static_document.get("revision", {})
    runtime_revision = runtime_document.get("revision", {})
    if runtime_revision.get("value") != static_revision.get("value"):
        raise ValueError("runtime revision does not match static revision")
    if runtime_revision.get("type") != static_revision.get("type"):
        raise ValueError("runtime revision type does not match static revision type")
    if static_revision.get("repository") != runtime_revision.get("repository"):
        raise ValueError("runtime revision repository does not match static revision repository")

    incident_id = runtime_document.get("incident_id")
    if not incident_id:
        raise ValueError("runtime incident_id is required")

    entities = {entity["id"]: entity for entity in static_document.get("entities", [])}
    executions = {execution["id"]: execution for execution in runtime_document.get("executions", [])}

    relationships = []
    for interaction in runtime_document.get("pool_interactions", []):
        execution = executions.get(interaction.get("execution_id"))
        if execution is None:
            raise ValueError(f"unknown execution for pool interaction {interaction.get('id')}")

        for field in ("code_symbol", "trace_id", "span_id"):
            if interaction.get(field) != execution.get(field):
                raise ValueError(
                    f"pool interaction {interaction.get('id')} {field} does not match its execution"
                )

        pool_id = interaction.get("pool_id")
        pool = entities.get(pool_id)
        if pool is None:
            raise ValueError(f"pool interaction {interaction.get('id')} references unknown resource {pool_id}")
        if pool.get("kind") != "resource_pool":
            raise ValueError(f"runtime resource {pool_id} is not a static resource_pool")

        attributes = pool.get("attributes", {})
        static_technology = attributes.get("technology")
        if static_technology and interaction.get("technology") != static_technology:
            raise ValueError(f"runtime technology does not match static resource {pool_id}")

        static_config_name = attributes.get("config_name")
        if static_config_name and interaction.get("config_name") != static_config_name:
            raise ValueError(f"runtime config_name does not match static resource {pool_id}")

        relationships.append(
            {
                "id": stable_relationship_id(
                    system_id,
                    static_revision["value"],
                    incident_id,
                    interaction,
                ),
                "subject_execution": execution["id"],
                "code_symbol": execution["code_symbol"],
                "relation": "used_resource",
                "object_resource": pool_id,
                "object_kind": "resource_pool",
                "interaction_kind": "resource_pool_checkout",
                "evidence_ref": interaction["id"],
                "trace_id": execution["trace_id"],
                "span_id": execution["span_id"],
                "observed_at": interaction["observed_at"],
                "source": interaction["source"],
            }
        )

    relationships.sort(
        key=lambda item: (
            item["subject_execution"],
            item["object_resource"],
            item["evidence_ref"],
            item["id"],
        )
    )

    return {
        "schema_version": "0.1",
        "kind": "runtime_resolved_relationships",
        "system_id": system_id,
        "revision": static_revision,
        "incident_id": incident_id,
        "relationships": relationships,
        "limitations": [LIMITATION],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Project exact runtime interactions into incident-scoped resource relationships."
    )
    parser.add_argument("--static-facts", required=True)
    parser.add_argument("--runtime-facts", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    document = project(load_json(args.static_facts), load_json(args.runtime_facts))
    indent = 2 if args.pretty else None
    rendered = json.dumps(document, indent=indent, sort_keys=True)
    Path(args.output).write_text(rendered + "\n")


if __name__ == "__main__":
    main()

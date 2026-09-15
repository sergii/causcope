#!/usr/bin/env python3

from __future__ import annotations

import copy
from typing import Any

from instrument_router import InstrumentRouter
from instrument_routing_projection import validate_instrument_routing_projection
from routable_probe_selection import ranked_probe_candidates, select_highest_ranked_routable_probe


def build_ranked_routable_projection(
    snapshot: dict[str, Any],
    router: InstrumentRouter,
) -> dict[str, Any]:
    """Project one server-authorized executable fallback per diagnosis.

    Semantic probe ranking remains untouched. If rank 1 cannot be safely routed,
    the projection may expose rank 2+ as the highest-ranked executable option.
    """

    if snapshot.get("kind") != "diagnosis_snapshot":
        raise ValueError("ranked routable projection requires a diagnosis_snapshot")
    incident_id = snapshot.get("incident_id")
    revision = snapshot.get("evidence_revision")
    if not isinstance(incident_id, str) or not incident_id:
        raise ValueError("diagnosis snapshot must include incident_id")
    if not isinstance(revision, int) or revision < 0:
        raise ValueError("diagnosis snapshot must include a non-negative evidence_revision")

    routes: list[dict[str, Any]] = []
    for partition in snapshot.get("partitions", []):
        if not isinstance(partition, dict):
            continue
        scope = partition.get("scope")
        for diagnosis in partition.get("diagnoses", []):
            if not isinstance(diagnosis, dict):
                continue
            target = diagnosis.get("target")
            if not isinstance(target, str) or not target:
                continue
            ranked = ranked_probe_candidates(diagnosis)
            if not ranked:
                continue

            selected = select_highest_ranked_routable_probe(
                diagnosis,
                router,
                scope,
                execution_requirement="direct",
            )
            if selected is None:
                top = ranked[0]
                decision = router.route(
                    top["probe_id"],
                    scope,
                    execution_requirement="direct",
                )
                routes.append(
                    {
                        "scope": copy.deepcopy(decision.get("scope")),
                        "target": target,
                        "probe_id": top["probe_id"],
                        "probe_rank": top["probe_rank"],
                        "routing_strategy": "ranked_routable_fallback",
                        "decision": {
                            "selected_instrument": None,
                            "stop_reason": decision.get("stop_reason") or "no_ranked_probe_has_safe_direct_route",
                            "selection_reason": None,
                        },
                        "agent_action": {
                            "kind": "stop",
                            "mcp_execution_available": False,
                            "reason": "no semantically ranked probe has a safe direct route in this environment",
                        },
                    }
                )
                continue

            decision = selected["decision"]
            instrument = copy.deepcopy(decision["selection"]["instrument"])
            routes.append(
                {
                    "scope": copy.deepcopy(decision.get("scope")),
                    "target": target,
                    "probe_id": selected["probe_id"],
                    "probe_rank": selected["probe_rank"],
                    "routing_strategy": "ranked_routable_fallback",
                    "decision": {
                        "selected_instrument": instrument,
                        "stop_reason": None,
                        "selection_reason": (
                            f"semantic probe rank {selected['probe_rank']} is the highest-ranked probe "
                            "with a current safe exact-scope direct route; higher-ranked unroutable "
                            "probes remain higher-ranked in diagnosis"
                        ),
                    },
                    "agent_action": {
                        "kind": "use_external_instrument",
                        "mcp_execution_available": True,
                        "reason": (
                            "server selected the highest-ranked currently routable read-only probe; "
                            "execution remains revision-, scope-, probe-, and instrument-bound"
                        ),
                    },
                }
            )

    routes.sort(
        key=lambda item: (
            str(item.get("scope")),
            item["target"],
            item["probe_rank"],
            item["probe_id"],
        )
    )
    document = {
        "schema_version": "0.1",
        "kind": "instrument_routing_projection",
        "incident_id": incident_id,
        "evidence_revision": revision,
        "routes": routes,
    }
    validate_instrument_routing_projection(document)
    return document

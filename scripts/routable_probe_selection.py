#!/usr/bin/env python3

from __future__ import annotations

import copy
from typing import Any

from instrument_router import InstrumentRouter


def ranked_probe_candidates(diagnosis: dict[str, Any]) -> list[dict[str, Any]]:
    ranking = diagnosis.get("probe_ranking", {})
    probes = ranking.get("probes", []) if isinstance(ranking, dict) else []
    if ranking.get("found") is not True or not isinstance(probes, list):
        return []
    output: list[dict[str, Any]] = []
    for index, candidate in enumerate(probes):
        if not isinstance(candidate, dict):
            continue
        probe = candidate.get("probe", {})
        probe_id = probe.get("id") if isinstance(probe, dict) else None
        if not isinstance(probe_id, str) or not probe_id:
            continue
        output.append(
            {
                "probe_id": probe_id,
                "probe_rank": index + 1,
                "probe_candidate": copy.deepcopy(candidate),
            }
        )
    return output


def select_highest_ranked_routable_probe(
    diagnosis: dict[str, Any],
    router: InstrumentRouter,
    scope: dict[str, Any] | None,
    *,
    execution_requirement: str = "direct",
) -> dict[str, Any] | None:
    """Select the first semantically ranked probe with a safe current route.

    This is an execution-eligibility projection only. It does not reorder or
    rewrite semantic probe ranking. An unroutable higher-ranked probe remains
    higher-ranked in the diagnosis; it simply cannot authorize execution here.
    """

    for item in ranked_probe_candidates(diagnosis):
        decision = router.route(
            item["probe_id"],
            scope,
            execution_requirement=execution_requirement,
        )
        if isinstance(decision.get("selection"), dict):
            return {
                **item,
                "decision": decision,
            }
    return None

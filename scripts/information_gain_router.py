#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from autonomous_investigation import ProbeInsufficientEvidence
from causal_projection import ROOT
from instrument_router import InstrumentRouter, RoutedProvider

SCHEMA_PATH = ROOT / "schema" / "information-gain-routing-decision.schema.json"
ROUTER_ID = "information_gain_router.v0"
BASE_ROUTER_ID = "instrument_router.v0"
SELECTION_POLICY = "safe_target_routes_then_information_gain_proxy"


def _load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    Draft202012Validator.check_schema(schema)
    return schema


def validate_information_gain_routing_decision(document: dict[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(_load_schema()).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ValueError(
            "information-gain routing decision schema validation failed: "
            + "; ".join(error.message for error in errors)
        )


def _pair(value: Any, label: str) -> tuple[str, str]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise ValueError(f"{label} must contain two non-empty hypothesis IDs")
    return value[0], value[1]


def _validate_probe_candidate(probe_candidate: dict[str, Any]) -> str:
    if not isinstance(probe_candidate, dict):
        raise ValueError("probe candidate must be an object")
    probe_id = probe_candidate.get("probe", {}).get("id")
    if not isinstance(probe_id, str) or not probe_id:
        raise ValueError("probe candidate must include probe.id")
    factors = probe_candidate.get("factors")
    if not isinstance(factors, dict):
        raise ValueError("probe candidate must include factors")
    top_candidate = factors.get("top_candidate")
    if not isinstance(top_candidate, str) or not top_candidate:
        raise ValueError("probe candidate must include factors.top_candidate")
    analyses = probe_candidate.get("outcome_analysis")
    if not isinstance(analyses, list):
        raise ValueError("probe candidate must include outcome_analysis")
    for index, analysis in enumerate(analyses):
        if not isinstance(analysis, dict):
            raise ValueError(f"outcome_analysis[{index}] must be an object")
        observation = analysis.get("observation")
        if not isinstance(observation, str) or not observation:
            raise ValueError(f"outcome_analysis[{index}] must include observation")
        for field in ("observed_distinguishes_pairs", "absent_distinguishes_pairs"):
            pairs = analysis.get(field)
            if not isinstance(pairs, list):
                raise ValueError(f"outcome_analysis[{index}].{field} must be a list")
            for pair_index, pair in enumerate(pairs):
                _pair(pair, f"outcome_analysis[{index}].{field}[{pair_index}]")
    return probe_id


def _sorted_pairs(pairs: set[tuple[str, str]]) -> list[list[str]]:
    return [list(pair) for pair in sorted(pairs)]


def _top_alternatives(
    pairs: set[tuple[str, str]],
    top_candidate: str,
) -> list[str]:
    alternatives: set[str] = set()
    for left, right in pairs:
        if left == top_candidate and right != top_candidate:
            alternatives.add(right)
        elif right == top_candidate and left != top_candidate:
            alternatives.add(left)
    return sorted(alternatives)


def _probe_entry(
    projection: dict[str, Any],
    probe_id: str,
) -> dict[str, Any]:
    for entry in projection.get("probes", []):
        if entry.get("probe", {}).get("id") == probe_id:
            return entry
    raise ValueError(
        f"provider {projection.get('id')} does not advertise selected probe {probe_id}"
    )


def build_information_gain_proxy(
    probe_candidate: dict[str, Any],
    provider_projection: dict[str, Any],
) -> dict[str, Any]:
    probe_id = _validate_probe_candidate(probe_candidate)
    entry = _probe_entry(provider_projection, probe_id)
    mapped_observations = {
        observation
        for observation in entry.get("mapped_observations", [])
        if isinstance(observation, str)
    }
    top_candidate = probe_candidate["factors"]["top_candidate"]
    positive_only = bool(
        provider_projection.get("evidence_semantics", {}).get("positive_findings_only")
    )

    observed_pairs: set[tuple[str, str]] = set()
    absent_pairs: set[tuple[str, str]] = set()
    covered_observations: set[str] = set()

    for analysis in probe_candidate["outcome_analysis"]:
        observation = analysis["observation"]
        if observation not in mapped_observations:
            continue
        covered_observations.add(observation)
        for pair in analysis["observed_distinguishes_pairs"]:
            observed_pairs.add(_pair(pair, "observed_distinguishes_pairs"))
        if not positive_only:
            for pair in analysis["absent_distinguishes_pairs"]:
                absent_pairs.add(_pair(pair, "absent_distinguishes_pairs"))

    discriminated_pairs = observed_pairs | absent_pairs
    two_sided_pairs = observed_pairs & absent_pairs
    return {
        "type": "deterministic_causal_contrast_proxy",
        "probabilistic_information_gain": False,
        "outcome_support": (
            "positive_findings_only" if positive_only else "observed_and_absent"
        ),
        "discriminating_observations": sorted(covered_observations),
        "observed_distinguishes_pairs": _sorted_pairs(observed_pairs),
        "absent_distinguishes_pairs": _sorted_pairs(absent_pairs),
        "discriminated_candidate_pairs": _sorted_pairs(discriminated_pairs),
        "two_sided_candidate_pairs": _sorted_pairs(two_sided_pairs),
        "top_candidate_discriminated_alternatives": _top_alternatives(
            discriminated_pairs, top_candidate
        ),
        "top_candidate_two_sided_alternatives": _top_alternatives(
            two_sided_pairs, top_candidate
        ),
    }


def _gain_sort_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    gain = candidate["information_gain_proxy"]
    return (
        -len(gain["top_candidate_two_sided_alternatives"]),
        -len(gain["top_candidate_discriminated_alternatives"]),
        -len(gain["two_sided_candidate_pairs"]),
        -len(gain["discriminated_candidate_pairs"]),
        -len(gain["discriminating_observations"]),
        0 if gain["outcome_support"] == "observed_and_absent" else 1,
        candidate["instrument"]["id"],
    )


class InformationGainInstrumentRouter:
    """Choose the most discriminating provider after base router safety filtering.

    This layer never makes an unsafe route eligible and never changes semantic
    probe ranking. The score is an ordinal proxy over the existing probe-ranking
    causal contrasts, not Shannon information gain or a learned probability.
    """

    def __init__(
        self,
        *,
        router: InstrumentRouter,
        provider_instance_bindings: dict[str, RoutedProvider],
    ) -> None:
        self.router = router
        self.provider_instance_bindings = dict(provider_instance_bindings)

    def route(
        self,
        probe_candidate: dict[str, Any],
        scope: dict[str, Any] | None,
        *,
        target_resource: str,
        execution_requirement: str = "any",
    ) -> dict[str, Any]:
        probe_id = _validate_probe_candidate(probe_candidate)
        base_decision = self.router.route(
            probe_id,
            scope,
            execution_requirement=execution_requirement,
            target_resource=target_resource,
        )

        provider_candidates: list[dict[str, Any]] = []
        for base_candidate in base_decision["candidates"]:
            instrument = base_candidate["instrument"]
            if instrument["kind"] != "diagnostic_provider":
                continue
            provider = self.provider_instance_bindings.get(instrument["id"])
            if provider is None:
                continue
            projection = provider.capability_projection()
            gain = build_information_gain_proxy(probe_candidate, projection)
            provider_candidates.append(
                {
                    "rank": 0,
                    "instrument": copy.deepcopy(instrument),
                    "eligible": bool(base_candidate["eligible"]),
                    "base_reasons": copy.deepcopy(base_candidate["reasons"]),
                    "information_gain_proxy": gain,
                }
            )

        base_eligible = [
            candidate for candidate in provider_candidates if candidate["eligible"]
        ]
        eligible = [
            candidate
            for candidate in base_eligible
            if candidate["information_gain_proxy"]["discriminated_candidate_pairs"]
        ]
        eligible.sort(key=_gain_sort_key)
        eligible_ids = {candidate["instrument"]["id"] for candidate in eligible}
        ordered = eligible + sorted(
            [
                candidate
                for candidate in provider_candidates
                if candidate["instrument"]["id"] not in eligible_ids
            ],
            key=lambda candidate: candidate["instrument"]["id"],
        )
        for rank, candidate in enumerate(ordered, start=1):
            candidate["rank"] = rank

        selected = eligible[0] if eligible else None
        if selected is None:
            selection = None
            stop_reason = (
                "no_informative_provider"
                if base_eligible
                else base_decision.get("stop_reason") or "no_safe_available_provider"
            )
        else:
            selection = {
                "instrument": copy.deepcopy(selected["instrument"]),
                "information_gain_proxy": copy.deepcopy(selected["information_gain_proxy"]),
                "reason": (
                    "provider passed the base safety, exact-scope, exact-target, endpoint, runner, "
                    "and execution-mode checks and maximizes the deterministic causal-contrast "
                    "information-gain proxy"
                ),
            }
            stop_reason = None

        document = {
            "schema_version": "0.1",
            "kind": "information_gain_routing_decision",
            "probe": copy.deepcopy(base_decision["probe"]),
            "scope": copy.deepcopy(base_decision["scope"]),
            "target_resource": target_resource,
            "execution_requirement": execution_requirement,
            "selection_policy": SELECTION_POLICY,
            "base_router_selection": copy.deepcopy(base_decision.get("selection")),
            "provider_candidates": ordered,
            "selection": selection,
            "stop_reason": stop_reason,
        }
        validate_information_gain_routing_decision(document)
        return document

    def execute(
        self,
        probe_candidate: dict[str, Any],
        target: str,
        scope: dict[str, Any] | None,
        *,
        target_resource: str,
    ) -> dict[str, Any]:
        decision = self.route(
            probe_candidate,
            scope,
            target_resource=target_resource,
            execution_requirement="direct",
        )
        selection = decision["selection"]
        if selection is None:
            raise ProbeInsufficientEvidence(
                f"information-gain router cannot execute: {decision['stop_reason']}"
            )

        instrument = selection["instrument"]
        provider = self.provider_instance_bindings.get(instrument["id"])
        if provider is None:
            raise ProbeInsufficientEvidence(
                f"selected provider has no execution binding: {instrument['id']}"
            )
        probe_id = decision["probe"]["id"]
        evidence = provider.execute(probe_id, target, copy.deepcopy(scope))
        for instance in evidence.get("instances", []):
            source = instance.setdefault("source", {})
            attributes = source.setdefault("attributes", {})
            attributes["routing.router"] = ROUTER_ID
            attributes["routing.base_router"] = BASE_ROUTER_ID
            attributes["routing.instrument_id"] = instrument["id"]
            attributes["routing.instrument_kind"] = instrument["kind"]
            attributes["routing.execution_mode"] = instrument["execution_mode"]
            attributes["routing.target_resource"] = target_resource
            attributes["routing.selection_policy"] = SELECTION_POLICY
            if "endpoint_resource" in instrument:
                attributes["routing.endpoint_resource"] = instrument["endpoint_resource"]
            labels = instance.setdefault("labels", {})
            labels["instrument"] = instrument["id"]
        return evidence

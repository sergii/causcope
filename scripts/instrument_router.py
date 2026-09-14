#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator

from autonomous_investigation import ProbeInsufficientEvidence
from causal_projection import ROOT, load_concepts
from diagnostic_provider_capabilities import build_provider_capabilities
from live_diagnosis import normalize_scope, scope_key
from pgbot_adapter import load_adapter
from pgbot_autonomous_provider import PgbotAutonomousProbeProvider, file_context_supplier
from probe_executor_registry import CAPABILITIES_SCHEMA_PATH
from probe_executor_runtime import build_probe_execution_capabilities
from resource_topology import ResourceTopology
from runtime_evidence import build_scope_query

SCHEMA_PATH = ROOT / "schema" / "instrument-routing-decision.schema.json"
ROUTER_ID = "instrument_router.v0"
SELECTION_POLICY = "safe_exact_scope_then_stable_identity"
TARGET_SELECTION_POLICY = "safe_exact_scope_and_target_then_stable_identity"


class RoutedProvider(Protocol):
    def capability_projection(self) -> dict[str, Any]: ...

    def execute(
        self,
        probe_id: str,
        target: str,
        scope: dict[str, Any] | None,
    ) -> dict[str, Any]: ...


def _load_schema(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    Draft202012Validator.check_schema(schema)
    return schema


def _validate(document: dict[str, Any], schema_path: Path, label: str) -> None:
    errors = sorted(
        Draft202012Validator(_load_schema(schema_path)).iter_errors(document),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ValueError(
            f"{label} schema validation failed: "
            + "; ".join(error.message for error in errors)
        )


def validate_instrument_routing_decision(document: dict[str, Any]) -> None:
    _validate(document, SCHEMA_PATH, "instrument routing decision")


def _availability_from_host(entry: dict[str, Any]) -> dict[str, Any]:
    if entry["available"]:
        return {"state": "available", "reason": None}
    return {
        "state": "unavailable",
        "reason": entry.get("unavailable_reason") or "host executor is unavailable",
    }


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[str, str]:
    instrument = candidate["instrument"]
    return (instrument["id"], instrument["kind"])


class InstrumentRouter:
    """Route a canonical read-only probe to a currently safe configured instrument.

    Routing is deliberately downstream from semantic probe ranking. It does not
    score evidence quality or change causal/probe ranking. Legacy routing filters
    by exact semantic scope, availability, and execution-mode fit. Target-aware
    routing additionally requires an exact observed-resource binding plus a runner
    that satisfies the provider transport and can reach the provider endpoint.
    Direct providers omit endpoint_resource, which means endpoint == target.
    """

    def __init__(
        self,
        *,
        concepts: dict[str, dict[str, Any]],
        host_capabilities: dict[str, Any],
        providers: list[RoutedProvider],
        resource_topology: ResourceTopology | None = None,
        provider_instance_bindings: dict[str, RoutedProvider] | None = None,
    ) -> None:
        _validate(
            host_capabilities,
            CAPABILITIES_SCHEMA_PATH,
            "host probe execution capabilities",
        )
        self.concepts = concepts
        self.host_capabilities = copy.deepcopy(host_capabilities)
        self.providers = list(providers)
        self.provider_capabilities = build_provider_capabilities(self.providers)
        self.resource_topology = resource_topology
        self.provider_instance_bindings = dict(provider_instance_bindings or {})
        if self.provider_instance_bindings and self.resource_topology is None:
            raise ValueError("provider_instance_bindings require resource_topology")

        self._providers_by_id: dict[str, RoutedProvider] = {}
        for provider in self.providers:
            provider_id = provider.capability_projection()["id"]
            if provider_id in self._providers_by_id:
                raise ValueError(f"duplicate routed provider id: {provider_id}")
            self._providers_by_id[provider_id] = provider

        self._provider_instance_capabilities: dict[str, dict[str, Any]] = {}
        if self.resource_topology is not None:
            for instance_id, provider in sorted(self.provider_instance_bindings.items()):
                instance = self.resource_topology.provider_instance(instance_id)
                provider_type = self.resource_topology.provider_type(instance["provider_type"])
                projection = provider.capability_projection()
                provider_id = projection.get("id")
                if provider_id != provider_type["provider_id"]:
                    raise ValueError(
                        f"provider instance {instance_id} expects {provider_type['provider_id']} "
                        f"but runtime binding exposes {provider_id}"
                    )
                if instance_id in self._providers_by_id:
                    raise ValueError(f"duplicate routed provider id: {instance_id}")
                self._providers_by_id[instance_id] = provider
                self._provider_instance_capabilities[instance_id] = copy.deepcopy(projection)

    def _canonical_probe(self, probe_id: str) -> dict[str, Any]:
        probe = self.concepts.get(probe_id)
        if not isinstance(probe, dict) or probe.get("kind") != "probe":
            raise ValueError(f"instrument router target is not a canonical probe: {probe_id}")
        if probe.get("risk") != "read_only":
            raise ValueError(
                f"instrument router refuses non-read-only probe {probe_id}: risk={probe.get('risk')}"
            )
        return probe

    def _host_candidates(
        self,
        probe_id: str,
        normalized_scope: dict[str, Any] | None,
        *,
        execution_requirement: str,
        target_resource: str | None = None,
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for entry in self.host_capabilities.get("executors", []):
            if entry.get("probe", {}).get("id") != probe_id:
                continue
            availability = _availability_from_host(entry)
            reasons: list[str] = []
            scope_match = "exact" if normalized_scope is None else "mismatch"
            if scope_match == "mismatch":
                reasons.append(
                    "host executor has no declared scope binding; router refuses to relabel "
                    "host-global evidence into a scoped diagnosis"
                )
            if availability["state"] != "available":
                reasons.append(
                    f"instrument availability is {availability['state']}: "
                    f"{availability['reason'] or 'no reason supplied'}"
                )
            if execution_requirement == "direct":
                reasons.append("host executor requires the existing begin/finish session lifecycle")

            candidate: dict[str, Any] = {
                "instrument": {
                    "id": entry["executor"]["id"],
                    "kind": "host_executor",
                    "execution_mode": "session",
                },
                "availability": availability,
                "scope_match": scope_match,
                "capabilities": [entry["capability"]],
                "observations": [entry["observation"]],
                "eligible": False,
                "reasons": reasons,
            }
            if target_resource is not None:
                candidate["target_match"] = "unbound"
                candidate["reasons"].append(
                    "host executor has no explicit resource target binding"
                )
            candidate["eligible"] = not candidate["reasons"]
            output.append(candidate)
        return output

    def _legacy_provider_candidates(
        self,
        probe_id: str,
        normalized_scope: dict[str, Any] | None,
        *,
        execution_requirement: str,
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for provider in self.provider_capabilities.get("providers", []):
            provider_scope = normalize_scope(provider.get("scope"), self.concepts)
            for probe_entry in provider.get("probes", []):
                if probe_entry.get("probe", {}).get("id") != probe_id:
                    continue
                reasons: list[str] = []
                scope_match = (
                    "exact"
                    if scope_key(provider_scope) == scope_key(normalized_scope)
                    else "mismatch"
                )
                if scope_match == "mismatch":
                    reasons.append(
                        "provider fixed_exact scope does not match the selected diagnosis scope"
                    )
                availability = copy.deepcopy(provider["availability"])
                if availability["state"] != "available":
                    reasons.append(
                        f"instrument availability is {availability['state']}: "
                        f"{availability['reason'] or 'no reason supplied'}"
                    )
                execution_mode = "direct"
                if execution_requirement == "direct" and execution_mode != "direct":
                    reasons.append("instrument does not support direct autonomous execution")

                output.append(
                    {
                        "instrument": {
                            "id": provider["id"],
                            "kind": "diagnostic_provider",
                            "execution_mode": execution_mode,
                        },
                        "availability": availability,
                        "scope_match": scope_match,
                        "capabilities": sorted(probe_entry.get("requires", [])),
                        "observations": sorted(probe_entry.get("mapped_observations", [])),
                        "eligible": not reasons,
                        "reasons": reasons,
                    }
                )
        return output

    def _target_provider_candidates(
        self,
        probe_id: str,
        normalized_scope: dict[str, Any] | None,
        *,
        execution_requirement: str,
        target_resource: str,
    ) -> list[dict[str, Any]]:
        if self.resource_topology is None:
            raise ValueError("target_resource routing requires resource_topology")
        self.resource_topology.resource(target_resource)

        output: list[dict[str, Any]] = []
        for instance in self.resource_topology.provider_instances:
            projection = self._provider_instance_capabilities.get(instance["id"])
            if projection is None:
                continue
            provider_type = self.resource_topology.provider_type(instance["provider_type"])
            provider_scope = normalize_scope(projection.get("scope"), self.concepts)
            for probe_entry in projection.get("probes", []):
                if probe_entry.get("probe", {}).get("id") != probe_id:
                    continue

                reasons: list[str] = []
                scope_match = (
                    "exact"
                    if scope_key(provider_scope) == scope_key(normalized_scope)
                    else "mismatch"
                )
                if scope_match == "mismatch":
                    reasons.append(
                        "provider fixed_exact scope does not match the selected diagnosis scope"
                    )

                target_match = (
                    "exact" if instance["target"] == target_resource else "mismatch"
                )
                if target_match == "mismatch":
                    reasons.append(
                        f"provider instance targets {instance['target']} instead of {target_resource}"
                    )

                availability = copy.deepcopy(projection["availability"])
                if availability["state"] != "available":
                    reasons.append(
                        f"instrument availability is {availability['state']}: "
                        f"{availability['reason'] or 'no reason supplied'}"
                    )

                runner = self.resource_topology.runner(instance["runner"])
                if not runner["available"]:
                    reasons.append(f"runner {runner['id']} is unavailable")
                required_runner_capabilities = set(provider_type.get("runner_capabilities", []))
                missing_runner_capabilities = sorted(
                    required_runner_capabilities - set(runner.get("capabilities", []))
                )
                if missing_runner_capabilities:
                    reasons.append(
                        f"runner {runner['id']} lacks provider capabilities: "
                        + ", ".join(missing_runner_capabilities)
                    )

                endpoint_resource_id = instance.get("endpoint_resource", instance["target"])
                endpoint_resource = self.resource_topology.resource(endpoint_resource_id)
                network_domain = endpoint_resource.get("network_domain")
                if network_domain and network_domain not in runner["network_domains"]:
                    reasons.append(
                        f"runner {runner['id']} cannot reach provider endpoint network domain "
                        f"{network_domain}"
                    )

                execution_mode = "direct"
                if execution_requirement == "direct" and execution_mode != "direct":
                    reasons.append("instrument does not support direct autonomous execution")

                instrument = {
                    "id": instance["id"],
                    "kind": "diagnostic_provider",
                    "execution_mode": execution_mode,
                    "provider_type": instance["provider_type"],
                    "target_resource": instance["target"],
                    "runner": instance["runner"],
                }
                if "endpoint_resource" in instance:
                    instrument["endpoint_resource"] = endpoint_resource_id

                output.append(
                    {
                        "instrument": instrument,
                        "availability": availability,
                        "scope_match": scope_match,
                        "target_match": target_match,
                        "capabilities": sorted(probe_entry.get("requires", [])),
                        "observations": sorted(probe_entry.get("mapped_observations", [])),
                        "eligible": not reasons,
                        "reasons": reasons,
                    }
                )
        return output

    def route(
        self,
        probe_id: str,
        scope: dict[str, Any] | None,
        *,
        execution_requirement: str = "any",
        target_resource: str | None = None,
    ) -> dict[str, Any]:
        if execution_requirement not in {"any", "direct"}:
            raise ValueError("execution_requirement must be 'any' or 'direct'")
        probe = self._canonical_probe(probe_id)
        normalized_scope = normalize_scope(scope, self.concepts)
        produced = set(probe.get("produces", []))

        candidates = self._host_candidates(
            probe_id,
            normalized_scope,
            execution_requirement=execution_requirement,
            target_resource=target_resource,
        )
        if target_resource is None:
            candidates += self._legacy_provider_candidates(
                probe_id,
                normalized_scope,
                execution_requirement=execution_requirement,
            )
            selection_policy = SELECTION_POLICY
        else:
            candidates += self._target_provider_candidates(
                probe_id,
                normalized_scope,
                execution_requirement=execution_requirement,
                target_resource=target_resource,
            )
            selection_policy = TARGET_SELECTION_POLICY
        candidates.sort(key=_candidate_sort_key)

        for candidate in candidates:
            undeclared = set(candidate["observations"]) - produced
            if undeclared:
                raise ValueError(
                    f"instrument {candidate['instrument']['id']} advertises observations not "
                    f"declared by {probe_id}: {sorted(undeclared)}"
                )

        eligible = [candidate for candidate in candidates if candidate["eligible"]]
        selected = min(eligible, key=_candidate_sort_key) if eligible else None
        if selected is not None:
            reason = "instrument is available, exact-scope compatible, execution-mode compatible"
            if target_resource is not None:
                reason += ", exact-target, provider-endpoint, and runner compatible"
            reason += ", and wins the stable instrument-identity tie-break"
            selection = {
                "instrument": copy.deepcopy(selected["instrument"]),
                "reason": reason,
            }
            stop_reason = None
        else:
            selection = None
            stop_reason = (
                "no_instrument_for_probe" if not candidates else "no_safe_available_instrument"
            )

        document: dict[str, Any] = {
            "schema_version": "0.1",
            "kind": "instrument_routing_decision",
            "probe": {
                "id": probe_id,
                "title": probe.get("title", probe_id),
                "risk": "read_only",
            },
            "scope": copy.deepcopy(normalized_scope),
            "execution_requirement": execution_requirement,
            "selection_policy": selection_policy,
            "candidates": candidates,
            "selection": selection,
            "stop_reason": stop_reason,
        }
        if target_resource is not None:
            document["target_resource"] = target_resource
        validate_instrument_routing_decision(document)
        return document

    @property
    def routable_probe_ids(self) -> set[str]:
        output = {
            entry["probe"]["id"]
            for entry in self.host_capabilities.get("executors", [])
            if isinstance(entry, dict) and isinstance(entry.get("probe"), dict)
        }
        provider_projections = list(self.provider_capabilities.get("providers", []))
        provider_projections += list(self._provider_instance_capabilities.values())
        for provider in provider_projections:
            for entry in provider.get("probes", []):
                probe_id = entry.get("probe", {}).get("id")
                if isinstance(probe_id, str):
                    output.add(probe_id)
        return output

    @property
    def autonomous_probe_ids(self) -> set[str]:
        output: set[str] = set()
        provider_projections = list(self.provider_capabilities.get("providers", []))
        provider_projections += list(self._provider_instance_capabilities.values())
        for provider in provider_projections:
            if provider.get("availability", {}).get("state") != "available":
                continue
            for entry in provider.get("probes", []):
                probe_id = entry.get("probe", {}).get("id")
                if isinstance(probe_id, str):
                    output.add(probe_id)
        return output

    def execute(
        self,
        probe_id: str,
        target: str,
        scope: dict[str, Any] | None,
        *,
        target_resource: str | None = None,
    ) -> dict[str, Any]:
        decision = self.route(
            probe_id,
            scope,
            execution_requirement="direct",
            target_resource=target_resource,
        )
        selection = decision["selection"]
        if selection is None:
            raise ProbeInsufficientEvidence(
                f"instrument router cannot execute {probe_id}: {decision['stop_reason']}"
            )
        instrument = selection["instrument"]
        if instrument["kind"] != "diagnostic_provider":
            raise ProbeInsufficientEvidence(
                f"instrument router selected {instrument['id']} but it requires session execution"
            )
        provider = self._providers_by_id.get(instrument["id"])
        if provider is None:
            raise ProbeInsufficientEvidence(
                "selected diagnostic provider is discovery-only and has no execution binding: "
                f"{instrument['id']}"
            )

        evidence = provider.execute(probe_id, target, copy.deepcopy(scope))
        for instance in evidence.get("instances", []):
            source = instance.setdefault("source", {})
            attributes = source.setdefault("attributes", {})
            attributes["routing.router"] = ROUTER_ID
            attributes["routing.instrument_id"] = instrument["id"]
            attributes["routing.instrument_kind"] = instrument["kind"]
            attributes["routing.execution_mode"] = instrument["execution_mode"]
            if target_resource is not None:
                attributes["routing.target_resource"] = target_resource
            if "endpoint_resource" in instrument:
                attributes["routing.endpoint_resource"] = instrument["endpoint_resource"]
            labels = instance.setdefault("labels", {})
            labels["instrument"] = instrument["id"]
        return evidence


def _parse_scope_attributes(values: list[str]) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    for value in values:
        if "=" not in value:
            raise ValueError("--scope-attribute must use KEY=VALUE")
        key, attribute_value = value.split("=", 1)
        key = key.strip()
        attribute_value = attribute_value.strip()
        if not key or not attribute_value:
            raise ValueError("--scope-attribute must use non-empty KEY=VALUE")
        output.append((key, attribute_value))
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Route one canonical Causcope probe to a configured safe diagnostic instrument."
    )
    parser.add_argument("--probe", required=True)
    parser.add_argument("--execution-requirement", choices=["any", "direct"], default="any")
    parser.add_argument("--scope-entity", action="append", default=[])
    parser.add_argument("--scope-boundary", action="append", default=[])
    parser.add_argument("--scope-attribute", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--pgbot-adapter", type=Path)
    parser.add_argument("--pgbot-report", type=Path)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(root: Path = ROOT) -> int:
    parser = build_parser()
    args = parser.parse_args()
    if (args.pgbot_adapter is None) != (args.pgbot_report is None):
        parser.error("--pgbot-adapter and --pgbot-report must be provided together")

    try:
        concepts = load_concepts(root)
        providers: list[RoutedProvider] = []
        if args.pgbot_adapter is not None:
            providers.append(
                PgbotAutonomousProbeProvider(
                    adapter=load_adapter(args.pgbot_adapter),
                    concepts=concepts,
                    context_supplier=file_context_supplier(args.pgbot_report),
                )
            )
        router = InstrumentRouter(
            concepts=concepts,
            host_capabilities=build_probe_execution_capabilities(concepts),
            providers=providers,
        )
        scope = build_scope_query(
            entities=args.scope_entity,
            boundaries=args.scope_boundary,
            attributes=_parse_scope_attributes(args.scope_attribute),
        )
        decision = router.route(
            args.probe,
            scope,
            execution_requirement=args.execution_requirement,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print(json.dumps(decision, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

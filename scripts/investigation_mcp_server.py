#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from diagnosis_http_api import DiagnosisSnapshotReader
from diagnosis_mcp_server import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    LEGACY_RESOURCE_NOT_FOUND,
    DiagnosisMcpServer,
    McpProtocolError,
    serve_stdio,
)
from recommendation_information_gaps import (
    INPUT_SCHEMA as RECOMMENDATION_SCHEMA,
    load_json as load_recommendation_json,
    project as project_recommendation_information_gaps,
    validate_schema as validate_recommendation_schema,
)
from scoping_projection import ROOT, build_scoping_projection, load_incident_context

INCIDENT_CONTEXT_URI = "causcope://incident/context"
INCIDENT_SCOPING_URI = "causcope://incident/scoping"
RECOMMENDATION_CURRENT_URI = "causcope://recommendation/current"
RECOMMENDATION_GAPS_URI = "causcope://recommendation/information-gaps"


class InvestigationMcpServer(DiagnosisMcpServer):
    def __init__(
        self,
        reader: DiagnosisSnapshotReader,
        *,
        incident_context_provider: Callable[[], dict[str, Any]],
        recommendation_projection_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(reader)
        self.incident_context_provider = incident_context_provider
        self.recommendation_projection_provider = recommendation_projection_provider

    def _instructions(self) -> str:
        instructions = (
            super()._instructions()
            + f" Read {INCIDENT_CONTEXT_URI} for the current pre-evidence incident context and "
            + f"{INCIDENT_SCOPING_URI} for the ten-dimension scoping projection and next "
            + "clarification question. Scope before asserting a root cause."
        )
        if self.recommendation_projection_provider is not None:
            instructions += (
                f" Read {RECOMMENDATION_CURRENT_URI} for the current evidence-gated architecture "
                f"candidate and {RECOMMENDATION_GAPS_URI} for ranked missing information and the "
                "next bounded action. Recommendation resources never authorize probe execution, "
                "experiments, or architecture changes."
            )
        return instructions

    def _resource_descriptors(self, *, modern: bool) -> list[dict[str, Any]]:
        resources = super()._resource_descriptors(modern=modern)
        incident_resources = [
            {
                "uri": INCIDENT_CONTEXT_URI,
                "name": "incident_context",
                "description": (
                    "Validated pre-evidence incident context including blast-radius inputs, "
                    "location, flow, client, change, dependency, data, reproducibility, and impact."
                ),
                "mimeType": "application/json",
            },
            {
                "uri": INCIDENT_SCOPING_URI,
                "name": "incident_scoping",
                "description": (
                    "Deterministic ten-dimension investigation scoping projection with explicit "
                    "known, partial, and unknown state plus the next clarification question."
                ),
                "mimeType": "application/json",
            },
        ]
        if modern:
            incident_resources[0]["title"] = "Causcope incident context"
            incident_resources[1]["title"] = "Causcope incident scoping"

        recommendation_resources: list[dict[str, Any]] = []
        if self.recommendation_projection_provider is not None:
            recommendation_resources = [
                {
                    "uri": RECOMMENDATION_CURRENT_URI,
                    "name": "architectural_recommendation",
                    "description": (
                        "Current strict evidence-gated architectural recommendation projection, "
                        "including maturity, causal basis, trade-offs, and approval boundary."
                    ),
                    "mimeType": "application/json",
                },
                {
                    "uri": RECOMMENDATION_GAPS_URI,
                    "name": "recommendation_information_gaps",
                    "description": (
                        "Deterministic recommendation information-gap ranking with the exact next "
                        "operator question, read-only probe handoff, experiment plan, or terminal human action."
                    ),
                    "mimeType": "application/json",
                },
            ]
            if modern:
                recommendation_resources[0]["title"] = "Causcope architectural recommendation"
                recommendation_resources[1]["title"] = "Causcope recommendation information gaps"

        return sorted(
            resources + incident_resources + recommendation_resources,
            key=lambda resource: resource["uri"],
        )

    def _incident_context(self, uri: str) -> dict[str, Any]:
        try:
            document = self.incident_context_provider()
        except (OSError, ValueError) as exc:
            raise McpProtocolError(
                INTERNAL_ERROR,
                f"incident context read failed: {exc}",
                data={"uri": uri},
            ) from exc
        if not isinstance(document, dict):
            raise McpProtocolError(
                INTERNAL_ERROR,
                "incident context provider returned a non-object",
                data={"uri": uri},
            )
        return document

    def _recommendation_projection(self, uri: str) -> dict[str, Any]:
        if self.recommendation_projection_provider is None:
            raise McpProtocolError(
                LEGACY_RESOURCE_NOT_FOUND,
                f"resource not found: {uri}",
                data={"uri": uri},
            )
        try:
            document = self.recommendation_projection_provider()
            if not isinstance(document, dict):
                raise ValueError("recommendation projection provider returned a non-object")
            validate_recommendation_schema(
                document,
                RECOMMENDATION_SCHEMA,
                "architectural recommendation projection",
            )
        except (OSError, ValueError) as exc:
            raise McpProtocolError(
                INTERNAL_ERROR,
                f"recommendation projection read failed: {exc}",
                data={"uri": uri},
            ) from exc
        return document

    def _read_resource(self, uri: str, *, modern: bool) -> dict[str, Any]:
        if uri == INCIDENT_CONTEXT_URI:
            document = self._incident_context(uri)
        elif uri == INCIDENT_SCOPING_URI:
            context = self._incident_context(uri)
            try:
                document = build_scoping_projection(context)
            except (OSError, ValueError) as exc:
                raise McpProtocolError(
                    INTERNAL_ERROR,
                    f"incident scoping projection failed: {exc}",
                    data={"uri": uri},
                ) from exc
        elif uri == RECOMMENDATION_CURRENT_URI and self.recommendation_projection_provider is not None:
            document = self._recommendation_projection(uri)
        elif uri == RECOMMENDATION_GAPS_URI and self.recommendation_projection_provider is not None:
            recommendation = self._recommendation_projection(uri)
            try:
                document = project_recommendation_information_gaps(recommendation)
            except ValueError as exc:
                raise McpProtocolError(
                    INTERNAL_ERROR,
                    f"recommendation information-gap projection failed: {exc}",
                    data={"uri": uri},
                ) from exc
        else:
            return super()._read_resource(uri, modern=modern)

        payload = {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": self._json_text(document),
                }
            ]
        }
        if modern:
            return self._modern_result(payload, cacheable=True, ttl_ms=0, cache_scope="private")
        return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Expose Causcope diagnosis plus incident context, scoping, and optional recommendation state over MCP stdio."
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        required=True,
        help="Diagnosis snapshot JSON file produced by live_diagnosis_watch.py",
    )
    parser.add_argument(
        "--incident-context",
        type=Path,
        required=True,
        help="Incident context YAML file",
    )
    parser.add_argument(
        "--recommendation-projection",
        type=Path,
        help="Optional architectural recommendation projection JSON file",
    )
    parser.add_argument("--verbose", action="store_true", help="Write request diagnostics to stderr")
    return parser


def main(root: Path = ROOT) -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        reader = DiagnosisSnapshotReader(
            args.snapshot,
            schema_path=root / "schema" / "diagnosis-snapshot.schema.json",
        )
        context_path = args.incident_context
        recommendation_path = args.recommendation_projection
        server = InvestigationMcpServer(
            reader,
            incident_context_provider=lambda: load_incident_context(context_path),
            recommendation_projection_provider=(
                (lambda: load_recommendation_json(recommendation_path))
                if recommendation_path is not None
                else None
            ),
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return serve_stdio(server, verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())

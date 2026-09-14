from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from autonomous_investigation import ProbeInsufficientEvidence

COMPARE_CLIENT_COHORTS = "probe.http.compare_client_cohorts"
INSPECT_LOCK_ERRORS = "probe.database.inspect_lock_error_events"
CLIENT_COHORT_SKEW = "observation.http.client_cohort_failure_skew"
DATABASE_LOCK_ERROR = "observation.database.lock_error_event"
SUPPORTED_PROBE_IDS = {COMPARE_CLIENT_COHORTS, INSPECT_LOCK_ERRORS}
REQUEST_SCOPE_ATTRIBUTES = {"method", "path", "client_platform", "app_version"}


def _timestamp(event: dict[str, Any], fallback: str) -> str:
    value = event.get("observed_at")
    return value if isinstance(value, str) and value else fallback


def _instance_id(
    incident_id: str,
    probe_id: str,
    target: str,
    scope: dict[str, Any] | None,
) -> str:
    raw = json.dumps(
        {
            "incident_id": incident_id,
            "probe_id": probe_id,
            "target": target,
            "scope": scope,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"evidence.probe.{digest}"


def _source(probe_id: str) -> dict[str, Any]:
    return {
        "type": "probe",
        "name": probe_id,
        "attributes": {
            "adapter": "causcope-shop-structured-log-read-only",
            "source": "docker-compose:causcope-shop/app",
        },
    }


def _document(
    *,
    incident_id: str,
    instance: dict[str, Any],
    probe_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "kind": "runtime_evidence",
        "incident_id": incident_id,
        "description": f"Evidence produced by autonomous read-only probe {probe_id}.",
        "instances": [instance],
    }


def _request_scope_attributes(scope: dict[str, Any] | None) -> dict[str, str]:
    if scope is None:
        return {}
    attributes = scope.get("attributes", {})
    if not isinstance(attributes, dict):
        return {}
    unsupported = set(attributes) - REQUEST_SCOPE_ATTRIBUTES
    if unsupported:
        raise ProbeInsufficientEvidence(
            "Shop structured-log probes cannot prove request scope attributes: "
            + ", ".join(sorted(unsupported))
        )
    return {str(key): str(value) for key, value in attributes.items()}


def _event_matches_request_scope(event: dict[str, Any], attributes: dict[str, str]) -> bool:
    return all(str(event.get(key, "")) == value for key, value in attributes.items())


class ShopStructuredLogProbeAdapter:
    def __init__(
        self,
        *,
        events: list[dict[str, Any]],
        incident_id: str,
        collected_at: str,
        cohort_skew_threshold_pct: float = 50.0,
    ) -> None:
        self.events = list(events)
        self.incident_id = incident_id
        self.collected_at = collected_at
        self.cohort_skew_threshold_pct = float(cohort_skew_threshold_pct)

    @property
    def supported_probe_ids(self) -> set[str]:
        return set(SUPPORTED_PROBE_IDS)

    def execute(
        self,
        probe_id: str,
        target: str,
        scope: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if probe_id == COMPARE_CLIENT_COHORTS:
            return self._compare_client_cohorts(target=target, scope=scope)
        if probe_id == INSPECT_LOCK_ERRORS:
            return self._inspect_lock_errors(target=target, scope=scope)
        raise ValueError(f"unsupported Shop read-only probe: {probe_id}")

    def _compare_client_cohorts(
        self,
        *,
        target: str,
        scope: dict[str, Any] | None,
    ) -> dict[str, Any]:
        attributes = _request_scope_attributes(scope)
        wanted_method = attributes.get("method")
        wanted_path = attributes.get("path")
        if wanted_method is None or wanted_path is None:
            raise ProbeInsufficientEvidence(
                "client cohort comparison requires method and path in the selected diagnosis scope"
            )

        grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(
            lambda: {"total": 0, "failures": 0, "latest": self.collected_at}
        )
        for event in self.events:
            if event.get("event") != "http_request":
                continue
            method = str(event.get("method", "unknown"))
            path = str(event.get("path", "unknown"))
            if method != wanted_method or path != wanted_path:
                continue
            platform = str(event.get("client_platform", "unknown"))
            version = str(event.get("app_version", "unknown"))
            try:
                status = int(event.get("status", 0))
            except (TypeError, ValueError):
                continue
            bucket = grouped[(platform, version)]
            bucket["total"] += 1
            if status >= 400:
                bucket["failures"] += 1
            bucket["latest"] = _timestamp(event, self.collected_at)

        usable = [(cohort, bucket) for cohort, bucket in grouped.items() if int(bucket["total"]) > 0]
        if len(usable) < 2:
            raise ProbeInsufficientEvidence(
                "client cohort comparison requires at least two comparable cohorts in the scoped log window"
            )

        def failure_pct(item: tuple[tuple[str, str], dict[str, Any]]) -> float:
            bucket = item[1]
            return (int(bucket["failures"]) / int(bucket["total"])) * 100.0

        highest = max(usable, key=lambda item: (failure_pct(item), item[0]))
        lowest = min(usable, key=lambda item: (failure_pct(item), item[0]))
        high_pct = round(failure_pct(highest), 3)
        low_pct = round(failure_pct(lowest), 3)
        delta = round(high_pct - low_pct, 3)
        observed = highest[0] != lowest[0] and delta >= self.cohort_skew_threshold_pct
        high_platform, high_version = highest[0]
        low_platform, low_version = lowest[0]
        latest = max(str(bucket["latest"]) for _, bucket in usable)
        probe_id = COMPARE_CLIENT_COHORTS
        instance = {
            "id": _instance_id(self.incident_id, probe_id, target, scope),
            "observation": CLIENT_COHORT_SKEW,
            "state": "observed" if observed else "absent",
            "observed_at": latest,
            "confidence": "high",
            "source": _source(probe_id),
            "measurement": {
                "value": high_pct,
                "baseline": low_pct,
                "delta": delta,
                "unit": "percentage_points",
                "comparison": "above_baseline" if observed else "equal",
            },
            "labels": {
                "probe": probe_id,
                "failing_cohort": f"{high_platform}@{high_version}",
                "working_cohort": f"{low_platform}@{low_version}",
                "cohorts_compared": str(len(usable)),
            },
            "note": (
                "The probe compared request outcomes for the same method/path across client cohorts. "
                "The result is bound to the selected failing diagnosis scope; cohort skew is a discriminator, not causal proof."
            ),
        }
        if scope is not None:
            instance["scope"] = json.loads(json.dumps(scope))
        return _document(incident_id=self.incident_id, instance=instance, probe_id=probe_id)

    def _inspect_lock_errors(
        self,
        *,
        target: str,
        scope: dict[str, Any] | None,
    ) -> dict[str, Any]:
        attributes = _request_scope_attributes(scope)
        if not attributes:
            raise ProbeInsufficientEvidence(
                "database lock error inspection requires a request scope for safe correlation"
            )

        scoped_requests = [
            event
            for event in self.events
            if event.get("event") == "http_request"
            and _event_matches_request_scope(event, attributes)
        ]
        if not scoped_requests:
            raise ProbeInsufficientEvidence(
                "captured logs contain no request event matching the selected diagnosis scope"
            )

        lock_events = [
            event
            for event in self.events
            if event.get("event") == "sqlite_operational_error"
            and "locked" in str(event.get("error", "")).lower()
            and _event_matches_request_scope(event, attributes)
        ]
        latest = max(
            [_timestamp(event, self.collected_at) for event in scoped_requests + lock_events],
            default=self.collected_at,
        )
        probe_id = INSPECT_LOCK_ERRORS
        count = len(lock_events)
        instance = {
            "id": _instance_id(self.incident_id, probe_id, target, scope),
            "observation": DATABASE_LOCK_ERROR,
            "state": "observed" if count > 0 else "absent",
            "observed_at": latest,
            "confidence": "high",
            "source": _source(probe_id),
            "measurement": {
                "value": count,
                "unit": "events",
                "comparison": "present" if count > 0 else "absent",
            },
            "labels": {
                "probe": probe_id,
                "database_engine": "sqlite",
                "matcher": "sqlite_operational_error:locked",
                "scope_correlation": "request_metadata",
            },
            "note": (
                "The probe matched explicit SQLite lock errors to the same request metadata carried by the selected diagnosis scope. "
                "Absent means the captured application-log window contained matching requests but no matching lock error; "
                "it decreases this hypothesis and does not prove all forms of lock contention impossible."
            ),
        }
        if scope is not None:
            instance["scope"] = json.loads(json.dumps(scope))
        return _document(incident_id=self.incident_id, instance=instance, probe_id=probe_id)

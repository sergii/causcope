#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from runtime_evidence import load_runtime_evidence


def _attributes(instance: Any) -> dict[str, Any]:
    if not isinstance(instance, dict):
        return {}
    source = instance.get("source")
    if not isinstance(source, dict):
        return {}
    attributes = source.get("attributes")
    return attributes if isinstance(attributes, dict) else {}


def load_causal_verification_source(path: Path) -> dict[str, Any]:
    """Load evidence for verification without making verification a prerequisite for normal diagnosis.

    Existing diagnosis/routing fixtures and external evidence producers may not use the complete
    canonical runtime-evidence schema. If they make no causal-verification claim, this surface may
    safely project zero claims. Once any verification_id is present, strict canonical validation is
    mandatory before a claim can be evaluated.
    """
    with path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict):
        raise ValueError("runtime evidence document must be an object")
    if document.get("kind") != "runtime_evidence":
        raise ValueError("causal verification source must be runtime_evidence")

    has_verification_claim = any(
        isinstance(_attributes(instance).get("causcope.verification_id"), str)
        and bool(_attributes(instance).get("causcope.verification_id"))
        for instance in document.get("instances", [])
    )
    return load_runtime_evidence(path) if has_verification_claim else document

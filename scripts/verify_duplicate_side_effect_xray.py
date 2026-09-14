#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from concrete_system_facts import load_document
from duplicate_side_effect_causal_confirmation import confirm, load_json
from duplicate_side_effect_xray_projection import project
from otel_concrete_runtime_facts import load_json as load_runtime_json
from runtime_evidence import load_runtime_evidence


def expect_rejected(label: str, callback) -> None:
    try:
        callback()
    except ValueError:
        return
    raise AssertionError(f"{label} should fail closed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify duplicate side-effect X-Ray epistemic and identity boundaries.")
    parser.add_argument("--static-facts", required=True, type=Path)
    parser.add_argument("--runtime-facts", required=True, type=Path)
    parser.add_argument("--xray", required=True, type=Path)
    parser.add_argument("--effect-evidence", required=True, type=Path)
    parser.add_argument("--runtime-evidence", required=True, type=Path)
    parser.add_argument("--confirmation", required=True, type=Path)
    args = parser.parse_args()

    static = load_document(args.static_facts)
    runtime = load_runtime_json(args.runtime_facts)
    xray = load_json(args.xray)
    effect = load_json(args.effect_evidence)
    canonical = load_runtime_evidence(args.runtime_evidence)
    confirmation = load_json(args.confirmation)

    if xray["risk_state"] != "PRECONDITIONS_PRESENT":
        raise AssertionError("static retry/external-effect path must reach PRECONDITIONS_PRESENT")
    if xray["idempotency_evidence"]["state"] != "bounded_absence_observed":
        raise AssertionError("static X-Ray must preserve bounded negative idempotency evidence")
    if confirmation["epistemic_state"] != "CAUSAL_DIAGNOSIS_CONFIRMED":
        raise AssertionError("exact live binding must reach CAUSAL_DIAGNOSIS_CONFIRMED")
    if confirmation["causal_diagnosis"]["state"] != "confirmed":
        raise AssertionError("causal diagnosis must be confirmed")
    if len(confirmation["binding"]["provider_effect_ids"]) != 2:
        raise AssertionError("unsafe retry must bind two distinct provider effects")
    if confirmation["counterfactual_recovery"]["provider_effect_count"] != 1:
        raise AssertionError("idempotent recovery must apply exactly one provider effect")

    protected_static = copy.deepcopy(static)
    for fact in protected_static["facts"]:
        attrs = fact.get("context", {}).get("attributes", {})
        if attrs.get("idempotency_key") == "absent_in_supported_client_source":
            attrs["idempotency_key"] = "present_in_supported_client_source"
    protected_xray = project(protected_static)
    if protected_xray["risk_state"] != "UNKNOWN":
        raise AssertionError("static projection must not retain the unsafe precondition after idempotency evidence is present")

    tampered_trace = copy.deepcopy(effect)
    tampered_trace["unsafe"]["attempts"][1]["span_id"] = "ffffffffffffffff"
    expect_rejected(
        "tampered exact execution identity",
        lambda: confirm(static, runtime, xray, tampered_trace, canonical),
    )

    tampered_business_identity = copy.deepcopy(effect)
    tampered_business_identity["unsafe"]["provider_effects"][1]["business_event_id"] = "payment-other"
    expect_rejected(
        "mismatched provider business identity",
        lambda: confirm(static, runtime, xray, tampered_business_identity, canonical),
    )

    no_recovery = copy.deepcopy(effect)
    no_recovery["protected"]["provider_effects"].append(copy.deepcopy(no_recovery["protected"]["provider_effects"][0]))
    no_recovery["protected"]["provider_effects"][1]["effect_id"] = "effect-extra"
    expect_rejected(
        "missing idempotent counterfactual recovery",
        lambda: confirm(static, runtime, xray, no_recovery, canonical),
    )

    cross_incident = copy.deepcopy(canonical)
    cross_incident["incident_id"] = "INC-OTHER"
    expect_rejected(
        "cross-incident canonical evidence",
        lambda: confirm(static, runtime, xray, effect, cross_incident),
    )

    print(
        json.dumps(
            {
                "status": "ok",
                "epistemic_state": confirmation["epistemic_state"],
                "unsafe_effects": len(confirmation["binding"]["provider_effect_ids"]),
                "protected_effects": confirmation["counterfactual_recovery"]["provider_effect_count"],
                "tampered_trace": "rejected",
                "business_identity_mismatch": "rejected",
                "missing_recovery": "rejected",
                "cross_incident": "rejected",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schema" / "xray-profile.schema.json"
MAX_SOLUTIONS = 1000
MISSING = object()


def load_document(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        if path.suffix.lower() == ".json":
            payload = json.load(handle)
        else:
            payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def get_path(value: Any, path: str) -> Any:
    if path in {"", "$"}:
        return value
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


def validate_profile(profile: dict[str, Any], schema_path: Path = DEFAULT_SCHEMA) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(profile), key=lambda error: list(error.path))
    if errors:
        rendered = []
        for error in errors:
            path = ".".join(str(part) for part in error.path) or "<root>"
            rendered.append(f"{path}: {error.message}")
        raise ValueError("X-Ray profile validation failed:\n" + "\n".join(rendered))


def parse_inputs(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        alias, separator, path = value.partition("=")
        if not separator or not alias or not path:
            raise ValueError(f"invalid --input {value!r}; expected alias=path")
        if alias in result:
            raise ValueError(f"duplicate input alias: {alias}")
        result[alias] = Path(path)
    return result


def validate_inputs(profile: dict[str, Any], documents: dict[str, dict[str, Any]]) -> None:
    specs = profile["inputs"]
    unknown = sorted(set(documents) - set(specs))
    if unknown:
        raise ValueError(f"profile does not declare input aliases: {', '.join(unknown)}")
    for alias, spec in specs.items():
        document = documents.get(alias)
        if document is None:
            if spec.get("required", False):
                raise ValueError(f"missing required X-Ray input: {alias}")
            continue
        expected_kind = spec.get("kind")
        if expected_kind and document.get("kind") != expected_kind:
            raise ValueError(
                f"input {alias} has kind {document.get('kind')!r}; expected {expected_kind!r}"
            )


def resolve_input_ref(documents: dict[str, dict[str, Any]], reference: str) -> Any:
    alias, separator, path = reference.partition(".")
    document = documents.get(alias)
    if document is None:
        return MISSING
    if not separator:
        return document
    return get_path(document, path)


def validate_identity_groups(profile: dict[str, Any], documents: dict[str, dict[str, Any]]) -> None:
    for group in profile.get("identity_groups", []):
        values: list[tuple[str, Any]] = []
        for reference in group["refs"]:
            value = resolve_input_ref(documents, reference)
            if value is MISSING:
                continue
            values.append((reference, value))
        if len(values) < 2:
            continue
        expected = values[0][1]
        mismatched = [reference for reference, value in values[1:] if value != expected]
        if mismatched:
            refs = ", ".join(reference for reference, _value in values)
            raise ValueError(f"identity group {group['name']} does not match across: {refs}")


def source_rows(documents: dict[str, dict[str, Any]], source: str, path: str) -> list[Any]:
    document = documents.get(source)
    if document is None:
        return []
    value = get_path(document, path)
    if value is MISSING:
        return []
    if isinstance(value, list):
        return value
    return [value]


def resolve_value(expression: Any, bindings: dict[str, Any]) -> Any:
    if isinstance(expression, dict):
        if set(expression) == {"var"}:
            return bindings.get(expression["var"], MISSING)
        if set(expression) == {"list"}:
            values = [resolve_value(item, bindings) for item in expression["list"]]
            if any(item is MISSING for item in values):
                return MISSING
            return values
    return expression


def matches_expression(actual: Any, expression: Any, bindings: dict[str, Any]) -> bool:
    if isinstance(expression, dict):
        if set(expression) == {"var"}:
            expected = resolve_value(expression, bindings)
            return expected is not MISSING and actual == expected
        if set(expression) == {"list"}:
            expected = resolve_value(expression, bindings)
            return expected is not MISSING and actual == expected
        if set(expression) == {"one_of_vars"}:
            values = [bindings.get(name, MISSING) for name in expression["one_of_vars"]]
            return all(value is not MISSING for value in values) and actual in values
        if set(expression) == {"neq"}:
            expected = resolve_value(expression["neq"], bindings)
            return expected is not MISSING and actual != expected
        if set(expression) == {"one_of"}:
            values = [resolve_value(item, bindings) for item in expression["one_of"]]
            return all(value is not MISSING for value in values) and actual in values
    return actual == expression


def row_matches(row: Any, where: dict[str, Any], bindings: dict[str, Any]) -> bool:
    for path, expression in where.items():
        actual = get_path(row, path)
        if actual is MISSING or not matches_expression(actual, expression, bindings):
            return False
    return True


def apply_clause(
    documents: dict[str, dict[str, Any]],
    clause: dict[str, Any],
    seeds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = source_rows(documents, clause["source"], clause.get("path", "$"))
    results: list[dict[str, Any]] = []
    for seed in seeds:
        for row in rows:
            if not row_matches(row, clause.get("where", {}), seed):
                continue
            candidate = dict(seed)
            valid = True
            for variable, path in clause.get("bind", {}).items():
                value = get_path(row, path)
                if value is MISSING:
                    valid = False
                    break
                if variable in candidate and candidate[variable] != value:
                    valid = False
                    break
                candidate[variable] = value
            if valid:
                results.append(candidate)
                if len(results) > MAX_SOLUTIONS:
                    raise ValueError("X-Ray rule exceeded bounded solution limit")
    return dedupe_bindings(results)


def normalized_set(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("set_eq operands must resolve to lists")
    return sorted(json.dumps(item, sort_keys=True, separators=(",", ":")) for item in value)


def constraint_matches(constraint: dict[str, Any], bindings: dict[str, Any]) -> bool:
    left = resolve_value(constraint["left"], bindings)
    right = resolve_value(constraint["right"], bindings)
    if left is MISSING or right is MISSING:
        return False
    operation = constraint["op"]
    if operation == "eq":
        return left == right
    if operation == "neq":
        return left != right
    if operation == "lt":
        return left < right
    if operation == "set_eq":
        return normalized_set(left) == normalized_set(right)
    raise ValueError(f"unsupported constraint operation: {operation}")


def apply_constraints(
    constraints: list[dict[str, Any]], seeds: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [seed for seed in seeds if all(constraint_matches(item, seed) for item in constraints)]


def cardinality_matches(
    documents: dict[str, dict[str, Any]],
    rule: dict[str, Any],
    bindings: dict[str, Any],
) -> bool:
    rows = source_rows(documents, rule["source"], rule.get("path", "$"))
    count = sum(1 for row in rows if row_matches(row, rule.get("where", {}), bindings))
    if "exact" in rule and count != rule["exact"]:
        return False
    if "min" in rule and count < rule["min"]:
        return False
    if "max" in rule and count > rule["max"]:
        return False
    return True


def apply_cardinality(
    documents: dict[str, dict[str, Any]],
    rules: list[dict[str, Any]],
    seeds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [seed for seed in seeds if all(cardinality_matches(documents, rule, seed) for rule in rules)]


def dedupe_bindings(bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        key = json.dumps(binding, sort_keys=True, separators=(",", ":"))
        unique[key] = binding
    return [unique[key] for key in sorted(unique)]


def evaluate_stage(
    stage: dict[str, Any],
    documents: dict[str, dict[str, Any]],
    seeds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results = [dict(seed) for seed in seeds]
    for clause in stage.get("clauses", []):
        results = apply_clause(documents, clause, results)
        if not results:
            return []
    results = apply_constraints(stage.get("constraints", []), results)
    if not results:
        return []
    results = apply_cardinality(documents, stage.get("cardinality", []), results)
    return dedupe_bindings(results)


def first_identity(documents: dict[str, dict[str, Any]], field: str) -> Any:
    for alias in sorted(documents):
        value = documents[alias].get(field, MISSING)
        if value is not MISSING:
            return value
    return None


def project(profile: dict[str, Any], documents: dict[str, dict[str, Any]]) -> dict[str, Any]:
    validate_profile(profile)
    validate_inputs(profile, documents)
    validate_identity_groups(profile, documents)

    solutions: list[dict[str, Any]] = [{}]
    stage_results: list[dict[str, Any]] = []
    highest_state = "UNKNOWN"
    stopped = False
    max_emit = profile.get("max_emitted_bindings", 20)

    for stage in profile["stages"]:
        if stopped:
            stage_results.append(
                {
                    "id": stage["id"],
                    "state": "not_evaluated",
                    "reason": "A prerequisite stage was not reached.",
                }
            )
            continue
        next_solutions = evaluate_stage(stage, documents, solutions)
        if not next_solutions:
            stage_results.append({"id": stage["id"], "state": "not_reached", "match_count": 0})
            stopped = True
            continue
        solutions = next_solutions
        highest_state = stage["id"]
        stage_results.append(
            {
                "id": stage["id"],
                "state": "reached",
                "match_count": len(solutions),
                "bindings": solutions[:max_emit],
                "bindings_truncated": len(solutions) > max_emit,
            }
        )

    output = {
        "schema_version": "0.1",
        "kind": "xray_projection",
        "profile_id": profile["id"],
        "catalog_code": profile["catalog_code"],
        "hypothesis": profile["hypothesis"],
        "system_id": first_identity(documents, "system_id"),
        "revision": first_identity(documents, "revision"),
        "incident_id": first_identity(documents, "incident_id"),
        "epistemic_state": highest_state,
        "stages": stage_results,
        "evidence_progression": [
            item["id"] for item in stage_results if item["state"] == "reached"
        ],
        "input_kinds": {
            alias: document.get("kind") for alias, document in sorted(documents.items())
        },
    }
    for field in ("symptom", "observation"):
        if field in profile:
            output[field] = profile[field]
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a declarative Concrete System X-Ray profile.")
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--input", action="append", default=[], metavar="ALIAS=PATH")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--require-state")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        profile = load_document(args.profile)
        validate_profile(profile, args.schema)
        input_paths = parse_inputs(args.input)
        documents = {alias: load_document(path) for alias, path in input_paths.items()}
        output = project(profile, documents)
        if args.require_state and output["epistemic_state"] != args.require_state:
            raise ValueError(
                f"X-Ray state {output['epistemic_state']} does not satisfy required state {args.require_state}"
            )
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SystemExit(str(exc)) from exc

    rendered = json.dumps(output, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

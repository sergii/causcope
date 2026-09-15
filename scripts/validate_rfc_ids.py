#!/usr/bin/env python3

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RFC_DIR = ROOT / "RFC"
EXCEPTIONS_FILE = ROOT / "vocabulary" / "rfc-id-exceptions.yaml"
RFC_FILENAME = re.compile(r"^(?P<id>\d{4})-[a-z0-9][a-z0-9-]*\.md$")


def load_exceptions() -> dict[str, set[str]]:
    with EXCEPTIONS_FILE.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}

    raw = document.get("legacy_collisions", {})
    if not isinstance(raw, dict):
        raise ValueError("legacy_collisions must be a mapping")

    result: dict[str, set[str]] = {}
    for rfc_id, paths in raw.items():
        if not re.fullmatch(r"\d{4}", str(rfc_id)):
            raise ValueError(f"invalid RFC exception id: {rfc_id}")
        if not isinstance(paths, list) or len(paths) < 2:
            raise ValueError(
                f"legacy collision {rfc_id} must list at least two exact RFC paths"
            )
        normalized = {str(path) for path in paths}
        if len(normalized) != len(paths):
            raise ValueError(f"legacy collision {rfc_id} contains duplicate paths")
        result[str(rfc_id)] = normalized
    return result


def validate() -> None:
    errors: list[str] = []
    groups: dict[str, set[str]] = defaultdict(set)

    for path in sorted(RFC_DIR.glob("*.md")):
        match = RFC_FILENAME.fullmatch(path.name)
        if not match:
            # Non-numbered Markdown files are outside numeric RFC identity governance.
            continue
        groups[match.group("id")].add(path.relative_to(ROOT).as_posix())

    try:
        exceptions = load_exceptions()
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise SystemExit(f"ERROR: cannot load RFC id exceptions: {exc}") from exc

    for rfc_id, paths in sorted(groups.items()):
        if len(paths) <= 1:
            continue

        expected = exceptions.get(rfc_id)
        if expected is None:
            errors.append(
                f"RFC {rfc_id}: duplicate numeric id is not a registered legacy collision: "
                + ", ".join(sorted(paths))
            )
            continue

        if paths != expected:
            added = sorted(paths - expected)
            missing = sorted(expected - paths)
            details: list[str] = []
            if added:
                details.append("unexpected=" + ", ".join(added))
            if missing:
                details.append("missing=" + ", ".join(missing))
            errors.append(
                f"RFC {rfc_id}: registered legacy collision changed: " + "; ".join(details)
            )

    for rfc_id, expected in sorted(exceptions.items()):
        actual = groups.get(rfc_id, set())
        if actual == expected:
            continue
        if len(actual) > 1:
            # Already reported above with a more specific collision-change message.
            continue
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        details: list[str] = []
        if missing:
            details.append("missing=" + ", ".join(missing))
        if unexpected:
            details.append("unexpected=" + ", ".join(unexpected))
        errors.append(
            f"RFC {rfc_id}: legacy collision registry is stale: " + "; ".join(details)
        )

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)

    collision_count = sum(1 for paths in groups.values() if len(paths) > 1)
    print(
        f"Validated {sum(len(paths) for paths in groups.values())} numbered RFC files, "
        f"{len(groups)} numeric ids, and {collision_count} registered legacy collisions."
    )


if __name__ == "__main__":
    validate()

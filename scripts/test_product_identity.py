#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_PRODUCT = "atl" + "error"


def main() -> int:
    violations: list[str] = []

    for path in sorted(ROOT.rglob("*")):
        if ".git" in path.parts:
            continue

        relative = path.relative_to(ROOT)
        if LEGACY_PRODUCT in str(relative).casefold():
            violations.append(f"legacy product name in path: {relative}")

        if not path.is_file():
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        if LEGACY_PRODUCT in text.casefold():
            violations.append(f"legacy product name in content: {relative}")

    if violations:
        for violation in violations:
            print(f"ERROR: {violation}")
        return 1

    print("Product identity is consistently Causcope.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

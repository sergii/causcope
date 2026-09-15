#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

import causcope_why

DEFAULT_WORKSPACE = Path(".causcope")
GOLDEN_FILES = {
    "--static": "concrete-system-facts.json",
    "--runtime": "concrete-runtime-facts.json",
    "--pool": "resource-pool-runtime-evidence.json",
}


def _workspace(argv: list[str]) -> Path:
    for index, argument in enumerate(argv):
        if argument == "--workspace":
            if index + 1 >= len(argv):
                return DEFAULT_WORKSPACE
            return Path(argv[index + 1])
        if argument.startswith("--workspace="):
            return Path(argument.split("=", 1)[1])
    return DEFAULT_WORKSPACE


def _has_explicit_golden_paths(argv: list[str]) -> bool:
    return any(
        argument == option or argument.startswith(f"{option}=")
        for argument in argv
        for option in GOLDEN_FILES
    )


def resolve_workspace_golden_paths(argv: list[str]) -> list[str]:
    if _has_explicit_golden_paths(argv) or "--acquire" in argv:
        return argv

    workspace = _workspace(argv)
    paths = {option: workspace / filename for option, filename in GOLDEN_FILES.items()}
    existing = {option: path.exists() for option, path in paths.items()}

    if all(existing.values()):
        resolved = list(argv)
        for option, path in paths.items():
            resolved.extend([option, str(path)])
        return resolved

    if "--require-confirmed" in argv and any(existing.values()):
        missing = [path.name for option, path in paths.items() if not existing[option]]
        raise ValueError(
            "workspace does not contain a complete Rails D3.1 proof; missing: "
            + ", ".join(missing)
        )

    return argv


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        resolved = resolve_workspace_golden_paths(arguments)
    except ValueError as error:
        print(f"causcope: {error}", file=sys.stderr)
        return 2
    return causcope_why.main(resolved)


if __name__ == "__main__":
    raise SystemExit(main())

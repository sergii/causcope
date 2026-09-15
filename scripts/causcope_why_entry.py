#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import causcope_why
from causal_verification_surfaces import run_canonical_workspace

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "causcope"
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


def _has_workspace(argv: list[str]) -> bool:
    return any(
        argument == "--workspace" or argument.startswith("--workspace=")
        for argument in argv
    )


def _has_explicit_golden_paths(argv: list[str]) -> bool:
    return any(
        argument == option or argument.startswith(f"{option}=")
        for argument in argv
        for option in GOLDEN_FILES
    )


def resolve_workspace_golden_paths(argv: list[str]) -> list[str]:
    if _has_explicit_golden_paths(argv) or "--acquire" in argv or _has_observe(argv):
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


def _has_observe(argv: list[str]) -> bool:
    return any(argument == "--observe" or argument.startswith("--observe=") for argument in argv)


def _extract_observe(argv: list[str]) -> tuple[list[str], Path | None, list[str]]:
    if not _has_observe(argv):
        return argv, None, []

    try:
        separator = argv.index("--")
    except ValueError as error:
        raise ValueError("--observe requires a bounded application command after `--`") from error

    control = list(argv[:separator])
    application = list(argv[separator + 1 :])
    if not application:
        raise ValueError("--observe requires a bounded application command after `--`")

    observe_root: Path | None = None
    cleaned: list[str] = []
    index = 0
    while index < len(control):
        argument = control[index]
        if argument == "--observe":
            if observe_root is not None:
                raise ValueError("--observe may be supplied only once")
            if index + 1 >= len(control):
                raise ValueError("--observe requires a Rails root path")
            observe_root = Path(control[index + 1]).expanduser().resolve()
            index += 2
            continue
        if argument.startswith("--observe="):
            if observe_root is not None:
                raise ValueError("--observe may be supplied only once")
            value = argument.split("=", 1)[1]
            if not value:
                raise ValueError("--observe requires a Rails root path")
            observe_root = Path(value).expanduser().resolve()
            index += 1
            continue
        cleaned.append(argument)
        index += 1

    if observe_root is None:
        raise ValueError("--observe requires a Rails root path")
    if not observe_root.is_dir():
        raise ValueError(f"--observe Rails root does not exist: {observe_root}")
    if "--acquire" in cleaned:
        raise ValueError("--observe cannot be combined with --acquire; observe first, then authorize acquisition separately")
    if "--require-confirmed" in cleaned:
        raise ValueError("--observe cannot be combined with --require-confirmed")
    if _has_explicit_golden_paths(cleaned):
        raise ValueError("--observe cannot be combined with --static/--runtime/--pool")

    if not _has_workspace(cleaned):
        cleaned.extend(["--workspace", str((observe_root / ".causcope").resolve())])

    return cleaned, observe_root, application


def _run_observe(base_arguments: list[str], observe_root: Path, application: list[str]) -> int:
    parsed = causcope_why.build_parser().parse_args(base_arguments)
    parsed.workspace = parsed.workspace.expanduser().resolve()

    if causcope_why.load_workspace_diagnosis(parsed.workspace) is not None:
        raise ValueError(
            "--observe is for creating the first observed diagnosis revision; "
            "this workspace already has diagnosis.json. Use `causcope why` or `causcope why --acquire`."
        )

    causcope_why.scoping_projection(parsed)

    command = [
        str(CLI),
        "runtime",
        "observe",
        str(observe_root),
        "--workspace",
        str(parsed.workspace),
        "--json",
        "--",
        *application,
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "bounded observation failed"
        raise ValueError(f"bounded observation failed: {detail}")

    return causcope_why.main(base_arguments)


def _run_canonical_if_available(arguments: list[str]) -> int | None:
    if _has_explicit_golden_paths(arguments):
        return None
    parsed = causcope_why.build_parser().parse_args(arguments)
    parsed.workspace = parsed.workspace.expanduser().resolve()
    diagnosis_path = parsed.workspace / causcope_why.WORKSPACE_DIAGNOSIS
    evidence_path = parsed.workspace / causcope_why.WORKSPACE_RUNTIME_EVIDENCE
    if not diagnosis_path.exists():
        return None
    if not evidence_path.exists() and not parsed.require_confirmed:
        return None
    return run_canonical_workspace(parsed)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        base_arguments, observe_root, application = _extract_observe(arguments)
        if observe_root is not None:
            return _run_observe(base_arguments, observe_root, application)
        canonical = _run_canonical_if_available(arguments)
        if canonical is not None:
            return canonical
        resolved = resolve_workspace_golden_paths(arguments)
    except (ValueError, FileNotFoundError, OSError) as error:
        print(f"causcope: {error}", file=sys.stderr)
        return 2
    return causcope_why.main(resolved)


if __name__ == "__main__":
    raise SystemExit(main())

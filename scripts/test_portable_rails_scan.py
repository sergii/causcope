#!/usr/bin/env python3

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "lab" / "rails-connection-pool"
SCHEMA = ROOT / "schema" / "concrete-system-facts.schema.json"
CLI = ROOT / "bin" / "causcope"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI), *args],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="causcope-portable-rails-") as temporary:
        output = Path(temporary) / "facts.json"
        result = run(
            "scan",
            str(FIXTURE),
            "--provider",
            "rails",
            "--environment",
            "production",
            "--env-file",
            "deployment.yml",
            "--system-id",
            "portable-rails-fixture",
            "--revision",
            "revision-test-123",
            "--repository",
            "https://github.com/sergii/causcope",
            "--output",
            str(output),
            "--json",
        )
        assert "Provider: rails" in result.stdout
        assert "Revision: revision-test-123" in result.stdout

        document = json.loads(output.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(document)

        assert document["kind"] == "concrete_system_facts"
        assert document["system_id"] == "portable-rails-fixture"
        assert document["revision"]["value"] == "revision-test-123"

        entities = {item["id"]: item for item in document["entities"]}
        pool = entities["pool:active_record.primary"]
        assert pool["kind"] == "resource_pool"
        assert pool["attributes"]["technology"] == "active_record"
        assert pool["attributes"]["adapter"] == "postgresql"
        assert pool["attributes"]["configured_capacity"] == 1
        assert pool["attributes"]["checkout_timeout_seconds"] == 5.0

        code_symbols = {item["id"] for item in document["entities"] if item["kind"] == "code_symbol"}
        assert "code:PoolController#work()" in code_symbols
        assert "code:PoolController#hold()" in code_symbols
        assert "code:PoolController#pool()" in code_symbols

        facts = document["facts"]
        assert any(
            item["subject"] == "code:PoolController#work()"
            and item["relation"] == "depends_on"
            and item["object"] == "pool:active_record.primary"
            for item in facts
        )
        assert any(
            item["subject"] == "pool:active_record.primary"
            and item["relation"] == "depends_on"
            and item["object"] == "dependency:postgresql"
            for item in facts
        )

        copied = Path(temporary) / "implicit-app"
        shutil.copytree(FIXTURE, copied)
        controller = copied / "app" / "controllers" / "implicit_controller.rb"
        controller.write_text(
            "class ImplicitController < ApplicationController\n"
            "  def show\n"
            "    User.first\n"
            "  end\n"
            "end\n",
            encoding="utf-8",
        )
        implicit_output = Path(temporary) / "implicit.json"
        run(
            "scan",
            str(copied),
            "--provider",
            "rails",
            "--env-file",
            "deployment.yml",
            "--revision",
            "revision-implicit",
            "--output",
            str(implicit_output),
        )
        implicit_document = json.loads(implicit_output.read_text(encoding="utf-8"))
        assert not any(
            item["id"] == "code:ImplicitController#show()"
            for item in implicit_document["entities"]
        )

        unsafe = Path(temporary) / "unsafe-app"
        shutil.copytree(FIXTURE, unsafe)
        unsafe_database = unsafe / "config" / "database.yml"
        unsafe_database.write_text(
            "production:\n"
            "  adapter: postgresql\n"
            "  pool: <%= system('touch SHOULD_NOT_EXIST') %>\n",
            encoding="utf-8",
        )
        unsafe_output = Path(temporary) / "unsafe.json"
        unsafe_result = run(
            "scan",
            str(unsafe),
            "--provider",
            "rails",
            "--revision",
            "revision-unsafe",
            "--output",
            str(unsafe_output),
            check=False,
        )
        assert unsafe_result.returncode == 2
        assert "unsupported ERB" in unsafe_result.stderr
        assert not (ROOT / "SHOULD_NOT_EXIST").exists()
        assert not (unsafe / "SHOULD_NOT_EXIST").exists()

    print("Portable Rails repository scan: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

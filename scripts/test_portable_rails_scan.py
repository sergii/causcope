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


def load_and_validate(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(document)
    return document


def scan_app(app: Path, output: Path, revision: str, *extra: str) -> dict:
    run(
        "scan",
        str(app),
        "--provider",
        "rails",
        "--environment",
        "production",
        "--revision",
        revision,
        "--output",
        str(output),
        *extra,
    )
    return load_and_validate(output)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="causcope-portable-rails-") as temporary:
        temporary_root = Path(temporary)
        output = temporary_root / "facts.json"
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

        document = load_and_validate(output)
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

        code_symbols = {
            item["id"] for item in document["entities"] if item["kind"] == "code_symbol"
        }
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

        copied = temporary_root / "implicit-app"
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
        implicit_output = temporary_root / "implicit.json"
        implicit_document = scan_app(
            copied,
            implicit_output,
            "revision-implicit",
            "--env-file",
            "deployment.yml",
        )
        assert not any(
            item["id"] == "code:ImplicitController#show()"
            for item in implicit_document["entities"]
        )

        value_erb = temporary_root / "value-erb-app"
        shutil.copytree(FIXTURE, value_erb)
        value_database = value_erb / "config" / "database.yml"
        value_database.write_text(
            "production:\n"
            "  adapter: postgresql\n"
            "  pool: <%= system('touch SHOULD_NOT_EXIST') %>\n"
            "  checkout_timeout: 5\n",
            encoding="utf-8",
        )
        value_output = temporary_root / "value-erb.json"
        value_document = scan_app(value_erb, value_output, "revision-value-erb")
        value_entities = {item["id"]: item for item in value_document["entities"]}
        assert "configured_capacity" not in value_entities["pool:active_record.primary"]["attributes"]
        assert any("non-bounded ERB" in item for item in value_document["limitations"])
        assert not (ROOT / "SHOULD_NOT_EXIST").exists()
        assert not (value_erb / "SHOULD_NOT_EXIST").exists()

        structural = temporary_root / "structural-erb-app"
        shutil.copytree(FIXTURE, structural)
        structural_database = structural / "config" / "database.yml"
        structural_database.write_text(
            "<% if system('touch SHOULD_NOT_EXIST_STRUCTURAL') %>\n"
            "production:\n"
            "  adapter: postgresql\n"
            "  pool: 5\n"
            "<% end %>\n",
            encoding="utf-8",
        )
        structural_output = temporary_root / "structural-erb.json"
        structural_result = run(
            "scan",
            str(structural),
            "--provider",
            "rails",
            "--revision",
            "revision-structural-erb",
            "--output",
            str(structural_output),
            check=False,
        )
        assert structural_result.returncode == 2
        assert "structural ERB" in structural_result.stderr
        assert not (ROOT / "SHOULD_NOT_EXIST_STRUCTURAL").exists()
        assert not (structural / "SHOULD_NOT_EXIST_STRUCTURAL").exists()

        lobsters_like = temporary_root / "lobsters-like-app"
        shutil.copytree(FIXTURE, lobsters_like)
        (lobsters_like / "config" / "database.yml").unlink()
        (lobsters_like / "config" / "database.yml.sample").write_text(
            "sqlite3: &sqlite3\n"
            "  adapter: sqlite3\n"
            "  timeout: 1000\n"
            "production:\n"
            "  primary:\n"
            "    <<: *sqlite3\n"
            "    database: storage/primary.sqlite3\n"
            "  cache:\n"
            "    <<: *sqlite3\n"
            "    database: storage/cache.sqlite3\n"
            "  queue:\n"
            "    <<: *sqlite3\n"
            "    database: storage/queue.sqlite3\n"
            "  rack_attack:\n"
            "    <<: *sqlite3\n"
            "    database: storage/rack_attack.sqlite3\n",
            encoding="utf-8",
        )
        lobsters_output = temporary_root / "lobsters-like.json"
        lobsters_document = scan_app(
            lobsters_like, lobsters_output, "revision-lobsters-like"
        )
        lobsters_entities = {item["id"]: item for item in lobsters_document["entities"]}
        expected_pool_ids = {
            "pool:active_record.primary",
            "pool:active_record.cache",
            "pool:active_record.queue",
            "pool:active_record.rack_attack",
        }
        actual_pool_ids = {
            item["id"]
            for item in lobsters_document["entities"]
            if item["kind"] == "resource_pool"
        }
        assert actual_pool_ids == expected_pool_ids
        for pool_id in expected_pool_ids:
            assert lobsters_entities[pool_id]["attributes"]["adapter"] == "sqlite3"
            assert lobsters_entities[pool_id]["attributes"]["config_source"] == "config/database.yml.sample"
        sqlite_dependencies = [
            item
            for item in lobsters_document["entities"]
            if item["kind"] == "external_dependency"
        ]
        assert len(sqlite_dependencies) == 4
        assert all(item["attributes"]["dbms"] == "sqlite" for item in sqlite_dependencies)
        assert not any(
            item["relation"] == "depends_on" and item["subject"].startswith("code:")
            for item in lobsters_document["facts"]
        )
        assert any("database.yml.sample" in item for item in lobsters_document["limitations"])
        assert any("Multiple ActiveRecord" in item for item in lobsters_document["limitations"])

        mastodon_like = temporary_root / "mastodon-like-app"
        shutil.copytree(FIXTURE, mastodon_like)
        (mastodon_like / "config" / "database.yml").write_text(
            "default: &default\n"
            "  adapter: postgresql\n"
            "  pool: <%= ENV[\"DB_POOL\"] || (if Sidekiq.server? then Sidekiq.default_configuration[:concurrency] else ENV['MAX_THREADS'] end) || 5 %>\n"
            "  timeout: 5000\n"
            "production:\n"
            "  primary:\n"
            "    <<: *default\n"
            "    database: <%= ENV['DB_NAME'] || 'mastodon_production' %>\n"
            "  replica:\n"
            "    <<: *default\n"
            "    database: <%= ENV['REPLICA_DB_NAME'] || ENV['DB_NAME'] || 'mastodon_production' %>\n"
            "    replica: true\n",
            encoding="utf-8",
        )
        mastodon_output = temporary_root / "mastodon-like.json"
        mastodon_document = scan_app(
            mastodon_like, mastodon_output, "revision-mastodon-like"
        )
        mastodon_entities = {item["id"]: item for item in mastodon_document["entities"]}
        assert {
            item["id"]
            for item in mastodon_document["entities"]
            if item["kind"] == "resource_pool"
        } == {"pool:active_record.primary", "pool:active_record.replica"}
        for pool_id in ("pool:active_record.primary", "pool:active_record.replica"):
            attributes = mastodon_entities[pool_id]["attributes"]
            assert attributes["adapter"] == "postgresql"
            assert "configured_capacity" not in attributes
        assert mastodon_entities["pool:active_record.replica"]["attributes"]["replica"] is True
        postgres_dependencies = [
            item
            for item in mastodon_document["entities"]
            if item["kind"] == "external_dependency"
        ]
        assert len(postgres_dependencies) == 2
        assert all(
            item["attributes"]["dbms"] == "postgresql" for item in postgres_dependencies
        )
        assert any("unresolved value ERB" in item for item in mastodon_document["limitations"])
        assert any("Configured pool capacity" in item for item in mastodon_document["limitations"])
        assert not any(
            item["relation"] == "depends_on" and item["subject"].startswith("code:")
            for item in mastodon_document["facts"]
        )

        custom = temporary_root / "custom-config-app"
        shutil.copytree(FIXTURE, custom)
        custom_config = custom / "config" / "database.custom.yml"
        custom_config.write_text(
            "production:\n"
            "  adapter: sqlite3\n"
            "  database: storage/custom.sqlite3\n"
            "  pool: 7\n",
            encoding="utf-8",
        )
        custom_output = temporary_root / "custom.json"
        custom_document = scan_app(
            custom,
            custom_output,
            "revision-custom",
            "--database-config",
            "config/database.custom.yml",
        )
        custom_entities = {item["id"]: item for item in custom_document["entities"]}
        custom_pool = custom_entities["pool:active_record.primary"]
        assert custom_pool["attributes"]["adapter"] == "sqlite3"
        assert custom_pool["attributes"]["configured_capacity"] == 7
        assert custom_pool["attributes"]["config_source"] == "config/database.custom.yml"

    print("Portable Rails repository scan: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

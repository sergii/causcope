#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from provider_bindings import load_provider_bindings_document


class PostgreSQLHealthBindingSchemaTest(unittest.TestCase):
    def test_postgresql_health_binding_is_explicit_and_environment_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "providers.yaml"
            path.write_text(
                """schema_version: \"0.1\"
kind: provider_bindings
bindings:
  - provider_instance: provider.postgresql-health.orders-prod
    driver: postgresql_health
    database_url_env: ORDERS_DATABASE_URL
    long_transaction_seconds: 90
    scope:
      boundaries:
        - boundary.application.database
      attributes:
        service: orders-api
        dependency: postgresql
""",
                encoding="utf-8",
            )
            document = load_provider_bindings_document(path)
        binding = document["bindings"][0]
        self.assertEqual("postgresql_health", binding["driver"])
        self.assertEqual("ORDERS_DATABASE_URL", binding["database_url_env"])
        self.assertEqual(90, binding["long_transaction_seconds"])
        self.assertNotIn("database_url", binding)


if __name__ == "__main__":
    unittest.main()

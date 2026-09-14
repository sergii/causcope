#!/usr/bin/env python3

from __future__ import annotations

import copy
import unittest
from pathlib import Path

from concrete_system_facts import (
    load_document,
    load_schema,
    opposing_access_orders,
    validate_schema,
    validate_semantics,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schema" / "concrete-system-facts.schema.json"
FIXTURE = ROOT / "examples" / "concrete-system" / "deadlock-risk.yaml"


class ConcreteSystemFactsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_schema(SCHEMA)
        cls.fixture = load_document(FIXTURE)

    def validate(self, document: dict) -> None:
        validate_schema(document, self.schema)
        validate_semantics(document)

    def test_fixture_is_valid(self) -> None:
        self.validate(self.fixture)
        self.assertEqual("concrete_system_facts", self.fixture["kind"])
        self.assertEqual("checkout-app", self.fixture["system_id"])

    def test_every_inferred_fact_names_its_deriving_rule(self) -> None:
        self.validate(self.fixture)
        inferred = [fact for fact in self.fixture["facts"] if fact["certainty"] == "inferred"]
        self.assertTrue(inferred)
        for fact in inferred:
            self.assertTrue(fact["provenance"].get("rule"), fact["id"])

    def test_rejects_unknown_entity_references(self) -> None:
        document = copy.deepcopy(self.fixture)
        document["facts"][0]["object"] = "tx:missing"
        validate_schema(document, self.schema)
        with self.assertRaisesRegex(ValueError, "unknown object tx:missing"):
            validate_semantics(document)

    def test_rejects_inferred_entity_without_rule(self) -> None:
        document = copy.deepcopy(self.fixture)
        entity = next(item for item in document["entities"] if item["id"] == "tx:checkout")
        entity["provenance"].pop("rule")
        validate_schema(document, self.schema)
        with self.assertRaisesRegex(ValueError, "inferred entity tx:checkout"):
            validate_semantics(document)

    def test_opposing_order_projects_a_structural_precondition_not_a_deadlock(self) -> None:
        self.validate(self.fixture)
        projected = opposing_access_orders(self.fixture)
        self.assertEqual(1, len(projected))
        result = projected[0]
        self.assertEqual("opposing_access_order_precondition", result["kind"])
        self.assertEqual(
            {"db:public.accounts", "db:public.ledger_entries"},
            set(result["resources"]),
        )
        self.assertEqual(
            {"code:CheckoutService#call", "code:SettlementJob#perform"},
            {result["left"]["code_path"], result["right"]["code_path"]},
        )
        self.assertFalse(result["deadlock_observed"])
        self.assertIn("Runtime overlap", result["interpretation"])
        self.assertIn("wait-for cycle", result["interpretation"])

    def test_same_direction_is_not_a_d2_2_precondition(self) -> None:
        document = copy.deepcopy(self.fixture)
        reverse = next(
            fact
            for fact in document["facts"]
            if fact["id"] == "fact.settlement.ledger_before_accounts"
        )
        reverse["subject"] = "db:public.accounts"
        reverse["object"] = "db:public.ledger_entries"
        self.validate(document)
        self.assertEqual([], opposing_access_orders(document))


if __name__ == "__main__":
    unittest.main()

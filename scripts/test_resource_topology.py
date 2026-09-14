#!/usr/bin/env python3

from __future__ import annotations

import copy
import unittest
from pathlib import Path

import yaml

from resource_topology import ResourceTopology, load_resource_topology

ROOT = Path(__file__).resolve().parents[1]
SHOP_PATH = ROOT / "examples" / "topology" / "shop.yaml"


class ResourceTopologyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.topology = load_resource_topology(SHOP_PATH)
        with SHOP_PATH.open("r", encoding="utf-8") as handle:
            cls.document = yaml.safe_load(handle)

    def test_shop_has_two_distinct_postgresql_targets(self) -> None:
        self.assertEqual("orders", self.topology.resource("db.orders.prod")["attributes"]["database"])
        self.assertEqual(
            "payments",
            self.topology.resource("db.payments.prod")["attributes"]["database"],
        )
        self.assertEqual(
            ["db.orders.prod", "db.payments.prod"],
            [
                relationship["to"]
                for relationship in self.topology.dependencies_from("service.checkout.prod")
            ],
        )

    def test_provider_instances_are_exactly_target_bound(self) -> None:
        self.assertEqual(
            ["provider.pgbot.orders-prod", "provider.prometheus.orders-prod"],
            [
                instance["id"]
                for instance in self.topology.provider_instances_for_target("db.orders.prod")
            ],
        )
        self.assertEqual(
            ["provider.pgbot.payments-prod", "provider.prometheus.payments-prod"],
            [
                instance["id"]
                for instance in self.topology.provider_instances_for_target("db.payments.prod")
            ],
        )

    def test_indirect_provider_has_distinct_endpoint_resource(self) -> None:
        endpoint = self.topology.provider_endpoint("provider.prometheus.orders-prod")
        self.assertEqual("observability.prometheus.prod", endpoint["id"])
        direct_endpoint = self.topology.provider_endpoint("provider.pgbot.orders-prod")
        self.assertEqual("db.orders.prod", direct_endpoint["id"])

    def test_provider_types_declare_runner_transport_capabilities(self) -> None:
        self.assertEqual(
            ["outbound_postgresql"],
            self.topology.provider_type("provider_type.pgbot.postgresql")["runner_capabilities"],
        )
        self.assertEqual(
            ["outbound_http"],
            self.topology.provider_type("provider_type.prometheus.metrics")["runner_capabilities"],
        )

    def test_canonical_document_is_deterministically_sorted(self) -> None:
        document = self.topology.canonical_document()
        self.assertEqual(
            sorted(resource["id"] for resource in document["resources"]),
            [resource["id"] for resource in document["resources"]],
        )
        self.assertEqual(
            sorted(instance["id"] for instance in document["provider_instances"]),
            [instance["id"] for instance in document["provider_instances"]],
        )

    def test_duplicate_ids_fail_closed(self) -> None:
        document = copy.deepcopy(self.document)
        document["resources"].append(copy.deepcopy(document["resources"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate topology id"):
            ResourceTopology(document)

    def test_dangling_provider_target_fails_closed(self) -> None:
        document = copy.deepcopy(self.document)
        document["provider_instances"][0]["target"] = "db.unknown.prod"
        with self.assertRaisesRegex(ValueError, "unknown target resource"):
            ResourceTopology(document)

    def test_dangling_provider_endpoint_fails_closed(self) -> None:
        document = copy.deepcopy(self.document)
        prometheus = next(
            instance
            for instance in document["provider_instances"]
            if instance["id"] == "provider.prometheus.orders-prod"
        )
        prometheus["endpoint_resource"] = "observability.missing.prod"
        with self.assertRaisesRegex(ValueError, "unknown endpoint resource"):
            ResourceTopology(document)

    def test_unknown_lookup_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown topology resource"):
            self.topology.provider_instances_for_target("db.missing.prod")


if __name__ == "__main__":
    unittest.main()

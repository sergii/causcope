#!/usr/bin/env python3

from __future__ import annotations

import unittest
from pathlib import Path

from scoping_projection import ROOT, build_scoping_projection, load_incident_context


class ScopingProjectionTest(unittest.TestCase):
    def test_investigation_lab_context_recommends_client_scope_first(self) -> None:
        context = load_incident_context(
            ROOT / "lab" / "investigation" / "checkout-client-version" / "initial-context.yaml"
        )
        projection = build_scoping_projection(context)

        self.assertEqual(0.7, projection["completeness"])
        self.assertEqual(7, projection["known_count"])
        self.assertEqual(0, projection["partial_count"])
        self.assertEqual(3, projection["unknown_count"])
        self.assertEqual(
            "investigation.client",
            projection["next_action"]["dimension"],
        )

    def test_explicit_unknown_keeps_populated_dimension_partial(self) -> None:
        context = load_incident_context(
            ROOT / "examples" / "incidents" / "checkout-latency.yaml"
        )
        projection = build_scoping_projection(context)
        blast_radius = next(
            item
            for item in projection["dimensions"]
            if item["id"] == "investigation.blast_radius"
        )

        self.assertEqual("partial", blast_radius["state"])
        self.assertIn("impact.populations.affected", blast_radius["signals"])
        self.assertEqual(
            "investigation.blast_radius",
            projection["next_action"]["dimension"],
        )

    def test_registry_contains_exactly_ten_stable_dimensions(self) -> None:
        context = load_incident_context(
            ROOT / "examples" / "incidents" / "checkout-latency.yaml"
        )
        projection = build_scoping_projection(context)
        ids = [item["id"] for item in projection["dimensions"]]

        self.assertEqual(10, len(ids))
        self.assertEqual(10, len(set(ids)))
        self.assertEqual("investigation.blast_radius", ids[0])
        self.assertEqual("investigation.impact", ids[-1])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3

from __future__ import annotations

import unittest

from run_investigation_lab import ROOT, load_scenario, run_baseline


class InvestigationLabTest(unittest.TestCase):
    def test_checkout_client_version_baseline_passes(self) -> None:
        scenario_path = (
            ROOT / "lab" / "investigation" / "checkout-client-version" / "scenario.yaml"
        )
        scenario = load_scenario(scenario_path)
        result = run_baseline(scenario)

        self.assertTrue(result["passed"])
        self.assertEqual(
            "investigation.client",
            result["expected_first_dimension"],
        )
        self.assertEqual(
            result["expected_first_dimension"],
            result["actual_first_dimension"],
        )
        self.assertIn(
            "treat_change_as_cause_without_evidence",
            result["forbidden_behaviors"],
        )

    def test_oracle_is_separate_from_initial_incident_context(self) -> None:
        scenario_path = (
            ROOT / "lab" / "investigation" / "checkout-client-version" / "scenario.yaml"
        )
        scenario = load_scenario(scenario_path)
        context_path = ROOT / scenario["initial_context_file"]
        context_text = context_path.read_text(encoding="utf-8")

        self.assertNotIn(scenario["oracle"]["root_cause"], context_text)
        self.assertGreater(len(scenario["oracle"]["facts"]), 0)
        self.assertGreater(len(scenario["oracle"]["red_herrings"]), 0)


if __name__ == "__main__":
    unittest.main()

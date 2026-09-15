#!/usr/bin/env python3

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from routed_execution_set_journal import verify_execution_set_journal
from routed_execution_set_mcp_tool import (
    TOOL_NAME,
    RoutedExecutionSetToolController,
)
from routed_execution_sets import build_routed_execution_sets
from test_multi_target_execution_set import MultiTargetExecutionSetTest


class CountingInformationRouter:
    def __init__(self, router: Any, counts: dict[str, int]) -> None:
        self.router = router
        self.counts = counts

    def route(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.router.route(*args, **kwargs)

    def execute(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        target = kwargs["target_resource"]
        self.counts[target] = self.counts.get(target, 0) + 1
        return self.router.execute(*args, **kwargs)


class DurableExecutionSetJournalTest(MultiTargetExecutionSetTest):
    def test_process_restart_resumes_without_repeating_completed_member_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (
                snapshot,
                _evidence,
                snapshot_path,
                evidence_path,
                reader,
                routing_provider,
                _base_router_provider,
                controller,
            ) = self.setup_runtime(directory)
            execution_set = build_routed_execution_sets(routing_provider(snapshot))["sets"][0]
            before_snapshot = snapshot_path.read_text(encoding="utf-8")
            before_evidence = evidence_path.read_text(encoding="utf-8")

            counts: dict[str, int] = {}
            raw_factory = controller.information_gain_router_provider

            def counting_factory() -> CountingInformationRouter:
                return CountingInformationRouter(raw_factory(), counts)

            controller.information_gain_router_provider = counting_factory

            def crash_after_orders(stage: str, context: dict[str, Any]) -> None:
                if (
                    stage == "after_member_journaled"
                    and context["target_resource"] == "db.orders.prod"
                ):
                    raise RuntimeError("simulated process crash after durable member journal")

            controller.member_fault_hook = crash_after_orders
            with self.assertRaisesRegex(RuntimeError, "simulated process crash"):
                controller.call(TOOL_NAME, execution_set["arguments"])

            self.assertEqual({"db.orders.prod": 1}, counts)
            self.assertEqual(before_snapshot, snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(before_evidence, evidence_path.read_text(encoding="utf-8"))

            state_dir = Path(directory) / "execution-sets"
            partial = verify_execution_set_journal(state_dir, execution_set["id"])
            self.assertEqual(
                ["set_started", "member_succeeded"],
                [event["event_type"] for event in partial["events"]],
            )
            self.assertEqual(
                "db.orders.prod",
                partial["events"][1]["data"]["target_resource"],
            )

            restarted = RoutedExecutionSetToolController(
                reader=reader,
                snapshot_path=snapshot_path,
                runtime_evidence_path=evidence_path,
                concepts=self.concepts,
                edges=self.edges,
                routing_projection_provider=routing_provider,
                information_gain_router_provider=counting_factory,
                mutation_lock_dir=Path(directory) / "locks",
                clock=lambda: self.NOW if hasattr(self, "NOW") else controller.clock(),
            )
            result = restarted.call(TOOL_NAME, execution_set["arguments"])

            self.assertEqual(1, counts["db.orders.prod"])
            self.assertEqual(1, counts["db.payments.prod"])
            self.assertEqual(1, result["resumed_member_count"])
            self.assertEqual(
                [True, False],
                [item["resumed_from_journal"] for item in result["member_results"]],
            )
            self.assertEqual(8, result["evidence_revision"])
            self.assertEqual(1, result["rerank_count"])

            final = verify_execution_set_journal(state_dir, execution_set["id"])
            self.assertEqual(
                [
                    "set_started",
                    "member_succeeded",
                    "member_succeeded",
                    "set_committed",
                ],
                [event["event_type"] for event in final["events"]],
            )
            committed_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(8, committed_snapshot["evidence_revision"])

    def test_tampered_journal_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (
                snapshot,
                _evidence,
                _snapshot_path,
                _evidence_path,
                _reader,
                routing_provider,
                _base_router_provider,
                controller,
            ) = self.setup_runtime(directory)
            execution_set = build_routed_execution_sets(routing_provider(snapshot))["sets"][0]

            def crash_after_orders(stage: str, context: dict[str, Any]) -> None:
                if stage == "after_member_journaled":
                    raise RuntimeError("stop after first durable result")

            controller.member_fault_hook = crash_after_orders
            with self.assertRaises(RuntimeError):
                controller.call(TOOL_NAME, execution_set["arguments"])

            state_dir = Path(directory) / "execution-sets"
            journal = Path(
                verify_execution_set_journal(state_dir, execution_set["id"])["path"]
            )
            lines = journal.read_text(encoding="utf-8").splitlines()
            event = json.loads(lines[-1])
            event["data"]["target_resource"] = "db.tampered.prod"
            lines[-1] = json.dumps(event, sort_keys=True, separators=(",", ":"))
            journal.write_text("\n".join(lines) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "event_hash mismatch"):
                verify_execution_set_journal(state_dir, execution_set["id"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.demo import DEMO_STEP_NAMES, GuidedDemoController, GuidedDemoError
from app.store import LocalStore
from app.workflow import WorkflowEngine

ROOT = Path(__file__).resolve().parents[1]


class GuidedDemoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = LocalStore(ROOT / "seed")
        self.engine = WorkflowEngine(self.store)
        self.now = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
        self.demo = GuidedDemoController(
            self.store,
            ROOT / "scenarios" / "recall_peanut_01.jsonl",
            daily_limit=1,
            ttl_minutes=20,
        )

    def test_guided_steps_are_ordered_and_reach_verified_state(self) -> None:
        started = self.demo.start(self.now)
        run_id = started["run_id"]
        self.assertEqual(started["next_step"], "transfer")
        self.assertEqual(self.store.collection("processed_events"), [])

        with self.assertRaisesRegex(GuidedDemoError, "Next guided-demo step is transfer"):
            self.demo.prepare_step(run_id, "recall", self.now)

        for step in DEMO_STEP_NAMES:
            event = self.demo.prepare_step(run_id, step, self.now)
            result = self.engine.process(event)
            if result["status"] == "duplicate_ignored":
                self.demo.confirm_duplicate(event.event_id, self.now)

        status = self.demo.status(run_id, self.now)
        self.assertEqual(status["status"], "completed")
        self.assertTrue(all(step["completed"] for step in status["steps"]))
        self.assertEqual(self.engine.summary()["quarantined_units"], 400)
        self.assertEqual(len(self.store.collection("demo_runs")), 1)

    def test_active_run_resumes_and_daily_ledger_survives_reset(self) -> None:
        first = self.demo.start(self.now)
        resumed = self.demo.start(self.now + timedelta(minutes=1))
        self.assertEqual(resumed["run_id"], first["run_id"])
        self.assertTrue(resumed["resumed"])

        for step in DEMO_STEP_NAMES:
            event = self.demo.prepare_step(first["run_id"], step, self.now)
            result = self.engine.process(event)
            if result["status"] == "duplicate_ignored":
                self.demo.confirm_duplicate(event.event_id, self.now)
        self.store.reset()
        with self.assertRaisesRegex(GuidedDemoError, "safety limit"):
            self.demo.start(self.now + timedelta(minutes=2))

    def test_expired_run_cannot_publish(self) -> None:
        run = self.demo.start(self.now)
        with self.assertRaisesRegex(GuidedDemoError, "expired"):
            self.demo.prepare_step(run["run_id"], "transfer", self.now + timedelta(minutes=21))

    def test_latest_run_is_selected_by_start_time_not_firestore_order(self) -> None:
        self.demo.daily_limit = 2
        first = self.demo.start(self.now)
        for step in DEMO_STEP_NAMES:
            event = self.demo.prepare_step(first["run_id"], step, self.now)
            result = self.engine.process(event)
            if result["status"] == "duplicate_ignored":
                self.demo.confirm_duplicate(event.event_id, self.now)

        second = self.demo.start(self.now + timedelta(minutes=2))
        runs = self.store.collection("demo_runs")
        runs.sort(key=lambda run: run["run_id"])
        if runs[-1]["run_id"] == second["run_id"]:
            runs.reverse()

        latest = self.demo.latest_status()
        self.assertEqual(latest["run_id"], second["run_id"])
        self.assertEqual(latest["status"], "active")
        self.assertTrue(latest["steps"][0]["available"])


if __name__ == "__main__":
    unittest.main()

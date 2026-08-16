from __future__ import annotations

import unittest
from pathlib import Path

from app.dashboard_view import company_snapshot, story_snapshot
from app.demo import GuidedDemoController
from app.store import LocalStore
from app.workflow import WorkflowEngine

ROOT = Path(__file__).resolve().parents[1]


class DashboardViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = LocalStore(ROOT / "seed")
        self.engine = WorkflowEngine(self.store)
        self.demo = GuidedDemoController(
            self.store,
            ROOT / "scenarios" / "recall_peanut_01.jsonl",
            daily_limit=5,
            ttl_minutes=20,
        )

    def test_company_snapshot_is_curated_and_contains_no_customer_pii(self) -> None:
        company = company_snapshot(self.store)
        self.assertEqual(company["counts"]["products"], 40)
        self.assertEqual(company["counts"]["orders"], 80)
        self.assertEqual(len(company["agents"]), 3)
        self.assertEqual(company["case"]["affected_orders"], 20)
        self.assertNotIn("customer_email", str(company))

    def test_story_explains_agent_actions(self) -> None:
        for event in self.demo.events[:3]:
            self.engine.process(event)
        story = story_snapshot(self.store, self.demo)
        recall = next(item for item in story["events"] if item["step"] == "recall")
        self.assertEqual(
            {action["agent"] for action in recall["actions"]},
            {"Recall Coordinator", "Supply Continuity", "Financial Recovery"},
        )
        self.assertTrue(
            any(
                "Quarantined 370" in message
                for action in recall["actions"]
                for message in action["messages"]
            )
        )


if __name__ == "__main__":
    unittest.main()

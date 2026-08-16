from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DashboardTests(unittest.TestCase):
    def test_control_room_communicates_company_events_actions_and_state(self) -> None:
        dashboard = (ROOT / "app" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        for text in (
            "Company map",
            "Event simulation",
            "Agent conversation and actions",
            "Business state",
            "Start guided run",
            "Agent Registry",
            "Typed tools",
        ):
            with self.subTest(text=text):
                self.assertIn(text, dashboard)

    def test_dashboard_uses_safe_dom_rendering_and_contains_no_customer_email(self) -> None:
        dashboard = (ROOT / "app" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("innerHTML", dashboard)
        self.assertNotIn("@example.invalid", dashboard)
        self.assertIn("textContent", dashboard)
        self.assertIn("replaceChildren", dashboard)
        self.assertIn('story.demo.status === "active"', dashboard)
        self.assertIn('sessionStorage.setItem("recallops-demo-run"', dashboard)


if __name__ == "__main__":
    unittest.main()

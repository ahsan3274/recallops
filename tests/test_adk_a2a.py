from __future__ import annotations

import unittest
from pathlib import Path

from fastapi import FastAPI

from app.a2a import A2AServer
from app.adk_a2a import install_adk_a2a_routes
from app.store import LocalStore
from app.workflow import WorkflowEngine

ROOT = Path(__file__).resolve().parents[1]

try:
    from google.adk.agents import LlmAgent

    GOOGLE_RUNTIME_INSTALLED = True
except ImportError:
    GOOGLE_RUNTIME_INSTALLED = False


@unittest.skipUnless(GOOGLE_RUNTIME_INSTALLED, "Google runtime optional dependency is absent")
class AdkA2AServerTests(unittest.TestCase):
    def test_official_adk_executor_registers_card_and_rpc_routes(self) -> None:
        app = FastAPI()
        engine = WorkflowEngine(LocalStore(ROOT / "seed"))
        card = A2AServer(
            "supply", engine, ROOT / "agent_cards", "https://supply.example"
        ).agent_card()
        agent = LlmAgent(
            name="supply_continuity",
            model="gemini-3.5-flash-lite",
            description="Test specialist",
        )

        install_adk_a2a_routes(app, agent, card)

        methods_by_path = {
            route.path: route.methods
            for route in app.routes
            if route.path in {"/a2a", "/.well-known/agent-card.json"}
        }
        self.assertIn("POST", methods_by_path["/a2a"])
        self.assertIn("GET", methods_by_path["/.well-known/agent-card.json"])


if __name__ == "__main__":
    unittest.main()

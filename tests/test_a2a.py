from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.a2a import A2AServer
from app.models import EnterpriseEvent
from app.store import LocalStore
from app.workflow import WorkflowEngine

ROOT = Path(__file__).resolve().parents[1]


class A2ATests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = LocalStore(ROOT / "seed")
        self.engine = WorkflowEngine(self.store)
        events = [
            EnterpriseEvent.from_dict(json.loads(line))
            for line in (ROOT / "scenarios" / "recall_peanut_01.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        self.event = next(item for item in events if item.event_type == "recall.issued")

    def test_cards_have_required_a2a_fields_and_dynamic_url(self) -> None:
        for role in ("recall", "supply", "finance"):
            card = A2AServer(
                role, self.engine, ROOT / "agent_cards", "https://agent.example/"
            ).agent_card()
            self.assertEqual(card["protocolVersion"], "0.3.0")
            self.assertEqual(card["preferredTransport"], "JSONRPC")
            self.assertEqual(card["url"], "https://agent.example/a2a")
            self.assertIn("text/plain", card["defaultInputModes"])
            self.assertTrue(card["skills"])
            self.assertTrue(all(skill.get("tags") for skill in card["skills"]))

    def test_message_send_invokes_role_scoped_typed_tool(self) -> None:
        payload = self.event.payload
        data = {
            "event_id": self.event.event_id,
            "occurred_at": self.event.occurred_at,
            "source": self.event.source,
            "scenario_id": self.event.scenario_id,
            "recall_id": payload["recall_id"],
            "recall_number": payload["recall_number"],
            "product_id": payload["product_id"],
            "lot_codes": payload["lot_codes"],
            "classification": payload["classification"],
            "reason": payload["reason"],
        }
        request = {
            "jsonrpc": "2.0",
            "id": "rpc-1",
            "method": "message/send",
            "params": {
                "message": {
                    "kind": "message",
                    "messageId": "message-1",
                    "role": "user",
                    "parts": [{"kind": "data", "data": data}],
                }
            },
        }
        response = A2AServer(
            "recall", self.engine, ROOT / "agent_cards", "http://localhost:8000"
        ).handle(request)

        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertEqual(response["id"], "rpc-1")
        self.assertEqual(response["result"]["role"], "agent")
        result = response["result"]["parts"][0]["data"]
        self.assertEqual(result["status"], "contained")

    def test_invalid_method_returns_json_rpc_error(self) -> None:
        response = A2AServer(
            "recall", self.engine, ROOT / "agent_cards", "http://localhost:8000"
        ).handle({"jsonrpc": "2.0", "id": 1, "method": "unknown"})
        self.assertEqual(response["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()

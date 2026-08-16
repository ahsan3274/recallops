"""Small A2A 0.3 JSON-RPC adapter for the three RecallOps agents."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.agent_tools import build_toolsets
from app.workflow import WorkflowEngine

ROLE_CARD = {
    "recall": "recall-agent.json",
    "supply": "supply-agent.json",
    "finance": "finance-agent.json",
}


class A2AError(ValueError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class A2AServer:
    def __init__(self, role: str, engine: WorkflowEngine, card_dir: Path, public_base_url: str):
        if role not in ROLE_CARD:
            raise ValueError(f"Unsupported AGENT_ROLE: {role}")
        self.role = role
        self.card_dir = card_dir
        self.public_base_url = public_base_url.rstrip("/")
        self.recall_tools, self.supply_tools, self.finance_tools = build_toolsets(engine)

    def agent_card(self) -> dict[str, Any]:
        card = json.loads((self.card_dir / ROLE_CARD[self.role]).read_text(encoding="utf-8"))
        card["url"] = f"{self.public_base_url}/a2a"
        return card

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = request.get("id")
        try:
            if request.get("jsonrpc") != "2.0":
                raise A2AError(-32600, "Invalid JSON-RPC request")
            if request.get("method") != "message/send":
                raise A2AError(-32601, "Method not found")
            data = self._message_data(request.get("params"))
            result = self._invoke(data)
            message: dict[str, Any] = {
                "kind": "message",
                "messageId": str(uuid4()),
                "role": "agent",
                "parts": [{"kind": "data", "data": result}],
            }
            source_message = request["params"]["message"]
            if source_message.get("contextId"):
                message["contextId"] = source_message["contextId"]
            return {"jsonrpc": "2.0", "id": request_id, "result": message}
        except A2AError as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": exc.code, "message": str(exc)},
            }
        except (KeyError, TypeError, ValueError) as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": f"Invalid params: {exc}"},
            }

    @staticmethod
    def _message_data(params: Any) -> dict[str, Any]:
        if not isinstance(params, dict) or not isinstance(params.get("message"), dict):
            raise A2AError(-32602, "params.message is required")
        message = params["message"]
        if message.get("role") != "user" or not message.get("messageId"):
            raise A2AError(-32602, "A user message with messageId is required")
        parts = message.get("parts", [])
        data_parts = [part.get("data") for part in parts if part.get("kind") == "data"]
        if len(data_parts) != 1 or not isinstance(data_parts[0], dict):
            raise A2AError(-32602, "Exactly one data part is required")
        return copy.deepcopy(data_parts[0])

    def _invoke(self, data: dict[str, Any]) -> dict[str, Any]:
        if self.role == "recall":
            return self.recall_tools.contain_recall(**data)
        if self.role == "supply":
            return self.supply_tools.restore_supply(**data)
        return self.finance_tools.recover_finances(**data)

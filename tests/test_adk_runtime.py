from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.adk_runtime import AdkEventRuntime
from app.agents.specialist import DeterministicSpecialistAgent
from app.models import EnterpriseEvent
from app.store import LocalStore
from app.workflow import RECALL_AGENT, WorkflowEngine

ROOT = Path(__file__).resolve().parents[1]


class FakeSessions:
    def __init__(self):
        self.created: list[dict] = []

    async def create_session(self, **kwargs: object) -> None:
        self.created.append(kwargs)


class FakeRunner:
    def __init__(self):
        self.calls: list[dict] = []

    async def run_async(self, **kwargs: object):
        self.calls.append(kwargs)
        yield SimpleNamespace(
            is_final_response=lambda: True,
            content=SimpleNamespace(parts=[SimpleNamespace(text="workflow complete")]),
        )


class FakePart:
    def __init__(self, text: str):
        self.text = text


class FakeContent:
    def __init__(self, role: str, parts: list[FakePart]):
        self.role = role
        self.parts = parts


class AdkRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_event_is_sent_through_runner_with_fresh_model_budget(self) -> None:
        sessions = FakeSessions()
        runner = FakeRunner()
        types = SimpleNamespace(Content=FakeContent, Part=FakePart)
        runtime = AdkEventRuntime(object(), runner, sessions, types)
        event = EnterpriseEvent(
            event_id="evt-adk-1",
            event_type="recall.issued",
            occurred_at="2026-08-16T10:05:00Z",
            source="test",
            scenario_id="scenario-adk",
            payload={"recall_id": "REC-1"},
        )

        result = await runtime.run_event(event)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["agent_response"], "workflow complete")
        self.assertEqual(sessions.created[0]["state"]["recallops:model_call_count"], 0)
        message = runner.calls[0]["new_message"]
        self.assertIn('"event_id": "evt-adk-1"', message.parts[0].text)

    async def test_recall_routing_invokes_both_required_registry_specialists(self) -> None:
        store = LocalStore(ROOT / "seed")
        engine = WorkflowEngine(store)
        event = EnterpriseEvent.from_dict(
            json.loads(
                next(
                    line
                    for line in (ROOT / "scenarios" / "recall_peanut_01.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                    if '"event_type":"recall.issued"' in line
                )
            )
        )
        engine.contain_recall(
            event,
            actor=RECALL_AGENT,
            reason="Prepare deterministic routing test",
        )
        coordinator = FakeRunner()
        supply = FakeRunner()
        finance = FakeRunner()
        runtime = AdkEventRuntime(
            object(),
            coordinator,
            FakeSessions(),
            SimpleNamespace(Content=FakeContent, Part=FakePart),
            engine=engine,
            specialist_runners={
                "supply": (supply, FakeSessions()),
                "finance": (finance, FakeSessions()),
            },
        )

        result = await runtime.run_event(event)

        self.assertEqual(set(result["specialist_responses"]), {"supply", "finance"})
        supply_args = json.loads(supply.calls[0]["new_message"].parts[0].text)
        finance_args = json.loads(finance.calls[0]["new_message"].parts[0].text)
        self.assertEqual(supply_args["recall_id"], "RECALL-001")
        self.assertEqual(finance_args["recall_id"], "RECALL-001")
        self.assertEqual(finance_args["purchase_order_id"], "")

    async def test_deterministic_specialist_executes_typed_handler_without_model(self) -> None:
        calls: list[dict] = []

        def handler(**arguments: object) -> dict:
            calls.append(arguments)
            return {"status": "created", "actions": ["specialist completed"]}

        agent = DeterministicSpecialistAgent(
            name="test_specialist",
            description="Test specialist",
            handler=handler,
        )
        context = SimpleNamespace(
            user_content=FakeContent(
                role="user", parts=[FakePart('{"event_id":"evt-specialist"}')]
            ),
            invocation_id="invocation-1",
            branch=None,
        )

        events = [event async for event in agent._run_async_impl(context)]

        self.assertEqual(calls, [{"event_id": "evt-specialist"}])
        self.assertEqual(json.loads(events[0].content.parts[0].text)["status"], "created")


if __name__ == "__main__":
    unittest.main()

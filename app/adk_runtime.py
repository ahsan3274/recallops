"""Lazy Google ADK runner used by the production Pub/Sub consumer."""

from __future__ import annotations

import json
from typing import Any

from app.models import EnterpriseEvent
from app.telemetry import trace_span
from app.workflow import FINANCE_AGENT, RECALL_AGENT, SUPPLY_AGENT, WorkflowEngine


class AdkEventRuntime:
    def __init__(
        self,
        agent: Any,
        runner: Any,
        session_service: Any,
        types_module: Any,
        *,
        engine: WorkflowEngine | None = None,
        specialist_runners: dict[str, tuple[Any, Any]] | None = None,
    ):
        self.agent = agent
        self.runner = runner
        self.session_service = session_service
        self.types = types_module
        self.engine = engine
        self.specialist_runners = specialist_runners or {}

    @classmethod
    def create(cls) -> AdkEventRuntime:
        try:
            from google.adk.runners import Runner
            from google.adk.sessions import InMemorySessionService
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError("ADK mode requires `pip install -e \".[google]\"`") from exc
        from app.agents.definitions import registered_specialists, root_agent
        from app.runtime_state import engine

        sessions = InMemorySessionService()
        runner = Runner(agent=root_agent, app_name="recallops", session_service=sessions)
        specialist_runners = {}
        for role, specialist in registered_specialists.items():
            specialist_sessions = InMemorySessionService()
            specialist_runners[role] = (
                Runner(
                    agent=specialist,
                    app_name=f"recallops_{role}_handoff",
                    session_service=specialist_sessions,
                ),
                specialist_sessions,
            )
        return cls(
            root_agent,
            runner,
            sessions,
            types,
            engine=engine,
            specialist_runners=specialist_runners,
        )

    async def run_event(self, event: EnterpriseEvent) -> dict[str, Any]:
        session_id = f"{event.scenario_id}-{event.event_id}".replace(":", "-")
        prompt = (
            "Process this enterprise event. Call only typed tools. Contain exact matches; "
            "request approval for ambiguity. The runtime handles downstream specialist routing "
            "from validated tool results. Event JSON:\n"
            + json.dumps(event.to_dict(), sort_keys=True)
        )
        final_text = await self._run_agent(
            runner=self.runner,
            session_service=self.session_service,
            app_name="recallops",
            user_id="enterprise-event-bus",
            session_id=session_id,
            prompt=prompt,
            state={"recallops:model_call_count": 0},
        )
        specialist_responses = await self._run_required_specialists(event)
        return {
            "status": "completed",
            "agent_response": final_text,
            "specialist_responses": specialist_responses,
        }

    async def _run_agent(
        self,
        *,
        runner: Any,
        session_service: Any,
        app_name: str,
        user_id: str,
        session_id: str,
        prompt: str,
        state: dict[str, Any] | None = None,
    ) -> str:
        await session_service.create_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            state=state or {},
        )
        message = self.types.Content(role="user", parts=[self.types.Part(text=prompt)])
        final_text = ""
        async for response_event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=message,
        ):
            if getattr(response_event, "error_message", None):
                raise RuntimeError(response_event.error_message)
            is_final = getattr(response_event, "is_final_response", lambda: False)()
            if is_final and getattr(response_event, "content", None):
                final_text = "".join(
                    part.text or ""
                    for part in response_event.content.parts
                    if hasattr(part, "text")
                )
        return final_text

    async def _run_required_specialists(self, event: EnterpriseEvent) -> dict[str, str]:
        if event.event_type != "recall.issued" or self.engine is None:
            return {}
        self.engine.store.refresh()
        execution = self.engine.store.find_one(
            "tool_executions", "idempotency_key", f"{event.event_id}:contain_recall"
        )
        if execution is None:
            return {}
        containment = execution["result"]
        if containment.get("status") != "contained":
            return {}

        responses: dict[str, str] = {}
        purchase_order_id = ""
        if containment.get("requires_supply"):
            supply_reason = "Safe stock is below the seven-day target"
            responses["supply"] = await self._handoff(
                role="supply",
                event=event,
                target_agent=SUPPLY_AGENT,
                arguments={
                    "event_id": event.event_id,
                    "scenario_id": event.scenario_id,
                    "recall_id": containment["recall_id"],
                    "reason": supply_reason,
                },
            )
            self.engine.store.refresh()
            supply_execution = self.engine.store.find_one(
                "tool_executions", "idempotency_key", f"{event.event_id}:restore_supply"
            )
            if supply_execution:
                self.engine.record_handoff(
                    event,
                    to_agent=SUPPLY_AGENT,
                    request_summary=supply_reason,
                    response_actions=supply_execution["result"].get("actions", []),
                    trace_id=supply_execution.get("trace_id"),
                )
                purchase_order_id = supply_execution["result"].get("purchase_order_id", "")

        if containment.get("requires_finance"):
            finance_reason = "Contained stock or fulfilled orders created recoverable loss"
            responses["finance"] = await self._handoff(
                role="finance",
                event=event,
                target_agent=FINANCE_AGENT,
                arguments={
                    "event_id": event.event_id,
                    "scenario_id": event.scenario_id,
                    "recall_id": containment["recall_id"],
                    "reason": finance_reason,
                    "purchase_order_id": purchase_order_id,
                },
            )
            self.engine.store.refresh()
            finance_execution = self.engine.store.find_one(
                "tool_executions", "idempotency_key", f"{event.event_id}:recover_finances"
            )
            if finance_execution:
                self.engine.record_handoff(
                    event,
                    to_agent=FINANCE_AGENT,
                    request_summary=finance_reason,
                    response_actions=finance_execution["result"].get("actions", []),
                    trace_id=finance_execution.get("trace_id"),
                )
        return responses

    async def _handoff(
        self,
        *,
        role: str,
        event: EnterpriseEvent,
        target_agent: str,
        arguments: dict[str, Any],
    ) -> str:
        specialist = self.specialist_runners.get(role)
        if specialist is None:
            raise RuntimeError(f"Required Registry specialist is unavailable: {role}")
        runner, sessions = specialist
        with trace_span(
            "agent.handoff",
            {
                "recallops.from_agent": RECALL_AGENT,
                "recallops.to_agent": target_agent,
                "recallops.event_id": event.event_id,
            },
        ):
            return await self._run_agent(
                runner=runner,
                session_service=sessions,
                app_name=f"recallops_{role}_handoff",
                user_id=RECALL_AGENT,
                session_id=f"{event.event_id}-{role}",
                prompt=json.dumps(arguments, sort_keys=True),
            )

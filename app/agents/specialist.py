"""Deterministic ADK agents for policy-owned specialist services."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Callable
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from google.genai import types
from pydantic import PrivateAttr
from typing_extensions import override


class DeterministicSpecialistAgent(BaseAgent):
    """Run one typed department tool behind an official ADK/A2A endpoint."""

    _handler: Callable[..., dict[str, Any]] = PrivateAttr()

    def __init__(
        self,
        *,
        name: str,
        description: str,
        handler: Callable[..., dict[str, Any]],
    ) -> None:
        super().__init__(name=name, description=description)
        self._handler = handler

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        content = ctx.user_content
        text = "".join(
            part.text or "" for part in (content.parts if content and content.parts else [])
        )
        try:
            arguments = json.loads(text)
            if not isinstance(arguments, dict):
                raise ValueError("Specialist input must be a JSON object")
            result = self._handler(**arguments)
            response = json.dumps(result, sort_keys=True)
            yield Event(
                invocation_id=ctx.invocation_id,
                branch=ctx.branch,
                author=self.name,
                content=types.Content(role="model", parts=[types.Part(text=response)]),
            )
        except Exception as exc:
            yield Event(
                invocation_id=ctx.invocation_id,
                branch=ctx.branch,
                author=self.name,
                error_message=f"Specialist tool execution failed: {exc}",
            )

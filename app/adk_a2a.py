"""Official Google ADK A2A route installation for cloud agent mode."""

from __future__ import annotations

from typing import Any


def install_adk_a2a_routes(app: Any, agent: Any, agent_card: dict[str, Any]) -> None:
    """Attach the ADK A2A JSON-RPC executor to an existing FastAPI application.

    Imports remain lazy so deterministic local mode does not require Google packages.
    """

    try:
        from a2a.server.apps import A2AStarletteApplication
        from a2a.server.request_handlers import DefaultRequestHandler
        from a2a.server.tasks import InMemoryPushNotificationConfigStore, InMemoryTaskStore
        from a2a.types import AgentCard
        from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
    except ImportError as exc:
        raise RuntimeError("ADK A2A mode requires `pip install -e \".[google]\"`") from exc

    runner = Runner(
        agent=agent,
        app_name=f"recallops-{agent.name}",
        session_service=InMemorySessionService(),
    )
    handler = DefaultRequestHandler(
        agent_executor=A2aAgentExecutor(runner=runner),
        task_store=InMemoryTaskStore(),
        push_config_store=InMemoryPushNotificationConfigStore(),
    )
    a2a_app = A2AStarletteApplication(
        agent_card=AgentCard(**agent_card),
        http_handler=handler,
    )
    a2a_app.add_routes_to_app(
        app,
        agent_card_url="/.well-known/agent-card.json",
        rpc_url="/a2a",
    )

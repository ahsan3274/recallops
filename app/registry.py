"""Cold-start Agent Registry resolution for remote A2A specialists."""

from __future__ import annotations

from typing import Any


class RegistryAgentResolver:
    """Resolve each registered agent once and reuse the ADK remote-agent object."""

    def __init__(
        self,
        project: str,
        location: str,
        *,
        registry: Any | None = None,
        httpx_client: Any | None = None,
    ):
        if not project or not location:
            raise ValueError("Agent Registry requires GOOGLE_CLOUD_PROJECT and location")
        if registry is None:
            try:
                from google.adk.integrations.agent_registry import AgentRegistry
            except ImportError as exc:
                raise RuntimeError(
                    "Agent Registry requires the Google runtime with ADK's "
                    "`agent-identity` and `mcp` extras: `pip install -e \".[google]\"`"
                ) from exc
            registry = AgentRegistry(project_id=project, location=location)
        self.registry = registry
        self.httpx_client = httpx_client or self._authenticated_http_client()
        self._cache: dict[str, Any] = {}

    @staticmethod
    def _authenticated_http_client() -> Any:
        try:
            import httpx
            from google.auth.transport.requests import Request
            from google.oauth2 import id_token
        except ImportError as exc:
            raise RuntimeError(
                "Authenticated A2A discovery requires `pip install -e \".[google]\"`"
            ) from exc

        class GoogleAuth(httpx.Auth):
            def auth_flow(self, request: Any) -> Any:
                audience = f"{request.url.scheme}://{request.url.host}"
                token = id_token.fetch_id_token(Request(), audience)
                request.headers["Authorization"] = f"Bearer {token}"
                yield request

        return httpx.AsyncClient(auth=GoogleAuth(), timeout=httpx.Timeout(60.0))

    def resolve(self, agent_name: str) -> Any:
        if not agent_name.startswith(("agents/", "projects/")):
            raise ValueError("Registry agent name must be a short or full resource name")
        if agent_name not in self._cache:
            self._cache[agent_name] = self.registry.get_remote_a2a_agent(
                agent_name=agent_name,
                httpx_client=self.httpx_client,
            )
        return self._cache[agent_name]

    def resolve_specialists(self, supply_name: str, finance_name: str) -> tuple[Any, Any]:
        return self.resolve(supply_name), self.resolve(finance_name)

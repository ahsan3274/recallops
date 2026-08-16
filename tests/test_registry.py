from __future__ import annotations

import unittest

from app.registry import RegistryAgentResolver


class FakeRegistry:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    def get_remote_a2a_agent(self, *, agent_name: str, httpx_client: object) -> dict[str, str]:
        self.calls.append((agent_name, httpx_client))
        return {"resource_name": agent_name}


class RegistryTests(unittest.TestCase):
    def test_specialists_are_resolved_once_and_cached(self) -> None:
        registry = FakeRegistry()
        httpx_client = object()
        resolver = RegistryAgentResolver(
            "project-1",
            "us-central1",
            registry=registry,
            httpx_client=httpx_client,
        )

        supply, finance = resolver.resolve_specialists(
            "agents/supply-agent", "agents/finance-agent"
        )
        self.assertIs(supply, resolver.resolve("agents/supply-agent"))
        self.assertIs(finance, resolver.resolve("agents/finance-agent"))
        self.assertEqual(
            [name for name, _client in registry.calls],
            ["agents/supply-agent", "agents/finance-agent"],
        )
        self.assertTrue(all(client is httpx_client for _name, client in registry.calls))

    def test_invalid_resource_name_is_rejected(self) -> None:
        resolver = RegistryAgentResolver(
            "project-1", "us-central1", registry=FakeRegistry(), httpx_client=object()
        )
        with self.assertRaises(ValueError):
            resolver.resolve("https://hard-coded.example/a2a")


if __name__ == "__main__":
    unittest.main()

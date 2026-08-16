from __future__ import annotations

import unittest
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app, store


@contextmanager
def public_dashboard_settings(
    *, demo_api_key: str = "", enable_public_demo: bool = False
) -> Iterator[None]:
    original_public = settings.public_dashboard
    original_key = settings.demo_api_key
    original_demo = settings.enable_public_demo
    object.__setattr__(settings, "public_dashboard", True)
    object.__setattr__(settings, "demo_api_key", demo_api_key)
    object.__setattr__(settings, "enable_public_demo", enable_public_demo)
    try:
        yield
    finally:
        object.__setattr__(settings, "public_dashboard", original_public)
        object.__setattr__(settings, "demo_api_key", original_key)
        object.__setattr__(settings, "enable_public_demo", original_demo)


class PublicDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        store.collection("demo_runs").clear()
        store.reset()

    def test_public_submission_routes_are_read_only(self) -> None:
        with public_dashboard_settings():
            for path in (
                "/",
                "/health",
                "/api/summary",
                "/api/audit",
                "/api/company",
                "/api/story",
                "/.well-known/agent-card.json",
            ):
                with self.subTest(path=path):
                    self.assertEqual(self.client.get(path).status_code, 200)

            self.assertEqual(
                self.client.get("/health").json()["dashboard_mode"], "public-read-only"
            )
            for method, path in (
                ("get", "/api/state"),
                ("get", "/docs"),
                ("post", "/api/reset"),
                ("post", "/api/events"),
                ("post", "/api/scenarios/recall_peanut_01/replay"),
                ("post", "/api/demo/start"),
                ("post", "/a2a"),
            ):
                with self.subTest(method=method, path=path):
                    response = (
                        self.client.get(path)
                        if method == "get"
                        else self.client.post(path, json={})
                    )
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(response.json()["detail"], "Public dashboard is read-only")

    def test_operator_key_can_reach_protected_routes(self) -> None:
        with public_dashboard_settings(demo_api_key="operator-secret"):
            response = self.client.get(
                "/api/state", headers={"X-Demo-Key": "operator-secret"}
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("products", response.json())

            denied = self.client.get("/api/state", headers={"X-Demo-Key": "wrong"})
            self.assertEqual(denied.status_code, 403)

    def test_public_guided_demo_allows_only_fixed_ordered_events(self) -> None:
        with public_dashboard_settings(enable_public_demo=True):
            health = self.client.get("/health")
            self.assertEqual(health.json()["dashboard_mode"], "public-guided-demo")
            started = self.client.post("/api/demo/start")
            self.assertEqual(started.status_code, 200)
            run_id = started.json()["demo"]["run_id"]
            headers = {"X-Demo-Run": run_id}

            skipped = self.client.post("/api/demo/events/recall", headers=headers)
            self.assertEqual(skipped.status_code, 409)
            transfer = self.client.post("/api/demo/events/transfer", headers=headers)
            self.assertEqual(transfer.status_code, 200)
            self.assertEqual(transfer.json()["result"]["event_id"], "evt-transfer-001")

            self.assertEqual(self.client.get("/api/state").status_code, 403)
            self.assertEqual(self.client.post("/api/events", json={}).status_code, 403)
            invented = self.client.post(
                "/api/demo/events/not-a-real-event", headers=headers
            )
            self.assertEqual(invented.status_code, 403)


if __name__ == "__main__":
    unittest.main()

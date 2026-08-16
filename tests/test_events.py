from __future__ import annotations

import json
import unittest
from typing import Any

from app.events import PubSubPublisher, verify_pubsub_oidc
from app.models import EnterpriseEvent


class FakeFuture:
    def result(self, timeout: int) -> str:
        if timeout != 30:
            raise AssertionError("unexpected timeout")
        return "message-123"


class FakePublisher:
    def __init__(self):
        self.published: list[tuple[str, bytes, dict[str, str]]] = []

    def topic_path(self, project: str, topic: str) -> str:
        return f"projects/{project}/topics/{topic}"

    def publish(self, path: str, data: bytes, **attributes: str) -> FakeFuture:
        self.published.append((path, data, attributes))
        return FakeFuture()


class EventTransportTests(unittest.TestCase):
    def event(self) -> EnterpriseEvent:
        return EnterpriseEvent(
            event_id="evt-1",
            event_type="recall.issued",
            occurred_at="2026-08-16T10:05:00Z",
            source="test",
            scenario_id="scenario-1",
            payload={"recall_id": "REC-1"},
        )

    def test_publisher_uses_documented_envelope_and_attributes(self) -> None:
        client = FakePublisher()
        publisher = PubSubPublisher("project-1", "enterprise-events", client=client)

        self.assertEqual(publisher.publish(self.event()), "message-123")
        path, data, attributes = client.published[0]
        self.assertEqual(path, "projects/project-1/topics/enterprise-events")
        self.assertEqual(json.loads(data), self.event().to_dict())
        self.assertEqual(attributes["event_type"], "recall.issued")
        self.assertEqual(attributes["scenario_id"], "scenario-1")

    def test_oidc_verification_checks_audience_email_and_verified_claim(self) -> None:
        calls: list[tuple[str, str]] = []

        def verifier(token: str, audience: str) -> dict[str, Any]:
            calls.append((token, audience))
            return {"email": "push@example.iam.gserviceaccount.com", "email_verified": True}

        claims = verify_pubsub_oidc(
            "Bearer signed-token",
            audience="https://recall.example/api/pubsub",
            expected_email="push@example.iam.gserviceaccount.com",
            token_verifier=verifier,
        )
        self.assertTrue(claims["email_verified"])
        self.assertEqual(calls, [("signed-token", "https://recall.example/api/pubsub")])

        with self.assertRaises(PermissionError):
            verify_pubsub_oidc(
                "Bearer signed-token",
                audience="expected-audience",
                expected_email="different@example.iam.gserviceaccount.com",
                token_verifier=verifier,
            )

    def test_oidc_verification_rejects_missing_bearer_token(self) -> None:
        with self.assertRaises(PermissionError):
            verify_pubsub_oidc(
                None,
                audience="expected-audience",
                expected_email="push@example.iam.gserviceaccount.com",
                token_verifier=lambda _token, _audience: {},
            )


if __name__ == "__main__":
    unittest.main()
